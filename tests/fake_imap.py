import asyncio
import base64
import json
import ssl


class FakeImapServer:
    """Speaks just enough IMAP to exercise XOAUTH2 and the byte pipe."""

    def __init__(self, ssl_context: ssl.SSLContext | None, mode: str = "ok") -> None:
        self.ssl_context = ssl_context
        self.mode = mode
        self.received: list[bytes] = []
        self.auth_strings: list[str] = []
        self.closed = asyncio.Event()
        self.port = 0
        self._stop = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> "FakeImapServer":
        self._server = await asyncio.start_server(
            self._handle, "127.0.0.1", 0, ssl=self.ssl_context
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        self._stop.set()
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._conversation(reader, writer)
        finally:
            writer.close()
            self.closed.set()

    async def _conversation(self, reader, writer) -> None:
        if self.mode == "silent":
            await self._stop.wait()
            return
        if self.mode == "bad_greeting":
            writer.write(b"* BYE go away\r\n")
            await writer.drain()
            return
        writer.write(b"* OK Fake IMAP ready\r\n")
        await writer.drain()
        line = await reader.readline()
        self.received.append(line)
        tag, _, rest = line.decode().rstrip("\r\n").partition(" ")
        self.auth_strings.append(rest.split(" ", 2)[2])
        if self.mode == "close":
            return
        if self.mode == "no":
            writer.write(
                f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials (Failure)\r\n".encode()
            )
            await writer.drain()
            return
        if self.mode == "continuation":
            error = {"status": "400", "schemes": "Bearer", "scope": "https://mail.google.com/"}
            encoded = base64.b64encode(json.dumps(error).encode()).decode()
            writer.write(f"+ {encoded}\r\n".encode())
            await writer.drain()
            self.received.append(await reader.readline())
            writer.write(
                f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials (Failure)\r\n".encode()
            )
            await writer.drain()
            return
        writer.write(b"* CAPABILITY IMAP4rev1 IDLE\r\n" + f"{tag} OK Authenticated\r\n".encode())
        await writer.drain()
        while True:
            data = await reader.readline()
            if not data:
                return
            self.received.append(data)
            writer.write(b"ECHO " + data)
            await writer.drain()
