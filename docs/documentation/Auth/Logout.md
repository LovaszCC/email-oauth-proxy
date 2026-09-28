# Logout

**Purpose:** Clears the admin session.

**Method + URL:** `POST /logout`

**Auth:** None (works with or without a session).

**Request:** No body.

**Response:** `303 See Other`, `Location: /login`; the session cookie is cleared.

**Errors:**
- none
