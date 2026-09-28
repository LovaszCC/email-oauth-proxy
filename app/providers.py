from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    imap_host: str
    imap_port: int
    permission_url: str
    token_url: str
    scope: str
    use_pkce: bool = False
    extra_auth_params: dict[str, str] = field(default_factory=dict)


PROVIDERS: dict[str, Provider] = {
    "gmail": Provider(
        key="gmail",
        name="Gmail",
        imap_host="imap.gmail.com",
        imap_port=993,
        permission_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="https://mail.google.com/",
        extra_auth_params={"access_type": "offline", "prompt": "consent"},
    ),
    "o365": Provider(
        key="o365",
        name="Office 365 / Outlook",
        imap_host="outlook.office365.com",
        imap_port=993,
        permission_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scope="https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    ),
    "custom": Provider(
        key="custom",
        name="Custom",
        imap_host="",
        imap_port=993,
        permission_url="",
        token_url="",
        scope="",
    ),
}

PROVIDER_KEYS = list(PROVIDERS)


def get_provider(key: str) -> Provider:
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {key}") from exc
