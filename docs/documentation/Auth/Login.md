# Login

**Purpose:** Authenticates the admin and starts a session.

**Method + URL:** `POST /login`

**Auth:** None.

**Request:** `application/x-www-form-urlencoded`

| Field | Required | Notes |
|---|---|---|
| username | yes | must equal `ADMIN_USER` |
| password | yes | must equal `ADMIN_PASSWORD` |

**Response:** `303 See Other`, `Location: /`, `Set-Cookie: session=…` (HttpOnly, SameSite=Lax).

**Errors:**
- `401 Unauthorized` – wrong username or password; the login page is re-rendered with the message *Invalid username or password*.
