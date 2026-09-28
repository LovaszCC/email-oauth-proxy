from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes)."""
    return datetime.now(UTC).replace(tzinfo=None)


class AccountStatus(StrEnum):
    AUTHORIZED = "authorized"
    NEEDS_AUTHORIZATION = "needs_authorization"
    ERROR = "error"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32))
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    permission_url: Mapped[str] = mapped_column(Text)
    token_url: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    client_id: Mapped[str] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(Text, default="http://localhost")
    use_pkce: Mapped[bool] = mapped_column(Boolean, default=False)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_state: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pending_code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def status(self) -> AccountStatus:
        if self.last_error:
            return AccountStatus.ERROR
        if self.refresh_token_enc:
            return AccountStatus.AUTHORIZED
        return AccountStatus.NEEDS_AUTHORIZATION

    def clear_tokens(self) -> None:
        """Forget all OAuth state; the account must be authorized again."""
        self.access_token_enc = None
        self.access_token_expiry = None
        self.refresh_token_enc = None
        self.pending_state = None
        self.pending_code_verifier = None
        self.last_error = None
