import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import DBSession, require_tester
from app.models.hand import GameType
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.hand import HandDetailOut, HandOut
from app.services.hand_service import get_hand, get_hand_by_external_id, list_hands

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[HandOut])
async def list_hands_route(
    db: DBSession,
    _tester: User = Depends(require_tester),
    club_id: uuid.UUID | None = None,
    game_type: GameType | None = None,
    player_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> PaginatedResponse[HandOut]:
    return await list_hands(
        db,
        club_id=club_id,
        game_type=game_type,
        player_id=player_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )


# Must be before /{hand_id} so FastAPI doesn't try to parse "lookup" as a UUID.
@router.get("/lookup", response_model=HandDetailOut)
async def lookup_hand_by_external_id(
    external_id: str,
    db: DBSession,
    _tester: User = Depends(require_tester),
) -> HandDetailOut:
    """Fetch a hand by its external_id string (e.g. 'ClubGG Hand #12345678')."""
    hand = await get_hand_by_external_id(db, external_id)
    if hand is None:
        raise HTTPException(status_code=404, detail="Hand not found")
    return hand


@router.get("/{hand_id}", response_model=HandDetailOut)
async def get_hand_route(
    hand_id: uuid.UUID,
    db: DBSession,
    _tester: User = Depends(require_tester),
) -> HandDetailOut:
    hand = await get_hand(db, hand_id)
    if hand is None:
        raise HTTPException(status_code=404, detail="Hand not found")
    return hand
