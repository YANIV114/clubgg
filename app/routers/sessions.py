import uuid

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import DBSession
from app.models.hand import GameType
from app.models.session import SessionStatus
from app.schemas.common import PaginatedResponse
from app.schemas.session import GameSessionDetailOut, GameSessionOut
from app.services.session_service import get_session, list_sessions

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[GameSessionOut])
async def list_sessions_route(
    db: DBSession,
    club_id: uuid.UUID | None = None,
    game_type: GameType | None = None,
    status: SessionStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> PaginatedResponse[GameSessionOut]:
    return await list_sessions(
        db,
        club_id=club_id,
        game_type=game_type,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/{session_id}", response_model=GameSessionDetailOut)
async def get_session_route(
    session_id: uuid.UUID, db: DBSession
) -> GameSessionDetailOut:
    session = await get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
