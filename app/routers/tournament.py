import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import require_tester
from app.models.user import User
from app.schemas.tournament import TournamentHandOut, TournamentOut
from app.services import tournament_service
from app.services.user_player_service import get_primary_player

router = APIRouter()


async def _player_or_404(session: AsyncSession, user_id: uuid.UUID):
    player = await get_primary_player(session, user_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No player linked to your account",
        )
    return player


@router.get("/me/tournaments", response_model=list[TournamentOut])
async def list_my_tournaments(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> list[TournamentOut]:
    player = await _player_or_404(session, current_user.id)
    return await tournament_service.list_tournaments(session, player.id)


@router.get("/me/tournaments/{tournament_id}/hands", response_model=list[TournamentHandOut])
async def get_tournament_hands(
    tournament_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> list[TournamentHandOut]:
    player = await _player_or_404(session, current_user.id)
    hands = await tournament_service.get_tournament_hands(session, player.id, tournament_id)
    if hands is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tournament ID")
    return hands


@router.get("/me/tournaments/{tournament_id}/review", response_model=list[TournamentHandOut])
async def get_tournament_review(
    tournament_id: str,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> list[TournamentHandOut]:
    """Full hand data + coaching for every hand in a tournament group."""
    player = await _player_or_404(session, current_user.id)
    hands = await tournament_service.get_tournament_hands(session, player.id, tournament_id)
    if hands is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tournament ID")
    return hands
