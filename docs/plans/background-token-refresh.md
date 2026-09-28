# Background Token Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every authorized account's tokens fresh without waiting for an IMAP login, and log refresh failures (e.g. expired client secret) loudly instead of only storing them on the account.

**Architecture:** A `TokenRefresher` asyncio task started in the FastAPI lifespan runs `run_once()` immediately and then every `REFRESH_INTERVAL` seconds. It refreshes each account whose access token would expire before the next run, under the same per-account lock the proxy login uses (moved into a shared `AccountLocks`). `OAuthService.refresh()` now distinguishes `invalid_grant` (tokens cleared → re-authorize) from every other rejection (tokens kept, `last_error` set → typically fix the client secret). Failures are logged at ERROR/WARNING by both the refresher and the proxy authenticator.

**Tech Stack:** unchanged (asyncio, SQLAlchemy async, httpx, pytest + respx, caplog).

**Spec:** design agreed in chat (2026-09-28): interval default 3600 s; `invalid_client`/other 4xx keeps tokens; ERROR log for rejections, WARNING for provider unreachable; no new endpoints.

## Context

Today tokens refresh lazily on `LOGIN` only (`app/services/oauth.py:get_valid_access_token`). An account nobody logs into for weeks never refreshes, so Office 365's 90-day refresh-token inactivity limit can kill it; and any 4xx on refresh wipes the tokens, so an expired client secret (`invalid_client`) forces a full re-authorization even though only the secret needed replacing. Failures are only visible on the account list page, not in `docker compose logs`.

Branch: `feature/4-background-token-refresh` (from `main` @ 0821208).

## Global Constraints

- `ruff format . && ruff check .` clean; `pytest --cov` → 100 % before the last commit.
- Routers untouched (no new endpoints → no Bruno / endpoint-doc changes). Business logic in `app/services/`.
- No secrets/tokens in log lines: log account email + provider error message only.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Plan file renamed to `docs/plans/background-token-refresh.md` in Task 1.

## Review Focus

1. A refresh rejected with `invalid_client` (expired secret) must keep the refresh token so that replacing the secret in the UI is enough – Task 1 `test_refresh_invalid_client_keeps_tokens`, Task 2 `test_refresh_rejected_keeps_tokens_and_logs`.
2. The refresher and a concurrent IMAP login on the same account must not double-refresh – Task 3 `test_run_once_respects_account_lock`.
3. A refresher crash (e.g. DB locked) must not kill the loop – Task 3 `test_loop_survives_run_once_exception`.
4. Accounts without a refresh token (never authorized / revoked) must be skipped silently – Task 3 `test_run_once_refreshes_only_due_accounts`.
5. Shutdown must cancel the refresher promptly (no hang on `docker stop`) – Task 4 `test_lifespan_starts_and_stops_refresher`.

---

### Task 1: `OAuthService.refresh()` – keep tokens unless `invalid_grant`

**Files:** Modify `app/services/oauth.py`; Test `tests/test_oauth_service.py`.

**Interfaces produced:** `OAuthError(message, code: str | None = None)` gains `.code`; new `class RefreshRejected(OAuthError)` (tokens kept); `_token_request` passes `payload.get("error")` as `code`.

- [ ] **Step 1: Rename plan** `git mv`-free: `mv docs/plans/nifty-skipping-lollipop.md docs/plans/background-token-refresh.md`.
- [ ] **Step 2: Failing tests** (append to `tests/test_oauth_service.py`):

