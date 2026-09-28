# Edit account form

**Purpose:** Renders the account form with the stored values. The client secret is never rendered; leaving it blank keeps the stored one.

**Method + URL:** `GET /accounts/{id}/edit`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Path parameter `id` – account id.

**Response:** `200 OK`, HTML form posting to `POST /accounts/{id}`.

**Errors:**
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
