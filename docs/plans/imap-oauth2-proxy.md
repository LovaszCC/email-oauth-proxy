# IMAP OAuth2 Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-container, headless IMAP proxy that lets plain-`LOGIN` mail clients reach Gmail / Office 365 / any XOAUTH2 IMAP server, configured and authorized entirely through a web UI.

**Architecture:** One Python 3.12 asyncio process. uvicorn serves a FastAPI app (server-rendered Jinja2 pages, admin login from env vars, SQLite via SQLAlchemy async). The app's lifespan starts an `asyncio.start_server` IMAP proxy on the same loop; on `LOGIN user *` the proxy looks the account up by username, refreshes the OAuth token if needed, opens a verified-TLS connection to the real server, does `AUTHENTICATE XOAUTH2`, then pipes raw bytes both ways. Business logic lives in `app/services/*` ("Actions"), validation in `app/web/forms.py` ("Form Requests"), JSON responses in `app/web/dto.py` ("DTOs").

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, Jinja2, SQLAlchemy 2 async + aiosqlite, pydantic v2 + pydantic-settings, cryptography (Fernet), httpx; tests: pytest, pytest-asyncio, pytest-cov (100 %), respx, asgi-lifespan; lint/format: ruff.

**Spec:** `docs/superpowers/specs/2026-09-28-imap-oauth2-proxy-design.md`

## Context