```python
from app.services.oauth import RefreshRejected  # add to imports


@respx.mock
async def test_refresh_invalid_client_keeps_tokens(service, crypto):
    """An expired client secret must not throw away a valid refresh token."""
    account = make_account(
        crypto, refresh_token_enc=crypto.encrypt("RT"), access_token_enc=crypto.encrypt("AT")
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": "invalid_client", "error_description": "AADSTS7000222 expired"},
        )
    )
    with pytest.raises(RefreshRejected, match="AADSTS7000222") as info:
        await service.refresh(account)
    assert info.value.code == "invalid_client"
    assert crypto.decrypt(account.refresh_token_enc) == "RT"
    assert account.last_error == "Token refresh rejected: AADSTS7000222 expired"


@respx.mock
async def test_refresh_4xx_without_error_code_keeps_tokens(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(403, text="forbidden"))
    with pytest.raises(RefreshRejected, match="HTTP 403"):
        await service.refresh(account)
    assert account.refresh_token_enc is not None
```

- [ ] **Step 3: Run** `pytest tests/test_oauth_service.py -k "invalid_client or without_error_code"` → FAIL (ImportError).
- [ ] **Step 4: Implement** in `app/services/oauth.py`:

```python
class OAuthError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class RefreshRejected(OAuthError):
    """The provider rejected the refresh for a reason other than a revoked grant
    (typically an expired/wrong client secret). Tokens are kept."""
```

`refresh()` error branch:

```python
        except OAuthError as exc:
            account.last_error = f"Token refresh rejected: {exc.message}"
            if exc.code == "invalid_grant":
                account.clear_tokens()
                account.last_error = f"Token refresh rejected: {exc.message}"
                raise NeedsAuthorization(exc.message, exc.code) from exc
            raise RefreshRejected(exc.message, exc.code) from exc
```

(`clear_tokens()` resets `last_error`, hence it is set again after it.) In `_token_request` the 4xx branch becomes `raise OAuthError(message or f"HTTP {response.status_code} from token endpoint", payload.get("error"))`.

- [ ] **Step 5: Run** `ruff format . && ruff check . && pytest tests/test_oauth_service.py` → all PASS (existing `test_refresh_invalid_grant_clears_tokens` unchanged).
- [ ] **Step 6: Commit** `feat(oauth): keep tokens when refresh is rejected for a non-invalid_grant reason`.

---

### Task 2: Shared `AccountLocks`, `RefreshRejected` in the proxy, warning logs

**Files:** Create `app/services/locks.py`; Modify `app/proxy/server.py`; Test `tests/test_proxy_authenticator.py`, `tests/test_locks.py`.

**Interfaces produced:** `AccountLocks` with `get(account_id: int) -> asyncio.Lock` (same lock for same id); `ProxyAuthenticator(db, crypto, oauth, connect=..., locks: AccountLocks | None = None)` (creates its own when None).

- [ ] **Step 1: Failing tests**

`tests/test_locks.py`:

```python
from app.services.locks import AccountLocks


def test_same_id_same_lock():
    locks = AccountLocks()
    assert locks.get(1) is locks.get(1)
    assert locks.get(1) is not locks.get(2)
```

Append to `tests/test_proxy_authenticator.py`:

```python
import logging  # add to imports


@respx.mock
async def test_refresh_rejected_keeps_tokens_and_logs(authenticator, db, crypto, caplog):
    account_id = await create_account(db, crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401, json={"error": "invalid_client", "error_description": "secret expired"}
        )
    )
    with caplog.at_level(logging.WARNING), pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert info.value.message == "Token refresh rejected: secret expired"
    account = await load(db, crypto, account_id)
    assert account.refresh_token_enc is not None
    assert account.last_error == "Token refresh rejected: secret expired"
    assert "user@example.com" in caplog.text and "secret expired" in caplog.text


async def test_rejections_are_logged(authenticator, db, crypto, connect, caplog):
    await create_account(db, crypto)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(LoginRejected):
            await authenticator.authenticate("nobody@example.com")
        with pytest.raises(LoginRejected):
            await authenticator.authenticate("user@example.com")
    assert "Unknown account" in caplog.text
    assert "needs authorization" in caplog.text
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

`app/services/locks.py`:

```python
import asyncio
from collections import defaultdict


