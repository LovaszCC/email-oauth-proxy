# Update account

**Purpose:** Updates an account. If `client_id`, `token_url` or `scope` change, stored tokens are cleared and the account must be authorized again.

**Method + URL:** `POST /accounts/{id}`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** `application/x-www-form-urlencoded`; path parameter `id`.

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

A blank `client_secret` keeps the stored secret; a value replaces it.

**Response:** `303 See Other`, `Location: /`, flash message *Account … updated*.

**Errors:**
- `422 Unprocessable Entity` – validation failed or the new email belongs to another account.
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
