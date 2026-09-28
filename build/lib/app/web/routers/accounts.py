from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account
from app.providers import PROVIDER_KEYS, PROVIDERS
from app.services.accounts import AccountService, DuplicateEmailError
from app.state import AppState
from app.web.deps import get_db_session, get_state, require_admin
from app.web.dto import AccountDto
from app.web.flash import flash
from app.web.forms import AccountForm, parse_form
from app.web.templating import render

router = APIRouter(dependencies=[Depends(require_admin)])

DUPLICATE_MESSAGE = "An account with this email already exists"


async def load_account(service: AccountService, account_id: int) -> Account:
    account = await service.get(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _presets() -> dict[str, dict]:
    return {key: vars(PROVIDERS[key]) for key in PROVIDER_KEYS}


def _values_from_account(account: Account) -> dict:
    return {
        "email": account.email,
        "provider": account.provider,
        "imap_host": account.imap_host,
        "imap_port": account.imap_port,
        "permission_url": account.permission_url,
        "token_url": account.token_url,
        "scope": account.scope,
        "client_id": account.client_id,
        "client_secret": "",
        "redirect_uri": account.redirect_uri,
        "use_pkce": account.use_pkce,
    }


def _render_form(request, *, values, errors, action, is_edit, has_secret, status_code=200):
    return render(
        request,
        "accounts/form.html",
        {
            "values": values,
            "errors": errors,
            "action": action,
            "is_edit": is_edit,
            "has_secret": has_secret,
            "presets": _presets(),
        },
        status_code=status_code,
    )


@router.get("/")
async def list_accounts(
    request: Request,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    accounts = await AccountService(session, state.crypto).list()
    dtos = [AccountDto.from_model(account) for account in accounts]
    return render(request, "accounts/list.html", {"accounts": dtos})


@router.get("/accounts/new")
async def new_account(request: Request):
    gmail = PROVIDERS["gmail"]
    values = {
        "provider": "gmail",
        "imap_host": gmail.imap_host,
        "imap_port": gmail.imap_port,
        "permission_url": gmail.permission_url,
        "token_url": gmail.token_url,
        "scope": gmail.scope,
        "redirect_uri": "http://localhost",
        "use_pkce": False,
    }
    return _render_form(
        request, values=values, errors={}, action="/accounts", is_edit=False, has_secret=False
    )


@router.post("/accounts")
async def create_account(
    request: Request,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    raw = dict(await request.form())
    form, errors = parse_form(AccountForm, raw)
    if form is None:
        return _render_form(
            request,
            values=raw,
            errors=errors,
            action="/accounts",
            is_edit=False,
            has_secret=False,
            status_code=422,
        )
    service = AccountService(session, state.crypto)
    try:
        account = await service.create(form.to_input())
    except DuplicateEmailError:
        return _render_form(
            request,
            values=raw,
            errors={"email": DUPLICATE_MESSAGE},
            action="/accounts",
            is_edit=False,
            has_secret=False,
            status_code=422,
        )
    await session.commit()
    flash(request, f"Account {account.email} created. Authorize it below.", "success")
    return RedirectResponse(f"/accounts/{account.id}/authorize", status_code=303)


@router.get("/accounts/{account_id}/edit")
async def edit_account(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    account = await load_account(AccountService(session, state.crypto), account_id)
    return _render_form(
        request,
        values=_values_from_account(account),
        errors={},
        action=f"/accounts/{account.id}",
        is_edit=True,
        has_secret=account.client_secret_enc is not None,
    )


@router.post("/accounts/{account_id}")
async def update_account(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    service = AccountService(session, state.crypto)
    account = await load_account(service, account_id)
    raw = dict(await request.form())
    form, errors = parse_form(AccountForm, raw)
    action = f"/accounts/{account.id}"
    has_secret = account.client_secret_enc is not None
    if form is None:
        return _render_form(
            request,
            values=raw,
            errors=errors,
            action=action,
            is_edit=True,
            has_secret=has_secret,
            status_code=422,
        )
    try:
        await service.update(account, form.to_input(), keep_secret=form.client_secret is None)
    except DuplicateEmailError:
        return _render_form(
            request,
            values=raw,
            errors={"email": DUPLICATE_MESSAGE},
            action=action,
            is_edit=True,
            has_secret=has_secret,
            status_code=422,
        )
    await session.commit()
    flash(request, f"Account {account.email} updated.", "success")
    return RedirectResponse("/", status_code=303)


@router.post("/accounts/{account_id}/delete")
async def delete_account(
    request: Request,
    account_id: int,
    state: AppState = Depends(get_state),
    session: AsyncSession = Depends(get_db_session),
):
    service = AccountService(session, state.crypto)
    account = await load_account(service, account_id)
    email = account.email
    await service.delete(account)
    await session.commit()
    flash(request, f"Account {email} deleted.", "success")
    return RedirectResponse("/", status_code=303)
