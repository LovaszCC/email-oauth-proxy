import asyncio
import base64
import ssl

import pytest

from app.proxy.upstream import (
    UpstreamAuthError,
    UpstreamConnectionError,
    connect_and_authenticate,
)
from tests.fake_imap import FakeImapServer


@pytest.fixture
async def make_server(server_ssl):
    servers: list[FakeImapServer] = []

    async def factory(mode: str = "ok") -> FakeImapServer:
        server = await FakeImapServer(server_ssl, mode).start()
        servers.append(server)
        return server

    yield factory
    for server in servers:
        await server.stop()


async def test_authenticate_ok(make_server, client_ssl):
    server = await make_server("ok")
    conn = await connect_and_authenticate(
        "localhost", server.port, "u@example.com", "tok", ssl_context=client_ssl
    )
    assert (
        base64.b64decode(server.auth_strings[0]) == b"user=u@example.com\x01auth=Bearer tok\x01\x01"
    )
    conn.writer.write(b"A2 NOOP\r\n")
    await conn.writer.drain()
    assert await conn.reader.readline() == b"ECHO A2 NOOP\r\n"
    await conn.close()
    await asyncio.wait_for(server.closed.wait(), 2)


async def test_authenticate_no(make_server, client_ssl):
    server = await make_server("no")
    with pytest.raises(UpstreamAuthError, match=r"^Invalid credentials \(Failure\)$"):
        await connect_and_authenticate("localhost", server.port, "u", "t", ssl_context=client_ssl)


async def test_authenticate_handles_continuation_error(make_server, client_ssl):
    server = await make_server("continuation")
    with pytest.raises(UpstreamAuthError, match="status 400"):
        await connect_and_authenticate("localhost", server.port, "u", "t", ssl_context=client_ssl)
    assert server.received[1] == b"\r\n"


async def test_connection_refused(client_ssl):
    with pytest.raises(UpstreamConnectionError):
        await connect_and_authenticate("localhost", 1, "u", "t", ssl_context=client_ssl)


async def test_tls_verification_failure(make_server):
    server = await make_server("ok")
    with pytest.raises(UpstreamConnectionError, match="CERTIFICATE_VERIFY_FAILED"):
        await connect_and_authenticate("localhost", server.port, "u", "t")


async def test_bad_greeting(make_server, client_ssl):
    server = await make_server("bad_greeting")
    with pytest.raises(UpstreamConnectionError, match="greeting"):
        await connect_and_authenticate("localhost", server.port, "u", "t", ssl_context=client_ssl)


async def test_closed_during_auth(make_server, client_ssl):
    server = await make_server("close")
    with pytest.raises(UpstreamConnectionError, match="closed"):
        await connect_and_authenticate("localhost", server.port, "u", "t", ssl_context=client_ssl)


async def test_timeout(make_server, client_ssl):
    server = await make_server("silent")
    with pytest.raises(UpstreamConnectionError, match="Timed out"):
        await connect_and_authenticate(
            "localhost", server.port, "u", "t", ssl_context=client_ssl, timeout=0.2
        )


def test_default_ssl_context_is_verifying():
    from app.proxy.upstream import default_ssl_context

    ctx = default_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


async def test_readline_socket_error():
    from app.proxy.upstream import _readline

    reader = asyncio.StreamReader()
    reader.set_exception(ConnectionResetError("reset"))
    with pytest.raises(UpstreamConnectionError, match="reset"):
        await _readline(reader, 1.0)
