# Authorization page

**Purpose:** Shows the account's authorization state. Before an authorization was started it offers a *Start authorization* button; while one is pending it shows the paste form and a *Restart* button. Authorized accounts also get a *Remove stored tokens* button.

**Method + URL:** `GET /accounts/{id}/authorize`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Path parameter `id`.

**Response:** `200 OK`, HTML.

**Errors:**
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
