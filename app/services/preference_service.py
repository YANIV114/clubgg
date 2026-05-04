import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.preference import ClientPreference


async def get_last_player_id(session: AsyncSession, client_id: uuid.UUID) -> uuid.UUID | None:
    result = await session.execute(
        select(ClientPreference.last_player_id).where(ClientPreference.client_id == client_id)
    )
    return result.scalar_one_or_none()


async def set_last_player_id(
    session: AsyncSession, client_id: uuid.UUID, player_id: uuid.UUID
) -> None:
    stmt = (
        insert(ClientPreference)
        .values(client_id=client_id, last_player_id=player_id)
        .on_conflict_do_update(
            index_elements=["client_id"],
            set_={"last_player_id": player_id, "updated_at": __import__("sqlalchemy").func.now()},
        )
    )
    await session.execute(stmt)
    await session.commit()
