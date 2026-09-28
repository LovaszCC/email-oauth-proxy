import logging
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.crypto import Cryptographer
from app.db import Database
from app.proxy.server import ImapProxyServer, ProxyAuthenticator
from app.services.oauth import OAuthService
from app.settings import Settings
from app.state import AppState
from app.web.deps import NotAuthenticated
from app.web.routers import accounts, auth, health
from app.web.templating import STATIC_DIR

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    crypto = Cryptographer(settings.secret_key)
    db = Database(settings.database_url)
    http = httpx.AsyncClient(timeout=30.0)
    oauth = OAuthService(crypto, http)
    proxy = ImapProxyServer(
        settings.imap_host, settings.imap_port, ProxyAuthenticator(db, crypto, oauth)
    )
    state = AppState(settings, db, crypto, http, oauth, proxy)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        await db.create_all()
        await proxy.start()
        try:
            yield
        finally:
            await proxy.stop()
            await http.aclose()
            await db.dispose()

    app = FastAPI(title="Email OAuth2 Proxy", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.container = state
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(accounts.router)

    @app.exception_handler(NotAuthenticated)
    async def _redirect_to_login(request: Request, exc: NotAuthenticated):
        return RedirectResponse("/login", status_code=303)

    return app


def main() -> None:  # pragma: no cover - covered in Task 10
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(
        create_app(settings),
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )
