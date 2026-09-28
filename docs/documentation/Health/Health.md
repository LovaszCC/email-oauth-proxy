# Health

**Purpose:** Liveness/readiness endpoint used by the Docker `HEALTHCHECK`.

**Method + URL:** `GET /api/health`

**Auth:** None.

**Request:** No parameters.

**Response:** `200 OK`, `application/json` (`HealthDto`):

```json
{"status": "ok", "imap_listening": true, "accounts_total": 1, "accounts_authorized": 1}
```

`accounts_authorized` counts accounts with a refresh token and no error.

**Errors:**
- none
