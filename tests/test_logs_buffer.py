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


def test_entries_safe_while_another_thread_appends():
    """aiosqlite logs from its worker thread; reading must not raise 'deque mutated'."""
    import threading

    buffer = LogBuffer(capacity=50)
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            buffer.append(entry("DEBUG", f"sql {i}"))
            i += 1

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        for _ in range(3000):
            buffer.entries(query="sql", limit=50)
    finally:
        stop.set()
        thread.join()


def test_emit_never_raises_into_the_caller(capsys):
    buffer = LogBuffer()
    handler = BufferHandler(buffer)
    logger = logging.getLogger("app.test.badcall")
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.error("%s %s", "only-one-arg")  # malformed call from some library
    finally:
        logger.removeHandler(handler)
    assert buffer.entries() == []
    assert "Logging error" in capsys.readouterr().err


def test_handler_skips_sql_loggers():
    buffer = LogBuffer()
    handler = BufferHandler(buffer)
    for name in ("aiosqlite", "sqlalchemy.pool.impl.QueuePool"):
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.addHandler(handler)
        try:
            logger.warning("INSERT INTO accounts ... ('secret', 'verifier')")
        finally:
            logger.removeHandler(handler)
    assert buffer.entries() == []


def test_install_captures_uvicorn_error_logger():
    """uvicorn's dictConfig stops propagation, so the handler must be attached explicitly."""
    import logging.config

    from uvicorn.config import LOGGING_CONFIG

    logging.config.dictConfig(LOGGING_CONFIG)
    buffer = LogBuffer()
    handler = install_log_buffer(buffer, "INFO")
    try:
        logging.getLogger("uvicorn.error").error("Exception in ASGI application")
        logging.getLogger("uvicorn.access").info('"GET / HTTP/1.1" 200')
    finally:
        uninstall_log_buffer(handler)
    assert [e.message for e in buffer.entries()] == ["Exception in ASGI application"]
    assert handler not in logging.getLogger("uvicorn").handlers
    logging.getLogger("uvicorn.error").error("after uninstall")
    assert len(buffer) == 1
