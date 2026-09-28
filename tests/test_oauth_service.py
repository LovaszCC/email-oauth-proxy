import base64
import hashlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.models import Account
from app.services.oauth import (
    NeedsAuthorization,
    OAuthError,
    OAuthService,
    ProviderUnavailable,
    RefreshRejected,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
NOW = datetime(2026, 9, 28, 12, 0, 0)


def make_account(crypto, **overrides) -> Account:
    values = dict(
        email="user@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url=TOKEN_URL,
        scope="https://mail.google.com/",
        client_id="cid",
        client_secret_enc=crypto.encrypt("csecret"),
        redirect_uri="http://localhost",
        use_pkce=False,
    )
    values.update(overrides)
    return Account(**values)


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def service(crypto, http) -> OAuthService:
    return OAuthService(crypto, http, now=lambda: NOW)


def test_build_url_gmail(service, crypto):
    account = make_account(crypto)
    url = service.build_authorization_url(account)
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.scheme == "https" and parts.netloc == "accounts.google.com"
    assert query["client_id"] == "cid"
    assert query["redirect_uri"] == "http://localhost"
    assert query["response_type"] == "code"
    assert query["scope"] == "https://mail.google.com/"
    assert query["state"] == account.pending_state
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert "code_challenge" not in query
    assert account.pending_code_verifier is None


def test_build_url_pkce_and_existing_query(service, crypto):
    account = make_account(
        crypto, provider="custom", use_pkce=True, permission_url="https://x.test/auth?tenant=1"
    )
    url = service.build_authorization_url(account)
    assert url.startswith("https://x.test/auth?tenant=1&")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(account.pending_code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert query["code_challenge"] == expected
    assert query["code_challenge_method"] == "S256"
    assert "access_type" not in query


def test_build_url_unknown_provider_has_no_extras(service, crypto):
    account = make_account(crypto, provider="legacy")
    url = service.build_authorization_url(account)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert "access_type" not in query and query["state"] == account.pending_state


@pytest.mark.parametrize(
    "text",
    [
        "http://localhost/?code=abc&state=st",
        "code=abc&state=st",
        "?code=abc&state=st",
        "  http://localhost/?state=st&code=abc  ",
    ],
)
def test_parse_redirect(text):
    assert OAuthService.parse_redirect(text) == {"code": "abc", "state": "st"}


@respx.mock
async def test_complete_success_stores_tokens(service, crypto):
    account = make_account(crypto, use_pkce=True)
    service.build_authorization_url(account)
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 100}
        )
    )
    await service.complete_authorization(
        account, f"http://localhost/?code=abc&state={account.pending_state}"
    )
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["abc"]
    assert body["client_secret"] == ["csecret"]
    assert body["redirect_uri"] == ["http://localhost"]
    assert len(body["code_verifier"][0]) >= 43
    assert crypto.decrypt(account.access_token_enc) == "AT"
    assert crypto.decrypt(account.refresh_token_enc) == "RT"
    assert account.access_token_expiry == NOW + timedelta(seconds=100)
    assert account.pending_state is None
    assert account.pending_code_verifier is None
    assert account.last_error is None


@respx.mock
async def test_complete_without_secret_or_pkce_or_expires(service, crypto):
    account = make_account(crypto, client_secret_enc=None)
    service.build_authorization_url(account)
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})
    )
    await service.complete_authorization(account, f"code=abc&state={account.pending_state}")
    body = parse_qs(route.calls.last.request.content.decode())
    assert "client_secret" not in body
    assert "code_verifier" not in body
    assert account.access_token_expiry == NOW + timedelta(seconds=3600)


async def test_complete_surfaces_provider_error(service, crypto):
    account = make_account(crypto, refresh_token_enc="keep")
    service.build_authorization_url(account)
    with pytest.raises(OAuthError, match="User denied"):
        await service.complete_authorization(
            account, "http://localhost/?error=access_denied&error_description=User+denied"
        )
    with pytest.raises(OAuthError, match="access_denied"):
        await service.complete_authorization(account, "http://localhost/?error=access_denied")
    assert account.refresh_token_enc == "keep"
    assert account.pending_state is not None


async def test_complete_requires_code(service, crypto):
    account = make_account(crypto)
    service.build_authorization_url(account)
    with pytest.raises(OAuthError, match="code"):
        await service.complete_authorization(account, "http://localhost/?state=x")