class AccountLocks:
    """One asyncio.Lock per account id, shared by the IMAP proxy and the background refresher
    so that a token refresh never runs twice concurrently for the same account."""

    def __init__(self) -> None:
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get(self, account_id: int) -> asyncio.Lock:
        return self._locks[account_id]
```

`app/proxy/server.py`: replace the `defaultdict` with `self._locks = locks or AccountLocks()`, use `self._locks.get(account.id)`; add `except RefreshRejected as exc: await session.commit(); raise LoginRejected("AUTHENTICATIONFAILED", f"Token refresh rejected: {exc.message}") from None`; add `log.warning(...)` before each `raise LoginRejected` (`"IMAP login for %s rejected: %s"`), including the unknown-account case (`log.warning("IMAP login for unknown account %s", username)`). Remove the now-unused `defaultdict` import.

- [ ] **Step 4: Run** `ruff format . && ruff check . && pytest tests/test_locks.py tests/test_proxy_authenticator.py tests/test_session.py` → PASS.
- [ ] **Step 5: Commit** `feat(proxy): shared account locks, log rejected logins, map RefreshRejected`.

---

### Task 3: `TokenRefresher`

**Files:** Create `app/services/refresh.py`; Test `tests/test_refresh.py`.

**Interfaces produced:** `TokenRefresher(db, crypto, oauth, locks, *, interval: float = 3600.0, now=utcnow)` with `start()`, `stop()`, `running: bool`, `async run_once() -> RefreshReport`; `@dataclass RefreshReport(refreshed: list[str], skipped: list[str], failed: list[str])`.

- [ ] **Step 1: Failing tests** `tests/test_refresh.py`:

```python
import asyncio
import logging
from datetime import timedelta

import httpx
import pytest
import respx

from app.services.accounts import AccountService
from app.services.locks import AccountLocks
from app.services.oauth import OAuthService
from app.services.refresh import RefreshReport, TokenRefresher
from tests.test_accounts_service import gmail_input
from tests.test_oauth_service import NOW, TOKEN_URL


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def locks() -> AccountLocks:
    return AccountLocks()


@pytest.fixture
def refresher(db, crypto, http, locks) -> TokenRefresher:
    oauth = OAuthService(crypto, http, now=lambda: NOW)
    return TokenRefresher(db, crypto, oauth, locks, interval=3600, now=lambda: NOW)


async def add(db, crypto, email, **fields):
    async with db.session() as session:
        account = await AccountService(session, crypto).create(gmail_input(email=email))
        for key, value in fields.items():
            setattr(account, key, value)
        await session.commit()
        return account.id


async def get(db, crypto, account_id):
    async with db.session() as session:
        return await AccountService(session, crypto).get(account_id)


@respx.mock
async def test_run_once_refreshes_only_due_accounts(refresher, db, crypto, caplog):
    rt = crypto.encrypt("RT")
    unauthorized = await add(db, crypto, "none@example.com")
    fresh = await add(
        db,
        crypto,
        "fresh@example.com",
        refresh_token_enc=rt,
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=2),
    )
    due = await add(
        db,
        crypto,
        "due@example.com",
        refresh_token_enc=rt,
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(minutes=30),
    )
    never = await add(db, crypto, "never@example.com", refresh_token_enc=rt)
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "NEW", "expires_in": 3600})
    )
    with caplog.at_level(logging.INFO):
        report = await refresher.run_once()
    assert route.call_count == 2
    assert report.refreshed == ["due@example.com", "never@example.com"]
    assert report.skipped == ["fresh@example.com"]
    assert report.failed == []
    assert crypto.decrypt((await get(db, crypto, due)).access_token_enc) == "NEW"
    assert (await get(db, crypto, never)).access_token_expiry == NOW + timedelta(hours=1)
    assert (await get(db, crypto, fresh)).access_token_expiry == NOW + timedelta(hours=2)
    assert (await get(db, crypto, unauthorized)).access_token_enc is None
    assert "Refreshed token for due@example.com" in caplog.text


