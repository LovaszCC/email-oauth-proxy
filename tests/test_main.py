from app import main as main_module


def test_main_runs_uvicorn(monkeypatch, fernet_key):
    monkeypatch.setenv("ADMIN_PASSWORD", "pw")
    monkeypatch.setenv("SECRET_KEY", fernet_key)
    monkeypatch.setenv("WEB_PORT", "9999")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    main_module.main()
    ((app, kwargs),) = calls
    assert app.title == "Email OAuth2 Proxy"
    assert kwargs == {"host": "0.0.0.0", "port": 9999, "log_level": "debug"}
