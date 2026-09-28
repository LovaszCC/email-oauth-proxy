# Web Log Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the application log (token refresh results, rejected IMAP logins, errors) in the web UI so the admin does not need shell access to `docker compose logs`.

**Architecture:** An in-memory ring buffer (`LogBuffer`, `deque(maxlen=LOG_BUFFER_SIZE)`) fed by a `logging.Handler` installed on the root logger during the app lifespan (removed on shutdown). `uvicorn.access` records are excluded (noise). New admin-only routes: `GET /logs` (Jinja2 page with level / text / limit filters and an optional 10 s auto-refresh) and `GET /api/logs` (JSON built from `LogEntryDto`). Filters are validated by a pydantic query form (`LogFilterForm`). No schema change.

**Tech Stack:** unchanged. Decision (chat, 2026-09-28): memory ring buffer, default 1000 lines, lost on restart; `docker compose logs` stays the durable source.

**Spec:** this plan (bounded feature agreed in chat).

## Context

After adding background token refresh the useful diagnostics (why an account is in *Error*, which client login was rejected) live only in container stdout. The user asked to expose them on the web UI.

Branch `feature/5-web-log-viewer` from `main` @ 9f3b893. Plan file renamed to `docs/plans/web-log-viewer.md` in Task 1.

## Global Constraints

