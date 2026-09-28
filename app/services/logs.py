import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

EXCLUDED_LOGGERS = ("uvicorn.access",)


@dataclass(frozen=True)
class LogEntry:
    time: datetime  # naive UTC
    level: str
    levelno: int
    logger: str
    message: str


class LogBuffer:
    """Fixed-size in-memory ring of the most recent log records."""

    def __init__(self, capacity: int = 1000) -> None:
        self._entries: deque[LogEntry] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        return self._entries.maxlen or 0

    def __len__(self) -> int:
        return len(self._entries)

    def append(self, entry: LogEntry) -> None:
        self._entries.append(entry)

    def entries(
        self, *, min_level: int = logging.NOTSET, query: str = "", limit: int = 200
    ) -> list[LogEntry]:
        needle = query.strip().lower()
        result: list[LogEntry] = []
        for entry in reversed(self._entries):
            if entry.levelno < min_level:
                continue
            if (
                needle
                and needle not in entry.message.lower()
                and needle not in entry.logger.lower()
            ):
                continue
            result.append(entry)
            if len(result) >= limit:
                break
        return result


class BufferHandler(logging.Handler):
    def __init__(self, buffer: LogBuffer) -> None:
        super().__init__()
        self._buffer = buffer
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(EXCLUDED_LOGGERS):
            return
        self._buffer.append(
            LogEntry(
                time=datetime.fromtimestamp(record.created, UTC).replace(tzinfo=None),
                level=record.levelname,
                levelno=record.levelno,
                logger=record.name,
                message=self.format(record),
            )
        )


def install_log_buffer(buffer: LogBuffer, level: str) -> BufferHandler:
    """Attach a BufferHandler to the root logger; make sure `level` records reach it."""
    handler = BufferHandler(buffer)
    handler.setLevel(level.upper())
    root = logging.getLogger()
    root.addHandler(handler)
    wanted = logging.getLevelName(level.upper())
    if root.level == logging.NOTSET or root.level > wanted:
        root.setLevel(wanted)
    return handler


def uninstall_log_buffer(handler: BufferHandler) -> None:
    logging.getLogger().removeHandler(handler)
