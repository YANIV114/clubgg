import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hand import Hand
from app.models.player import Agent, Club, Player
from app.models.transaction import ChipTransaction
from app.schemas.common import PaginatedResponse
from app.schemas.ingestion import IngestTransactionPayload
from app.schemas.transaction import ChipTransactionOut


async def upsert_transaction(
    session: AsyncSession, payload: IngestTransactionPayload
) -> None:
    # Resolve foreign keys by external_id
    club_row = await session.execute(
        select(Club.id).where(Club.external_id == payload.club_external_id)
    )
    club_id: uuid.UUID | None = club_row.scalar_one_or_none()
    if club_id is None:
        raise ValueError(f"Club external_id={payload.club_external_id} not found")

    async def _resolve_player(ext_id: int | None) -> uuid.UUID | None:
        if ext_id is None:
            return None
        row = await session.execute(select(Player.id).where(Player.external_id == ext_id))
        return row.scalar_one_or_none()

    async def _resolve_agent(ext_id: int | None) -> uuid.UUID | None:
        if ext_id is None:
            return None
        row = await session.execute(select(Agent.id).where(Agent.external_id == ext_id))
        return row.scalar_one_or_none()

    async def _resolve_hand(ext_id: str | None) -> uuid.UUID | None:
        if ext_id is None:
            return None
        row = await session.execute(select(Hand.id).where(Hand.external_id == ext_id))
        return row.scalar_one_or_none()

    values: dict[str, Any] = {
        "external_id": payload.external_id,
        "club_id": club_id,
        "player_id": await _resolve_player(payload.player_external_id),
        "agent_id": await _resolve_agent(payload.agent_external_id),
        "counterparty_player_id": await _resolve_player(payload.counterparty_player_external_id),
        "counterparty_agent_id": await _resolve_agent(payload.counterparty_agent_external_id),
        "transaction_type": payload.transaction_type.value,
        "amount": payload.amount,
        "balance_before": payload.balance_before,
        "balance_after": payload.balance_after,
        "hand_id": await _resolve_hand(payload.hand_external_id),
        "transacted_at": payload.transacted_at,
        "notes": payload.notes,
    }
    stmt = (
        insert(ChipTransaction)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["external_id"],
            set_={k: v for k, v in values.items() if k != "external_id"},
        )
    )
    await session.execute(stmt)


async def list_transactions(
    session: AsyncSession,
    club_id: uuid.UUID | None = None,
    player_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    transaction_type: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[ChipTransactionOut]:
    q = select(ChipTransaction)
    if club_id:
        q = q.where(ChipTransaction.club_id == club_id)
    if player_id:
        q = q.where(ChipTransaction.player_id == player_id)
    if agent_id:
        q = q.where(ChipTransaction.agent_id == agent_id)
    if transaction_type:
        q = q.where(ChipTransaction.transaction_type == transaction_type)
    if from_date:
        q = q.where(ChipTransaction.transacted_at >= from_date)
    if to_date:
        q = q.where(ChipTransaction.transacted_at <= to_date)

    count_result = await session.execute(
        select(ChipTransaction.id).where(*(q.whereclause,) if q.whereclause is not None else ())
    )
    total = len(count_result.all())

    q = q.order_by(ChipTransaction.transacted_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    txns = result.scalars().all()

    return PaginatedResponse(
        items=[ChipTransactionOut.model_validate(t) for t in txns],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )
