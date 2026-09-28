import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from app.crypto import Cryptographer
from app.db import Database
from app.models import utcnow
from app.proxy.session import Authenticator, ClientSession, LoginRejected
from app.proxy.upstream import (
    UpstreamAuthError,
    UpstreamConnection,
    UpstreamConnectionError,
    connect_and_authenticate,
)
from app.services.accounts import AccountService
from app.services.oauth import NeedsAuthorization, OAuthService, ProviderUnavailable

log = logging.getLogger(__name__)

ConnectFn = Callable[..., Awaitable[UpstreamConnection]]


class ProxyAuthenticator:
    """Resolves a LOGIN username to an authenticated upstream IMAP connection."""

    def __init__(
        self,
        db: Database,
        crypto: Cryptographer,
        oauth: OAuthService,
        connect: ConnectFn = connect_and_authenticate,
    ) -> None:
        self._db = db
        self._crypto = crypto
        self._oauth = oauth
        self._connect = connect

    async def authenticate(self, username: str) -> UpstreamConnection:
        async with self._db.session() as session:
            accounts = AccountService(session, self._crypto)
            account = await accounts.get_by_email(username)
            if account is None:
                raise LoginRejected("AUTHENTICATIONFAILED", "Unknown account")
            try:
                token = await self._oauth.get_valid_access_token(account)
            except NeedsAuthorization:
                await session.commit()
                raise LoginRejected(
                    "AUTHENTICATIONFAILED", "Account needs authorization in the web UI"
                ) from None
            except ProviderUnavailable:
                await session.commit()
                raise LoginRejected("UNAVAILABLE", "Token refresh failed") from None
            try:
                connection = await self._connect(
                    account.imap_host, account.imap_port, account.email, token
                )
            except UpstreamConnectionError as exc:
                account.last_error = f"Upstream connection failed: {exc}"
                await session.commit()
                raise LoginRejected("UNAVAILABLE", "Upstream connection failed") from exc
            except UpstreamAuthError as exc:
                account.last_error = f"Upstream rejected authentication: {exc}"
                await session.commit()
                raise LoginRejected("AUTHENTICATIONFAILED", str(exc)) from exc
            account.last_activity = utcnow()
            account.last_error = None
            await session.commit()
            return connection


class ImapProxyServer:
    def __init__(
        self, host: str, port: int, authenticator: Authenticator, *, timeout: float = 60.0
    ) -> None:
        self._host = host
        self._port = port
        self._authenticator = authenticator
        self._timeout = timeout
        self._server: asyncio.AbstractServer | None = None

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def port(self) -> int:
        if self._server is None:
            return 0
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        log.info("IMAP proxy listening on %s:%s", self._host, self.port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.debug("Client connected from %s", peer)
        session = ClientSession(reader, writer, self._authenticator, timeout=self._timeout)
        try:
            await session.run()
        except Exception:
            log.exception("Unhandled error in client session from %s", peer)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            log.debug("Client from %s disconnected", peer)
