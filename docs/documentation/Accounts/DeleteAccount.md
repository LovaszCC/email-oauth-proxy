# Delete account

**Purpose:** Deletes an account together with its stored secret and tokens.

**Method + URL:** `POST /accounts/{id}/delete`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Path parameter `id`. No body.

**Response:** `303 See Other`, `Location: /`, flash message *Account … deleted*.

**Errors:**
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
