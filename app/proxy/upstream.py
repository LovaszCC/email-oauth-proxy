import asyncio
import contextlib
import ssl
from dataclasses import dataclass

from app.proxy.xoauth2 import build_xoauth2_string, decode_xoauth2_error

AUTH_TAG = b"P1"


class UpstreamConnectionError(Exception):
    """Could not reach the IMAP server, or it misbehaved before authentication."""


class UpstreamAuthError(Exception):
    """The IMAP server rejected the XOAUTH2 credentials."""


@dataclass
class UpstreamConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    async def close(self) -> None:
        self.writer.close()
        with contextlib.suppress(Exception):
            await self.writer.wait_closed()


def default_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


async def connect_and_authenticate(
    host: str,
    port: int,
    email: str,
    access_token: str,
    *,
    ssl_context: ssl.SSLContext | None = None,
    timeout: float = 30.0,
) -> UpstreamConnection:
    context = ssl_context or default_ssl_context()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=context), timeout
        )
    except TimeoutError as exc:
        raise UpstreamConnectionError(f"Timed out connecting to {host}:{port}") from exc
    except OSError as exc:
        raise UpstreamConnectionError(f"{host}:{port}: {exc}") from exc
    connection = UpstreamConnection(reader, writer)
    try:
        await _authenticate(connection, email, access_token, timeout)
    except BaseException:
        await connection.close()
        raise
    return connection


async def _authenticate(
    connection: UpstreamConnection, email: str, access_token: str, timeout: float
) -> None:
    reader, writer = connection.reader, connection.writer
    greeting = await _readline(reader, timeout)
    if not greeting.startswith(b"* OK"):
        text = greeting.decode(errors="replace").strip()
        raise UpstreamConnectionError(f"Unexpected greeting: {text}")
    auth_string = build_xoauth2_string(email, access_token).encode()
    writer.write(AUTH_TAG + b" AUTHENTICATE XOAUTH2 " + auth_string + b"\r\n")
    await writer.drain()
    pending_error: str | None = None
    while True:
        line = await _readline(reader, timeout)
        if line.startswith(b"+"):
            pending_error = decode_xoauth2_error(line[1:].strip().decode(errors="replace"))
            writer.write(b"\r\n")
            await writer.drain()
            continue
        if not line.startswith(AUTH_TAG + b" "):
            continue  # untagged response (e.g. * CAPABILITY)
        response = line[len(AUTH_TAG) + 1 :].decode(errors="replace").strip()
        if response.upper().startswith("OK"):
            return
        raise UpstreamAuthError(pending_error or _strip_response_code(response))


async def _readline(reader: asyncio.StreamReader, timeout: float) -> bytes:
    try:
        line = await asyncio.wait_for(reader.readline(), timeout)
    except TimeoutError as exc:
        raise UpstreamConnectionError("Timed out waiting for the IMAP server") from exc
    except OSError as exc:
        raise UpstreamConnectionError(str(exc)) from exc
    if not line:
        raise UpstreamConnectionError("Connection closed by the IMAP server during authentication")
    return line


def _strip_response_code(response: str) -> str:
    """'NO [AUTHENTICATIONFAILED] Invalid credentials' -> 'Invalid credentials'."""
    _, _, text = response.partition(" ")
    if text.startswith("["):
        _, _, text = text.partition("] ")
    return text or response
