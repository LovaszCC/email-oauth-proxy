import asyncio
import contextlib

CHUNK = 65536


async def pipe(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    """Copy bytes in both directions until either side closes, then close both."""
    await asyncio.gather(
        _copy(client_reader, upstream_writer),
        _copy(upstream_reader, client_writer),
        return_exceptions=True,
    )


async def _copy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (OSError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
