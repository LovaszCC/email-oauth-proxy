# Logs API

**Purpose:** JSON view of the in-memory log buffer for scripts/monitoring (same data as the Logs page).

**Method + URL:** `GET /api/logs`

**Auth:** Admin session cookie (log in via `POST /login` first). Unauthenticated requests are redirected to `/login` (303 See Other).

**Request:** Query parameters (all optional)

| Parameter | Default | Notes |
|---|---|---|
| level | `INFO` | minimum level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| q | – | case-insensitive substring matched against message or logger name |
| limit | `200` | 1–1000 entries |

**Response:** `200 OK`, `application/json` (`LogsDto`), entries newest first, times naive UTC:

```json
{
  "count": 1,
  "buffered": 42,
  "capacity": 1000,
  "entries": [
    {
      "time": "2026-09-28T13:05:00",
      "level": "ERROR",
      "logger": "app.services.refresh",
      "message": "Token refresh for a@example.com rejected (check client id / client secret): AADSTS7000222 ..."
    }
  ]
}
```

`count` = entries returned, `buffered` = lines currently in memory, `capacity` = `LOG_BUFFER_SIZE`.

**Errors:**
- `422 Unprocessable Entity` – `{"errors": {"limit": "..."}}` for an invalid filter.
- `303 → /login` – not logged in.
