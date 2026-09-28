from urllib.parse import parse_qs, urlsplit

import httpx
import respx

from app.services.accounts import AccountService
from tests.test_forms import VALID
from tests.test_oauth_service import TOKEN_URL


async def create(admin, app):
    await admin.post("/accounts", data=VALID)
    state = app.state.container
    async with state.db.session() as session:
        (account,) = await AccountService(session, state.crypto).list()
    return account.id


async def reload(app, account_id):
    state = app.state.container
    async with state.db.session() as session:
        return await AccountService(session, state.crypto).get(account_id)


def extract_state(html: str) -> str:
    start = html.index("https://accounts.google.com/o/oauth2/auth?")
    end = html.index('"', start)
    url = html[start:end].replace("&amp;", "&")
    return parse_qs(urlsplit(url).query)["state"][0]


async def test_get_page_before_start(admin, app):
    account_id = await create(admin, app)
    response = await admin.get(f"/accounts/{account_id}/authorize")
    assert response.status_code == 200
    assert "Start authorization" in response.text
    assert "redirect_url" not in response.text


async def test_start_shows_url_and_paste_form(admin, app):
    account_id = await create(admin, app)
    response = await admin.post(f"/accounts/{account_id}/authorize/start")
    assert response.status_code == 200
    state = extract_state(response.text)
    assert (await reload(app, account_id)).pending_state == state
    assert 'name="redirect_url"' in response.text
    page = await admin.get(f"/accounts/{account_id}/authorize")
    assert 'name="redirect_url"' in page.text
    assert "Restart authorization" in page.text


@respx.mock
async def test_complete_success(admin, app):
    account_id = await create(admin, app)
    response = await admin.post(f"/accounts/{account_id}/authorize/start")
    state = extract_state(response.text)
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
        )
    )
    response = await admin.post(
        f"/accounts/{account_id}/authorize/complete",
        data={"redirect_url": f"http://localhost/?code=abc&state={state}"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    account = await reload(app, account_id)
    assert account.refresh_token_enc is not None
    page = await admin.get("/")
    assert "Authorized" in page.text and "authorized successfully" in page.text


async def test_complete_validation_error(admin, app):
    account_id = await create(admin, app)
    await admin.post(f"/accounts/{account_id}/authorize/start")
    response = await admin.post(
        f"/accounts/{account_id}/authorize/complete", data={"redirect_url": ""}
    )
    assert response.status_code == 422
    assert "redirect_url" in response.text


async def test_complete_oauth_error(admin, app):
    account_id = await create(admin, app)
    await admin.post(f"/accounts/{account_id}/authorize/start")
    response = await admin.post(
        f"/accounts/{account_id}/authorize/complete",
        data={"redirect_url": "http://localhost/?code=abc&state=wrong"},
    )
    assert response.status_code == 422
    assert "State mismatch" in response.text
    assert (await reload(app, account_id)).pending_state is not None


async def test_revoke(admin, app):
    account_id = await create(admin, app)
    state = app.state.container
    async with state.db.session() as session:
        account = await AccountService(session, state.crypto).get(account_id)
        account.refresh_token_enc = "x"
        await session.commit()
    response = await admin.post(f"/accounts/{account_id}/revoke")
    assert response.status_code == 303
    assert (await reload(app, account_id)).refresh_token_enc is None


async def test_not_found_and_login_required(admin):
    for url in [
        "/accounts/99/authorize/start",
        "/accounts/99/authorize/complete",
        "/accounts/99/revoke",
    ]:
        assert (await admin.post(url, data={"redirect_url": "x"})).status_code == 404
    assert (await admin.get("/accounts/99/authorize")).status_code == 404
    await admin.post("/logout")  # same client object, now unauthenticated
    assert (await admin.get("/accounts/1/authorize")).status_code == 303
