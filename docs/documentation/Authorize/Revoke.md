# Remove stored tokens

**Purpose:** Deletes the account's access/refresh tokens and any pending authorization locally (the provider is not contacted). The account goes back to *Needs authorization*; IMAP logins are rejected until it is authorized again.

**Method + URL:** `POST /accounts/{id}/revoke`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Path parameter `id`. No body.

**Response:** `303 See Other`, `Location: /`, flash message *Tokens for … were removed*.

**Errors:**
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