The user runs [simonrob/email-oauth2-proxy](https://github.com/simonrob/email-oauth2-proxy) today. It is a desktop-oriented single-file script (3674 lines, asyncore, INI config, tkinter/pystray GUI popups for OAuth). They want the same IMAP capability as a Linux Docker service where all configuration (client id / secret / provider) and the OAuth authorization (open URL → log in → paste the redirect URL back) happen in a browser. POP/SMTP are out of scope. Decisions taken during brainstorming (own Python code, single process, single IMAP port routed by username, ignored client password, env-var admin login, Gmail/O365/Custom presets, Jinja2 UI) are recorded in the spec §3.

The repository is empty except for the spec; git was initialised on branch `feature/1-imap-oauth2-proxy` (commit 7b9e8d7). Local Python is 3.13; the Docker image uses 3.12-slim, so code targets 3.12.

## Global Constraints

- Python `>=3.12` (`[project] requires-python`), ruff `target-version = "py312"`, line length 100.
- Every commit: `ruff format . && ruff check .` clean, `pytest` green (full suite with `--cov-fail-under=100` before the last step).
- Never commit to `main`; all commits on `feature/1-imap-oauth2-proxy`. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Routers stay thin; logic in `app/services/`; validation only in `app/web/forms.py`; JSON only via `app/web/dto.py`.
- Secrets (client secret, access token, refresh token) are stored Fernet-encrypted, never in plaintext; never logged.
- Environment: `ADMIN_PASSWORD` and `SECRET_KEY` are required; defaults per spec §9: `ADMIN_USER=admin`, `IMAP_HOST=0.0.0.0`, `IMAP_PORT=1993`, `WEB_HOST=0.0.0.0`, `WEB_PORT=8080`, `DATA_DIR=/data`, `LOG_LEVEL=INFO`.
- IMAP wire strings (exact): greeting `* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] Email OAuth2 Proxy ready`; capability line `* CAPABILITY IMAP4rev1 AUTH=PLAIN`; rejections `NO [AUTHENTICATIONFAILED] …` / `NO [UNAVAILABLE] …`.
- The plan file is renamed to `docs/plans/imap-oauth2-proxy.md` in Task 1 (CLAUDE.md wants a descriptive name).
- Deviation from the CLAUDE.md default step order (agreed via this plan): tests are written per task (TDD) instead of in one separate step; Task 10 is the full-suite/coverage gate; Task 11 is docs + Bruno.

## Review Focus

1. A mail client that sends `LOGIN` with a **literal** password (`{8}` + continuation, e.g. Thunderbird when the password has special characters) must be parsed correctly and log in – test in Task 6 (`test_login_with_literal_arguments`).
2. A pasted redirect URL whose `state` does not match, or that carries `error=access_denied`, must not touch stored tokens and must show the message – tests in Task 4 (`test_complete_rejects_state_mismatch`, `test_complete_surfaces_provider_error`).
3. A provider that **rotates the refresh token** on refresh (Microsoft does) must have the new one stored; a provider that omits it (Google) must keep the old one – tests in Task 4 (`test_refresh_rotates_refresh_token`, `test_refresh_keeps_old_refresh_token_when_absent`).
4. The upstream server rejecting XOAUTH2 with the `+ <base64 json>` continuation must get an empty line, and the decoded message must reach the client and `last_error` – tests in Task 5 (`test_authenticate_handles_continuation_error`) and Task 6 (`test_login_upstream_auth_error_sets_last_error`).
5. When the mail client disconnects mid-session the upstream connection must be closed (no leaked TLS sockets) – test in Task 5 (`test_pipe_closes_peer_when_one_side_ends`).

---

## File structure

```
pyproject.toml, .gitignore, .env.example, README.md, Dockerfile, docker-compose.yml
app/__init__.py
app/settings.py            Settings (pydantic-settings)
app/crypto.py              Cryptographer (Fernet)
app/db.py                  Base, Database
app/models.py              utcnow(), AccountStatus, Account
app/providers.py           Provider presets
app/services/__init__.py
app/services/accounts.py   AccountInput, DuplicateEmailError, AccountService
app/services/oauth.py      OAuthError, NeedsAuthorization, ProviderUnavailable, OAuthService
app/proxy/__init__.py
app/proxy/xoauth2.py       build_xoauth2_string, decode_xoauth2_error
app/proxy/upstream.py      UpstreamConnection, UpstreamConnectionError, UpstreamAuthError, connect_and_authenticate
app/proxy/pipe.py          pipe()
app/proxy/session.py       LoginRejected, Authenticator (Protocol), ClientSession
app/proxy/server.py        ProxyAuthenticator, ImapProxyServer
app/state.py               AppState container
app/main.py                create_app(), main()
app/web/__init__.py
app/web/deps.py            get_state, get_db_session, require_admin, NotAuthenticated
app/web/flash.py           flash(), pop_flash()
app/web/templating.py      templates, render()
app/web/forms.py           LoginForm, AccountForm, AuthorizeCompleteForm, parse_form()
app/web/dto.py             HealthDto, AccountDto
app/web/routers/__init__.py
app/web/routers/auth.py    /login /logout
app/web/routers/health.py  /api/health
app/web/routers/accounts.py
app/web/routers/authorize.py
app/templates/base.html, login.html, accounts/list.html, accounts/form.html, accounts/authorize.html
app/static/pico.min.css
tests/conftest.py + one test module per app module
docs/documentation/{Auth,Accounts,Authorize,Health}/*.md
EmailOauth2ProxyBrunoCollection/
```

---

### Task 1: Project scaffold, settings, crypto

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `app/__init__.py`, `app/settings.py`, `app/crypto.py`
- Create: `tests/__init__.py`, `tests/test_settings.py`, `tests/test_crypto.py`
- Rename: `docs/plans/nifty-skipping-lollipop.md` → `docs/plans/imap-oauth2-proxy.md`

**Interfaces:**
- Produces: `Settings` (fields `admin_user, admin_password, secret_key, imap_host, imap_port, web_host, web_port, data_dir: Path, log_level`, property `database_url: str`); `Cryptographer(key: str)` with `encrypt(str) -> str`, `decrypt(str) -> str`, `@staticmethod generate_key() -> str`.

- [ ] **Step 1: Rename plan, create venv and project files**

```bash
git mv docs/plans/nifty-skipping-lollipop.md docs/plans/imap-oauth2-proxy.md
python3 -m venv .venv && source .venv/bin/activate
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "email-oauth2-proxy-web"
version = "0.1.0"
description = "IMAP OAuth 2.0 proxy with a web UI, for Docker"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "itsdangerous>=2.2",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "pydantic[email]>=2.7",
    "pydantic-settings>=2.3",
    "cryptography>=42",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5",
    "respx>=0.21",
    "asgi-lifespan>=2.1",
    "ruff>=0.5",
]

[project.scripts]
email-oauth2-proxy-web = "app.main:main"

[tool.setuptools.packages.find]
include = ["app*"]

[tool.setuptools.package-data]
app = ["templates/*.html", "templates/**/*.html", "static/*.css"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-q"

[tool.coverage.run]
source = ["app"]
branch = true

[tool.coverage.report]
fail_under = 100
show_missing = true

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.coverage
htmlcov/
.env
data/
*.db
```

`.env.example`:

```
ADMIN_USER=admin
ADMIN_PASSWORD=change-me
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SECRET_KEY=
IMAP_HOST=0.0.0.0
IMAP_PORT=1993
WEB_HOST=0.0.0.0
WEB_PORT=8080
DATA_DIR=/data
LOG_LEVEL=INFO
```

`app/__init__.py`, `tests/__init__.py`: empty.

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Write failing tests**

`tests/test_settings.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_defaults_and_required(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("SECRET_KEY", "k")
    s = Settings(_env_file=None)
    assert s.admin_user == "admin"
    assert s.imap_host == "0.0.0.0"
    assert s.imap_port == 1993
    assert s.web_port == 8080
    assert s.data_dir == Path("/data")
    assert s.database_url == "sqlite+aiosqlite:////data/proxy.db"


def test_missing_required_fails(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

`tests/test_crypto.py`:

```python
import pytest

from app.crypto import Cryptographer


def test_roundtrip():
    c = Cryptographer(Cryptographer.generate_key())
    token = c.encrypt("secret")
    assert token != "secret"
    assert c.decrypt(token) == "secret"


def test_invalid_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Cryptographer("not-a-key")


def test_decrypt_with_wrong_key():
    a = Cryptographer(Cryptographer.generate_key())
    b = Cryptographer(Cryptographer.generate_key())
    with pytest.raises(ValueError, match="decrypt"):
        b.decrypt(a.encrypt("x"))
```

- [ ] **Step 3: Run tests, expect ImportError**

Run: `pytest tests/test_settings.py tests/test_crypto.py -v` → FAIL (`ModuleNotFoundError: app.settings`).

- [ ] **Step 4: Implement**

`app/settings.py`:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_user: str = "admin"
    admin_password: str
    secret_key: str
    imap_host: str = "0.0.0.0"
    imap_port: int = 1993
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    data_dir: Path = Path("/data")
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'proxy.db'}"
```

`app/crypto.py`:

```python
from cryptography.fernet import Fernet, InvalidToken


class Cryptographer:
    """Encrypts secrets at rest with a Fernet key taken from SECRET_KEY."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except ValueError as exc:
            raise ValueError("SECRET_KEY must be a valid Fernet key") from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt value with the configured SECRET_KEY") from exc

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()
```

- [ ] **Step 5: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_settings.py tests/test_crypto.py -v` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold project with settings and crypto

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Database, Account model, provider presets

**Files:**
- Create: `app/db.py`, `app/models.py`, `app/providers.py`
- Test: `tests/conftest.py`, `tests/test_models.py`, `tests/test_providers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Database(url)` with `create_all()`, `dispose()`, `session() -> AsyncSession`; `Base`; `utcnow() -> datetime` (naive UTC); `AccountStatus` StrEnum (`authorized`, `needs_authorization`, `error`); `Account` ORM model (columns per spec §5) with `.status` property; `Provider` dataclass; `PROVIDERS: dict[str, Provider]`; `get_provider(key) -> Provider` (ValueError on unknown); `PROVIDER_KEYS`.

- [ ] **Step 1: Write failing tests**

`tests/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest

from app.crypto import Cryptographer
from app.db import Database


@pytest.fixture
def fernet_key() -> str:
    return Cryptographer.generate_key()


@pytest.fixture
def crypto(fernet_key) -> Cryptographer:
    return Cryptographer(fernet_key)


@pytest.fixture
async def db(tmp_path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.create_all()
    yield database
    await database.dispose()
```

`tests/test_models.py`:

```python
from datetime import datetime

from sqlalchemy import select

from app.models import Account, AccountStatus, utcnow


def make_account(**overrides) -> Account:
    values = dict(
        email="user@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://mail.google.com/",
        client_id="cid",
    )
    values.update(overrides)
    return Account(**values)


def test_utcnow_is_naive():
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is None


def test_status_needs_authorization():
    assert make_account().status is AccountStatus.NEEDS_AUTHORIZATION


def test_status_authorized():
    assert make_account(refresh_token_enc="x").status is AccountStatus.AUTHORIZED


def test_status_error_wins():
    assert make_account(refresh_token_enc="x", last_error="boom").status is AccountStatus.ERROR


def test_clear_tokens():
    account = make_account(
        refresh_token_enc="r",
        access_token_enc="a",
        access_token_expiry=utcnow(),
        pending_state="s",
        pending_code_verifier="v",
        last_error="e",
    )
    account.clear_tokens()
    assert account.refresh_token_enc is None
    assert account.access_token_enc is None
    assert account.access_token_expiry is None
    assert account.pending_state is None
    assert account.pending_code_verifier is None
    assert account.last_error is None


async def test_persist_and_defaults(db):
    async with db.session() as session:
        session.add(make_account())
        await session.commit()
    async with db.session() as session:
        account = (await session.execute(select(Account))).scalar_one()
        assert account.redirect_uri == "http://localhost"
        assert account.use_pkce is False
        assert account.created_at is not None
        assert account.updated_at is not None
```

`tests/test_providers.py`:

```python
import pytest

from app.providers import PROVIDER_KEYS, PROVIDERS, get_provider


def test_presets_present():
    assert PROVIDER_KEYS == ["gmail", "o365", "custom"]
    assert PROVIDERS["gmail"].imap_host == "imap.gmail.com"
    assert PROVIDERS["o365"].imap_host == "outlook.office365.com"
    assert "offline_access" in PROVIDERS["o365"].scope
    assert PROVIDERS["gmail"].extra_auth_params == {"access_type": "offline", "prompt": "consent"}
    assert PROVIDERS["custom"].permission_url == ""


def test_get_provider():
    assert get_provider("o365").name == "Office 365 / Outlook"
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("nope")
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `pytest tests/test_models.py tests/test_providers.py -v` → FAIL.

- [ ] **Step 3: Implement**

`app/db.py`:

```python
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url)
        self._session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        from app import models  # noqa: F401  (register tables)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    def session(self) -> AsyncSession:
        return self._session_factory()
```

`app/models.py`:

```python
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)


class AccountStatus(StrEnum):
    AUTHORIZED = "authorized"
    NEEDS_AUTHORIZATION = "needs_authorization"
    ERROR = "error"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    permission_url: Mapped[str] = mapped_column(Text)
    token_url: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    client_id: Mapped[str] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(Text, default="http://localhost")
    use_pkce: Mapped[bool] = mapped_column(Boolean, default=False)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def status(self) -> AccountStatus:
        if self.last_error:
            return AccountStatus.ERROR
        if self.refresh_token_enc:
            return AccountStatus.AUTHORIZED
        return AccountStatus.NEEDS_AUTHORIZATION

    def clear_tokens(self) -> None:
        """Forget all OAuth state; the account must be authorized again."""
        self.access_token_enc = None
        self.access_token_expiry = None
        self.refresh_token_enc = None
        self.pending_state = None
        self.pending_code_verifier = None
        self.last_error = None
```

`app/providers.py`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    imap_host: str
    imap_port: int
    permission_url: str
    token_url: str
    scope: str
    use_pkce: bool = False
    extra_auth_params: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    "gmail": Provider(
        key="gmail",
        name="Gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://mail.google.com/",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
    ),
    "o365": Provider(
        key="o365",
        name="Office 365 / Outlook",
        imap_host="outlook.office365.com",
        imap_port=993,
        permission_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scope="https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    ),
    "custom": Provider(
        key="custom",
        name="Custom",
        imap_host="",
        imap_port=993,
        permission_url="",
        token_url="",
        scope="",
    ),
}

PROVIDER_KEYS = list(PROVIDERS)


def get_provider(key: str) -> Provider:
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {key}") from exc
```

- [ ] **Step 4: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_models.py tests/test_providers.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add database layer, Account model and provider presets

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: AccountService

**Files:**
- Create: `app/services/__init__.py`, `app/services/accounts.py`
- Test: `tests/test_accounts_service.py`

**Interfaces:**
- Consumes: `Database`, `Account`, `Cryptographer`.
- Produces:
  - `@dataclass AccountInput(email, provider, imap_host, imap_port, permission_url, token_url, scope, client_id, client_secret: str | None, redirect_uri, use_pkce)`
  - `class DuplicateEmailError(Exception)`
  - `AccountService(session: AsyncSession, crypto: Cryptographer)` with `async list() -> list[Account]`, `async get(id: int) -> Account | None`, `async get_by_email(email: str) -> Account | None`, `async create(data: AccountInput) -> Account`, `async update(account, data, *, keep_secret: bool) -> Account`, `async delete(account) -> None`, `client_secret(account) -> str | None`, `async count() -> tuple[int, int]` (total, authorized).
  - `update` clears tokens/pending/last_error when `client_id`, `token_url` or `scope` changed. Service methods `flush` but do **not** commit; caller commits.

- [ ] **Step 1: Write failing tests**

`tests/test_accounts_service.py`:

```python
import pytest

from app.models import AccountStatus
from app.services.accounts import AccountInput, AccountService, DuplicateEmailError


def gmail_input(**overrides) -> AccountInput:
    values = dict(
        email="User@Example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://mail.google.com/",
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost",
        use_pkce=False,
    )
    values.update(overrides)
    return AccountInput(**values)


async def test_create_lowercases_and_encrypts(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        await session.commit()
        assert account.id is not None
        assert account.email == "user@example.com"
        assert account.client_secret_enc != "csecret"
        assert svc.client_secret(account) == "csecret"


async def test_create_without_secret(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input(client_secret=None))
        assert account.client_secret_enc is None
        assert svc.client_secret(account) is None


async def test_create_duplicate(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        await svc.create(gmail_input())
        await session.commit()
        with pytest.raises(DuplicateEmailError):
            await svc.create(gmail_input(email="USER@example.com"))


async def test_list_get_and_get_by_email(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        b = await svc.create(gmail_input(email="b@example.com"))
        a = await svc.create(gmail_input(email="a@example.com"))
        await session.commit()
        assert [x.email for x in await svc.list()] == ["a@example.com", "b@example.com"]
        assert (await svc.get(a.id)).id == a.id
        assert await svc.get(9999) is None
        assert (await svc.get_by_email("B@EXAMPLE.COM")).id == b.id
        assert await svc.get_by_email("nobody@example.com") is None


async def test_update_keeps_secret_and_tokens_when_unchanged(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        account.refresh_token_enc = "rt"
        account.access_token_enc = "at"
        await session.commit()
        await svc.update(account, gmail_input(imap_host="imap.other.com"), keep_secret=True)
        assert account.imap_host == "imap.other.com"
        assert svc.client_secret(account) == "csecret"
        assert account.refresh_token_enc == "rt"


async def test_update_replaces_secret(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        await svc.update(account, gmail_input(client_secret="new"), keep_secret=False)
        assert svc.client_secret(account) == "new"
        await svc.update(account, gmail_input(client_secret=None), keep_secret=False)
        assert svc.client_secret(account) is None


@pytest.mark.parametrize("field", ["client_id", "token_url", "scope"])
async def test_update_credential_change_clears_tokens(db, crypto, field):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        account.refresh_token_enc = "rt"
        account.access_token_enc = "at"
        account.pending_state = "s"
        account.last_error = "e"
        await svc.update(account, gmail_input(**{field: "changed"}), keep_secret=True)
        assert account.refresh_token_enc is None
        assert account.access_token_enc is None
        assert account.pending_state is None
        assert account.last_error is None
        assert account.status is AccountStatus.NEEDS_AUTHORIZATION


async def test_update_to_duplicate_email(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        await svc.create(gmail_input(email="a@example.com"))
        b = await svc.create(gmail_input(email="b@example.com"))
        await session.commit()
        with pytest.raises(DuplicateEmailError):
            await svc.update(b, gmail_input(email="a@example.com"), keep_secret=True)


async def test_delete_and_count(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        a = await svc.create(gmail_input(email="a@example.com"))
        b = await svc.create(gmail_input(email="b@example.com"))
        b.refresh_token_enc = "rt"
        await session.commit()
        assert await svc.count() == (2, 1)
        await svc.delete(a)
        await session.commit()
        assert await svc.count() == (1, 1)
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `pytest tests/test_accounts_service.py -v` → FAIL.

- [ ] **Step 3: Implement**

`app/services/__init__.py`: empty.

`app/services/accounts.py`:

```python
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import Cryptographer
from app.models import Account


@dataclass
class AccountInput:
    email: str
    provider: str
    imap_host: str
    imap_port: int
    permission_url: str
    token_url: str
    scope: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    use_pkce: bool


class DuplicateEmailError(Exception):
    pass


class AccountService:
    """CRUD for accounts. Methods flush but never commit; the caller owns the transaction."""

    def __init__(self, session: AsyncSession, crypto: Cryptographer) -> None:
        self._session = session
        self._crypto = crypto

    async def list(self) -> list[Account]:
        result = await self._session.execute(select(Account).order_by(Account.email))
        return list(result.scalars())

    async def get(self, account_id: int) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_by_email(self, email: str) -> Account | None:
        stmt = select(Account).where(Account.email == email.strip().lower())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self) -> tuple[int, int]:
        total = (await self._session.execute(select(func.count(Account.id)))).scalar_one()
        authorized = (
            await self._session.execute(
                select(func.count(Account.id)).where(
                    Account.refresh_token_enc.is_not(None), Account.last_error.is_(None)
                )
            )
        ).scalar_one()
        return total, authorized

    async def create(self, data: AccountInput) -> Account:
        email = data.email.strip().lower()
        if await self.get_by_email(email) is not None:
            raise DuplicateEmailError(email)
        account = Account(email=email)
        self._apply(account, data)
        account.client_secret_enc = self._encrypt_secret(data.client_secret)
        self._session.add(account)
        await self._session.flush()
        return account

    async def update(self, account: Account, data: AccountInput, *, keep_secret: bool) -> Account:
        email = data.email.strip().lower()
        if email != account.email and await self.get_by_email(email) is not None:
            raise DuplicateEmailError(email)
        credentials_changed = (
            account.client_id != data.client_id
            or account.token_url != data.token_url
            or account.scope != data.scope
        )
        account.email = email
        self._apply(account, data)
        if not keep_secret:
            account.client_secret_enc = self._encrypt_secret(data.client_secret)
        if credentials_changed:
            account.clear_tokens()
        await self._session.flush()
        return account

    async def delete(self, account: Account) -> None:
        await self._session.delete(account)
        await self._session.flush()

    def client_secret(self, account: Account) -> str | None:
        if account.client_secret_enc is None:
            return None
        return self._crypto.decrypt(account.client_secret_enc)

    @staticmethod
    def _apply(account: Account, data: AccountInput) -> None:
        account.provider = data.provider
        account.imap_host = data.imap_host
        account.imap_port = data.imap_port
        account.permission_url = data.permission_url
        account.token_url = data.token_url
        account.scope = data.scope
        account.client_id = data.client_id
        account.redirect_uri = data.redirect_uri
        account.use_pkce = data.use_pkce

    def _encrypt_secret(self, secret: str | None) -> str | None:
        if not secret:
            return None
        return self._crypto.encrypt(secret)
```

- [ ] **Step 4: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_accounts_service.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add AccountService

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: OAuthService

**Files:**
- Create: `app/services/oauth.py`
- Test: `tests/test_oauth_service.py`

**Interfaces:**
- Consumes: `Cryptographer`, `Account` (+ `clear_tokens()`), `utcnow`, `PROVIDERS`.
- Produces:
  - `class OAuthError(Exception)` with `.message: str`; subclasses `NeedsAuthorization`, `ProviderUnavailable`.
  - `OAuthService(crypto: Cryptographer, http: httpx.AsyncClient, now: Callable[[], datetime] = utcnow)` with
    `build_authorization_url(account) -> str` (sets `pending_state`, `pending_code_verifier`),
    `async complete_authorization(account, redirect_url: str) -> None` (raises `OAuthError` / `ProviderUnavailable`),
    `async get_valid_access_token(account) -> str` (raises `NeedsAuthorization` / `ProviderUnavailable`),
    `async refresh(account) -> str`, `revoke(account) -> None`, `@staticmethod parse_redirect(text) -> dict[str, str]`.
  - `REFRESH_MARGIN = timedelta(seconds=60)`.

- [ ] **Step 1: Write failing tests**

`tests/test_oauth_service.py`:

```python
import base64
import hashlib
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.models import Account
from app.services.oauth import NeedsAuthorization, OAuthError, OAuthService, ProviderUnavailable

TOKEN_URL = "https://oauth2.googleapis.com/token"
NOW = datetime(2026, 9, 28, 12, 0, 0)


def make_account(crypto, **overrides) -> Account:
    values = dict(
        email="user@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url=TOKEN_URL,
        scope="https://mail.google.com/",
        client_id="cid",
        client_secret_enc=crypto.encrypt("csecret"),
        redirect_uri="http://localhost",
        use_pkce=False,
    )
    values.update(overrides)
    return Account(**values)


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def service(crypto, http) -> OAuthService:
    return OAuthService(crypto, http, now=lambda: NOW)


def test_build_url_gmail(service, crypto):
    account = make_account(crypto)
    url = service.build_authorization_url(account)
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.scheme == "https" and parts.netloc == "accounts.google.com"
    assert query["client_id"] == "cid"
    assert query["redirect_uri"] == "http://localhost"
    assert query["response_type"] == "code"
    assert query["scope"] == "https://mail.google.com/"
    assert query["state"] == account.pending_state
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert "code_challenge" not in query
    assert account.pending_code_verifier is None


def test_build_url_pkce_and_existing_query(service, crypto):
    account = make_account(
        crypto, provider="custom", use_pkce=True, permission_url="https://x.test/auth?tenant=1"
    )
    url = service.build_authorization_url(account)
    assert url.startswith("https://x.test/auth?tenant=1&")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(account.pending_code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert query["code_challenge"] == expected
    assert query["code_challenge_method"] == "S256"
    assert "access_type" not in query


@pytest.mark.parametrize(
    "text",
    [
        "http://localhost/?code=abc&state=st",
        "code=abc&state=st",
        "?code=abc&state=st",
        "  http://localhost/?state=st&code=abc  ",
    ],
)
def test_parse_redirect(text):
    assert OAuthService.parse_redirect(text) == {"code": "abc", "state": "st"}


@respx.mock
async def test_complete_success_stores_tokens(service, crypto):
    account = make_account(crypto, use_pkce=True)
    service.build_authorization_url(account)
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 100}
        )
    )
    await service.complete_authorization(
        account, f"http://localhost/?code=abc&state={account.pending_state}"
    )
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["abc"]
    assert body["client_secret"] == ["csecret"]
    assert body["redirect_uri"] == ["http://localhost"]
    assert len(body["code_verifier"][0]) >= 43
    assert crypto.decrypt(account.access_token_enc) == "AT"
    assert crypto.decrypt(account.refresh_token_enc) == "RT"
    assert account.access_token_expiry == NOW + timedelta(seconds=100)
    assert account.pending_state is None
    assert account.pending_code_verifier is None
    assert account.last_error is None


@respx.mock
async def test_complete_without_secret_or_pkce_or_expires(service, crypto):
    account = make_account(crypto, client_secret_enc=None)
    service.build_authorization_url(account)
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT"})
    )
    await service.complete_authorization(account, f"code=abc&state={account.pending_state}")
    body = parse_qs(route.calls.last.request.content.decode())
    assert "client_secret" not in body
    assert "code_verifier" not in body
    assert account.access_token_expiry == NOW + timedelta(seconds=3600)


async def test_complete_surfaces_provider_error(service, crypto):
    account = make_account(crypto, refresh_token_enc="keep")
    service.build_authorization_url(account)
    with pytest.raises(OAuthError, match="User denied"):
        await service.complete_authorization(
            account, "http://localhost/?error=access_denied&error_description=User+denied"
        )
    with pytest.raises(OAuthError, match="access_denied"):
        await service.complete_authorization(account, "http://localhost/?error=access_denied")
    assert account.refresh_token_enc == "keep"
    assert account.pending_state is not None


async def test_complete_requires_code(service, crypto):
    account = make_account(crypto)
    service.build_authorization_url(account)
    with pytest.raises(OAuthError, match="code"):
        await service.complete_authorization(account, "http://localhost/?state=x")


async def test_complete_rejects_state_mismatch(service, crypto):
    account = make_account(crypto)
    with pytest.raises(OAuthError, match="State mismatch"):
        await service.complete_authorization(account, "http://localhost/?code=abc&state=x")
    service.build_authorization_url(account)
    with pytest.raises(OAuthError, match="State mismatch"):
        await service.complete_authorization(account, "http://localhost/?code=abc&state=wrong")


@respx.mock
async def test_complete_token_endpoint_errors(service, crypto):
    account = make_account(crypto)
    service.build_authorization_url(account)
    url = f"code=abc&state={account.pending_state}"
    route = respx.post(TOKEN_URL)

    route.mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Bad code"}
        )
    )
    with pytest.raises(OAuthError, match="Bad code"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(400, json={"error": "invalid_client"}))
    with pytest.raises(OAuthError, match="invalid_client"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(403, text="nope"))
    with pytest.raises(OAuthError, match="HTTP 403"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(200, json={"token_type": "Bearer"}))
    with pytest.raises(OAuthError, match="access token"):
        await service.complete_authorization(account, url)

    route.mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(ProviderUnavailable, match="HTTP 502"):
        await service.complete_authorization(account, url)

    route.mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderUnavailable, match="ConnectError"):
        await service.complete_authorization(account, url)

    assert account.access_token_enc is None
    assert account.pending_state is not None


def test_build_url_unknown_provider_has_no_extras(service, crypto):
    account = make_account(crypto, provider="legacy")
    url = service.build_authorization_url(account)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert "access_type" not in query and query["state"] == account.pending_state


async def test_get_valid_access_token_uses_cache(service, crypto):
    account = make_account(
        crypto,
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(seconds=61),
    )
    assert await service.get_valid_access_token(account) == "AT"


@respx.mock
async def test_get_valid_access_token_refreshes_when_expiring(service, crypto):
    account = make_account(
        crypto,
        access_token_enc=crypto.encrypt("OLD"),
        access_token_expiry=NOW + timedelta(seconds=60),
        refresh_token_enc=crypto.encrypt("RT"),
        last_error="stale",
    )
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "NEW", "expires_in": 10})
    )
    assert await service.get_valid_access_token(account) == "NEW"
    body = parse_qs(route.calls.last.request.content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["RT"]
    assert body["client_id"] == ["cid"]
    assert body["client_secret"] == ["csecret"]
    assert account.last_error is None


@respx.mock
async def test_refresh_keeps_old_refresh_token_when_absent(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "NEW"}))
    await service.refresh(account)
    assert crypto.decrypt(account.refresh_token_enc) == "RT"


@respx.mock
async def test_refresh_rotates_refresh_token(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2"})
    )
    await service.refresh(account)
    assert crypto.decrypt(account.refresh_token_enc) == "RT2"


async def test_refresh_without_refresh_token(service, crypto):
    account = make_account(crypto)
    with pytest.raises(NeedsAuthorization, match="not been authorized"):
        await service.get_valid_access_token(account)
    assert account.last_error is None


@respx.mock
async def test_refresh_invalid_grant_clears_tokens(service, crypto):
    account = make_account(
        crypto, refresh_token_enc=crypto.encrypt("RT"), access_token_enc=crypto.encrypt("AT")
    )
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Token revoked"}
        )
    )
    with pytest.raises(NeedsAuthorization, match="Token revoked"):
        await service.refresh(account)
    assert account.refresh_token_enc is None
    assert account.access_token_enc is None
    assert account.last_error == "Token refresh rejected: Token revoked"


@respx.mock
async def test_refresh_network_error_keeps_tokens(service, crypto):
    account = make_account(crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderUnavailable):
        await service.refresh(account)
    assert crypto.decrypt(account.refresh_token_enc) == "RT"
    assert account.last_error.startswith("Token refresh failed: ReadTimeout")


def test_revoke(service, crypto):
    account = make_account(crypto, refresh_token_enc="x", pending_state="s", last_error="e")
    service.revoke(account)
    assert account.refresh_token_enc is None
    assert account.pending_state is None
    assert account.last_error is None
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `pytest tests/test_oauth_service.py -v` → FAIL.

- [ ] **Step 3: Implement**

`app/services/oauth.py`:

```python
import base64
import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from app.crypto import Cryptographer
from app.models import Account, utcnow
from app.providers import PROVIDERS

REFRESH_MARGIN = timedelta(seconds=60)
DEFAULT_EXPIRES_IN = 3600


class OAuthError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NeedsAuthorization(OAuthError):
    """No usable refresh token; the admin must authorize the account again."""


class ProviderUnavailable(OAuthError):
    """The token endpoint could not be reached or answered with a server error."""


class OAuthService:
    def __init__(
        self,
        crypto: Cryptographer,
        http: httpx.AsyncClient,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._crypto = crypto
        self._http = http
        self._now = now

    # -- authorization-code flow ---------------------------------------------------------

    def build_authorization_url(self, account: Account) -> str:
        state = secrets.token_urlsafe(32)
        account.pending_state = state
        params = {
            "client_id": account.client_id,
            "redirect_uri": account.redirect_uri,
            "response_type": "code",
            "scope": account.scope,
            "state": state,
        }
        if account.use_pkce:
            verifier = secrets.token_urlsafe(64)
            digest = hashlib.sha256(verifier.encode()).digest()
            params["code_challenge"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            params["code_challenge_method"] = "S256"
            account.pending_code_verifier = verifier
        else:
            account.pending_code_verifier = None
        provider = PROVIDERS.get(account.provider)
        if provider is not None:
            params.update(provider.extra_auth_params)
        separator = "&" if "?" in account.permission_url else "?"
        return f"{account.permission_url}{separator}{urlencode(params)}"

    @staticmethod
    def parse_redirect(text: str) -> dict[str, str]:
        text = text.strip()
        query = urlsplit(text).query if "://" in text else text.lstrip("?")
        return {key: values[0] for key, values in parse_qs(query, keep_blank_values=True).items()}

    async def complete_authorization(self, account: Account, redirect_url: str) -> None:
        params = self.parse_redirect(redirect_url)
        if "error" in params:
            raise OAuthError(params.get("error_description") or params["error"])
        code = params.get("code")
        if not code:
            raise OAuthError("The pasted URL does not contain a code parameter")
        if not account.pending_state or params.get("state") != account.pending_state:
            raise OAuthError("State mismatch – start the authorization again")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": account.redirect_uri,
            "client_id": account.client_id,
        }
        if account.pending_code_verifier:
            data["code_verifier"] = account.pending_code_verifier
        payload = await self._token_request(account, data)
        self._store_tokens(account, payload)
        account.pending_state = None
        account.pending_code_verifier = None
        account.last_error = None

    # -- token use -------------------------------------------------------------------------

    async def get_valid_access_token(self, account: Account) -> str:
        if (
            account.access_token_enc
            and account.access_token_expiry
            and account.access_token_expiry > self._now() + REFRESH_MARGIN
        ):
            return self._crypto.decrypt(account.access_token_enc)
        return await self.refresh(account)

    async def refresh(self, account: Account) -> str:
        if not account.refresh_token_enc:
            raise NeedsAuthorization("Account has not been authorized")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._crypto.decrypt(account.refresh_token_enc),
            "client_id": account.client_id,
        }
        try:
            payload = await self._token_request(account, data)
        except ProviderUnavailable as exc:
            account.last_error = f"Token refresh failed: {exc.message}"
            raise
        except OAuthError as exc:
            account.clear_tokens()
            account.last_error = f"Token refresh rejected: {exc.message}"
            raise NeedsAuthorization(exc.message) from exc
        self._store_tokens(account, payload)
        account.last_error = None
        return payload["access_token"]

    def revoke(self, account: Account) -> None:
        account.clear_tokens()

    # -- helpers ---------------------------------------------------------------------------

    async def _token_request(self, account: Account, data: dict[str, str]) -> dict:
        if account.client_secret_enc:
            data["client_secret"] = self._crypto.decrypt(account.client_secret_enc)
        try:
            response = await self._http.post(
                account.token_url, data=data, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{type(exc).__name__}: {exc}") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 500:
            raise ProviderUnavailable(f"HTTP {response.status_code} from token endpoint")
        if response.status_code >= 400 or "error" in payload:
            message = payload.get("error_description") or payload.get("error")
            raise OAuthError(message or f"HTTP {response.status_code} from token endpoint")
        if "access_token" not in payload:
            raise OAuthError("Token response did not include an access token")
        return payload

    def _store_tokens(self, account: Account, payload: dict) -> None:
        account.access_token_enc = self._crypto.encrypt(payload["access_token"])
        expires_in = int(payload.get("expires_in", DEFAULT_EXPIRES_IN))
        account.access_token_expiry = self._now() + timedelta(seconds=expires_in)
        if payload.get("refresh_token"):
            account.refresh_token_enc = self._crypto.encrypt(payload["refresh_token"])
```

- [ ] **Step 4: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_oauth_service.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add OAuthService with authorization-code and refresh flows

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Proxy primitives – XOAUTH2, upstream connection, byte pipe

**Files:**
- Create: `app/proxy/__init__.py`, `app/proxy/xoauth2.py`, `app/proxy/upstream.py`, `app/proxy/pipe.py`
- Test: `tests/fake_imap.py`, `tests/conftest.py` (add TLS cert fixtures), `tests/test_xoauth2.py`, `tests/test_upstream.py`, `tests/test_pipe.py`

**Interfaces:**
- Produces:
  - `build_xoauth2_string(email: str, access_token: str) -> str` (base64), `decode_xoauth2_error(payload: str) -> str`.
  - `@dataclass UpstreamConnection(reader: StreamReader, writer: StreamWriter)` with `async close()`.
  - `class UpstreamConnectionError(Exception)`, `class UpstreamAuthError(Exception)`.
  - `async connect_and_authenticate(host, port, email, access_token, *, ssl_context: ssl.SSLContext | None = None, timeout: float = 30.0) -> UpstreamConnection`.
  - `async pipe(client_reader, client_writer, upstream_reader, upstream_writer) -> None`.
- Test helper `tests/fake_imap.py::FakeImapServer(ssl_context, mode="ok")` with `.port`, `.received`, `.auth_strings`, `.closed` (asyncio.Event), `start()`, `stop()`. Modes: `ok`, `no`, `continuation`, `close`, `bad_greeting`, `silent`. After a successful auth it echoes every line back prefixed with `ECHO `.

- [ ] **Step 1: Test helpers**

Append to `tests/conftest.py`:

```python
import ssl
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@pytest.fixture(scope="session")
def tls_cert(tmp_path_factory) -> tuple[Path, Path]:
    """Self-signed cert for localhost, used by the fake upstream IMAP server."""
    directory = tmp_path_factory.mktemp("tls")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture(scope="session")
def server_ssl(tls_cert) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(str(tls_cert[0]), str(tls_cert[1]))
    return ctx


@pytest.fixture(scope="session")
def client_ssl(tls_cert) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(tls_cert[0]))
```

(Add `from pathlib import Path` at the top of conftest.)

`tests/fake_imap.py`:

```python
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
```

- [ ] **Step 2: Write failing tests**

`tests/test_xoauth2.py`:

```python
import base64

from app.proxy.xoauth2 import build_xoauth2_string, decode_xoauth2_error


def test_build_xoauth2_string():
    encoded = build_xoauth2_string("user@example.com", "tok")
    assert base64.b64decode(encoded) == b"user=user@example.com\x01auth=Bearer tok\x01\x01"


def test_decode_xoauth2_error_json():
    payload = base64.b64encode(b'{"status":"400","schemes":"Bearer","scope":"x"}').decode()
    assert decode_xoauth2_error(payload) == "status 400 (schemes: Bearer, scope: x)"


def test_decode_xoauth2_error_fallback():
    assert decode_xoauth2_error("not base64!") == "not base64!"
    assert decode_xoauth2_error(base64.b64encode(b"plain text").decode()) == "plain text"
    assert decode_xoauth2_error(base64.b64encode(b"[1,2]").decode()) == "[1,2]"
```

`tests/test_upstream.py`:

```python
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
```

`tests/test_pipe.py`:

```python
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
```

- [ ] **Step 3: Run tests, expect ImportError**

Run: `pytest tests/test_xoauth2.py tests/test_upstream.py tests/test_pipe.py -v` → FAIL.

- [ ] **Step 4: Implement**

`app/proxy/__init__.py`: empty.

`app/proxy/xoauth2.py`:

```python
import base64
import binascii
import json


def build_xoauth2_string(email: str, access_token: str) -> str:
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()


def decode_xoauth2_error(payload: str) -> str:
    """Decode the base64 JSON an IMAP server sends in the `+` continuation after a failed XOAUTH2."""
    try:
        text = base64.b64decode(payload, validate=True).decode(errors="replace")
    except (binascii.Error, ValueError):
        return payload
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict):
        return text
    status = data.pop("status", "unknown")
    details = ", ".join(f"{key}: {value}" for key, value in data.items())
    return f"status {status} ({details})" if details else f"status {status}"
```

`app/proxy/upstream.py`:

```python
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
        raise UpstreamConnectionError(
            f"Unexpected greeting: {greeting.decode(errors='replace').strip()}"
        )
    writer.write(
        AUTH_TAG
        + b" AUTHENTICATE XOAUTH2 "
        + build_xoauth2_string(email, access_token).encode()
        + b"\r\n"
    )
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
```

`app/proxy/pipe.py`:

```python
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
```

- [ ] **Step 5: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_xoauth2.py tests/test_upstream.py tests/test_pipe.py -v` → PASS. If `test_tls_verification_failure` fails because the platform wording differs, match on `"certificate"` (case-insensitive) instead.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add XOAUTH2 upstream connection and byte pipe

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: IMAP client session, proxy server, ProxyAuthenticator

**Files:**
- Create: `app/proxy/session.py`, `app/proxy/server.py`
- Test: `tests/test_session.py`, `tests/test_proxy_authenticator.py`

**Interfaces:**
- Consumes: `UpstreamConnection`, `UpstreamConnectionError`, `UpstreamAuthError`, `connect_and_authenticate`, `pipe`, `Database`, `AccountService`, `OAuthService`, `NeedsAuthorization`, `ProviderUnavailable`, `utcnow`.
- Produces:
  - `class LoginRejected(Exception)` with `.code` (`"AUTHENTICATIONFAILED"` | `"UNAVAILABLE"`) and `.message`.
  - `class Authenticator(Protocol)`: `async authenticate(username: str) -> UpstreamConnection`.
  - `ClientSession(reader, writer, authenticator, *, timeout: float = 60.0)` with `async run() -> None`.
  - `ProxyAuthenticator(db, crypto, oauth, connect=connect_and_authenticate)`.
  - `ImapProxyServer(host, port, authenticator, *, timeout=60.0)` with `async start()`, `async stop()`, `listening: bool`, `port: int` (actual bound port).

- [ ] **Step 1: Write failing tests**

`tests/test_session.py`:

```python
import asyncio
import base64

import pytest

from app.proxy.server import ImapProxyServer
from app.proxy.session import LoginRejected
from app.proxy.upstream import UpstreamConnection
from tests.test_pipe import EchoServer

GREETING = b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] Email OAuth2 Proxy ready\r\n"


class FakeAuthenticator:
    def __init__(self, echo: EchoServer | None = None) -> None:
        self.echo = echo
        self.usernames: list[str] = []
        self.error: Exception | None = None

    async def authenticate(self, username: str) -> UpstreamConnection:
        self.usernames.append(username)
        if self.error is not None:
            raise self.error
        assert self.echo is not None
        reader, writer = await asyncio.open_connection("127.0.0.1", self.echo.port)
        return UpstreamConnection(reader, writer)


@pytest.fixture
async def echo():
    server = await EchoServer().start()
    yield server
    await server.stop()


@pytest.fixture
async def proxy(echo):
    authenticator = FakeAuthenticator(echo)
    server = ImapProxyServer("127.0.0.1", 0, authenticator, timeout=0.5)
    await server.start()
    yield server, authenticator
    await server.stop()


@pytest.fixture
async def client(proxy):
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    assert await reader.readline() == GREETING
    yield reader, writer
    writer.close()


async def send(client, data: bytes) -> bytes:
    reader, writer = client
    writer.write(data)
    await writer.drain()
    return await asyncio.wait_for(reader.readline(), 2)


async def test_listening_and_port(proxy):
    server, _ = proxy
    assert server.listening is True
    assert server.port > 0
    idle = ImapProxyServer("127.0.0.1", 0, FakeAuthenticator())
    assert idle.listening is False
    assert idle.port == 0
    await idle.stop()  # no-op when never started


async def test_handler_survives_session_crash(proxy, monkeypatch):
    import app.proxy.server as server_module

    class Exploding:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(server_module, "ClientSession", Exploding)
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    assert await asyncio.wait_for(reader.read(), 2) == b""
    writer.close()
    assert server.listening is True


async def test_capability_noop_logout(client):
    reader, writer = client
    assert await send(client, b"A1 CAPABILITY\r\n") == b"* CAPABILITY IMAP4rev1 AUTH=PLAIN\r\n"
    assert await reader.readline() == b"A1 OK CAPABILITY completed\r\n"
    assert await send(client, b"A2 noop\r\n") == b"A2 OK NOOP completed\r\n"
    assert await send(client, b"A3 LOGOUT\r\n") == b"* BYE Logging out\r\n"
    assert await reader.readline() == b"A3 OK LOGOUT completed\r\n"
    assert await reader.read() == b""


async def test_bad_commands(client):
    assert await send(client, b"A1 SELECT INBOX\r\n") == (
        b"A1 BAD Command not allowed before authentication\r\n"
    )
    assert await send(client, b"garbage\r\n") == b"* BAD Invalid command\r\n"
    assert await send(client, b"A2 LOGIN onlyuser\r\n") == (
        b"A2 BAD LOGIN expects username and password\r\n"
    )
    assert await send(client, b'A3 LOGIN "unterminated pw\r\n') == (
        b"A3 BAD Unterminated quoted string\r\n"
    )
    assert await send(client, b"A4 LOGIN {abc} x\r\n") == b"A4 BAD Invalid literal\r\n"
    assert await send(client, b"A5 LOGIN {99999}\r\n") == b"A5 BAD Literal too large\r\n"
    assert await send(client, b"A6 LOGIN {5 x\r\n") == b"A6 BAD Invalid literal\r\n"


async def test_login_quoted_and_atom(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    assert await send(client, b'A1 LOGIN "User@Example.com" "p\\"w"\r\n') == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["User@Example.com"]
    writer.write(b"A2 SELECT INBOX\r\n")
    await writer.drain()
    assert await asyncio.wait_for(reader.readline(), 2) == b"ECHO A2 SELECT INBOX\r\n"


async def test_login_with_literal_arguments(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    assert await send(client, b"A1 LOGIN {16}\r\n") == b"+ Ready\r\n"
    writer.write(b"user@example.com {4}\r\n")
    await writer.drain()
    assert await reader.readline() == b"+ Ready\r\n"
    writer.write(b"pass\r\n")
    await writer.drain()
    assert await reader.readline() == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["user@example.com"]


async def test_login_with_non_synchronizing_literal(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    writer.write(b"A1 LOGIN {16+}\r\nuser@example.com {4+}\r\npass\r\n")
    await writer.drain()
    assert await asyncio.wait_for(reader.readline(), 2) == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["user@example.com"]


async def test_authenticate_plain_initial_response(client, proxy):
    _, authenticator = proxy
    initial = base64.b64encode(b"\x00user@example.com\x00pw").decode()
    assert await send(client, f"A1 AUTHENTICATE PLAIN {initial}\r\n".encode()) == (
        b"A1 OK Logged in\r\n"
    )
    assert authenticator.usernames == ["user@example.com"]


async def test_authenticate_plain_continuation(client, proxy):
    _, authenticator = proxy
    reader, writer = client
    assert await send(client, b"A1 AUTHENTICATE PLAIN\r\n") == b"+ \r\n"
    initial = base64.b64encode(b"authz\x00user@example.com\x00pw").decode()
    assert await send(client, f"{initial}\r\n".encode()) == b"A1 OK Logged in\r\n"
    assert authenticator.usernames == ["user@example.com"]


async def test_authenticate_errors(client):
    assert await send(client, b"A1 AUTHENTICATE XOAUTH2\r\n") == (
        b"A1 NO Unsupported authentication mechanism\r\n"
    )
    assert await send(client, b"A2 AUTHENTICATE PLAIN\r\n") == b"+ \r\n"
    assert await send(client, b"*\r\n") == b"A2 BAD Authentication cancelled\r\n"
    assert await send(client, b"A3 AUTHENTICATE PLAIN !!!\r\n") == (
        b"A3 BAD Invalid SASL PLAIN response\r\n"
    )
    bad = base64.b64encode(b"no-nul-separators").decode()
    assert await send(client, f"A4 AUTHENTICATE PLAIN {bad}\r\n".encode()) == (
        b"A4 BAD Invalid SASL PLAIN response\r\n"
    )


async def test_login_rejected_allows_retry(client, proxy):
    _, authenticator = proxy
    authenticator.error = LoginRejected("AUTHENTICATIONFAILED", "Unknown account")
    assert await send(client, b"A1 LOGIN nobody pw\r\n") == (
        b"A1 NO [AUTHENTICATIONFAILED] Unknown account\r\n"
    )
    authenticator.error = LoginRejected("UNAVAILABLE", "Token refresh failed")
    assert await send(client, b"A2 LOGIN nobody pw\r\n") == (
        b"A2 NO [UNAVAILABLE] Token refresh failed\r\n"
    )
    authenticator.error = None
    assert await send(client, b"A3 LOGIN user pw\r\n") == b"A3 OK Logged in\r\n"


async def test_unexpected_authenticator_error(client, proxy):
    _, authenticator = proxy
    authenticator.error = RuntimeError("db down")
    assert await send(client, b"A1 LOGIN user pw\r\n") == b"A1 NO [UNAVAILABLE] Internal error\r\n"


async def test_idle_timeout(client):
    reader, _ = client
    assert await asyncio.wait_for(reader.readline(), 2) == b"* BYE Idle timeout\r\n"
    assert await reader.read() == b""


async def test_client_disconnect_before_login(proxy):
    server, _ = proxy
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    await reader.readline()
    writer.write(b"A1 LOGIN {4}\r\n")
    await writer.drain()
    await reader.readline()
    writer.close()
    await asyncio.sleep(0.05)
    assert server.listening is True


async def test_pipe_ends_when_client_disconnects(client, proxy, echo):
    _, writer = client
    assert await send(client, b"A1 LOGIN user pw\r\n") == b"A1 OK Logged in\r\n"
    writer.close()
    await asyncio.wait_for(echo.eof.wait(), 2)
```

`tests/test_proxy_authenticator.py`:

```python
from datetime import timedelta

import httpx
import pytest
import respx

from app.proxy.server import ProxyAuthenticator
from app.proxy.session import LoginRejected
from app.proxy.upstream import UpstreamAuthError, UpstreamConnection, UpstreamConnectionError
from app.services.accounts import AccountService
from app.services.oauth import OAuthService
from tests.test_accounts_service import gmail_input
from tests.test_oauth_service import NOW, TOKEN_URL


class FakeConnect:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def __call__(self, host, port, email, token, **kwargs):
        self.calls.append((host, port, email, token))
        if self.error:
            raise self.error
        return UpstreamConnection(reader=None, writer=None)  # type: ignore[arg-type]


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def connect() -> FakeConnect:
    return FakeConnect()


@pytest.fixture
def authenticator(db, crypto, http, connect) -> ProxyAuthenticator:
    oauth = OAuthService(crypto, http, now=lambda: NOW)
    return ProxyAuthenticator(db, crypto, oauth, connect=connect)


async def create_account(db, crypto, **fields):
    async with db.session() as session:
        account = await AccountService(session, crypto).create(gmail_input())
        for key, value in fields.items():
            setattr(account, key, value)
        await session.commit()
        return account.id


async def load(db, crypto, account_id):
    async with db.session() as session:
        return await AccountService(session, crypto).get(account_id)


async def test_unknown_account(authenticator):
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("nobody@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert info.value.message == "Unknown account"


async def test_needs_authorization(authenticator, db, crypto):
    account_id = await create_account(db, crypto)
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("USER@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert "web UI" in info.value.message
    assert (await load(db, crypto, account_id)).last_error is None


@respx.mock
async def test_provider_unavailable(authenticator, db, crypto):
    account_id = await create_account(db, crypto, refresh_token_enc=crypto.encrypt("RT"))
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "UNAVAILABLE"
    assert (await load(db, crypto, account_id)).last_error.startswith("Token refresh failed")


async def test_success_updates_activity(authenticator, db, crypto, connect):
    account_id = await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=1),
        last_error="old",
    )
    conn = await authenticator.authenticate("user@example.com")
    assert isinstance(conn, UpstreamConnection)
    assert connect.calls == [("imap.gmail.com", 993, "user@example.com", "AT")]
    account = await load(db, crypto, account_id)
    assert account.last_error is None
    assert account.last_activity is not None


async def test_upstream_connection_error(authenticator, db, crypto, connect):
    account_id = await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=1),
    )
    connect.error = UpstreamConnectionError("refused")
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "UNAVAILABLE"
    assert info.value.message == "Upstream connection failed"
    assert (await load(db, crypto, account_id)).last_error == "Upstream connection failed: refused"


async def test_login_upstream_auth_error_sets_last_error(authenticator, db, crypto, connect):
    account_id = await create_account(
        db,
        crypto,
        refresh_token_enc=crypto.encrypt("RT"),
        access_token_enc=crypto.encrypt("AT"),
        access_token_expiry=NOW + timedelta(hours=1),
    )
    connect.error = UpstreamAuthError("status 400 (scope: x)")
    with pytest.raises(LoginRejected) as info:
        await authenticator.authenticate("user@example.com")
    assert info.value.code == "AUTHENTICATIONFAILED"
    assert info.value.message == "status 400 (scope: x)"
    account = await load(db, crypto, account_id)
    assert account.last_error == "Upstream rejected authentication: status 400 (scope: x)"
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `pytest tests/test_session.py tests/test_proxy_authenticator.py -v` → FAIL.

- [ ] **Step 3: Implement**

`app/proxy/session.py`:

```python
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
```

`app/proxy/server.py`:

```python
import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from app.crypto import Cryptographer
from app.db import Database
from app.models import utcnow
from app.proxy.session import Authenticator, ClientSession, LoginRejected
from app.proxy.upstream import (
    UpstreamAuthError,
    UpstreamConnection,
    UpstreamConnectionError,
    connect_and_authenticate,
)
from app.services.accounts import AccountService
from app.services.oauth import NeedsAuthorization, OAuthService, ProviderUnavailable

log = logging.getLogger(__name__)

ConnectFn = Callable[..., Awaitable[UpstreamConnection]]


class ProxyAuthenticator:
    """Resolves a LOGIN username to an authenticated upstream IMAP connection."""

    def __init__(
        self,
        db: Database,
        crypto: Cryptographer,
        oauth: OAuthService,
        connect: ConnectFn = connect_and_authenticate,
    ) -> None:
        self._db = db
        self._crypto = crypto
        self._oauth = oauth
        self._connect = connect

    async def authenticate(self, username: str) -> UpstreamConnection:
        async with self._db.session() as session:
            accounts = AccountService(session, self._crypto)
            account = await accounts.get_by_email(username)
            if account is None:
                raise LoginRejected("AUTHENTICATIONFAILED", "Unknown account")
            try:
                token = await self._oauth.get_valid_access_token(account)
            except NeedsAuthorization:
                await session.commit()
                raise LoginRejected(
                    "AUTHENTICATIONFAILED", "Account needs authorization in the web UI"
                ) from None
            except ProviderUnavailable:
                await session.commit()
                raise LoginRejected("UNAVAILABLE", "Token refresh failed") from None
            try:
                connection = await self._connect(
                    account.imap_host, account.imap_port, account.email, token
                )
            except UpstreamConnectionError as exc:
                account.last_error = f"Upstream connection failed: {exc}"
                await session.commit()
                raise LoginRejected("UNAVAILABLE", "Upstream connection failed") from exc
            except UpstreamAuthError as exc:
                account.last_error = f"Upstream rejected authentication: {exc}"
                await session.commit()
                raise LoginRejected("AUTHENTICATIONFAILED", str(exc)) from exc
            account.last_activity = utcnow()
            account.last_error = None
            await session.commit()
            return connection


class ImapProxyServer:
    def __init__(
        self, host: str, port: int, authenticator: Authenticator, *, timeout: float = 60.0
    ) -> None:
        self._host = host
        self._port = port
        self._authenticator = authenticator
        self._timeout = timeout
        self._server: asyncio.AbstractServer | None = None

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def port(self) -> int:
        if self._server is None:
            return 0
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        log.info("IMAP proxy listening on %s:%s", self._host, self.port)

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.debug("Client connected from %s", peer)
        session = ClientSession(reader, writer, self._authenticator, timeout=self._timeout)
        try:
            await session.run()
        except Exception:
            log.exception("Unhandled error in client session from %s", peer)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            log.debug("Client from %s disconnected", peer)
```

- [ ] **Step 4: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_session.py tests/test_proxy_authenticator.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add IMAP proxy server, client session and account authenticator

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: FastAPI app factory, session login, health endpoint

**Files:**
- Create: `app/state.py`, `app/main.py`, `app/web/__init__.py`, `app/web/deps.py`, `app/web/flash.py`, `app/web/templating.py`, `app/web/forms.py`, `app/web/dto.py`, `app/web/routers/__init__.py`, `app/web/routers/auth.py`, `app/web/routers/health.py`, `app/templates/base.html`, `app/templates/login.html`, `app/static/pico.min.css`
- Test: `tests/conftest.py` (app fixtures), `tests/test_web_auth.py`, `tests/test_web_health.py`, `tests/test_forms.py`, `tests/test_app.py`

**Interfaces:**
- Produces:
  - `AppState(settings, db, crypto, http, oauth, proxy)` dataclass; `create_app(settings: Settings | None = None) -> FastAPI` (stores `app.state.container: AppState`).
  - `web/deps.py`: `NotAuthenticated`, `get_state(request) -> AppState`, `get_db_session(request) -> AsyncIterator[AsyncSession]`, `require_admin(request) -> None`.
  - `web/flash.py`: `flash(request, message, category="info")`, `pop_flash(request) -> list[dict]`.
  - `web/templating.py`: `render(request, name, context=None, status_code=200) -> HTMLResponse`.
  - `web/forms.py`: `LoginForm`, `AccountForm` (+ `.to_input()`), `AuthorizeCompleteForm`, `parse_form(model, data) -> tuple[model | None, dict[str, str]]`.
  - `web/dto.py`: `HealthDto`, `AccountDto.from_model(account)`.
  - Test fixtures: `app_settings`, `app`, `client` (unauthenticated `httpx.AsyncClient` with lifespan), `admin` (logged-in client).

- [ ] **Step 1: Get Pico CSS**

```bash
mkdir -p app/static app/templates/accounts
curl -fsSL -o app/static/pico.min.css https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css
```

If the download fails, create `app/static/pico.min.css` with `body{font-family:system-ui;max-width:60rem;margin:2rem auto;padding:0 1rem}table{width:100%;border-collapse:collapse}td,th{padding:.4rem;border-bottom:1px solid #ddd}` and note it in the commit.

- [ ] **Step 2: Write failing tests**

Append to `tests/conftest.py`:

```python
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def app_settings(tmp_path, fernet_key) -> Settings:
    return Settings(
        _env_file=None,
        admin_user="admin",
        admin_password="pw",
        secret_key=fernet_key,
        imap_host="127.0.0.1",
        imap_port=0,
        data_dir=tmp_path / "data",
    )


@pytest.fixture
async def app(app_settings):
    application = create_app(app_settings)
    async with LifespanManager(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin(client):
    response = await client.post("/login", data={"username": "admin", "password": "pw"})
    assert response.status_code == 303
    return client
```

`tests/test_app.py`:

```python
import pytest

from app.main import create_app


def test_create_app_rejects_bad_secret(app_settings):
    app_settings.secret_key = "bad"
    with pytest.raises(ValueError, match="SECRET_KEY"):
        create_app(app_settings)


async def test_lifespan_creates_data_dir_and_starts_proxy(app, app_settings):
    assert (app_settings.data_dir / "proxy.db").exists()
    assert app.state.container.proxy.listening is True


def test_create_app_reads_settings_from_env(monkeypatch, fernet_key, tmp_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("SECRET_KEY", fernet_key)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    application = create_app()
    assert application.state.container.settings.data_dir == tmp_path


async def test_static_served(client):
    response = await client.get("/static/pico.min.css")
    assert response.status_code == 200
```

`tests/test_web_auth.py`:

```python
async def test_login_page(client):
    response = await client.get("/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text


async def test_login_wrong_password(client):
    response = await client.post("/login", data={"username": "admin", "password": "nope"})
    assert response.status_code == 401
    assert "Invalid username or password" in response.text


async def test_login_wrong_user(client):
    response = await client.post("/login", data={"username": "root", "password": "pw"})
    assert response.status_code == 401


async def test_login_success_and_redirect_when_logged_in(admin):
    response = await admin.get("/login")
    assert response.status_code == 303
    assert response.headers["location"] == "/"


async def test_logout(admin):
    response = await admin.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    response = await admin.get("/login")
    assert response.status_code == 200
```

`tests/test_web_health.py`:

```python
async def test_health_without_login(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "imap_listening": True,
        "accounts_total": 0,
        "accounts_authorized": 0,
    }
```

`tests/test_forms.py`:

```python
from app.web.forms import AccountForm, AuthorizeCompleteForm, LoginForm, parse_form

VALID = {
    "email": " User@Example.com ",
    "provider": "gmail",
    "imap_host": "imap.gmail.com",
    "imap_port": "993",
    "permission_url": "https://accounts.google.com/o/oauth2/auth",
    "token_url": "https://oauth2.googleapis.com/token",
    "scope": "https://mail.google.com/",
    "client_id": "cid",
    "client_secret": "",
    "redirect_uri": "http://localhost",
}


def test_account_form_valid_to_input():
    form, errors = parse_form(AccountForm, VALID)
    assert errors == {}
    data = form.to_input()
    assert data.email.lower() == "user@example.com"  # email-validator normalizes the domain
    assert data.imap_port == 993
    assert data.client_secret is None
    assert data.use_pkce is False


def test_account_form_checkbox_and_secret():
    form, _ = parse_form(AccountForm, {**VALID, "use_pkce": "on", "client_secret": " s "})
    assert form.use_pkce is True
    assert form.client_secret == "s"


def test_account_form_errors():
    form, errors = parse_form(
        AccountForm,
        {
            **VALID,
            "email": "not-an-email",
            "imap_port": "70000",
            "permission_url": "ftp://x",
            "scope": "",
            "provider": "aol",
        },
    )
    assert form is None
    assert set(errors) == {"email", "imap_port", "permission_url", "scope", "provider"}
    assert "http(s)" in errors["permission_url"]


def test_missing_fields_reported():
    _, errors = parse_form(AccountForm, {})
    assert "email" in errors and "client_id" in errors


def test_login_and_complete_forms():
    form, _ = parse_form(LoginForm, {"username": "a", "password": "b"})
    assert (form.username, form.password) == ("a", "b")
    _, errors = parse_form(AuthorizeCompleteForm, {"redirect_url": "  "})
    assert "redirect_url" in errors
```

- [ ] **Step 3: Run tests, expect ImportError**

Run: `pytest tests/test_app.py tests/test_web_auth.py tests/test_web_health.py tests/test_forms.py -v` → FAIL.

- [ ] **Step 4: Implement**

`app/state.py`:

```python
from dataclasses import dataclass

import httpx

from app.crypto import Cryptographer
from app.db import Database
from app.proxy.server import ImapProxyServer
from app.services.oauth import OAuthService
from app.settings import Settings


@dataclass
class AppState:
    settings: Settings
    db: Database
    crypto: Cryptographer
    http: httpx.AsyncClient
    oauth: OAuthService
    proxy: ImapProxyServer
```

`app/web/__init__.py`, `app/web/routers/__init__.py`: empty.

`app/web/deps.py`:

```python
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.state import AppState


class NotAuthenticated(Exception):
    pass


def get_state(request: Request) -> AppState:
    return request.app.state.container


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_state(request).db.session() as session:
        yield session


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise NotAuthenticated()
```

`app/web/flash.py`:

```python
from fastapi import Request


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session.setdefault("flash", []).append({"message": message, "category": category})


def pop_flash(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flash", [])
```

`app/web/templating.py`:

```python
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.web.flash import pop_flash

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(
    request: Request, name: str, context: dict | None = None, status_code: int = 200
) -> HTMLResponse:
    full_context = {
        "flash_messages": pop_flash(request),
        "admin": bool(request.session.get("admin")),
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, full_context, status_code=status_code)
```

`app/web/forms.py`:

```python
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator

from app.services.accounts import AccountInput

URL_PATTERN = re.compile(r"^https?://\S+$")


class LoginForm(BaseModel):
    username: str = ""
    password: str = ""


class AccountForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    provider: Literal["gmail", "o365", "custom"]
    imap_host: str = Field(min_length=1)
    imap_port: int = Field(ge=1, le=65535)
    permission_url: str
    token_url: str
    scope: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str | None = None
    redirect_uri: str = "http://localhost"
    use_pkce: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def _strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("permission_url", "token_url", "redirect_uri")
    @classmethod
    def _must_be_http_url(cls, value: str) -> str:
        if not URL_PATTERN.match(value):
            raise ValueError("must be an http(s) URL")
        return value

    @field_validator("client_secret")
    @classmethod
    def _blank_secret_is_none(cls, value: str | None) -> str | None:
        return value or None

    def to_input(self) -> AccountInput:
        return AccountInput(
            email=str(self.email),
            provider=self.provider,
            imap_host=self.imap_host,
            imap_port=self.imap_port,
            permission_url=self.permission_url,
            token_url=self.token_url,
            scope=self.scope,
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            use_pkce=self.use_pkce,
        )


class AuthorizeCompleteForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    redirect_url: str = Field(min_length=1)


def parse_form[T: BaseModel](
    model: type[T], data: Mapping[str, str]
) -> tuple[T | None, dict[str, str]]:
    """Validate submitted form data; returns (model, {}) or (None, {field: message})."""
    try:
        return model.model_validate(dict(data)), {}
    except ValidationError as exc:
        errors = {}
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "form"
            errors.setdefault(field, error["msg"].removeprefix("Value error, "))
        return None, errors
```

`app/web/dto.py`:

```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import Account, AccountStatus
from app.providers import PROVIDERS


class HealthDto(BaseModel):
    status: Literal["ok"] = "ok"
    imap_listening: bool
    accounts_total: int
    accounts_authorized: int


class AccountDto(BaseModel):
    id: int
    email: str
    provider: str
    provider_name: str
    imap_host: str
    imap_port: int
    redirect_uri: str
    status: AccountStatus
    access_token_expiry: datetime | None
    last_activity: datetime | None
    last_error: str | None
    has_pending_authorization: bool

    @classmethod
    def from_model(cls, account: Account) -> "AccountDto":
        provider = PROVIDERS.get(account.provider)
        return cls(
            id=account.id,
            email=account.email,
            provider=account.provider,
            provider_name=provider.name if provider else "Custom",
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            redirect_uri=account.redirect_uri,
            status=account.status,
            access_token_expiry=account.access_token_expiry,
            last_activity=account.last_activity,
            last_error=account.last_error,
            has_pending_authorization=account.pending_state is not None,
        )
```

`app/web/routers/auth.py`:

```python
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.state import AppState
from app.web.deps import get_state
from app.web.forms import LoginForm
from app.web.templating import render

router = APIRouter()


@router.get("/login")
async def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
async def login(request: Request, state: AppState = Depends(get_state)):
    form = LoginForm.model_validate(dict(await request.form()))
    settings = state.settings
    user_ok = secrets.compare_digest(form.username.encode(), settings.admin_user.encode())
    password_ok = secrets.compare_digest(form.password.encode(), settings.admin_password.encode())
    if not (user_ok & password_ok):
        return render(request, "login.html", {"error": "Invalid username or password"}, 401)
    request.session["admin"] = True
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
```

`app/web/routers/health.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.accounts import AccountService
from app.state import AppState
from app.web.deps import get_db_session, get_state
from app.web.dto import HealthDto

router = APIRouter()


@router.get("/api/health", response_model=HealthDto)
async def health(
    state: AppState = Depends(get_state), session: AsyncSession = Depends(get_db_session)
) -> HealthDto:
    total, authorized = await AccountService(session, state.crypto).count()
    return HealthDto(
        imap_listening=state.proxy.listening, accounts_total=total, accounts_authorized=authorized
    )
```

`app/main.py`:

```python
import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.crypto import Cryptographer
from app.db import Database
from app.proxy.server import ImapProxyServer, ProxyAuthenticator
from app.services.oauth import OAuthService
from app.settings import Settings
from app.state import AppState
from app.web.deps import NotAuthenticated
from app.web.routers import auth, health
from app.web.templating import STATIC_DIR

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    crypto = Cryptographer(settings.secret_key)
    db = Database(settings.database_url)
    http = httpx.AsyncClient(timeout=30.0)
    oauth = OAuthService(crypto, http)
    proxy = ImapProxyServer(
        settings.imap_host, settings.imap_port, ProxyAuthenticator(db, crypto, oauth)
    )
    state = AppState(settings, db, crypto, http, oauth, proxy)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        await db.create_all()
        await proxy.start()
        try:
            yield
        finally:
            await proxy.stop()
            await http.aclose()
            await db.dispose()

    app = FastAPI(title="Email OAuth2 Proxy", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.container = state
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(auth.router)
    app.include_router(health.router)

    @app.exception_handler(NotAuthenticated)
    async def _redirect_to_login(request: Request, exc: NotAuthenticated):
        return RedirectResponse("/login", status_code=303)

    return app


def main() -> None:  # pragma: no cover - covered in Task 10
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(
        create_app(settings),
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )
```

(The `pragma: no cover` on `main` is temporary and removed in Task 10 when its test is added.)

`app/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Email OAuth2 Proxy{% endblock %}</title>
  <link rel="stylesheet" href="/static/pico.min.css">
</head>
<body>
  <nav class="container">
    <ul><li><strong><a href="/">Email OAuth2 Proxy</a></strong></li></ul>
    <ul>
      {% if admin %}
      <li><a href="/accounts/new">Add account</a></li>
      <li><form method="post" action="/logout"><button class="secondary outline">Log out</button></form></li>
      {% endif %}
    </ul>
  </nav>
  <main class="container">
    {% for item in flash_messages %}
    <article class="flash flash-{{ item.category }}">{{ item.message }}</article>
    {% endfor %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

`app/templates/login.html`:

```html
{% extends "base.html" %}
{% block title %}Log in – Email OAuth2 Proxy{% endblock %}
{% block content %}
<article>
  <h2>Log in</h2>
  {% if error %}<p class="error"><mark>{{ error }}</mark></p>{% endif %}
  <form method="post" action="/login">
    <label>Username <input type="text" name="username" autofocus required></label>
    <label>Password <input type="password" name="password" required></label>
    <button type="submit">Log in</button>
  </form>
</article>
{% endblock %}
```

- [ ] **Step 5: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_app.py tests/test_web_auth.py tests/test_web_health.py tests/test_forms.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add web app factory with admin login and health endpoint

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Account pages (list, create, edit, delete)

**Files:**
- Create: `app/web/routers/accounts.py`, `app/templates/accounts/list.html`, `app/templates/accounts/form.html`
- Modify: `app/main.py` (include router)
- Test: `tests/test_web_accounts.py`

**Interfaces:**
- Consumes: `require_admin`, `get_db_session`, `get_state`, `AccountService`, `DuplicateEmailError`, `AccountForm`, `parse_form`, `AccountDto`, `PROVIDERS`, `render`, `flash`.
- Produces routes `GET /`, `GET /accounts/new`, `POST /accounts`, `GET /accounts/{id}/edit`, `POST /accounts/{id}`, `POST /accounts/{id}/delete`; helper `load_account(service, account_id) -> Account` raising `HTTPException(404)` (reused by Task 9).

- [ ] **Step 1: Write failing tests**

`tests/test_web_accounts.py`:

```python
import pytest

from app.services.accounts import AccountService
from tests.test_forms import VALID


async def get_accounts(app):
    state = app.state.container
    async with state.db.session() as session:
        return await AccountService(session, state.crypto).list()


async def test_requires_login(client):
    for url in ["/", "/accounts/new", "/accounts/1/edit"]:
        response = await client.get(url)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
    response = await client.post("/accounts", data=VALID)
    assert response.status_code == 303


async def test_list_empty(admin):
    response = await admin.get("/")
    assert response.status_code == 200
    assert "No accounts yet" in response.text


async def test_new_form_has_presets(admin):
    response = await admin.get("/accounts/new")
    assert response.status_code == 200
    assert "imap.gmail.com" in response.text
    assert "outlook.office365.com" in response.text
    assert 'name="use_pkce"' in response.text


async def test_create_redirects_to_authorize(admin, app):
    response = await admin.post("/accounts", data=VALID)
    assert response.status_code == 303
    accounts = await get_accounts(app)
    assert len(accounts) == 1
    assert response.headers["location"] == f"/accounts/{accounts[0].id}/authorize"
    page = await admin.get("/")
    assert "user@example.com" in page.text
    assert "Needs authorization" in page.text


async def test_create_invalid_rerenders(admin, app):
    response = await admin.post("/accounts", data={**VALID, "email": "bad"})
    assert response.status_code == 422
    assert "valid email" in response.text.lower()
    assert await get_accounts(app) == []


async def test_create_duplicate(admin):
    await admin.post("/accounts", data=VALID)
    response = await admin.post("/accounts", data=VALID)
    assert response.status_code == 422
    assert "already exists" in response.text


async def test_edit_and_update(admin, app):
    await admin.post("/accounts", data={**VALID, "client_secret": "sec"})
    (account,) = await get_accounts(app)
    response = await admin.get(f"/accounts/{account.id}/edit")
    assert response.status_code == 200
    assert "leave blank to keep" in response.text
    assert 'value="sec"' not in response.text  # stored secret never rendered
    response = await admin.post(
        f"/accounts/{account.id}", data={**VALID, "imap_host": "imap.example.org"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    (account,) = await get_accounts(app)
    assert account.imap_host == "imap.example.org"
    state = app.state.container
    async with state.db.session() as session:
        svc = AccountService(session, state.crypto)
        assert svc.client_secret(await svc.get(account.id)) == "sec"


async def test_update_invalid_and_duplicate(admin, app):
    await admin.post("/accounts", data=VALID)
    await admin.post("/accounts", data={**VALID, "email": "other@example.com"})
    first, second = await get_accounts(app)
    response = await admin.post(f"/accounts/{second.id}", data={**VALID, "scope": ""})
    assert response.status_code == 422
    response = await admin.post(f"/accounts/{second.id}", data=VALID)
    assert response.status_code == 422
    assert "already exists" in response.text


@pytest.mark.parametrize(
    "method,url",
    [("get", "/accounts/99/edit"), ("post", "/accounts/99"), ("post", "/accounts/99/delete")],
)
async def test_not_found(admin, method, url):
    response = await getattr(admin, method)(url, **({"data": VALID} if method == "post" else {}))
    assert response.status_code == 404


async def test_delete(admin, app):
    await admin.post("/accounts", data=VALID)
    (account,) = await get_accounts(app)
    response = await admin.post(f"/accounts/{account.id}/delete")
    assert response.status_code == 303
    assert await get_accounts(app) == []
    page = await admin.get("/")
    assert "deleted" in page.text
```

- [ ] **Step 2: Run tests, expect failures**

Run: `pytest tests/test_web_accounts.py -v` → FAIL (404s / ImportError).

- [ ] **Step 3: Implement**

`app/web/routers/accounts.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account
from app.providers import PROVIDER_KEYS, PROVIDERS
from app.services.accounts import AccountService, DuplicateEmailError
from app.state import AppState
from app.web.deps import get_db_session, get_state, require_admin
from app.web.dto import AccountDto
from app.web.flash import flash
from app.web.forms import AccountForm, parse_form
from app.web.templating import render

router = APIRouter(dependencies=[Depends(require_admin)])


async def load_account(service: AccountService, account_id: int) -> Account:
    account = await service.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _presets() -> dict[str, dict]:
    return {key: vars(PROVIDERS[key]) for key in PROVIDER_KEYS}


def _values_from_account(account: Account) -> dict:
    return {
        "email": account.email,
        "provider": account.provider,
        "imap_host": account.imap_host,
        "imap_port": account.imap_port,
        "permission_url": account.permission_url,
        "token_url": account.token_url,
        "scope": account.scope,
        "client_id": account.client_id,
        "client_secret": "",
        "redirect_uri": account.redirect_uri,
        "use_pkce": account.use_pkce,
    }


def _render_form(request, *, values, errors, action, is_edit, has_secret, status_code=200):
    return render(
        request,
        "accounts/form.html",
        {
            "values": values,
            "errors": errors,
            "action": action,
            "is_edit": is_edit,
            "has_secret": has_secret,
            "presets": _presets(),
        },
        status_code=status_code,
    )


@router.get("/")
async def list_accounts(
    request: Request,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    accounts = await AccountService(session, state.crypto).list()
    dtos = [AccountDto.from_model(account) for account in accounts]
    return render(request, "accounts/list.html", {"accounts": dtos})


@router.get("/accounts/new")
async def new_account(request: Request):
    gmail = PROVIDERS["gmail"]
    values = {
        "provider": "gmail",
        "imap_host": gmail.imap_host,
        "imap_port": gmail.imap_port,
        "permission_url": gmail.permission_url,
        "token_url": gmail.token_url,
        "scope": gmail.scope,
        "redirect_uri": "http://localhost",
        "use_pkce": False,
    }
    return _render_form(
        request, values=values, errors={}, action="/accounts", is_edit=False, has_secret=False
    )


@router.post("/accounts")
async def create_account(
    request: Request,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    raw = dict(await request.form())
    form, errors = parse_form(AccountForm, raw)
    if form is None:
        return _render_form(
            request,
            values=raw,
            errors=errors,
            action="/accounts",
            is_edit=False,
            has_secret=False,
            status_code=422,
        )
    service = AccountService(session, state.crypto)
    try:
        account = await service.create(form.to_input())
    except DuplicateEmailError:
        return _render_form(
            request,
            values=raw,
            errors={"email": "An account with this email already exists"},
            action="/accounts",
            is_edit=False,
            has_secret=False,
            status_code=422,
        )
    await session.commit()
    flash(request, f"Account {account.email} created. Authorize it below.", "success")
    return RedirectResponse(f"/accounts/{account.id}/authorize", status_code=303)


@router.get("/accounts/{account_id}/edit")
async def edit_account(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    return _render_form(
        request,
        values=_values_from_account(account),
        errors={},
        action=f"/accounts/{account.id}",
        is_edit=True,
        has_secret=account.client_secret_enc is not None,
    )


@router.post("/accounts/{account_id}")
async def update_account(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    service = AccountService(session, state.crypto)
    account = await load_account(service, account_id)
    raw = dict(await request.form())
    form, errors = parse_form(AccountForm, raw)
    action = f"/accounts/{account.id}"
    has_secret = account.client_secret_enc is not None
    if form is None:
        return _render_form(
            request,
            values=raw,
            errors=errors,
            action=action,
            is_edit=True,
            has_secret=has_secret,
            status_code=422,
        )
    try:
        await service.update(account, form.to_input(), keep_secret=form.client_secret is None)
    except DuplicateEmailError:
        return _render_form(
            request,
            values=raw,
            errors={"email": "An account with this email already exists"},
            action=action,
            is_edit=True,
            has_secret=has_secret,
            status_code=422,
        )
    await session.commit()
    flash(request, f"Account {account.email} updated.", "success")
    return RedirectResponse("/", status_code=303)


@router.post("/accounts/{account_id}/delete")
async def delete_account(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    service = AccountService(session, state.crypto)
    account = await load_account(service, account_id)
    email = account.email
    await service.delete(account)
    await session.commit()
    flash(request, f"Account {email} deleted.", "success")
    return RedirectResponse("/", status_code=303)
```

In `app/main.py` add `accounts` to the routers import and `app.include_router(accounts.router)` after `health`.

`app/templates/accounts/list.html`:

```html
{% extends "base.html" %}
{% block content %}
<h2>Accounts</h2>
{% if not accounts %}
<p>No accounts yet. <a href="/accounts/new">Add the first one</a>.</p>
{% else %}
<table>
  <thead>
    <tr><th>Email</th><th>Provider</th><th>Status</th><th>Token expires</th><th>Last login</th><th></th></tr>
  </thead>
  <tbody>
  {% for a in accounts %}
    <tr>
      <td>{{ a.email }}<br><small>{{ a.imap_host }}:{{ a.imap_port }}</small></td>
      <td>{{ a.provider_name }}</td>
      <td>
        {% if a.status == "authorized" %}<mark class="ok">Authorized</mark>
        {% elif a.status == "error" %}<mark class="err">Error</mark><br><small>{{ a.last_error }}</small>
        {% else %}<mark class="warn">Needs authorization</mark>{% endif %}
      </td>
      <td>{{ a.access_token_expiry.strftime("%Y-%m-%d %H:%M") ~ " UTC" if a.access_token_expiry else "–" }}</td>
      <td>{{ a.last_activity.strftime("%Y-%m-%d %H:%M") ~ " UTC" if a.last_activity else "never" }}</td>
      <td>
        <a href="/accounts/{{ a.id }}/authorize" role="button" class="outline">Authorize</a>
        <a href="/accounts/{{ a.id }}/edit" role="button" class="outline secondary">Edit</a>
        <form method="post" action="/accounts/{{ a.id }}/delete" style="display:inline" onsubmit="return confirm('Delete {{ a.email }}?')">
          <button class="outline contrast">Delete</button>
        </form>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`app/templates/accounts/form.html`:

```html
{% extends "base.html" %}
{% macro field(name, label, type="text", required=True) -%}
<label>{{ label }}
  <input type="{{ type }}" name="{{ name }}" id="f-{{ name }}" value="{{ values.get(name, '') }}" {% if required %}required{% endif %}
         {% if errors.get(name) %}aria-invalid="true"{% endif %}>
  {% if errors.get(name) %}<small class="error">{{ errors[name] }}</small>{% endif %}
</label>
{%- endmacro %}
{% block content %}
<h2>{{ "Edit account" if is_edit else "Add account" }}</h2>
<form method="post" action="{{ action }}">
  {{ field("email", "Email address (IMAP username)", "email") }}
  <label>Provider
    <select name="provider" id="f-provider">
      {% for key, preset in presets.items() %}
      <option value="{{ key }}" {% if values.get("provider") == key %}selected{% endif %}>{{ preset.name }}</option>
      {% endfor %}
    </select>
    {% if errors.get("provider") %}<small class="error">{{ errors["provider"] }}</small>{% endif %}
  </label>
  <div class="grid">
    {{ field("imap_host", "IMAP server") }}
    {{ field("imap_port", "IMAP port (TLS)", "number") }}
  </div>
  {{ field("client_id", "Client ID") }}
  <label>Client secret{% if has_secret %} <small>(leave blank to keep the stored secret)</small>{% endif %}
    <input type="password" name="client_secret" id="f-client_secret" value="" autocomplete="new-password">
  </label>
  {{ field("permission_url", "Authorization URL") }}
  {{ field("token_url", "Token URL") }}
  {{ field("scope", "Scope") }}
  {{ field("redirect_uri", "Redirect URI (as registered with the provider)") }}
  <label><input type="checkbox" name="use_pkce" id="f-use_pkce" {% if values.get("use_pkce") in (True, "on", "true") %}checked{% endif %}> Use PKCE</label>
  <button type="submit">{{ "Save" if is_edit else "Create and authorize" }}</button>
</form>
<script>
  const presets = {{ presets | tojson }};
  document.getElementById("f-provider").addEventListener("change", (event) => {
    const p = presets[event.target.value];
    if (!p) return;
    for (const key of ["imap_host", "imap_port", "permission_url", "token_url", "scope"]) {
      document.getElementById("f-" + key).value = p[key];
    }
    document.getElementById("f-use_pkce").checked = p.use_pkce;
  });
</script>
{% endblock %}
```

- [ ] **Step 4: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_web_accounts.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add account management pages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Authorization pages (start, paste redirect URL, revoke)

**Files:**
- Create: `app/web/routers/authorize.py`, `app/templates/accounts/authorize.html`
- Modify: `app/main.py` (include router)
- Test: `tests/test_web_authorize.py`

**Interfaces:**
- Consumes: `load_account`, `OAuthService` (via `state.oauth`), `OAuthError`, `AuthorizeCompleteForm`, `parse_form`, `AccountDto`, `render`, `flash`.
- Produces routes `GET /accounts/{id}/authorize`, `POST /accounts/{id}/authorize/start`, `POST /accounts/{id}/authorize/complete`, `POST /accounts/{id}/revoke`.

- [ ] **Step 1: Write failing tests**

`tests/test_web_authorize.py`:

```python
from urllib.parse import parse_qs, urlsplit

import httpx
import respx

from app.services.accounts import AccountService
from tests.test_forms import VALID
from tests.test_oauth_service import TOKEN_URL


async def create(admin, app):
    await admin.post("/accounts", data=VALID)
    state = app.state.container
    async with state.db.session() as session:
        (account,) = await AccountService(session, state.crypto).list()
    return account.id


async def reload(app, account_id):
    state = app.state.container
    async with state.db.session() as session:
        return await AccountService(session, state.crypto).get(account_id)


def extract_state(html: str) -> str:
    start = html.index("https://accounts.google.com/o/oauth2/auth?")
    end = html.index('"', start)
    url = html[start:end].replace("&amp;", "&")
    return parse_qs(urlsplit(url).query)["state"][0]


async def test_get_page_before_start(admin, app):
    account_id = await create(admin, app)
    response = await admin.get(f"/accounts/{account_id}/authorize")
    assert response.status_code == 200
    assert "Start authorization" in response.text
    assert "redirect_url" not in response.text


async def test_start_shows_url_and_paste_form(admin, app):
    account_id = await create(admin, app)
    response = await admin.post(f"/accounts/{account_id}/authorize/start")
    assert response.status_code == 200
    state = extract_state(response.text)
    assert (await reload(app, account_id)).pending_state == state
    assert 'name="redirect_url"' in response.text
    page = await admin.get(f"/accounts/{account_id}/authorize")
    assert 'name="redirect_url"' in page.text
    assert "Restart authorization" in page.text


@respx.mock
async def test_complete_success(admin, app):
    account_id = await create(admin, app)
    response = await admin.post(f"/accounts/{account_id}/authorize/start")
    state = extract_state(response.text)
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
        )
    )
    response = await admin.post(
        f"/accounts/{account_id}/authorize/complete",
        data={"redirect_url": f"http://localhost/?code=abc&state={state}"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    account = await reload(app, account_id)
    assert account.refresh_token_enc is not None
    page = await admin.get("/")
    assert "Authorized" in page.text and "authorized successfully" in page.text


async def test_complete_validation_error(admin, app):
    account_id = await create(admin, app)
    await admin.post(f"/accounts/{account_id}/authorize/start")
    response = await admin.post(
        f"/accounts/{account_id}/authorize/complete", data={"redirect_url": ""}
    )
    assert response.status_code == 422
    assert "redirect_url" in response.text


async def test_complete_oauth_error(admin, app):
    account_id = await create(admin, app)
    await admin.post(f"/accounts/{account_id}/authorize/start")
    response = await admin.post(
        f"/accounts/{account_id}/authorize/complete",
        data={"redirect_url": "http://localhost/?code=abc&state=wrong"},
    )
    assert response.status_code == 422
    assert "State mismatch" in response.text
    assert (await reload(app, account_id)).pending_state is not None


async def test_revoke(admin, app):
    account_id = await create(admin, app)
    state = app.state.container
    async with state.db.session() as session:
        account = await AccountService(session, state.crypto).get(account_id)
        account.refresh_token_enc = "x"
        await session.commit()
    response = await admin.post(f"/accounts/{account_id}/revoke")
    assert response.status_code == 303
    assert (await reload(app, account_id)).refresh_token_enc is None


async def test_not_found_and_login_required(admin, client):
    for url in [
        "/accounts/99/authorize/start",
        "/accounts/99/authorize/complete",
        "/accounts/99/revoke",
    ]:
        assert (await admin.post(url, data={"redirect_url": "x"})).status_code == 404
    assert (await admin.get("/accounts/99/authorize")).status_code == 404
    assert (await client.get("/accounts/1/authorize")).status_code == 303
```

- [ ] **Step 2: Run tests, expect failures**

Run: `pytest tests/test_web_authorize.py -v` → FAIL.

- [ ] **Step 3: Implement**

`app/web/routers/authorize.py`:

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.accounts import AccountService
from app.services.oauth import OAuthError
from app.state import AppState
from app.web.deps import get_db_session, get_state, require_admin
from app.web.dto import AccountDto
from app.web.flash import flash
from app.web.forms import AuthorizeCompleteForm, parse_form
from app.web.routers.accounts import load_account
from app.web.templating import render

router = APIRouter(dependencies=[Depends(require_admin)])


def _page(request, account, *, auth_url=None, error=None, errors=None, status_code=200):
    return render(
        request,
        "accounts/authorize.html",
        {
            "account": AccountDto.from_model(account),
            "auth_url": auth_url,
            "error": error,
            "errors": errors or {},
        },
        status_code=status_code,
    )


@router.get("/accounts/{account_id}/authorize")
async def authorize_page(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    return _page(request, account)


@router.post("/accounts/{account_id}/authorize/start")
async def authorize_start(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    auth_url = state.oauth.build_authorization_url(account)
    await session.commit()
    return _page(request, account, auth_url=auth_url)


@router.post("/accounts/{account_id}/authorize/complete")
async def authorize_complete(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    form, errors = parse_form(AuthorizeCompleteForm, dict(await request.form()))
    if form is None:
        return _page(request, account, errors=errors, status_code=422)
    try:
        await state.oauth.complete_authorization(account, form.redirect_url)
    except OAuthError as exc:
        return _page(request, account, error=exc.message, status_code=422)
    await session.commit()
    flash(request, f"Account {account.email} authorized successfully.", "success")
    return RedirectResponse("/", status_code=303)


@router.post("/accounts/{account_id}/revoke")
async def revoke(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    state.oauth.revoke(account)
    await session.commit()
    flash(request, f"Tokens for {account.email} were removed.", "info")
    return RedirectResponse("/", status_code=303)
```

In `app/main.py` import `authorize` and `app.include_router(authorize.router)`.

`app/templates/accounts/authorize.html`:

```html
{% extends "base.html" %}
{% block content %}
<h2>Authorize {{ account.email }}</h2>
<p>Provider: {{ account.provider_name }} · Status:
  {% if account.status == "authorized" %}<mark class="ok">Authorized</mark>
  {% elif account.status == "error" %}<mark class="err">Error</mark> <small>{{ account.last_error }}</small>
  {% else %}<mark class="warn">Needs authorization</mark>{% endif %}
</p>
{% if error %}<article class="flash flash-error">{{ error }}</article>{% endif %}

{% if auth_url %}
<article>
  <h3>Step 1 – log in with the provider</h3>
  <p>Open this link in your browser and sign in to <strong>{{ account.email }}</strong>:</p>
  <p><a href="{{ auth_url }}" target="_blank" rel="noopener">{{ auth_url }}</a></p>
  <p><small>After login the browser is sent to <code>{{ account.redirect_uri }}</code>. The page will most likely fail to load – that is expected. Copy the full address from the address bar.</small></p>
</article>
{% endif %}

{% if auth_url or account.has_pending_authorization %}
<article>
  <h3>Step 2 – paste the redirect URL</h3>
  <form method="post" action="/accounts/{{ account.id }}/authorize/complete">
    <label>Redirect URL
      <textarea name="redirect_url" rows="3" placeholder="{{ account.redirect_uri }}/?code=...&state=..." required {% if errors.get("redirect_url") %}aria-invalid="true"{% endif %}></textarea>
      {% if errors.get("redirect_url") %}<small class="error">{{ errors["redirect_url"] }}</small>{% endif %}
    </label>
    <button type="submit">Complete authorization</button>
  </form>
</article>
<form method="post" action="/accounts/{{ account.id }}/authorize/start">
  <button class="secondary outline">Restart authorization</button>
</form>
{% else %}
<form method="post" action="/accounts/{{ account.id }}/authorize/start">
  <button>Start authorization</button>
</form>
{% endif %}

{% if account.status != "needs_authorization" %}
<form method="post" action="/accounts/{{ account.id }}/revoke" onsubmit="return confirm('Remove stored tokens?')">
  <button class="outline contrast">Remove stored tokens</button>
</form>
{% endif %}
<p><a href="/">Back to accounts</a></p>
{% endblock %}
```

- [ ] **Step 4: Run tests + lint, expect pass**

Run: `ruff format . && ruff check . && pytest tests/test_web_authorize.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add OAuth authorization pages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Entrypoint, Docker image, README, full-suite coverage gate

**Files:**
- Modify: `app/main.py` (remove `pragma: no cover` from `main`)
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing test**

`tests/test_main.py`:

```python
from app import main as main_module


def test_main_runs_uvicorn(monkeypatch, fernet_key):
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("SECRET_KEY", fernet_key)
    monkeypatch.setenv("WEB_PORT", "9999")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    main_module.main()
    ((app, kwargs),) = calls
    assert app.title == "Email OAuth2 Proxy"
    assert kwargs == {"host": "0.0.0.0", "port": 9999, "log_level": "debug"}
```

- [ ] **Step 2: Run test, expect pass but coverage gap**

Run: `pytest tests/test_main.py -v` → PASS (the pragma only affects coverage). Remove the `# pragma: no cover - covered in Task 10` comment from `main()` in `app/main.py`.

- [ ] **Step 3: Docker + README**

`.dockerignore`:

```
.venv
.git
tests
docs
EmailOauth2ProxyBrunoCollection
.pytest_cache
__pycache__
*.db
.env
```

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --no-create-home proxy \
    && mkdir -p /data && chown proxy:proxy /data

USER proxy
VOLUME ["/data"]
EXPOSE 8080 1993

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

CMD ["email-oauth2-proxy-web"]
```

`docker-compose.yml`:

```yaml
services:
  email-oauth2-proxy:
    build: .
    image: email-oauth2-proxy-web:latest
    restart: unless-stopped
    ports:
      - "8080:8080"            # web UI
      - "127.0.0.1:1993:1993"  # IMAP – keep local/firewalled: the client password is ignored
    environment:
      ADMIN_USER: admin
      ADMIN_PASSWORD: change-me
      SECRET_KEY: ""           # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
      LOG_LEVEL: INFO
    volumes:
      - proxy-data:/data

volumes:
  proxy-data:
```

`README.md` sections (write in full):

1. **What it is** – two sentences + link to upstream project.
2. **Quick start** – generate `SECRET_KEY`, edit `docker-compose.yml`, `docker compose up -d`, open `http://localhost:8080`, log in.
3. **Registering an OAuth client** – Google Cloud Console (Desktop app client, redirect `http://localhost`, enable Gmail via scope `https://mail.google.com/`) and Microsoft Entra (Public client / mobile & desktop, redirect `http://localhost`, delegated permission `IMAP.AccessAsUser.All` + `offline_access`).
4. **Adding and authorizing an account** – Add account → choose preset → paste client id/secret → Create and authorize → Start authorization → open link → log in → copy the address bar URL (`http://localhost/?code=…&state=…`) → paste → Complete.
5. **Mail client setup** – server = docker host, port 1993, connection security none / plain, authentication "normal password", username = the account email, password = anything.
6. **Environment variables** – table copied from spec §9.
7. **Security notes** – client password ignored, so bind port 1993 to localhost/LAN only; secrets encrypted with `SECRET_KEY`; losing the key means re-authorizing all accounts.
8. **Development** – `python -m venv .venv`, `pip install -e ".[dev]"`, `ruff format . && ruff check .`, `pytest --cov`.

- [ ] **Step 4: Full suite with coverage; fix gaps**

Run: `ruff format . && ruff check . && pytest --cov --cov-report=term-missing`
Expected: all tests PASS, `TOTAL … 100%`. For any uncovered line: add a test that exercises it (do not add `pragma: no cover` except for `Protocol` method bodies `...`, which coverage already excludes when `exclude_also = ["\\.\\.\\."]` is added under `[tool.coverage.report]` – add that line if needed).

- [ ] **Step 5: Docker smoke test**

```bash
docker build -t email-oauth2-proxy-web .
KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
docker run --rm -d --name eop -e ADMIN_PASSWORD=pw -e SECRET_KEY=$KEY -p 8080:8080 -p 127.0.0.1:1993:1993 email-oauth2-proxy-web
sleep 3
curl -s http://localhost:8080/api/health          # {"status":"ok","imap_listening":true,...}
printf 'A1 CAPABILITY\r\nA2 LOGOUT\r\n' | nc -w 2 localhost 1993   # greeting + CAPABILITY + BYE
docker stop eop
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add entrypoint, Docker image and README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Endpoint docs + Bruno collection

**Files:**
- Create: `docs/documentation/Auth/Login.md`, `docs/documentation/Auth/Logout.md`, `docs/documentation/Accounts/ListAccounts.md`, `docs/documentation/Accounts/NewAccountForm.md`, `docs/documentation/Accounts/CreateAccount.md`, `docs/documentation/Accounts/EditAccountForm.md`, `docs/documentation/Accounts/UpdateAccount.md`, `docs/documentation/Accounts/DeleteAccount.md`, `docs/documentation/Authorize/AuthorizePage.md`, `docs/documentation/Authorize/StartAuthorization.md`, `docs/documentation/Authorize/CompleteAuthorization.md`, `docs/documentation/Authorize/Revoke.md`, `docs/documentation/Health/Health.md`
- Create: `EmailOauth2ProxyBrunoCollection/bruno.json`, `EmailOauth2ProxyBrunoCollection/environments/local.bru`, one `.bru` per endpoint in `Auth/`, `Accounts/`, `Authorize/`, `Health/`.

- [ ] **Step 1: Endpoint docs**

Each file follows this template (fill every section from the router code; example for `Accounts/CreateAccount.md`):

```markdown
# Create account

**Purpose:** Stores a new mailbox configuration (provider endpoints + OAuth client credentials) and redirects to its authorization page.

**Method + URL:** `POST /accounts`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303).

**Request:** `application/x-www-form-urlencoded`

| Field | Required | Notes |
|---|---|---|
| email | yes | valid email, stored lowercase, unique |
| provider | yes | `gmail`, `o365`, `custom` |
| imap_host | yes | |
| imap_port | yes | 1–65535 |
| permission_url | yes | http(s) URL |
| token_url | yes | http(s) URL |
| scope | yes | |
| client_id | yes | |
| client_secret | no | blank = none |
| redirect_uri | no | default `http://localhost` |
| use_pkce | no | checkbox (`on`) |

**Response:** `303 See Other`, `Location: /accounts/{id}/authorize`, flash message set.

**Errors:**
- `422` – validation failed or email already exists; the form is re-rendered with messages.
- `303 → /login` – not logged in.
```

Health doc includes the JSON body example `{"status":"ok","imap_listening":true,"accounts_total":1,"accounts_authorized":1}`.

- [ ] **Step 2: Bruno collection**

`EmailOauth2ProxyBrunoCollection/bruno.json`:

```json
{
  "version": "1",
  "name": "EmailOauth2ProxyBrunoCollection",
  "type": "collection",
  "ignore": ["node_modules", ".git"]
}
```

`EmailOauth2ProxyBrunoCollection/environments/local.bru`:

```
vars {
  baseUrl: http://localhost:8080
  adminUser: admin
  adminPassword: change-me
  accountId: 1
}
```

Request file format (example `Auth/Login.bru`; `seq` increments per folder):

```
meta {
  name: Login
  type: http
  seq: 1
}

post {
  url: {{baseUrl}}/login
  body: formUrlEncoded
  auth: none
}

body:form-urlencoded {
  username: {{adminUser}}
  password: {{adminPassword}}
}
```

Create: `Auth/Login.bru`, `Auth/Logout.bru`; `Accounts/ListAccounts.bru` (GET `/`), `Accounts/NewAccountForm.bru` (GET `/accounts/new`), `Accounts/CreateAccount.bru` (POST `/accounts`, all form fields with Gmail preset values), `Accounts/EditAccountForm.bru` (GET `/accounts/{{accountId}}/edit`), `Accounts/UpdateAccount.bru` (POST `/accounts/{{accountId}}`), `Accounts/DeleteAccount.bru`; `Authorize/AuthorizePage.bru` (GET), `Authorize/StartAuthorization.bru` (POST), `Authorize/CompleteAuthorization.bru` (POST with `redirect_url`), `Authorize/Revoke.bru`; `Health/Health.bru` (GET `/api/health`). GET requests use `body: none`.

- [ ] **Step 3: Final checks + commit**

Run: `ruff format . && ruff check . && pytest --cov` → PASS, 100 %.

```bash
git add -A
git commit -m "docs: add endpoint documentation and Bruno collection

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Verification (end-to-end)

1. `pytest --cov` → 100 %, `ruff check .` clean.
2. `docker compose up --build` with a real `SECRET_KEY`; open `http://localhost:8080`, log in.
3. Add a Gmail (or O365) account with real client credentials → Start authorization → sign in → paste redirect URL → status "Authorized".
4. Configure Thunderbird (or `openssl`-free test: `nc localhost 1993`, `A1 LOGIN user@gmail.com x`, `A2 LIST "" "*"`) → mailbox listing arrives from the real server.
5. Revoke tokens in the UI → IMAP login now answers `NO [AUTHENTICATIONFAILED] Account needs authorization in the web UI`.
6. `docker compose down && up` → account and tokens persist (volume).