async def test_complete_rejects_state_mismatch(service, crypto):
    account = make_account(crypto)
    with pytest.raises(OAuthError, match="State mismatch"):
        await service.complete_authorization(account, "http://localhost/?code=abc&state=x")
    service.build_authorization_url(account)
    with pytest.raises(OAuthError, match="State mismatch"):
        await service.complete_authorization(account, "http://localhost/?code=abc&state=wrong")


@respx.mock
async def test_complete_token_endpoint_errors(service, crypto):
    account = make_account(crypto)
    service.build_authorization_url(account)
    url = f"code=abc&state={account.pending_state}"
    route = respx.post(TOKEN_URL)

    route.mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Bad code"}
        )
    )
    with pytest.raises(OAuthError, match="Bad code"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(400, json={"error": "invalid_client"}))
    with pytest.raises(OAuthError, match="invalid_client"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(403, text="nope"))
    with pytest.raises(OAuthError, match="HTTP 403"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(200, json={"token_type": "Bearer"}))
    with pytest.raises(OAuthError, match="access token"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(ProviderUnavailable, match="HTTP 502"):
        await service.complete_authorization(account, url)

    route.mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable, match="ConnectError"):
        await service.complete_authorization(account, url)

    assert account.access_token_enc is None
    assert account.pending_state is not None


async def test_get_valid_access_token_uses_cache(service, crypto):
    account = make_account(
        crypto,
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(seconds=61),
    )
    assert await service.get_valid_access_token(account) == "AT"


@respx.mock
async def test_get_valid_access_token_refreshes_when_expiring(service, crypto):
    account = make_account(
        crypto,
        access_token_enc=crypto.encrypt("OLD"),
        access_token_expiry=NOW + timedelta(seconds=60),
        refresh_token_enc=crypto.encrypt("RT"),
        last_error="stale",
    )
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "NEW", "expires_in": 10})
    )
    assert await service.get_valid_access_token(account) == "NEW"
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["RT"]
    assert body["client_id"] == ["cid"]
    assert body["client_secret"] == ["csecret"]
    assert account.last_error is None


@respx.mock
async def test_refresh_keeps_old_refresh_token_when_absent(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "NEW"}))
    await service.refresh(account)
    assert crypto.decrypt(account.refresh_token_enc) == "RT"


@respx.mock
async def test_refresh_rotates_refresh_token(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2"})
    )
    await service.refresh(account)
    assert crypto.decrypt(account.refresh_token_enc) == "RT2"


async def test_refresh_without_refresh_token(service, crypto):
    account = make_account(crypto)
    with pytest.raises(NeedsAuthorization, match="not been authorized"):
        await service.get_valid_access_token(account)
    assert account.last_error is None


@respx.mock
async def test_refresh_invalid_grant_clears_tokens(service, crypto):
    account = make_account(
        crypto, refresh_token_enc=crypto.encrypt("RT"), access_token_enc=crypto.encrypt("AT")
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Token revoked"}
        )
    )
    with pytest.raises(NeedsAuthorization, match="Token revoked"):
        await service.refresh(account)
    assert account.refresh_token_enc is None
    assert account.access_token_enc is None
    assert account.last_error == "Token refresh rejected: Token revoked"


@respx.mock
async def test_refresh_network_error_keeps_tokens(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderUnavailable):
        await service.refresh(account)
    assert crypto.decrypt(account.refresh_token_enc) == "RT"
    assert account.last_error.startswith("Token refresh failed: ReadTimeout")


def test_revoke(service, crypto):
    account = make_account(crypto, refresh_token_enc="x", pending_state="s", last_error="e")
    service.revoke(account)
    assert account.refresh_token_enc is None
    assert account.pending_state is None
    assert account.last_error is None


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


@respx.mock
async def test_provider_error_message_is_single_line(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            401,
            json={
                "error": "invalid_client",
                "error_description": "AADSTS7000222: expired.\r\nTrace ID: abc\r\nTimestamp: x",
            },
        )
    )
    with pytest.raises(RefreshRejected) as info:
        await service.refresh(account)
    assert info.value.message == "AADSTS7000222: expired. Trace ID: abc Timestamp: x"
    assert (
        account.last_error
        == "Token refresh rejected: AADSTS7000222: expired. Trace ID: abc Timestamp: x"
    )
