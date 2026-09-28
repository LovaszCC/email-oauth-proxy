# IMAP OAuth 2.0 Proxy – Design Spec

Date: 2026-09-28
Branch: `feature/1-imap-oauth2-proxy`

## 1. Goal

A self-hosted, headless Linux service, shipped as **one Docker container**, that does what
[simonrob/email-oauth2-proxy](https://github.com/simonrob/email-oauth2-proxy) does for IMAP:
a mail client connects with plain `LOGIN user pass`, the proxy connects to the real IMAP server
(Gmail, Office 365, or any XOAUTH2-capable provider) and authenticates with OAuth 2.0
(`AUTHENTICATE XOAUTH2`), then pipes traffic transparently.

Differences from upstream:

- **Configuration and authorization happen in a web UI**, not in an INI file or desktop GUI.
  The admin enters client id / secret / provider details in the browser, the proxy generates the
  provider's authorization URL, the admin logs in with the provider in their own browser, and pastes
  the resulting redirect URL (`http://localhost/?code=...&state=...`) back into the web UI.
- **IMAP only.** No POP, no SMTP.
- **Single listening port**, accounts routed by the username sent in `LOGIN`.
- **The IMAP password sent by the mail client is ignored.** Only the username selects the account.

## 2. Scope

In scope:

- Multi-account support (each account = one mailbox / one email address).
- Provider presets: Gmail, Office 365 (`common` tenant), plus Custom (all URLs editable, optional PKCE).
- OAuth 2.0 authorization-code flow with manual redirect-URL paste; automatic refresh-token use.
- Web UI protected by a single admin login (credentials from environment variables).
- Encrypted-at-rest storage of client secret, access token and refresh token.
- Docker image + `docker-compose.yml` sample, persistent SQLite in a volume.
- Tests with 100% coverage target, endpoint docs, Bruno collection.

Out of scope (YAGNI, may be added later):

- POP3 / SMTP proxying.
- Device-code, client-credentials, ROPCG and service-account flows.
- Automatic redirect capture (local HTTP callback server).
- TLS between mail client and proxy (STARTTLS / implicit TLS on the listening port).
- Per-account local passwords; multi-user admin; catch-all domain accounts.
- Database migrations (tables are created on startup).

## 3. Decisions (agreed with the user)

| Topic | Decision |
|---|---|
| Stack | Python 3.12, own asyncio proxy code (not wrapping upstream `emailproxy.py`) |
| Process model | One process: uvicorn runs FastAPI; IMAP proxy runs as an asyncio task on the same loop |
| Listen model | One IMAP port, route by `LOGIN` username |
| Client password | Ignored (document that the IMAP port must be firewalled / LAN-only) |
| Web auth | Single admin, `ADMIN_USER` / `ADMIN_PASSWORD` env vars, signed session cookie |
| Providers | Gmail + Office 365 presets + Custom |
| Frontend | Server-rendered Jinja2 templates, vendored Pico.css, minimal inline JS for preset prefill; no build step |
| Storage | SQLite via SQLAlchemy async (aiosqlite) in `DATA_DIR` |

## 4. Architecture

```
app/
  main.py          FastAPI application factory; lifespan starts/stops the IMAP proxy task
  settings.py      pydantic-settings; env vars (see §9)
  db.py            async engine/session factory, create_all on startup
  models.py        SQLAlchemy models (Account)
  crypto.py        Fernet encrypt/decrypt helpers keyed by SECRET_KEY
  providers.py     preset definitions (gmail, o365, custom)
  services/
    accounts.py    AccountService – create/update/delete/list/get_by_email (the "Action" layer)
    oauth.py       OAuthService – build_authorization_url, complete_authorization, refresh, get_valid_access_token
  proxy/
    server.py      ImapProxyServer – asyncio.start_server wrapper, start/stop
    session.py     ClientSession – pre-authentication IMAP command handling
    upstream.py    connect_and_authenticate(host, port, email, token) -> (reader, writer)
    pipe.py        bidirectional byte pipe between client and upstream streams
    xoauth2.py     SASL XOAUTH2 string builder
  web/
    deps.py        get_db, require_admin (session check)
    forms.py       pydantic form models = validation layer ("Form Request")
    dto.py         pydantic response models for JSON endpoints ("DTO")
    routers/
      auth.py      /login, /logout
      accounts.py  /, /accounts...
      authorize.py /accounts/{id}/authorize...
      health.py    /api/health
  templates/       base.html, login.html, accounts/list.html, accounts/form.html, accounts/authorize.html
  static/          pico.min.css
tests/
Dockerfile, docker-compose.yml, pyproject.toml, README.md
```

Rules mirrored from the user's Laravel conventions:

- Routers stay thin (parse request, call a service, render/redirect).
- Business logic lives in `services/` classes.
- Input validation lives in `web/forms.py` pydantic models, never in routers or services.
- JSON responses are built from `web/dto.py` models.

## 5. Data model

Table `accounts`:

| Column | Type | Notes |
|---|---|---|
| id | int PK | |
| email | str unique | stored lowercase; the IMAP username |
| provider | str | `gmail` / `o365` / `custom` |
| imap_host | str | e.g. `imap.gmail.com`, `outlook.office365.com` |
| imap_port | int | default 993, implicit TLS |
| permission_url | str | authorization endpoint |
| token_url | str | token endpoint |
| scope | str | space-separated |
| client_id | str | |
| client_secret_enc | str nullable | Fernet-encrypted; null when provider needs no secret |
| redirect_uri | str | default `http://localhost` |
| use_pkce | bool | default false; preset `gmail`/`o365` false |
| access_token_enc | str nullable | Fernet-encrypted |
| access_token_expiry | datetime nullable | UTC |
| refresh_token_enc | str nullable | Fernet-encrypted |
| pending_state | str nullable | OAuth `state` of an in-progress authorization |
| pending_code_verifier | str nullable | PKCE verifier of an in-progress authorization |
| last_activity | datetime nullable | last successful proxied login |
| last_error | str nullable | last auth/refresh/upstream error message |
| created_at / updated_at | datetime | |

Derived **status** (not stored): `authorized` when a refresh token exists and `last_error` is empty;
`needs_authorization` when no refresh token; `error` when `last_error` is set.

## 6. OAuth 2.0 flow

**Start** (`POST /accounts/{id}/authorize/start`):

1. Generate `state = secrets.token_urlsafe(32)`; if `use_pkce`, generate a code verifier and S256 challenge.
2. Save `pending_state` / `pending_code_verifier` on the account.
3. Build the authorization URL: `client_id`, `redirect_uri`, `response_type=code`, `scope`, `state`,
   plus `code_challenge`/`code_challenge_method=S256` when PKCE, plus `access_type=offline&prompt=consent`
   for the Gmail preset (required to receive a refresh token).
4. Render the authorize page showing the URL (link + copyable text) and a textarea for the redirect URL.

**Complete** (`POST /accounts/{id}/authorize/complete`, field `redirect_url`):

1. Parse the pasted URL's query string. Require `code` and `state`; `state` must equal `pending_state`.
   Provider `error`/`error_description` parameters are surfaced as a form error.
2. POST to `token_url` with `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`,
   `client_secret` (if set), `code_verifier` (if PKCE). HTTP client: httpx, 30 s timeout.
3. On success store encrypted `access_token`, `refresh_token` (if absent, keep the previous one),
   `access_token_expiry = now + expires_in`, clear pending fields and `last_error`.
4. On failure keep pending fields, show the provider's error message.

**Refresh** (`OAuthService.get_valid_access_token(account)`), called by the proxy on every login:

1. If `access_token` exists and `access_token_expiry > now + 60 s`, return it.
2. Else POST `grant_type=refresh_token` with `refresh_token`, `client_id`, `client_secret` (if set).
3. On success store the new access token (and refresh token if the provider rotated it).
4. On `invalid_grant` (or any 4xx) clear all tokens, set `last_error`, raise `NeedsAuthorization`.
   On network error set `last_error`, raise `ProviderUnavailable` (tokens kept).

**Revoke** (`POST /accounts/{id}/revoke`): clears tokens and pending fields locally only.

## 7. IMAP proxy

Listening: `asyncio.start_server(handle, IMAP_HOST, IMAP_PORT)`, plain TCP.

**Pre-authentication state machine** (`ClientSession`), one per connection:

- Greeting: `* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] Email OAuth2 Proxy ready`.
- `CAPABILITY` → `* CAPABILITY IMAP4rev1 AUTH=PLAIN` + `tag OK`.
- `NOOP` → `tag OK`. `LOGOUT` → `* BYE` + `tag OK`, close.
- `LOGIN user pass` → arguments may be atoms, quoted strings or literals (`{n}` + continuation `+`).
- `AUTHENTICATE PLAIN [initial]` → continuation `+`, decode base64 `\0user\0pass`.
- Anything else → `tag BAD Command not allowed before authentication` (or `tag BAD` on parse error).
- Idle timeout before authentication: 60 s → `* BYE` and close.

**Login handling**:

1. Lowercase username, `AccountService.get_by_email`. Unknown → `tag NO [AUTHENTICATIONFAILED] Unknown account`.
2. `OAuthService.get_valid_access_token`. `NeedsAuthorization` → `tag NO [AUTHENTICATIONFAILED] Account needs authorization in the web UI`;
   `ProviderUnavailable` → `tag NO [UNAVAILABLE] Token refresh failed`.
3. `upstream.connect_and_authenticate`: TLS (default verified `ssl.create_default_context()`) to `imap_host:imap_port`,
   read greeting, send `P1 AUTHENTICATE XOAUTH2 <base64(user=..\x01auth=Bearer ..\x01\x01)>`.
   - Server `P1 OK` → success.
   - Server `+ <base64 json>` → send empty line `\r\n`, read the final `P1 NO`, fail with decoded message.
   - Server `P1 NO/BAD` → fail with message.
   - Connect/TLS/timeout errors → `tag NO [UNAVAILABLE] Upstream connection failed`; `last_error` set.
   - XOAUTH2 failure → `tag NO [AUTHENTICATIONFAILED] <message>`; `last_error` set.
4. On success: reply `tag OK [CAPABILITY ...] Logged in` (capabilities taken from the upstream `OK` response if present),
   set `last_activity`, clear `last_error`, then hand both stream pairs to `pipe.run()`.

**Pipe**: two tasks copying raw bytes in each direction (`reader.read(65536)` → `writer.write`), no parsing.
When either side hits EOF or error, both writers are closed. This preserves IDLE, literals, compression,
and anything else the client and server negotiate.

Client-side literals in `LOGIN` before authentication are handled; after authentication nothing is parsed.

## 8. Web UI

Session: Starlette `SessionMiddleware` with `SECRET_KEY`, cookie `HttpOnly`, `SameSite=Lax`.
`require_admin` dependency redirects unauthenticated requests to `/login`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/login` | login form |
| POST | `/login` | check against `ADMIN_USER`/`ADMIN_PASSWORD` (constant-time compare), set session |
| POST | `/logout` | clear session |
| GET | `/` | account list: email, provider, status badge, token expiry, last activity, last error, actions |
| GET | `/accounts/new` | new account form (preset select prefills fields via inline JS) |
| POST | `/accounts` | create (validation via `AccountForm`) |
| GET | `/accounts/{id}/edit` | edit form; secret field blank = keep existing |
| POST | `/accounts/{id}` | update; changing client_id/token_url/scope clears tokens |
| POST | `/accounts/{id}/delete` | delete |
| GET | `/accounts/{id}/authorize` | shows pending URL + paste form, or a Start button |
| POST | `/accounts/{id}/authorize/start` | generate state/PKCE, show URL |
| POST | `/accounts/{id}/authorize/complete` | exchange pasted redirect URL for tokens |
| POST | `/accounts/{id}/revoke` | clear tokens |
| GET | `/api/health` | JSON `HealthDto {status, imap_listening, accounts_total, accounts_authorized}` – no auth |

Form validation (`web/forms.py`): email format, host non-empty, port 1–65535, URLs `http(s)://`,
scope non-empty, client_id non-empty, redirect_uri valid URL. Validation errors re-render the form with messages.
Flash messages are stored in the session.

CSRF: all state-changing routes are `POST` with `SameSite=Lax` cookies; no cross-site form posting is possible
for the admin session, which is considered sufficient for a single-admin self-hosted tool.

## 9. Configuration (environment)

| Variable | Default | Notes |
|---|---|---|
| `ADMIN_USER` | `admin` | |
| `ADMIN_PASSWORD` | required | startup fails when missing |
| `SECRET_KEY` | required | Fernet key (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`); also signs the session cookie |
| `IMAP_HOST` | `0.0.0.0` | |
| `IMAP_PORT` | `1993` | |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `8080` | |
| `DATA_DIR` | `/data` | SQLite file `proxy.db` lives here |
| `LOG_LEVEL` | `INFO` | |

## 10. Docker

- `python:3.12-slim`, non-root user, dependencies installed from `pyproject.toml`.
- `VOLUME /data`, `EXPOSE 8080 1993`.
- `HEALTHCHECK` → `GET /api/health`.
- `docker-compose.yml` sample: ports `8080:8080`, `127.0.0.1:1993:1993` (IMAP bound to localhost by default
  because the client password is ignored), env vars, named volume.

## 11. Error handling summary

| Situation | Behaviour |
|---|---|
| Missing `SECRET_KEY` / `ADMIN_PASSWORD` | process exits with a clear message |
| Invalid form input | form re-rendered with field errors, HTTP 422 |
| Wrong pasted redirect URL / state mismatch | authorize page error, pending kept |
| Token endpoint error | error message shown; nothing stored |
| Refresh `invalid_grant` | tokens cleared, status `error`, IMAP login `NO [AUTHENTICATIONFAILED]` |
| Provider/network down | `last_error` set, IMAP login `NO [UNAVAILABLE]`, tokens kept |
| Upstream XOAUTH2 rejected | `NO [AUTHENTICATIONFAILED] <provider message>`, `last_error` set |
| Client disconnects mid-pipe | upstream closed; logged at DEBUG |

## 12. Testing

- `pytest`, `pytest-asyncio`, `pytest-cov` with `--cov=app --cov-fail-under=100`.
- Web: `httpx.AsyncClient` against the app with a temp SQLite file and test env vars.
- OAuth: `respx` mocks for token endpoints (success, invalid_grant, network error, rotated refresh token).
- Proxy: an in-test fake IMAP server over TLS (self-signed cert generated in a fixture) that records the
  XOAUTH2 string and answers OK / NO / `+ base64json`; a real asyncio client drives the proxy through
  LOGIN (quoted + literal), AUTHENTICATE PLAIN, CAPABILITY, NOOP, LOGOUT, BAD commands, timeout, pipe data both ways.
- Crypto, providers, forms, DTOs unit-tested.
- Tooling: `ruff format` + `ruff check` (Pint equivalent), run before every commit.

## 13. Documentation & Bruno

- Endpoint docs: `docs/documentation/Auth/*.md`, `docs/documentation/Accounts/*.md`,
  `docs/documentation/Authorize/*.md`, `docs/documentation/Health/Health.md`.
- Bruno collection: `EmailOauth2ProxyBrunoCollection/` with `bruno.json`, `environments/local.bru`,
  one folder per subsystem, one `.bru` per route.
- `README.md`: quick start, env vars, provider setup (Google Cloud / Entra app registration, redirect URI `http://localhost`),
  mail client setup (plain IMAP, port 1993, any password), security note about the ignored password.