@respx.mock
async def test_run_once_logs_failures(refresher, db, crypto, caplog):
    revoked = await add(db, crypto, "revoked@example.com", refresh_token_enc=crypto.encrypt("RT"))
    badsecret = await add(db, crypto, "secret@example.com", refresh_token_enc=crypto.encrypt("RT"))
    down = await add(db, crypto, "down@example.com", refresh_token_enc=crypto.encrypt("RT"))
    # accounts are processed in email order: down, revoked, secret
    responses = iter(
        [
            httpx.ConnectError("down"),
            httpx.Response(400, json={"error": "invalid_grant", "error_description": "revoked"}),
            httpx.Response(401, json={"error": "invalid_client", "error_description": "expired"}),
        ]
    )

    def side_effect(request):
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item

    respx.post(TOKEN_URL).mock(side_effect=side_effect)
    with caplog.at_level(logging.WARNING):
        report = await refresher.run_once()
    assert report.failed == ["down@example.com", "revoked@example.com", "secret@example.com"]
    assert (await get(db, crypto, revoked)).refresh_token_enc is None
    assert (await get(db, crypto, badsecret)).refresh_token_enc is not None
    assert (await get(db, crypto, down)).refresh_token_enc is not None
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(errors) == 2 and len(warnings) == 1
    assert "re-authorization required" in caplog.text
    assert "check client id / client secret" in caplog.text
    assert "expired" in caplog.text and "revoked" in caplog.text


async def test_run_once_respects_account_lock(refresher, db, crypto, locks):
    account_id = await add(db, crypto, "busy@example.com", refresh_token_enc=crypto.encrypt("RT"))
    lock = locks.get(account_id)
    await lock.acquire()
    task = asyncio.create_task(refresher.run_once())
    await asyncio.sleep(0.05)
    assert not task.done()  # waiting for the login holding the lock
    lock.release()
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "N"}))
        report = await asyncio.wait_for(task, 2)
    assert report.refreshed == ["busy@example.com"]


async def test_run_once_skips_account_deleted_meanwhile(refresher, db, crypto, monkeypatch):
    account_id = await add(db, crypto, "gone@example.com", refresh_token_enc=crypto.encrypt("RT"))
    real_get = AccountService.get

    async def get_then_delete(self, aid):
        account = await real_get(self, aid)
        if account is not None:
            await self.delete(account)
            await self._session.commit()
        return None

    monkeypatch.setattr(AccountService, "get", get_then_delete)
    report = await refresher.run_once()
    assert report == RefreshReport()
    monkeypatch.undo()
    assert await get(db, crypto, account_id) is None


async def test_loop_runs_periodically_and_stops(db, crypto, http, locks):
    calls = 0

    class CountingRefresher(TokenRefresher):
        async def run_once(self):
            nonlocal calls
            calls += 1
            return await super().run_once()

    refresher = CountingRefresher(db, crypto, OAuthService(crypto, http), locks, interval=0.01)
    assert refresher.running is False
    refresher.start()
    assert refresher.running is True
    await asyncio.sleep(0.08)
    await asyncio.wait_for(refresher.stop(), 1)
    assert refresher.running is False
    assert calls >= 3
    await refresher.stop()  # idempotent


async def test_loop_survives_run_once_exception(db, crypto, http, locks, caplog):
    refresher = TokenRefresher(db, crypto, OAuthService(crypto, http), locks, interval=0.01)
    calls = 0

    async def boom():
        nonlocal calls
        calls += 1
        raise RuntimeError("db locked")

    refresher.run_once = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR):
        refresher.start()
        await asyncio.sleep(0.08)
        await refresher.stop()
    assert calls >= 2
    assert "db locked" in caplog.text
