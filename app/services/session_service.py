import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.player import Club
from app.models.session import GameSession, SeatAssignment
from app.schemas.common import PaginatedResponse
from app.schemas.ingestion import IngestTablePayload
from app.schemas.session import GameSessionDetailOut, GameSessionOut


async def upsert_session(session: AsyncSession, payload: IngestTablePayload) -> None:
    club_row = await session.execute(
        select(Club.id).where(Club.external_id == payload.club_external_id)
    )
    club_id: uuid.UUID | None = club_row.scalar_one_or_none()
    if club_id is None:
        raise ValueError(f"Club external_id={payload.club_external_id} not found")

    values: dict[str, Any] = {
        "external_id": payload.external_id,
        "club_id": club_id,
        "table_name": payload.table_name,
        "game_type": payload.game_type.value,
        "stakes_sb": payload.stakes_sb,
        "stakes_bb": payload.stakes_bb,
        "stakes_ante": payload.stakes_ante,
        "max_players": payload.max_players,
        "status": payload.status.value,
        "started_at": payload.started_at,
        "ended_at": payload.ended_at,
        "hand_count": payload.hand_count,
    }
    stmt = (
        insert(GameSession)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["external_id"],
            set_={k: v for k, v in values.items() if k != "external_id"},
        )
    )
    await session.execute(stmt)


async def list_sessions(
    session: AsyncSession,
    club_id: uuid.UUID | None = None,
    game_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[GameSessionOut]:
    q = select(GameSession)
    if club_id:
        q = q.where(GameSession.club_id == club_id)
    if game_type:
        q = q.where(GameSession.game_type == game_type)
    if status:
        q = q.where(GameSession.status == status)

    count_result = await session.execute(
        select(GameSession.id).where(*(q.whereclause,) if q.whereclause is not None else ())
    )
    total = len(count_result.all())

    q = q.order_by(GameSession.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    sessions = result.scalars().all()

    return PaginatedResponse(
        items=[GameSessionOut.model_validate(s) for s in sessions],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


async def get_session(
    session: AsyncSession, session_id: uuid.UUID
) -> GameSessionDetailOut | None:
    result = await session.execute(
        select(GameSession)
        .options(selectinload(GameSession.seat_assignments))
        .where(GameSession.id == session_id)
    )
    gs = result.scalar_one_or_none()
    return GameSessionDetailOut.model_validate(gs) if gs else None
