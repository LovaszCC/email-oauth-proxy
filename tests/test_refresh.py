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
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "N"}))
        lock.release()
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