```

- [ ] **Step 2: Run** `pytest tests/test_refresh.py` → FAIL (ImportError).
- [ ] **Step 3: Implement** `app/services/refresh.py`:

```python
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
                await self._refresh_one(account_id, report)
        return report

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
                report.refreshed.append(account.email)
                log.info("Refreshed token for %s", account.email)
            await session.commit()
```

- [ ] **Step 4: Run** `ruff format . && ruff check . && pytest tests/test_refresh.py` → PASS.
- [ ] **Step 5: Commit** `feat: add background token refresher`.

---

### Task 4: Wiring, setting, docs, coverage gate

**Files:** Modify `app/settings.py`, `app/state.py`, `app/main.py`, `.env.example`, `README.md`, `docs/deployment.md`; Test `tests/test_app.py`, `tests/test_settings.py`.

- [ ] **Step 1: Failing tests**

`tests/test_settings.py` – in `test_defaults_and_required` add `assert s.refresh_interval == 3600`.

`tests/test_app.py`:

```python
async def test_lifespan_starts_and_stops_refresher(app_settings):
    import asyncio

    from asgi_lifespan import LifespanManager

    application = create_app(app_settings)
    container = application.state.container
    async with LifespanManager(application):
        assert container.refresher.running is True
    assert container.refresher.running is False
    assert container.proxy.listening is False
```

- [ ] **Step 2: Run** → FAIL (`refresh_interval` / `refresher` missing).
- [ ] **Step 3: Implement**
  - `app/settings.py`: `refresh_interval: int = 3600  # seconds between background token refresh runs`.
  - `app/state.py`: add `refresher: TokenRefresher` field.
  - `app/main.py`: `locks = AccountLocks()`; `ProxyAuthenticator(db, crypto, oauth, locks=locks)`; `refresher = TokenRefresher(db, crypto, oauth, locks, interval=settings.refresh_interval)`; lifespan: `refresher.start()` after `proxy.start()`, `await refresher.stop()` first in the `finally`.
  - `.env.example`: `REFRESH_INTERVAL=3600`.
  - `README.md` env table row: `| REFRESH_INTERVAL | 3600 | seconds between background token refresh runs; every authorized account is refreshed before its access token expires, so inactive accounts stay valid |`. Security/notes section: one bullet "Refresh failures are logged at ERROR (`docker compose logs`) and shown on the account list; an expired client secret only needs the secret replaced on the Edit page, a revoked grant needs *Authorize* again."
  - `docs/deployment.md`: add `REFRESH_INTERVAL` to §3 `.env` sample as optional, and in §8 cheat sheet a row `| Token refresh problems | grep "Token refresh" in logs – ERROR = fix secret / re-authorize, WARNING = provider unreachable, retried next run |`.
- [ ] **Step 4: Run** `ruff format . && ruff check . && pytest --cov` → 100 %, all PASS. Fix any gap with a test (no pragmas).
- [ ] **Step 5: Docker check** `docker build --load -t email-oauth2-proxy-web . && docker run --rm -d --name eop -e ADMIN_PASSWORD=pw -e SECRET_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") -e REFRESH_INTERVAL=5 -e LOG_LEVEL=DEBUG -p 18080:8080 email-oauth2-proxy-web; sleep 8; docker logs eop | grep -i refresh; docker stop eop` → the log shows the refresher running with 0 accounts and `docker stop` returns in ≈1 s.
- [ ] **Step 6: Commit** `feat: run token refresher from the app lifespan; document REFRESH_INTERVAL`.

## Verification

- `pytest --cov` 100 %, ruff clean.
- Container with `REFRESH_INTERVAL=5 LOG_LEVEL=DEBUG`: add + authorize a real account → within 5 s the log shows `Refreshed token for <email>` or a skip; break the client secret on the Edit page → next run logs `ERROR … rejected (check client id / client secret): …`, account list shows Error, refresh token still stored; fix the secret → next run logs `Refreshed token`.
