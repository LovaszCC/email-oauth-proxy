import pytest

from app.services.accounts import AccountService
from tests.test_forms import VALID


async def get_accounts(app):
    state = app.state.container
    async with state.db.session() as session:
        return await AccountService(session, state.crypto).list()


async def test_requires_login(client):
    for url in ["/", "/accounts/new", "/accounts/1/edit"]:
        response = await client.get(url)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
    response = await client.post("/accounts", data=VALID)
    assert response.status_code == 303


async def test_list_empty(admin):
    response = await admin.get("/")
    assert response.status_code == 200
    assert "No accounts yet" in response.text


async def test_new_form_has_presets(admin):
    response = await admin.get("/accounts/new")
    assert response.status_code == 200
    assert "imap.gmail.com" in response.text
    assert "outlook.office365.com" in response.text
    assert 'name="use_pkce"' in response.text


async def test_create_redirects_to_authorize(admin, app):
    response = await admin.post("/accounts", data=VALID)
    assert response.status_code == 303
    accounts = await get_accounts(app)
    assert len(accounts) == 1
    assert response.headers["location"] == f"/accounts/{accounts[0].id}/authorize"
    page = await admin.get("/")
    assert "user@example.com" in page.text
    assert "Needs authorization" in page.text


async def test_create_invalid_rerenders(admin, app):
    response = await admin.post("/accounts", data={**VALID, "email": "bad"})
    assert response.status_code == 422
    assert "valid email" in response.text.lower()
    assert await get_accounts(app) == []


async def test_create_duplicate(admin):
    await admin.post("/accounts", data=VALID)
    response = await admin.post("/accounts", data=VALID)
    assert response.status_code == 422
    assert "already exists" in response.text


async def test_edit_and_update(admin, app):
    await admin.post("/accounts", data={**VALID, "client_secret": "sec"})
    (account,) = await get_accounts(app)
    response = await admin.get(f"/accounts/{account.id}/edit")
    assert response.status_code == 200
    assert "leave blank to keep" in response.text
    assert 'value="sec"' not in response.text  # stored secret never rendered
    response = await admin.post(
        f"/accounts/{account.id}", data={**VALID, "imap_host": "imap.example.org"}
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    (account,) = await get_accounts(app)
    assert account.imap_host == "imap.example.org"
    state = app.state.container
    async with state.db.session() as session:
        svc = AccountService(session, state.crypto)
        assert svc.client_secret(await svc.get(account.id)) == "sec"


async def test_update_invalid_and_duplicate(admin, app):
    await admin.post("/accounts", data=VALID)
    await admin.post("/accounts", data={**VALID, "email": "other@example.com"})
    other = next(a for a in await get_accounts(app) if a.email == "other@example.com")
    response = await admin.post(f"/accounts/{other.id}", data={**VALID, "scope": ""})
    assert response.status_code == 422
    response = await admin.post(f"/accounts/{other.id}", data=VALID)  # rename onto existing
    assert response.status_code == 422
    assert "already exists" in response.text


@pytest.mark.parametrize(
    "method,url",
    [("get", "/accounts/99/edit"), ("post", "/accounts/99"), ("post", "/accounts/99/delete")],
)
async def test_not_found(admin, method, url):
    response = await getattr(admin, method)(url, **({"data": VALID} if method == "post" else {}))
    assert response.status_code == 404


async def test_delete(admin, app):
    await admin.post("/accounts", data=VALID)
    (account,) = await get_accounts(app)
    response = await admin.post(f"/accounts/{account.id}/delete")
    assert response.status_code == 303
    assert await get_accounts(app) == []
    page = await admin.get("/")
    assert "deleted" in page.text
