from datetime import datetime

from sqlalchemy import select

from app.models import Account, AccountStatus, utcnow


def make_account(**overrides) -> Account:
    values = dict(
        email="user@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://mail.google.com/",
        client_id="cid",
    )
    values.update(overrides)
    return Account(**values)


def test_utcnow_is_naive():
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is None


def test_status_needs_authorization():
    assert make_account().status is AccountStatus.NEEDS_AUTHORIZATION


def test_status_authorized():
    assert make_account(refresh_token_enc="x").status is AccountStatus.AUTHORIZED


def test_status_error_wins():
    assert make_account(refresh_token_enc="x", last_error="boom").status is AccountStatus.ERROR


def test_clear_tokens():
    account = make_account(
        refresh_token_enc="r",
        access_token_enc="a",
        access_token_expiry=utcnow(),
        pending_state="s",
        pending_code_verifier="v",
        last_error="e",
    )
    account.clear_tokens()
    assert account.refresh_token_enc is None
    assert account.access_token_enc is None
    assert account.access_token_expiry is None
    assert account.pending_state is None
    assert account.pending_code_verifier is None
    assert account.last_error is None


async def test_persist_and_defaults(db):
    async with db.session() as session:
        session.add(make_account())
        await session.commit()
    async with db.session() as session:
        account = (await session.execute(select(Account))).scalar_one()
        assert account.redirect_uri == "http://localhost"
        assert account.use_pkce is False
        assert account.created_at is not None
        assert account.updated_at is not None
