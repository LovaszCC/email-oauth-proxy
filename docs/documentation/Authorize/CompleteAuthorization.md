# Complete authorization

**Purpose:** Exchanges the pasted redirect URL for tokens. The URL's `state` must match the pending one; the `code` is posted to the provider's token endpoint (with `client_secret` / `code_verifier` when applicable). Tokens are stored encrypted; `access_token_expiry` is set from `expires_in`.

**Method + URL:** `POST /accounts/{id}/authorize/complete`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** `application/x-www-form-urlencoded`; path parameter `id`.

| Field | Required | Notes |
|---|---|---|
| redirect_url | yes | full URL from the browser address bar (`http://localhost/?code=…&state=…`); a bare `code=…&state=…` query string is accepted too |

**Response:** `303 See Other`, `Location: /`, flash message *Account … authorized successfully*.

**Errors:**
- `422 Unprocessable Entity` – empty field, missing `code`, state mismatch, provider `error=…` in the URL, or the token endpoint rejected the code; the page shows the message and keeps the pending authorization.
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
