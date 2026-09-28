import logging
from datetime import datetime

from app.services.logs import (
    BufferHandler,
    LogBuffer,
    LogEntry,
    install_log_buffer,
    uninstall_log_buffer,
)


def entry(level: str, message: str, logger: str = "app.x") -> LogEntry:
    return LogEntry(
        time=datetime(2026, 9, 28, 12, 0, 0),
        level=level,
        levelno=logging.getLevelName(level),
        logger=logger,
        message=message,
    )


def test_buffer_newest_first_and_capacity():
    buffer = LogBuffer(capacity=2)
    buffer.append(entry("INFO", "one"))
    buffer.append(entry("INFO", "two"))
    buffer.append(entry("INFO", "three"))
    assert [e.message for e in buffer.entries()] == ["three", "two"]
    assert len(buffer) == 2 and buffer.capacity == 2


def test_buffer_filters():
    buffer = LogBuffer()
    buffer.append(entry("DEBUG", "sql", logger="aiosqlite"))
    buffer.append(entry("INFO", "Refreshed token for a@example.com", logger="app.services.refresh"))
    buffer.append(entry("ERROR", "Token refresh for b@example.com rejected"))
    assert [e.level for e in buffer.entries(min_level=logging.WARNING)] == ["ERROR"]
    assert [e.message for e in buffer.entries(query="A@EXAMPLE")] == [
        "Refreshed token for a@example.com"
    ]
    assert [e.logger for e in buffer.entries(query="refresh", min_level=logging.INFO)] == [
        "app.x",
        "app.services.refresh",
    ]
    assert len(buffer.entries(limit=1)) == 1


def test_handler_captures_and_skips_access_log():
    buffer = LogBuffer()
    handler = BufferHandler(buffer)
    logger = logging.getLogger("app.test.handler")
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    access = logging.getLogger("uvicorn.access")
    try:
        logger.info("hello %s", "world")
        access.propagate = False
        access.addHandler(handler)
        access.warning("GET / 200")
    finally:
        logger.removeHandler(handler)
        access.removeHandler(handler)
    (captured,) = buffer.entries()
    assert captured.message == "hello world"
    assert captured.level == "INFO" and captured.levelno == logging.INFO
    assert captured.logger == "app.test.handler"
    assert captured.time.tzinfo is None


def test_handler_includes_exception_text():
    buffer = LogBuffer()
    handler = BufferHandler(buffer)
    logger = logging.getLogger("app.test.exc")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError("db locked")
        except RuntimeError:
            logger.exception("run failed")
    finally:
        logger.removeHandler(handler)
    (captured,) = buffer.entries()
    assert captured.message.startswith("run failed\nTraceback")
    assert "RuntimeError: db locked" in captured.message


def test_install_lowers_root_level():
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.WARNING)
    buffer = LogBuffer()
    handler = install_log_buffer(buffer, "INFO")
    try:
        assert root.level == logging.INFO
        assert handler in root.handlers
        logging.getLogger("app.test.install").info("visible")
        assert [e.message for e in buffer.entries()] == ["visible"]
        root.setLevel(logging.DEBUG)
        install_log_buffer(buffer, "INFO")  # never raises the level
        assert root.level == logging.DEBUG
    finally:
        uninstall_log_buffer(handler)
        for extra in [h for h in root.handlers if isinstance(h, BufferHandler)]:
            root.removeHandler(extra)
        root.setLevel(previous)
    assert handler not in root.handlers
