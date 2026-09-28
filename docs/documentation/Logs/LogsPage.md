# Logs page

**Purpose:** Shows the most recent application log lines (background token refresh results, rejected IMAP logins, errors) from an in-memory ring buffer of `LOG_BUFFER_SIZE` lines, newest first, so the admin does not need shell access. Lines are lost on restart; `docker compose logs` keeps the full history.

**Method + URL:** `GET /logs`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Query parameters (all optional)

| Parameter | Default | Notes |
|---|---|---|
| level | `INFO` | minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| q | – | case-insensitive substring matched against message or logger name (e.g. an email address) |
| limit | `200` | 1–1000 rows |
| refresh | – | `on` → page reloads every 10 s (`<meta http-equiv="refresh">`) |

**Response:** `200 OK`, HTML table (time UTC, level, logger, message). Messages include tracebacks and are HTML-escaped.

**Errors:**
- `422 Unprocessable Entity` – invalid filter (unknown level, limit out of range); the form is re-rendered with messages.
- `303 → /login` – not logged in.
