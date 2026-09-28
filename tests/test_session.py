import asyncio
import base64

import pytest

from app.proxy.server import ImapProxyServer
from app.proxy.session import LoginRejected
from app.proxy.upstream import UpstreamConnection
from tests.test_pipe import EchoServer

GREETING = b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] Email OAuth2 Proxy ready\r\n"


class FakeAuthenticator:
    def __init__(self, echo: EchoServer | None = None) -> None:
        self.echo = echo
        self.usernames: list[str] = []
        self.error: Exception | None = None

    async def authenticate(self, username: str) -> UpstreamConnection:
        self.usernames.append(username)
        if self.error is not None:
            raise self.error
        assert self.echo is not None
        reader, writer = await asyncio.open_connection("127.0.0.1", self.echo.port)
        return UpstreamConnection(reader, writer)


@pytest.fixture
async def echo():
    server = await EchoServer().start()
    yield server
    await server.stop()


@pytest.fixture
async def proxy(echo):
    authenticator = FakeAuthenticator(echo)
    server = ImapProxyServer("127.0.0.1", 0, authenticator, timeout=0.5)
    await server.start()
    yield server, authenticator
    await server.stop()


@pytest.fixture
async def client(proxy):
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    assert await reader.readline() == GREETING
    yield reader, writer
    writer.close()


async def send(client, data: bytes) -> bytes:
    reader, writer = client
    writer.write(data)
    await writer.drain()
    return await asyncio.wait_for(reader.readline(), 2)


async def test_listening_and_port(proxy):
    server, _ = proxy
    assert server.listening is True
    assert server.port > 0
    idle = ImapProxyServer("127.0.0.1", 0, FakeAuthenticator())
    assert idle.listening is False
    assert idle.port == 0
    await idle.stop()  # no-op when never started


async def test_handler_survives_session_crash(proxy, monkeypatch):
    import app.proxy.server as server_module

    class Exploding:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(server_module, "ClientSession", Exploding)
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    assert await asyncio.wait_for(reader.read(), 2) == b""
    writer.close()
    assert server.listening is True


async def test_capability_noop_logout(client):
    reader, writer = client
    assert await send(client, b"A1 CAPABILITY\r\n") == b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n"
    assert await reader.readline() == b"A1 OK CAPABILITY completed\r\n"
    assert await send(client, b"A2 noop\r\n") == b"A2 OK NOOP completed\r\n"
    assert await send(client, b"A3 LOGOUT\r\n") == b"* BYE Logging out\r\n"
    assert await reader.readline() == b"A3 OK LOGOUT completed\r\n"
    assert await reader.read() == b""


async def test_bad_commands(client):
    assert await send(client, b"A1 SELECT INBOX\r\n") == (
        b"A1 BAD Command not allowed before authentication\r\n"
    )
    assert await send(client, b"garbage\r\n") == b"* BAD Invalid command\r\n"
    assert await send(client, b"A2 LOGIN onlyuser\r\n") == (
        b"A2 BAD LOGIN expects username and password\r\n"
    )
    assert await send(client, b'A3 LOGIN "unterminated pw\r\n') == (
        b"A3 BAD Unterminated quoted string\r\n"
    )
    assert await send(client, b"A4 LOGIN {abc} x\r\n") == b"A4 BAD Invalid literal\r\n"
    assert await send(client, b"A5 LOGIN {99999}\r\n") == b"A5 BAD Literal too large\r\n"
    assert await send(client, b"A6 LOGIN {5 x\r\n") == b"A6 BAD Invalid literal\r\n"


