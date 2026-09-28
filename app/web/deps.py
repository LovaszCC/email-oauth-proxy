from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.state import AppState


class NotAuthenticated(Exception):
    pass


def get_state(request: Request) -> AppState:
    return request.app.state.container


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_state(request).db.session() as session:
        yield session


def require_admin(request: Request) -> None:
    if not request.session.get("admin"):
        raise NotAuthenticated()
