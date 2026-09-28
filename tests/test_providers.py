import pytest

from app.providers import PROVIDER_KEYS, PROVIDERS, get_provider


def test_presets_present():
    assert PROVIDER_KEYS == ["gmail", "o365", "custom"]
    assert PROVIDERS["gmail"].imap_host == "imap.gmail.com"
    assert PROVIDERS["o365"].imap_host == "outlook.office365.com"
    assert "offline_access" in PROVIDERS["o365"].scope
    assert PROVIDERS["gmail"].extra_auth_params == {"access_type": "offline", "prompt": "consent"}
    assert PROVIDERS["custom"].permission_url == ""


def test_get_provider():
    assert get_provider("o365").name == "Office 365 / Outlook"
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("nope")
