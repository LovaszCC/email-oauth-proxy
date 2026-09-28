import asyncio
import base64
import binascii
import contextlib
import logging
from typing import Protocol

from app.proxy.pipe import pipe
from app.proxy.upstream import UpstreamConnection

log = logging.getLogger(__name__)

GREETING = b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] Email OAuth2 Proxy ready\r\n"
CAPABILITIES = b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n"
MAX_LITERAL = 8192


class LoginRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class Authenticator(Protocol):
    async def authenticate(self, username: str) -> UpstreamConnection: ...


class ClientSession:
    """Handles one mail-client connection until it is authenticated, then pipes it upstream."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        authenticator: Authenticator,
        *,
        timeout: float = 60.0,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._authenticator = authenticator
        self._timeout = timeout

    async def run(self) -> None:
        try:
            await self._send(GREETING)
            while True:
                line = await self._readline()
                if not line:
                    return
                if await self._handle_line(line):
                    return
        except TimeoutError:
            with contextlib.suppress(OSError):
                await self._send(b"* BYE Idle timeout\r\n")
        except (asyncio.IncompleteReadError, OSError):
            return

    # -- command dispatch ------------------------------------------------------------------

    async def _handle_line(self, line: bytes) -> bool:
        """Returns True when the session is finished (LOGOUT or piped to completion)."""
        parts = line.rstrip(b"\r\n").split(b" ", 2)
        if len(parts) < 2 or not parts[0]:
            await self._send(b"* BAD Invalid command\r\n")
            return False
        tag, command = parts[0], parts[1].upper()
        rest = parts[2] if len(parts) > 2 else b""
        match command:
            case b"CAPABILITY":
                await self._send(CAPABILITIES + tag + b" OK CAPABILITY completed\r\n")
            case b"NOOP":
                await self._send(tag + b" OK NOOP completed\r\n")
            case b"LOGOUT":
                await self._send(b"* BYE Logging out\r\n" + tag + b" OK LOGOUT completed\r\n")
                return True
            case b"LOGIN":
                return await self._handle_login(tag, rest)
            case b"AUTHENTICATE":
                return await self._handle_authenticate(tag, rest)
            case _:
                await self._send(tag + b" BAD Command not allowed before authentication\r\n")
        return False

    async def _handle_login(self, tag: bytes, rest: bytes) -> bool:
        try:
            args = await self._parse_astrings(rest)
        except ValueError as exc:
            await self._send(tag + b" BAD " + str(exc).encode() + b"\r\n")
            return False
        if len(args) != 2:
            await self._send(tag + b" BAD LOGIN expects username and password\r\n")
            return False
        return await self._login(tag, args[0])

    async def _handle_authenticate(self, tag: bytes, rest: bytes) -> bool:
        mechanism, _, initial = rest.partition(b" ")
        if mechanism.upper() != b"PLAIN":
            await self._send(tag + b" NO Unsupported authentication mechanism\r\n")
            return False
        if not initial:
            await self._send(b"+ \r\n")
            initial = (await self._readline()).strip()
            if initial == b"*":
                await self._send(tag + b" BAD Authentication cancelled\r\n")
                return False
        try:
            _, username, _ = base64.b64decode(initial, validate=True).split(b"\x00")
        except (binascii.Error, ValueError):
            await self._send(tag + b" BAD Invalid SASL PLAIN response\r\n")
            return False
        return await self._login(tag, username.decode(errors="replace"))

    async def _login(self, tag: bytes, username: str) -> bool:
        try:
            upstream = await self._authenticator.authenticate(username)
        except LoginRejected as exc:
            await self._send(tag + f" NO [{exc.code}] {exc.message}\r\n".encode())
            return False
        except Exception:
            log.exception("Unexpected error while authenticating %s", username)
            await self._send(tag + b" NO [UNAVAILABLE] Internal error\r\n")
            return False
        await self._send(tag + b" OK Logged in\r\n")
        log.info("Proxying IMAP session for %s", username)
        await pipe(self._reader, self._writer, upstream.reader, upstream.writer)
        return True

    # -- IMAP argument parsing --------------------------------------------------------------

    async def _parse_astrings(self, data: bytes) -> list[str]:
        """Parse atoms, quoted strings and literals (RFC 3501 astring) from a command line."""
        args: list[str] = []
        pos = 0
        while True:
            while pos < len(data) and data[pos : pos + 1] == b" ":
                pos += 1
            if pos >= len(data):
                return args
            char = data[pos : pos + 1]
            if char == b'"':
                value, pos = self._parse_quoted(data, pos + 1)
                args.append(value)
            elif char == b"{":
                args.append(await self._parse_literal(data, pos))
                data = (await self._readline()).rstrip(b"\r\n")
                pos = 0
            else:
                end = data.find(b" ", pos)
                end = len(data) if end == -1 else end
                args.append(data[pos:end].decode(errors="replace"))
                pos = end

    @staticmethod
    def _parse_quoted(data: bytes, pos: int) -> tuple[str, int]:
        buffer = bytearray()
        while pos < len(data):
            char = data[pos : pos + 1]
            if char == b"\\":
                buffer += data[pos + 1 : pos + 2]
                pos += 2
            elif char == b'"':
                return buffer.decode(errors="replace"), pos + 1
            else:
                buffer += char
                pos += 1
        raise ValueError("Unterminated quoted string")

    async def _parse_literal(self, data: bytes, pos: int) -> str:
        close = data.find(b"}", pos)
        if close == -1:
            raise ValueError("Invalid literal")
        spec = data[pos + 1 : close]
        synchronizing = not spec.endswith(b"+")
        try:
            length = int(spec.rstrip(b"+"))
        except ValueError:
            raise ValueError("Invalid literal") from None
        if length > MAX_LITERAL:
            raise ValueError("Literal too large")
        if synchronizing:
            await self._send(b"+ Ready\r\n")
        literal = await asyncio.wait_for(self._reader.readexactly(length), self._timeout)
        return literal.decode(errors="replace")

    # -- io ---------------------------------------------------------------------------------

    async def _readline(self) -> bytes:
        return await asyncio.wait_for(self._reader.readline(), self._timeout)

    async def _send(self, data: bytes) -> None:
        self._writer.write(data)
        await self._writer.drain()