- `ruff format . && ruff check .` clean; `pytest --cov` 100 % before the last commit.
- Routers thin; buffer logic in `app/services/logs.py`; query validation in `app/web/forms.py`; JSON via `app/web/dto.py`.
- Never log or display secrets (nothing new is logged by this feature; it only displays existing records).
- Both new routes require the admin session; docs under `docs/documentation/Logs/`, Bruno requests under `EmailOauth2ProxyBrunoCollection/Logs/`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. A record with `exc_info` (the refresher's `log.exception`) must show the traceback text in the page – Task 1 `test_handler_includes_exception_text`.
2. The root logger level must not block INFO records when `basicConfig` was never called (tests, embedded use) – Task 1 `test_install_lowers_root_level`.
3. The handler must be removed on shutdown so a second `create_app()` in the same process does not double-capture – Task 2 `test_handler_removed_after_lifespan`.
4. Filter input from the query string must be validated (limit bounds, level enum) and never raise – Task 2 `test_logs_page_invalid_filter`.
5. Messages must be HTML-escaped (provider error text is untrusted) – Task 2 `test_logs_page_escapes_html`.

---

### Task 1: `LogBuffer`, `BufferHandler`, `install_log_buffer`, setting

**Files:** Create `app/services/logs.py`; Modify `app/settings.py`; Test `tests/test_logs_buffer.py`, `tests/test_settings.py`.

**Interfaces produced:**
- `@dataclass(frozen=True) LogEntry(time: datetime, level: str, levelno: int, logger: str, message: str)`
- `LogBuffer(capacity: int = 1000)`: `append(entry)`, `entries(*, min_level: int = logging.NOTSET, query: str = "", limit: int = 200) -> list[LogEntry]` (newest first, case-insensitive substring match on message or logger), `__len__`, `capacity`.
- `BufferHandler(buffer)` (`logging.Handler`), skips logger names starting with `uvicorn.access`.
- `install_log_buffer(buffer, level: str) -> BufferHandler` adds the handler to the root logger and lowers the root level to `level` if it is higher; `uninstall_log_buffer(handler)` removes it.
- `Settings.log_buffer_size: int = 1000`.

- [ ] **Step 1:** `mv docs/plans/nifty-skipping-lollipop.md docs/plans/web-log-viewer.md`
- [ ] **Step 2: Failing tests** – `tests/test_logs_buffer.py`:

```python
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
    try:
        logger.info("hello %s", "world")
        access = logging.getLogger("uvicorn.access")
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
```

`tests/test_settings.py`: add `assert s.log_buffer_size == 1000` to `test_defaults_and_required`.

- [ ] **Step 3: Run** `pytest tests/test_logs_buffer.py tests/test_settings.py` → FAIL (ImportError / AttributeError).
- [ ] **Step 4: Implement** `app/services/logs.py`:

```python
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
```

`app/settings.py`: `log_buffer_size: int = 1000  # log lines kept in memory for the web UI`.

- [ ] **Step 5: Run** `ruff format . && ruff check . && pytest tests/test_logs_buffer.py tests/test_settings.py` → PASS.
- [ ] **Step 6: Commit** `feat: add in-memory log buffer and logging handler`.

---

### Task 2: DTO, filter form, `/logs` page, `/api/logs`, wiring

**Files:** Create `app/web/routers/logs.py`, `app/templates/logs.html`; Modify `app/web/dto.py`, `app/web/forms.py`, `app/state.py`, `app/main.py`, `app/templates/base.html`; Test `tests/test_web_logs.py`, `tests/test_forms.py`, `tests/test_app.py`.

**Interfaces produced:**
- `LogFilterForm(level: Literal["DEBUG","INFO","WARNING","ERROR"] = "INFO", q: str = "", limit: int = Field(200, ge=1, le=1000), refresh: bool = False)` with `.min_level -> int`.
- `LogEntryDto(time, level, logger, message)` + `from_entry`; `LogsDto(count: int, buffered: int, capacity: int, entries: list[LogEntryDto])`.
- `AppState.logs: LogBuffer`; lifespan installs/uninstalls the handler.
- Routes: `GET /logs` (HTML), `GET /api/logs` (JSON), both under `require_admin`.

- [ ] **Step 1: Failing tests**

Append to `tests/test_forms.py`:

```python
import logging  # add to imports

from app.web.forms import LogFilterForm  # add to imports


def test_log_filter_form_defaults_and_bounds():
    form, errors = parse_form(LogFilterForm, {})
    assert errors == {}
    assert (form.level, form.q, form.limit, form.refresh) == ("INFO", "", 200, False)
    assert form.min_level == logging.INFO
    form, _ = parse_form(
        LogFilterForm, {"level": "ERROR", "q": " x ", "limit": "5", "refresh": "on"}
    )
    assert form.min_level == logging.ERROR and form.q == "x" and form.refresh is True
    _, errors = parse_form(LogFilterForm, {"level": "TRACE", "limit": "0"})
    assert set(errors) == {"level", "limit"}
```

Append to `tests/test_app.py`:

```python
async def test_handler_removed_after_lifespan(app_settings):
    import logging

    from asgi_lifespan import LifespanManager

    from app.services.logs import BufferHandler

    before = [h for h in logging.getLogger().handlers if isinstance(h, BufferHandler)]
    application = create_app(app_settings)
    async with LifespanManager(application):
        during = [h for h in logging.getLogger().handlers if isinstance(h, BufferHandler)]
        assert len(during) == len(before) + 1
        logging.getLogger("app.test").warning("captured while running")
    after = [h for h in logging.getLogger().handlers if isinstance(h, BufferHandler)]
    assert after == before
    assert "captured while running" in [
        e.message for e in application.state.container.logs.entries()
    ]
```

`tests/test_web_logs.py`:

```python
import logging

log = logging.getLogger("app.test.web")


async def test_requires_login(client):
    assert (await client.get("/logs")).status_code == 303
    assert (await client.get("/api/logs")).status_code == 303


async def test_logs_page_shows_entries_newest_first(admin):
    log.info("first entry")
    log.error("Token refresh for a@example.com rejected")
    response = await admin.get("/logs")
    assert response.status_code == 200
    body = response.text
    assert body.index("rejected") < body.index("first entry")
    assert 'class="level-error"' in body
    assert "http-equiv" not in body


async def test_logs_page_filters(admin):
    log.info("keep me")
    log.warning("drop me")
    response = await admin.get("/logs", params={"level": "WARNING", "q": "keep"})
    assert "keep me" not in response.text and "drop me" not in response.text
    response = await admin.get("/logs", params={"q": "keep", "refresh": "on"})
    assert "keep me" in response.text and "drop me" not in response.text
    assert '<meta http-equiv="refresh" content="10">' in response.text
    response = await admin.get("/logs", params={"limit": "1"})
    assert response.text.count("<tr class=") == 1


async def test_logs_page_invalid_filter(admin):
    response = await admin.get("/logs", params={"limit": "99999", "level": "TRACE"})
    assert response.status_code == 422
    assert "limit" in response.text and "level" in response.text


async def test_logs_page_escapes_html(admin):
    log.error("<script>alert(1)</script>")
    response = await admin.get("/logs")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


async def test_logs_api(admin, app):
    log.warning("api entry")
    response = await admin.get("/api/logs", params={"level": "WARNING", "q": "api"})
    assert response.status_code == 200
    data = response.json()
    assert data["capacity"] == app.state.container.logs.capacity
    assert data["count"] == 1 and data["buffered"] >= 1
    (entry,) = data["entries"]
    assert entry["level"] == "WARNING" and entry["logger"] == "app.test.web"
    assert entry["message"] == "api entry" and entry["time"].startswith("20")
    response = await admin.get("/api/logs", params={"limit": "0"})
    assert response.status_code == 422
    assert "limit" in response.json()["errors"]


async def test_nav_has_logs_link(admin):
    response = await admin.get("/")
    assert 'href="/logs"' in response.text
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**

`app/web/forms.py` – add:

```python
import logging  # top


class LogFilterForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    q: str = ""
    limit: int = Field(200, ge=1, le=1000)
    refresh: bool = False

    @property
    def min_level(self) -> int:
        return logging.getLevelName(self.level)
```

`app/web/dto.py` – add:

```python
from app.services.logs import LogEntry  # top


class LogEntryDto(BaseModel):
    time: datetime
    level: str
    logger: str
    message: str

    @classmethod
    def from_entry(cls, entry: LogEntry) -> "LogEntryDto":
        return cls(time=entry.time, level=entry.level, logger=entry.logger, message=entry.message)


class LogsDto(BaseModel):
    count: int
    buffered: int
    capacity: int
    entries: list[LogEntryDto]
```

`app/web/routers/logs.py`:

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.state import AppState
from app.web.deps import get_state, require_admin
from app.web.dto import LogEntryDto, LogsDto
from app.web.forms import LogFilterForm, parse_form
from app.web.templating import render

router = APIRouter(dependencies=[Depends(require_admin)])

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def _collect(state: AppState, form: LogFilterForm) -> LogsDto:
    entries = state.logs.entries(min_level=form.min_level, query=form.q, limit=form.limit)
    return LogsDto(
        count=len(entries),
        buffered=len(state.logs),
        capacity=state.logs.capacity,
        entries=[LogEntryDto.from_entry(e) for e in entries],
    )


@router.get("/logs")
async def logs_page(request: Request, state: AppState = Depends(get_state)):
    raw = dict(request.query_params)
    form, errors = parse_form(LogFilterForm, raw)
    context = {"values": raw, "errors": errors, "levels": LEVELS}
    if form is None:
        context["logs"] = None
        context["refresh"] = False
        return render(request, "logs.html", context, status_code=422)
    context["logs"] = _collect(state, form)
    context["refresh"] = form.refresh
    context["values"] = {"level": form.level, "q": form.q, "limit": form.limit}
    return render(request, "logs.html", context)


@router.get("/api/logs", response_model=LogsDto)
async def logs_api(request: Request, state: AppState = Depends(get_state)):
    form, errors = parse_form(LogFilterForm, dict(request.query_params))
    if form is None:
        return JSONResponse({"errors": errors}, status_code=422)
    return _collect(state, form)
```

`app/templates/logs.html`:

```html
{% extends "base.html" %}
{% block title %}Logs – Email OAuth2 Proxy{% endblock %}
{% block head %}{% if refresh %}<meta http-equiv="refresh" content="10">{% endif %}{% endblock %}
{% block content %}
<h2>Logs</h2>
<form method="get" action="/logs" class="grid">
  <label>Level
    <select name="level">
      {% for lvl in levels %}<option value="{{ lvl }}" {% if values.get("level", "INFO") == lvl %}selected{% endif %}>{{ lvl }}+</option>{% endfor %}
    </select>
    {% if errors.get("level") %}<small class="error">{{ errors["level"] }}</small>{% endif %}
  </label>
  <label>Search <input type="text" name="q" value="{{ values.get('q', '') }}" placeholder="email, logger, text"></label>
  <label>Rows <input type="number" name="limit" value="{{ values.get('limit', 200) }}" min="1" max="1000">
    {% if errors.get("limit") %}<small class="error">{{ errors["limit"] }}</small>{% endif %}
  </label>
  <label><input type="checkbox" name="refresh" {% if refresh %}checked{% endif %}> Auto-refresh (10 s)</label>
  <button type="submit">Apply</button>
</form>
{% if logs %}
<p><small>Showing {{ logs.count }} of {{ logs.buffered }} buffered lines (capacity {{ logs.capacity }}, newest first, times in UTC). Lines are lost on restart – <code>docker compose logs</code> keeps the full history.</small></p>
<table>
  <thead><tr><th>Time</th><th>Level</th><th>Logger</th><th>Message</th></tr></thead>
  <tbody>
  {% for e in logs.entries %}
    <tr class="level-{{ e.level | lower }}">
      <td><small>{{ e.time.strftime("%Y-%m-%d %H:%M:%S") }}</small></td>
      <td><mark class="{{ 'err' if e.level in ('ERROR', 'CRITICAL') else 'warn' if e.level == 'WARNING' else 'ok' }}">{{ e.level }}</mark></td>
      <td><small>{{ e.logger }}</small></td>
      <td><pre class="logmsg">{{ e.message }}</pre></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`app/templates/base.html`: add `{% block head %}{% endblock %}` inside `<head>`, nav item `<li><a href="/logs">Logs</a></li>` before "Add account", and CSS `pre.logmsg { white-space: pre-wrap; margin: 0; font-size: .8rem; background: none; padding: 0; }`.

`app/state.py`: field `logs: LogBuffer`. `app/main.py`: `logs = LogBuffer(settings.log_buffer_size)`; pass to `AppState`; lifespan: `handler = install_log_buffer(logs, settings.log_level)` first thing, `uninstall_log_buffer(handler)` last in `finally`; `app.include_router(logs_router.router)` (import as `from app.web.routers import accounts, auth, authorize, health, logs as logs_router` – or name the module import `logs` and the buffer variable `log_buffer`).

- [ ] **Step 4: Run** `ruff format . && ruff check . && pytest tests/test_web_logs.py tests/test_forms.py tests/test_app.py` → PASS.
- [ ] **Step 5: Commit** `feat(web): add log viewer page and /api/logs`.

---

### Task 3: Docs, Bruno, README, coverage gate, container check

**Files:** Create `docs/documentation/Logs/LogsPage.md`, `docs/documentation/Logs/LogsApi.md`, `EmailOauth2ProxyBrunoCollection/Logs/LogsPage.bru`, `EmailOauth2ProxyBrunoCollection/Logs/LogsApi.bru`; Modify `README.md`, `docs/deployment.md`, `.env.example`.

- [ ] **Step 1:** Endpoint docs in the existing template (Purpose / Method + URL / Auth / Request / Response / Errors). Request section lists query params `level` (`DEBUG|INFO|WARNING|ERROR`, default `INFO`), `q` (substring, case-insensitive, matches message or logger), `limit` (1–1000, default 200), `refresh` (page only, `on` → 10 s meta refresh). API response example:

```json
{"count": 1, "buffered": 42, "capacity": 1000,
 "entries": [{"time": "2026-09-28T13:05:00", "level": "ERROR", "logger": "app.services.refresh",
              "message": "Token refresh for a@example.com rejected (check client id / client secret): …"}]}
```

Errors: `422` (invalid filter; page re-rendered with messages / JSON `{"errors": {...}}`), `303 → /login`.

- [ ] **Step 2:** Bruno: `Logs/LogsPage.bru` (`get {{baseUrl}}/logs?level=INFO&limit=200`, seq 1), `Logs/LogsApi.bru` (`get {{baseUrl}}/api/logs?level=WARNING&limit=100`, seq 2), same format as `Health/Health.bru`.
- [ ] **Step 3:** README: env table row `| LOG_BUFFER_SIZE | 1000 | log lines kept in memory for the Logs page |`; in *Adding and authorizing an account* section add a sentence: "The **Logs** page shows the last lines of the application log (refresh results, rejected logins) without shell access." `.env.example`: `LOG_BUFFER_SIZE=1000`. `docs/deployment.md` §8 row: `| Logs without SSH | web UI → Logs (last LOG_BUFFER_SIZE lines, in memory) |`.
- [ ] **Step 4:** `ruff format . && ruff check . && pytest --cov` → 100 %.
- [ ] **Step 5:** Container: `docker build --load -t email-oauth2-proxy-web . && docker run -d --name eop -e ADMIN_PASSWORD=pw -e SECRET_KEY=<key> -p 18080:8080 email-oauth2-proxy-web` → log in with curl (cookie jar), `GET /logs` shows the "IMAP proxy listening" line, `GET /api/logs` returns JSON; `docker stop eop` ≈ 1 s.
- [ ] **Step 6: Commit** `docs: document the log viewer; add Bruno requests`.

## Verification

- Suite green, 100 % coverage, ruff clean.
- In the container: trigger a rejected IMAP login (`printf 'A1 LOGIN nobody@x y\r\n' | nc host 1993`) → the Logs page shows `WARNING app.proxy.server IMAP login for nobody@x rejected: Unknown account` within one auto-refresh.
