from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import Cryptographer
from app.models import Account


@dataclass
class AccountInput:
    email: str
    provider: str
    imap_host: str
    imap_port: int
    permission_url: str
    token_url: str
    scope: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    use_pkce: bool


class DuplicateEmailError(Exception):
    pass


class AccountService:
    """CRUD for accounts. Methods flush but never commit; the caller owns the transaction."""

    def __init__(self, session: AsyncSession, crypto: Cryptographer) -> None:
        self._session = session
        self._crypto = crypto

    async def list(self) -> list[Account]:
        result = await self._session.execute(select(Account).order_by(Account.email))
        return list(result.scalars())

    async def get(self, account_id: int) -> Account | None:
        return await self._session.get(Account, account_id)

    async def get_by_email(self, email: str) -> Account | None:
        stmt = select(Account).where(Account.email == email.strip().lower())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self) -> tuple[int, int]:
        total = (await self._session.execute(select(func.count(Account.id)))).scalar_one()
        authorized = (
            await self._session.execute(
                select(func.count(Account.id)).where(
                    Account.refresh_token_enc.is_not(None), Account.last_error.is_(None)
                )
            )
        ).scalar_one()
        return total, authorized

    async def create(self, data: AccountInput) -> Account:
        email = data.email.strip().lower()
        if await self.get_by_email(email) is not None:
            raise DuplicateEmailError(email)
        account = Account(email=email)
        self._apply(account, data)
        account.client_secret_enc = self._encrypt_secret(data.client_secret)
        self._session.add(account)
        await self._session.flush()
        return account

    async def update(self, account: Account, data: AccountInput, *, keep_secret: bool) -> Account:
        email = data.email.strip().lower()
        if email != account.email and await self.get_by_email(email) is not None:
            raise DuplicateEmailError(email)
        credentials_changed = (
            account.client_id != data.client_id
            or account.token_url != data.token_url
            or account.scope != data.scope
        )
        account.email = email
        self._apply(account, data)
        if not keep_secret:
            account.client_secret_enc = self._encrypt_secret(data.client_secret)
        if credentials_changed:
            account.clear_tokens()
        await self._session.flush()
        return account

    async def delete(self, account: Account) -> None:
        await self._session.delete(account)
        await self._session.flush()

    def client_secret(self, account: Account) -> str | None:
        if account.client_secret_enc is None:
            return None
        return self._crypto.decrypt(account.client_secret_enc)

    @staticmethod
    def _apply(account: Account, data: AccountInput) -> None:
        account.provider = data.provider
        account.imap_host = data.imap_host
        account.imap_port = data.imap_port
        account.permission_url = data.permission_url
        account.token_url = data.token_url
        account.scope = data.scope
        account.client_id = data.client_id
        account.redirect_uri = data.redirect_uri
        account.use_pkce = data.use_pkce

    def _encrypt_secret(self, secret: str | None) -> str | None:
        if not secret:
            return None
        return self._crypto.encrypt(secret)
