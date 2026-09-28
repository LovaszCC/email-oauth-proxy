import asyncio

import pytest

from app.proxy.pipe import pipe


class EchoServer:
    def __init__(self) -> None:
        self.eof = asyncio.Event()
        self.port = 0

    async def start(self) -> "EchoServer":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader, writer) -> None:
        self.writer = writer
        while True:
            data = await reader.read(1024)
            if not data:
                break
            writer.write(b"ECHO " + data)
            await writer.drain()
        self.eof.set()
        writer.close()


@pytest.fixture
async def echo():
    server = await EchoServer().start()
    yield server
    await server.stop()


@pytest.fixture
async def piped(echo):
    """Returns (test_client_reader, test_client_writer, pipe_task, echo)."""
    accepted: asyncio.Future = asyncio.get_running_loop().create_future()

    async def on_client(reader, writer):
        accepted.set_result((reader, writer))

    front = await asyncio.start_server(on_client, "127.0.0.1", 0)
    port = front.sockets[0].getsockname()[1]
    client_reader, client_writer = await asyncio.open_connection("127.0.0.1", port)
    server_side_reader, server_side_writer = await accepted
    up_reader, up_writer = await asyncio.open_connection("127.0.0.1", echo.port)
    task = asyncio.create_task(pipe(server_side_reader, server_side_writer, up_reader, up_writer))
    yield client_reader, client_writer, task, echo
    client_writer.close()
    front.close()
    await front.wait_closed()


async def test_pipe_moves_data_both_ways(piped):
    reader, writer, task, _ = piped
    writer.write(b"hello\r\n")
    await writer.drain()
    assert await asyncio.wait_for(reader.readline(), 2) == b"ECHO hello\r\n"
    assert not task.done()


async def test_pipe_closes_peer_when_one_side_ends(piped):
    reader, writer, task, echo = piped
    writer.close()
    await asyncio.wait_for(echo.eof.wait(), 2)
    await asyncio.wait_for(task, 2)


async def test_pipe_ends_when_upstream_closes(piped):
    reader, writer, task, echo = piped
    writer.write(b"x\r\n")
    await writer.drain()
    await asyncio.wait_for(reader.readline(), 2)
    echo.writer.close()
    assert await asyncio.wait_for(reader.read(), 2) == b""
    await asyncio.wait_for(task, 2)


async def test_copy_swallows_socket_errors(echo):
    from app.proxy.pipe import _copy

    reader = asyncio.StreamReader()
    reader.set_exception(ConnectionResetError("reset"))
    _, writer = await asyncio.open_connection("127.0.0.1", echo.port)
    await _copy(reader, writer)  # must not raise; closes the writer
    assert writer.is_closing()
