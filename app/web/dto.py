from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models import Account, AccountStatus
from app.providers import PROVIDERS
from app.services.logs import LogEntry


class HealthDto(BaseModel):
    status: Literal["ok"] = "ok"
    imap_listening: bool
    accounts_total: int
    accounts_authorized: int


class AccountDto(BaseModel):
    id: int
    email: str
    provider: str
    provider_name: str
    imap_host: str
    imap_port: int
    redirect_uri: str
    status: AccountStatus
    access_token_expiry: datetime | None
    last_activity: datetime | None
    last_error: str | None
    has_pending_authorization: bool

    @classmethod
    def from_model(cls, account: Account) -> "AccountDto":
        provider = PROVIDERS.get(account.provider)
        return cls(
            id=account.id,
            email=account.email,
            provider=account.provider,
            provider_name=provider.name if provider else "Custom",
            imap_host=account.imap_host,
            imap_port=account.imap_port,
            redirect_uri=account.redirect_uri,
            status=account.status,
            access_token_expiry=account.access_token_expiry,
            last_activity=account.last_activity,
            last_error=account.last_error,
            has_pending_authorization=account.pending_state is not None,
        )


class LogEntryDto(BaseModel):
    time: datetime
    level: str
    logger: str
    message: str

    @classmethod
    def from_entry(cls, entry: LogEntry) -> "LogEntryDto":
        return cls(time=entry.time, level=entry.level, logger=entry.logger, message=entry.message)


class LogsDto(BaseModel):
    count: int
    buffered: int
    capacity: int
    entries: list[LogEntryDto]
