from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    admin_user: str = "admin"
    admin_password: str
    secret_key: str
    imap_host: str = "0.0.0.0"
    imap_port: int = 1993
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    data_dir: Path = Path("/data")
    log_level: str = "INFO"
    refresh_interval: int = 3600  # seconds between background token refresh runs

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'proxy.db'}"
