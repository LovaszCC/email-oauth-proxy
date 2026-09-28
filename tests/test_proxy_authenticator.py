import logging
from datetime import timedelta

import httpx
import pytest
import respx

from app.proxy.server import ProxyAuthenticator
from app.proxy.session import LoginRejected
from app.proxy.upstream import UpstreamAuthError, UpstreamConnection, UpstreamConnectionError
from app.services.accounts import AccountService
from app.services.oauth import OAuthService
from tests.test_accounts_service import gmail_input
from tests.test_oauth_service import NOW, TOKEN_URL


class FakeConnect:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def __call__(self, host, port, email, token, **kwargs):
        self.calls.append((host, port, email, token))
        if self.error:
            raise self.error
        return UpstreamConnection(reader=None, writer=None)  # type: ignore[arg-type]


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def connect() -> FakeConnect:
    return FakeConnect()


@pytest.fixture
def authenticator(db, crypto, http, connect) -> ProxyAuthenticator:
    oauth = OAuthService(crypto, http, now=lambda: NOW)
    return ProxyAuthenticator(db, crypto, oauth, connect=connect)


async def create_account(db, crypto, **fields):
    async with db.session() as session:
        account = await AccountService(session, crypto).create(gmail_input())
        for key, value in fields.items():
            setattr(account, key, value)
        await session.commit()
        return account.id


async def load(db, crypto, account_id):
    async with db.session() as session:
        return await AccountService(session, crypto).get(account_id)


async def test_unknown_account(authenticator):
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("nobody@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert info.value.message == "Unknown account"


async def test_needs_authorization(authenticator, db, crypto):
    account_id = await create_account(db, crypto)
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("USER@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert "web UI" in info.value.message
    assert (await load(db, crypto, account_id)).last_error is None


@respx.mock
async def test_provider_unavailable(authenticator, db, crypto):
    account_id = await create_account(db, crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "UNAVAILABLE"
    assert (await load(db, crypto, account_id)).last_error.startswith("Token refresh failed")


async def test_success_updates_activity(authenticator, db, crypto, connect):
    account_id = await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=1),
        last_error="old",
    )
    conn = await authenticator.authenticate("user@example.com")
    assert isinstance(conn, UpstreamConnection)
    assert connect.calls == [("imap.gmail.com", 993, "user@example.com", "AT")]
    account = await load(db, crypto, account_id)
    assert account.last_error is None
    assert account.last_activity is not None


async def test_upstream_connection_error(authenticator, db, crypto, connect):
    account_id = await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=1),
    )
    connect.error = UpstreamConnectionError("refused")
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "UNAVAILABLE"
    assert info.value.message == "Upstream connection failed"
    assert (await load(db, crypto, account_id)).last_error == "Upstream connection failed: refused"


async def test_login_upstream_auth_error_sets_last_error(authenticator, db, crypto, connect):
    account_id = await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=1),
    )
    connect.error = UpstreamAuthError("status 400 (scope: x)")
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert info.value.message == "status 400 (scope: x)"
    account = await load(db, crypto, account_id)
    assert account.last_error == "Upstream rejected authentication: status 400 (scope: x)"


@respx.mock
async def test_concurrent_logins_refresh_once(authenticator, db, crypto, connect):
    """Mail clients open several connections at once; only one may hit the token endpoint."""
    await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("OLD"),
        access_token_expiry=NOW - timedelta(seconds=1),
    )
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600}
        )
    )
    import asyncio

    await asyncio.gather(*(authenticator.authenticate("user@example.com") for _ in range(3)))
    assert route.call_count == 1
    assert [call[3] for call in connect.calls] == ["NEW", "NEW", "NEW"]


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
