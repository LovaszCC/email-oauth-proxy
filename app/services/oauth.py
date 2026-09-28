import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from app.crypto import Cryptographer
from app.models import Account, utcnow
from app.providers import PROVIDERS

REFRESH_MARGIN = timedelta(seconds=60)
DEFAULT_EXPIRES_IN = 3600


class OAuthError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NeedsAuthorization(OAuthError):
    """No usable refresh token; the admin must authorize the account again."""


class RefreshRejected(OAuthError):
    """The provider rejected the refresh for a reason other than a revoked grant
    (typically an expired/wrong client secret). Tokens are kept."""


class ProviderUnavailable(OAuthError):
    """The token endpoint could not be reached or answered with a server error."""


class OAuthService:
    def __init__(
        self,
        crypto: Cryptographer,
        http: httpx.AsyncClient,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._crypto = crypto
        self._http = http
        self._now = now

    # -- authorization-code flow ---------------------------------------------------------

    def build_authorization_url(self, account: Account) -> str:
        state = secrets.token_urlsafe(32)
        account.pending_state = state
        params = {
            "client_id": account.client_id,
            "redirect_uri": account.redirect_uri,
            "response_type": "code",
            "scope": account.scope,
            "state": state,
        }
        if account.use_pkce:
            verifier = secrets.token_urlsafe(64)
            digest = hashlib.sha256(verifier.encode()).digest()
            params["code_challenge"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            params["code_challenge_method"] = "S256"
            account.pending_code_verifier = verifier
        else:
            account.pending_code_verifier = None
        provider = PROVIDERS.get(account.provider)
        if provider is not None:
            params.update(provider.extra_auth_params)
        separator = "&" if "?" in account.permission_url else "?"
        return f"{account.permission_url}{separator}{urlencode(params)}"

    @staticmethod
    def parse_redirect(text: str) -> dict[str, str]:
        text = text.strip()
        query = urlsplit(text).query if "://" in text else text.lstrip("?")
        return {key: values[0] for key, values in parse_qs(query, keep_blank_values=True).items()}

    async def complete_authorization(self, account: Account, redirect_url: str) -> None:
        params = self.parse_redirect(redirect_url)
        if "error" in params:
            raise OAuthError(params.get("error_description") or params["error"])
        code = params.get("code")
        if not code:
            raise OAuthError("The pasted URL does not contain a code parameter")
        if not account.pending_state or params.get("state") != account.pending_state:
            raise OAuthError("State mismatch – start the authorization again")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": account.redirect_uri,
            "client_id": account.client_id,
        }
        if account.pending_code_verifier:
            data["code_verifier"] = account.pending_code_verifier
        payload = await self._token_request(account, data)
        self._store_tokens(account, payload)
        account.pending_state = None
        account.pending_code_verifier = None
        account.last_error = None

    # -- token use -------------------------------------------------------------------------

    async def get_valid_access_token(self, account: Account) -> str:
        if (
            account.access_token_enc
            and account.access_token_expiry
            and account.access_token_expiry > self._now() + REFRESH_MARGIN
        ):
            return self._crypto.decrypt(account.access_token_enc)
        return await self.refresh(account)

    async def refresh(self, account: Account) -> str:
        if not account.refresh_token_enc:
            raise NeedsAuthorization("Account has not been authorized")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._crypto.decrypt(account.refresh_token_enc),
            "client_id": account.client_id,
        }
        try:
            payload = await self._token_request(account, data)
        except ProviderUnavailable as exc:
            account.last_error = f"Token refresh failed: {exc.message}"
            raise
        except OAuthError as exc:
            if exc.code == "invalid_grant":
                account.clear_tokens()  # also resets last_error, so set it afterwards
                account.last_error = f"Token refresh rejected: {exc.message}"
                raise NeedsAuthorization(exc.message, exc.code) from exc
            account.last_error = f"Token refresh rejected: {exc.message}"
            raise RefreshRejected(exc.message, exc.code) from exc
        self._store_tokens(account, payload)
        account.last_error = None
        return payload["access_token"]

    def revoke(self, account: Account) -> None:
        account.clear_tokens()

    # -- helpers ---------------------------------------------------------------------------

    async def _token_request(self, account: Account, data: dict[str, str]) -> dict:
        if account.client_secret_enc:
            data["client_secret"] = self._crypto.decrypt(account.client_secret_enc)
        try:
            response = await self._http.post(
                account.token_url, data=data, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 500:
            raise ProviderUnavailable(f"HTTP {response.status_code} from token endpoint")
        if response.status_code >= 400 or "error" in payload:
            message = payload.get("error_description") or payload.get("error")
            if message:
                message = " ".join(str(message).split())  # providers send multi-line text
            raise OAuthError(
                message or f"HTTP {response.status_code} from token endpoint",
                payload.get("error"),
            )
        if "access_token" not in payload:
            raise OAuthError("Token response did not include an access token")
        return payload

    def _store_tokens(self, account: Account, payload: dict) -> None:
        account.access_token_enc = self._crypto.encrypt(payload["access_token"])
        expires_in = int(payload.get("expires_in", DEFAULT_EXPIRES_IN))
        account.access_token_expiry = self._now() + timedelta(seconds=expires_in)
        if payload.get("refresh_token"):
            account.refresh_token_enc = self._crypto.encrypt(payload["refresh_token"])
