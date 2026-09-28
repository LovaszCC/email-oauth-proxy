from dataclasses import dataclass

import httpx

from app.crypto import Cryptographer
from app.db import Database
from app.proxy.server import ImapProxyServer
from app.services.oauth import OAuthService
from app.services.refresh import TokenRefresher
from app.settings import Settings


@dataclass
class AppState:
    settings: Settings
    db: Database
    crypto: Cryptographer
    http: httpx.AsyncClient
    oauth: OAuthService
    proxy: ImapProxyServer
    refresher: TokenRefresher
