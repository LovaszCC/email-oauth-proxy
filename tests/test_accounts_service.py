import pytest

from app.models import AccountStatus
from app.services.accounts import AccountInput, AccountService, DuplicateEmailError


def gmail_input(**overrides) -> AccountInput:
    values = dict(
        email="User@Example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://mail.google.com/",
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost",
        use_pkce=False,
    )
    values.update(overrides)
    return AccountInput(**values)


async def test_create_lowercases_and_encrypts(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        await session.commit()
        assert account.id is not None
        assert account.email == "user@example.com"
        assert account.client_secret_enc != "csecret"
        assert svc.client_secret(account) == "csecret"


async def test_create_without_secret(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input(client_secret=None))
        assert account.client_secret_enc is None
        assert svc.client_secret(account) is None


async def test_create_duplicate(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        await svc.create(gmail_input())
        await session.commit()
        with pytest.raises(DuplicateEmailError):
            await svc.create(gmail_input(email="USER@example.com"))


async def test_list_get_and_get_by_email(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        b = await svc.create(gmail_input(email="b@example.com"))
        a = await svc.create(gmail_input(email="a@example.com"))
        await session.commit()
        assert [x.email for x in await svc.list()] == ["a@example.com", "b@example.com"]
        assert (await svc.get(a.id)).id == a.id
        assert await svc.get(9999) is None
        assert (await svc.get_by_email("B@EXAMPLE.COM")).id == b.id
        assert await svc.get_by_email("nobody@example.com") is None


async def test_update_keeps_secret_and_tokens_when_unchanged(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        account.refresh_token_enc = "rt"
        account.access_token_enc = "at"
        await session.commit()
        await svc.update(account, gmail_input(imap_host="imap.other.com"), keep_secret=True)
        assert account.imap_host == "imap.other.com"
        assert svc.client_secret(account) == "csecret"
        assert account.refresh_token_enc == "rt"


async def test_update_replaces_secret(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        await svc.update(account, gmail_input(client_secret="new"), keep_secret=False)
        assert svc.client_secret(account) == "new"
        await svc.update(account, gmail_input(client_secret=None), keep_secret=False)
        assert svc.client_secret(account) is None


@pytest.mark.parametrize("field", ["client_id", "token_url", "scope"])
async def test_update_credential_change_clears_tokens(db, crypto, field):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        account.refresh_token_enc = "rt"
        account.access_token_enc = "at"
        account.pending_state = "s"
        account.last_error = "e"
        await svc.update(account, gmail_input(**{field: "changed"}), keep_secret=True)
        assert account.refresh_token_enc is None
        assert account.access_token_enc is None
        assert account.pending_state is None
        assert account.last_error is None
        assert account.status is AccountStatus.NEEDS_AUTHORIZATION


async def test_update_to_duplicate_email(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        await svc.create(gmail_input(email="a@example.com"))
        b = await svc.create(gmail_input(email="b@example.com"))
        await session.commit()
        with pytest.raises(DuplicateEmailError):
            await svc.update(b, gmail_input(email="a@example.com"), keep_secret=True)


async def test_delete_and_count(db, crypto):
    async with db.session() as session:
        svc = AccountService(session, crypto)
        a = await svc.create(gmail_input(email="a@example.com"))
        b = await svc.create(gmail_input(email="b@example.com"))
        b.refresh_token_enc = "rt"
        await session.commit()
        assert await svc.count() == (2, 1)
        await svc.delete(a)
        await session.commit()
        assert await svc.count() == (1, 1)


async def test_update_replacing_secret_clears_last_error(db, crypto):
    """After an expired secret is replaced the account must not stay in Error for an hour."""
    async with db.session() as session:
        svc = AccountService(session, crypto)
        account = await svc.create(gmail_input())
        account.refresh_token_enc = "rt"
        account.last_error = "Token refresh rejected: secret expired"
        await svc.update(account, gmail_input(), keep_secret=True)
        assert account.last_error == "Token refresh rejected: secret expired"
        await svc.update(account, gmail_input(client_secret="new"), keep_secret=False)
        assert account.last_error is None
        assert account.refresh_token_enc == "rt"
