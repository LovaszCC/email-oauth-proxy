from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.accounts import AccountService
from app.state import AppState
from app.web.deps import get_db_session, get_state
from app.web.dto import HealthDto

router = APIRouter()


@router.get("/api/health", response_model=HealthDto)
async def health(
    state: AppState = Depends(get_state), session: AsyncSession = Depends(get_db_session)
) -> HealthDto:
    total, authorized = await AccountService(session, state.crypto).count()
    return HealthDto(
        imap_listening=state.proxy.listening, accounts_total=total, accounts_authorized=authorized
    )
