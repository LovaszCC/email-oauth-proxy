import logging
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator

from app.services.accounts import AccountInput

URL_PATTERN = re.compile(r"^https?://\S+$")


class LoginForm(BaseModel):
    username: str = ""
    password: str = ""


class AccountForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    provider: Literal["gmail", "o365", "custom"]
    imap_host: str = Field(min_length=1)
    imap_port: int = Field(ge=1, le=65535)
    permission_url: str
    token_url: str
    scope: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str | None = None
    redirect_uri: str = "http://localhost"
    use_pkce: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def _strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("permission_url", "token_url", "redirect_uri")
    @classmethod
    def _must_be_http_url(cls, value: str) -> str:
        if not URL_PATTERN.match(value):
            raise ValueError("must be an http(s) URL")
        return value

    @field_validator("client_secret")
    @classmethod
    def _blank_secret_is_none(cls, value: str | None) -> str | None:
        return value or None

    def to_input(self) -> AccountInput:
        return AccountInput(
            email=str(self.email),
            provider=self.provider,
            imap_host=self.imap_host,
            imap_port=self.imap_port,
            permission_url=self.permission_url,
            token_url=self.token_url,
            scope=self.scope,
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            use_pkce=self.use_pkce,
        )


class AuthorizeCompleteForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    redirect_url: str = Field(min_length=1)


def parse_form[T: BaseModel](
    model: type[T], data: Mapping[str, str]
) -> tuple[T | None, dict[str, str]]:
    """Validate submitted form data; returns (model, {}) or (None, {field: message})."""
    try:
        return model.model_validate(dict(data)), {}
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "form"
            errors.setdefault(field, error["msg"].removeprefix("Value error, "))
        return None, errors


class LogFilterForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    q: str = ""
    limit: int = Field(200, ge=1, le=1000)
    refresh: bool = False

    @property
    def min_level(self) -> int:
        return logging.getLevelName(self.level)
