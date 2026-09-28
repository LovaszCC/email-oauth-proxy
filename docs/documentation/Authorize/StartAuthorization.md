# Start authorization

**Purpose:** Generates a fresh OAuth `state` (and PKCE verifier when enabled), stores them on the account and renders the provider's authorization URL together with the redirect-URL paste form. Gmail URLs include `access_type=offline&prompt=consent` so a refresh token is issued.

**Method + URL:** `POST /accounts/{id}/authorize/start`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Path parameter `id`. No body.

**Response:** `200 OK`, HTML page containing the authorization URL (link) and the paste form.

**Errors:**
- `404 Not Found` – unknown account id.
- `303 → /login` – not logged in.
