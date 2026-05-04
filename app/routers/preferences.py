import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.player_service import get_player
from app.services.preference_service import get_last_player_id, set_last_player_id

router = APIRouter()


class PreferenceOut(BaseModel):
    client_id: uuid.UUID
    last_player_id: uuid.UUID | None


class SetPreferenceIn(BaseModel):
    player_id: uuid.UUID


@router.get("/{client_id}", response_model=PreferenceOut)
async def get_preference(
    client_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PreferenceOut:
    last_player_id = await get_last_player_id(db, client_id)
    return PreferenceOut(client_id=client_id, last_player_id=last_player_id)


@router.put("/{client_id}", response_model=PreferenceOut)
async def set_preference(
    client_id: uuid.UUID,
    body: SetPreferenceIn,
    db: AsyncSession = Depends(get_db),
) -> PreferenceOut:
    player = await get_player(db, body.player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    await set_last_player_id(db, client_id, body.player_id)
    return PreferenceOut(client_id=client_id, last_player_id=body.player_id)
