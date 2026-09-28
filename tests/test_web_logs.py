import logging

log = logging.getLogger("app.test.web")


async def test_requires_login(client):
    assert (await client.get("/logs")).status_code == 303
    assert (await client.get("/api/logs")).status_code == 303


async def test_logs_page_shows_entries_newest_first(admin):
    log.info("first entry")
    log.error("Token refresh for a@example.com rejected")
    response = await admin.get("/logs")
    assert response.status_code == 200
    body = response.text
    assert body.index("rejected") < body.index("first entry")
    assert 'class="level-error"' in body
    assert "http-equiv" not in body


async def test_logs_page_filters(admin):
    log.info("keep me")
    log.warning("drop me")
    response = await admin.get("/logs", params={"level": "WARNING", "q": "keep"})
    assert "keep me" not in response.text and "drop me" not in response.text
    response = await admin.get("/logs", params={"q": "keep", "refresh": "on"})
    assert "keep me" in response.text and "drop me" not in response.text
    assert '<meta http-equiv="refresh" content="10">' in response.text
    response = await admin.get("/logs", params={"limit": "1"})
    assert response.text.count("<tr class=") == 1


async def test_logs_page_invalid_filter(admin):
    response = await admin.get("/logs", params={"limit": "99999", "level": "TRACE"})
    assert response.status_code == 422
    assert "limit" in response.text and "level" in response.text


async def test_logs_page_escapes_html(admin):
    log.error("<script>alert(1)</script>")
    response = await admin.get("/logs")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


async def test_logs_api(admin, app):
    log.warning("api entry")
    response = await admin.get("/api/logs", params={"level": "WARNING", "q": "api"})
    assert response.status_code == 200
    data = response.json()
    assert data["capacity"] == app.state.container.logs.capacity
    assert data["count"] == 1 and data["buffered"] >= 1
    (entry,) = data["entries"]
    assert entry["level"] == "WARNING" and entry["logger"] == "app.test.web"
    assert entry["message"] == "api entry" and entry["time"].startswith("20")
    response = await admin.get("/api/logs", params={"limit": "0"})
    assert response.status_code == 422
    assert "limit" in response.json()["errors"]


async def test_nav_has_logs_link(admin):
    response = await admin.get("/")
    assert 'href="/logs"' in response.text
