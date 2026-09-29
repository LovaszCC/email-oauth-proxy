from tests.test_forms import VALID


async def test_layout_has_sidebar_navigation(admin):
    body = (await admin.get("/")).text
    assert '<aside class="sidebar"' in body
    for href in ('href="/"', 'href="/logs"', 'href="/accounts/new"'):
        assert href in body
    assert 'aria-current="page"' in body  # active item marked
    assert "/static/app.css" in body


async def test_login_page_is_centered_card_without_sidebar(client):
    body = (await client.get("/login")).text
    assert 'class="auth-card' in body
    assert "sidebar" not in body


async def test_flash_rendered_as_toast(admin):
    await admin.post("/accounts", data=VALID)
    body = (await admin.get("/")).text
    assert 'class="toast toast-success"' in body


async def test_status_badges(admin):
    await admin.post("/accounts", data=VALID)
    body = (await admin.get("/")).text
    assert 'class="badge badge-warning"' in body and "Needs authorization" in body
