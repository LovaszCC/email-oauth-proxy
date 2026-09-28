# Create account

**Purpose:** Stores a new mailbox configuration (provider endpoints + OAuth client credentials) and redirects to its authorization page. The client secret is stored Fernet-encrypted.

**Method + URL:** `POST /accounts`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** `application/x-www-form-urlencoded`

| Field | Required | Notes |
|---|---|---|
| email | yes | valid email address; stored lowercase; unique; used as the IMAP username |
| provider | yes | `gmail`, `o365` or `custom` |
| imap_host | yes | real IMAP server, e.g. `imap.gmail.com` |
| imap_port | yes | 1–65535, implicit TLS (usually 993) |
| permission_url | yes | OAuth authorization endpoint, `http(s)://` |
| token_url | yes | OAuth token endpoint, `http(s)://` |
| scope | yes | space-separated OAuth scopes |
| client_id | yes | OAuth client id |
| client_secret | no | blank = no secret |
| redirect_uri | no | default `http://localhost`; must match the client registration |
| use_pkce | no | checkbox (`on`) – send a PKCE S256 challenge |

**Response:** `303 See Other`, `Location: /accounts/{id}/authorize`, flash message *Account … created*.

**Errors:**
- `422 Unprocessable Entity` – validation failed, or an account with this email already exists; the form is re-rendered with field messages.
- `303 → /login` – not logged in.