async def test_login_quoted_and_atom(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    assert await send(client, b'A1 LOGIN "User@Example.com" "p\\"w"\r\n') == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["User@Example.com"]
    writer.write(b"A2 SELECT INBOX\r\n")
    await writer.drain()
    assert await asyncio.wait_for(reader.readline(), 2) == b"ECHO A2 SELECT INBOX\r\n"


async def test_login_with_literal_arguments(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    assert await send(client, b"A1 LOGIN {16}\r\n") == b"+ Ready\r\n"
    writer.write(b"user@example.com {4}\r\n")
    await writer.drain()
    assert await reader.readline() == b"+ Ready\r\n"
    writer.write(b"pass\r\n")
    await writer.drain()
    assert await reader.readline() == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["user@example.com"]


async def test_login_with_non_synchronizing_literal(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    writer.write(b"A1 LOGIN {16+}\r\nuser@example.com {4+}\r\npass\r\n")
    await writer.drain()
    assert await asyncio.wait_for(reader.readline(), 2) == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["user@example.com"]


async def test_authenticate_plain_initial_response(client, proxy):
    _, authenticator = proxy
    initial = base64.b64encode(b"\x00user@example.com\x00pw").decode()
    assert await send(client, f"A1 AUTHENTICATE PLAIN {initial}\r\n".encode()) == (
        b"A1 OK Logged in\r\n"
    )
    assert authenticator.usernames == ["user@example.com"]


async def test_authenticate_plain_continuation(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    assert await send(client, b"A1 AUTHENTICATE PLAIN\r\n") == b"+ \r\n"
    initial = base64.b64encode(b"authz\x00user@example.com\x00pw").decode()
    assert await send(client, f"{initial}\r\n".encode()) == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["user@example.com"]


async def test_authenticate_errors(client):
    assert await send(client, b"A1 AUTHENTICATE XOAUTH2\r\n") == (
        b"A1 NO Unsupported authentication mechanism\r\n"
    )
    assert await send(client, b"A2 AUTHENTICATE PLAIN\r\n") == b"+ \r\n"
    assert await send(client, b"*\r\n") == b"A2 BAD Authentication cancelled\r\n"
    assert await send(client, b"A3 AUTHENTICATE PLAIN !!!\r\n") == (
        b"A3 BAD Invalid SASL PLAIN response\r\n"
    )
    bad = base64.b64encode(b"no-nul-separators").decode()
    assert await send(client, f"A4 AUTHENTICATE PLAIN {bad}\r\n".encode()) == (
        b"A4 BAD Invalid SASL PLAIN response\r\n"
    )


async def test_login_rejected_allows_retry(client, proxy):
    _, authenticator = proxy
    authenticator.error = LoginRejected("AUTHENTICATIONFAILED", "Unknown account")
    assert await send(client, b"A1 LOGIN nobody pw\r\n") == (
        b"A1 NO [AUTHENTICATIONFAILED] Unknown account\r\n"
    )
    authenticator.error = LoginRejected("UNAVAILABLE", "Token refresh failed")
    assert await send(client, b"A2 LOGIN nobody pw\r\n") == (
        b"A2 NO [UNAVAILABLE] Token refresh failed\r\n"
    )
    authenticator.error = None
    assert await send(client, b"A3 LOGIN user pw\r\n") == b"A3 OK Logged in\r\n"


async def test_unexpected_authenticator_error(client, proxy):
    _, authenticator = proxy
    authenticator.error = RuntimeError("db down")
    assert await send(client, b"A1 LOGIN user pw\r\n") == b"A1 NO [UNAVAILABLE] Internal error\r\n"


async def test_idle_timeout(client):
    reader, _ = client
    assert await asyncio.wait_for(reader.readline(), 2) == b"* BYE Idle timeout\r\n"
    assert await reader.read() == b""


async def test_client_disconnect_before_login(proxy):
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    await reader.readline()
    writer.write(b"A1 LOGIN {4}\r\n")
    await writer.drain()
    await reader.readline()
    writer.close()
    await asyncio.sleep(0.05)
    assert server.listening is True


async def test_pipe_ends_when_client_disconnects(client, proxy, echo):
    _, writer = client
    assert await send(client, b"A1 LOGIN user pw\r\n") == b"A1 OK Logged in\r\n"
    writer.close()
    await asyncio.wait_for(echo.eof.wait(), 2)


async def test_stop_disconnects_active_clients(proxy):
    """stop() must not wait for idle/piped clients to leave on their own (docker stop)."""
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    assert await reader.readline() == GREETING
    await asyncio.wait_for(server.stop(), 0.2)  # well under the 0.5 s idle timeout
    assert await asyncio.wait_for(reader.read(), 1) == b""
    assert server.listening is False
    writer.close()
