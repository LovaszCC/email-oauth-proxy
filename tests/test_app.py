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
    response = await client.get("/static/app.css")
    assert response.status_code == 200
    assert "--primary" in response.text
    assert (await client.get("/static/pico.min.css")).status_code == 404


async def test_lifespan_starts_and_stops_refresher(app_settings):
    from asgi_lifespan import LifespanManager

    application = create_app(app_settings)
    container = application.state.container
    async with LifespanManager(application):
        assert container.refresher.running is True
    assert container.refresher.running is False
    assert container.proxy.listening is False


async def test_handler_removed_after_lifespan(app_settings):
    import logging

    from asgi_lifespan import LifespanManager

    from app.services.logs import BufferHandler

    root = logging.getLogger()
    before = [h for h in root.handlers if isinstance(h, BufferHandler)]
    application = create_app(app_settings)
    async with LifespanManager(application):
        during = [h for h in root.handlers if isinstance(h, BufferHandler)]
        assert len(during) == len(before) + 1
        logging.getLogger("app.test").warning("captured while running")
    after = [h for h in root.handlers if isinstance(h, BufferHandler)]
    assert after == before
    messages = [e.message for e in application.state.container.logs.entries()]
    assert "captured while running" in messages
