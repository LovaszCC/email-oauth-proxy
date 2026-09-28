import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.crypto import Cryptographer
from app.db import Database
from app.models import utcnow
from app.services.accounts import AccountService
from app.services.locks import AccountLocks
from app.services.oauth import (
    REFRESH_MARGIN,
    NeedsAuthorization,
    OAuthService,
    ProviderUnavailable,
    RefreshRejected,
)

log = logging.getLogger(__name__)


@dataclass
class RefreshReport:
    refreshed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class TokenRefresher:
    """Periodically refreshes access tokens so accounts stay usable (and their refresh
    tokens stay active) even when no mail client logs in for a long time."""

    def __init__(
        self,
        db: Database,
        crypto: Cryptographer,
        oauth: OAuthService,
        locks: AccountLocks,
        *,
        interval: float = 3600.0,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._db = db
        self._crypto = crypto
        self._oauth = oauth
        self._locks = locks
        self._interval = interval
        self._now = now
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="token-refresher")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("Background token refresh run failed")
            await asyncio.sleep(self._interval)

    async def run_once(self) -> RefreshReport:
        report = RefreshReport()
        async with self._db.session() as session:
            accounts = await AccountService(session, self._crypto).list()
            candidates = [a.id for a in accounts if a.refresh_token_enc]
        for account_id in candidates:
            async with self._locks.get(account_id):
                try:
                    await self._refresh_one(account_id, report)
                except Exception:
                    # e.g. account deleted mid-flight, SQLite locked: log and go on to the rest
                    report.failed.append(self._email_of(account_id, accounts))
                    log.exception("Token refresh for account %s failed unexpectedly", account_id)
        return report

    @staticmethod
    def _email_of(account_id: int, accounts: list) -> str:
        return next(a.email for a in accounts if a.id == account_id)

    async def _refresh_one(self, account_id: int, report: RefreshReport) -> None:
        deadline = self._now() + timedelta(seconds=self._interval) + REFRESH_MARGIN
        async with self._db.session() as session:
            account = await AccountService(session, self._crypto).get(account_id)
            if account is None or not account.refresh_token_enc:
                return
            if account.access_token_expiry and account.access_token_expiry > deadline:
                report.skipped.append(account.email)
                return
            try:
                await self._oauth.refresh(account)
            except NeedsAuthorization as exc:
                report.failed.append(account.email)
                log.error(
                    "Token refresh for %s rejected, re-authorization required: %s",
                    account.email,
                    exc.message,
                )
            except RefreshRejected as exc:
                report.failed.append(account.email)
                log.error(
                    "Token refresh for %s rejected (check client id / client secret): %s",
                    account.email,
                    exc.message,
                )
            except ProviderUnavailable as exc:
                report.failed.append(account.email)
                log.warning(
                    "Token refresh for %s failed, will retry: %s", account.email, exc.message
                )
            else:
                await session.commit()
                report.refreshed.append(account.email)
                log.info("Refreshed token for %s", account.email)
                return
            await session.commit()
