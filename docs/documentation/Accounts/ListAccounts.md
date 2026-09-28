# List accounts

**Purpose:** Shows every configured account with its provider, status (`Authorized` / `Needs authorization` / `Error` + message), token expiry and last proxied login.

**Method + URL:** `GET /`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** No parameters.

**Response:** `200 OK`, HTML table built from `AccountDto` objects (id, email, provider, provider_name, imap_host, imap_port, status, access_token_expiry, last_activity, last_error, has_pending_authorization).

**Errors:**
- `303 → /login` – not logged in.
