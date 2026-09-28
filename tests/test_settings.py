from pathlib import Path

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_defaults_and_required(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("SECRET_KEY", "k")
    s = Settings(_env_file=None)
    assert s.admin_user == "admin"
    assert s.imap_host == "0.0.0.0"
    assert s.imap_port == 1993
    assert s.web_port == 8080
    assert s.data_dir == Path("/data")
    assert s.refresh_interval == 3600
    assert s.log_buffer_size == 1000
    assert s.database_url == "sqlite+aiosqlite:////data/proxy.db"


def test_missing_required_fails(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
