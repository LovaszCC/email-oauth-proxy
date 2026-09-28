import pytest

from app.main import create_app


def test_create_app_rejects_bad_secret(app_settings):
    app_settings.secret_key = "bad"
    with pytest.raises(ValueError, match="SECRET_KEY"):
        create_app(app_settings)


async def test_lifespan_creates_data_dir_and_starts_proxy(app, app_settings):
    assert (app_settings.data_dir / "proxy.db").exists()
    assert app.state.container.proxy.listening is True


def test_create_app_reads_settings_from_env(monkeypatch, fernet_key, tmp_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("SECRET_KEY", fernet_key)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    application = create_app()
    assert application.state.container.settings.data_dir == tmp_path


async def test_static_served(client):
    response = await client.get("/static/pico.min.css")
    assert response.status_code == 200
