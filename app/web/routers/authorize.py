from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.accounts import AccountService
from app.services.oauth import OAuthError
from app.state import AppState
from app.web.deps import get_db_session, get_state, require_admin
from app.web.dto import AccountDto
from app.web.flash import flash
from app.web.forms import AuthorizeCompleteForm, parse_form
from app.web.routers.accounts import load_account
from app.web.templating import render

router = APIRouter(dependencies=[Depends(require_admin)])


def _page(request, account, *, auth_url=None, error=None, errors=None, status_code=200):
    return render(
        request,
        "accounts/authorize.html",
        {
            "account": AccountDto.from_model(account),
            "auth_url": auth_url,
            "error": error,
            "errors": errors or {},
        },
        status_code=status_code,
    )


@router.get("/accounts/{account_id}/authorize")
async def authorize_page(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    return _page(request, account)


@router.post("/accounts/{account_id}/authorize/start")
async def authorize_start(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    auth_url = state.oauth.build_authorization_url(account)
    await session.commit()
    return _page(request, account, auth_url=auth_url)


@router.post("/accounts/{account_id}/authorize/complete")
async def authorize_complete(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    form, errors = parse_form(AuthorizeCompleteForm, dict(await request.form()))
    if form is None:
        return _page(request, account, errors=errors, status_code=422)
    try:
        await state.oauth.complete_authorization(account, form.redirect_url)
    except OAuthError as exc:
        return _page(request, account, error=exc.message, status_code=422)
    await session.commit()
    flash(request, f"Account {account.email} authorized successfully.", "success")
    return RedirectResponse("/", status_code=303)


@router.post("/accounts/{account_id}/revoke")
async def revoke(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    state.oauth.revoke(account)
    await session.commit()
    flash(request, f"Tokens for {account.email} were removed.", "info")
    return RedirectResponse("/", status_code=303)
