# New account form

**Purpose:** Renders the empty account form pre-filled with the Gmail preset. The provider dropdown re-fills the server/URL/scope fields client-side.

**Method + URL:** `GET /accounts/new`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** No parameters.

**Response:** `200 OK`, HTML form posting to `POST /accounts`.

**Errors:**
- `303 → /login` – not logged in.
