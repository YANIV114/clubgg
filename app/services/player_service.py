"""
Service layer for Club, Agent, and Player upserts and queries.
All upserts use PostgreSQL INSERT ... ON CONFLICT DO UPDATE for idempotency.
"""

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hand import Hand, HandPlayer
from app.models.player import Agent, Club, Player
from app.models.session import GameSession, TournamentFormat
from app.schemas.common import PaginatedResponse
from app.schemas.ingestion import IngestAgentPayload, IngestPlayerPayload
from app.schemas.player import ClubOut, PlayerDetailOut, PlayerOut, PlayerSampleOut

# ── Club ──────────────────────────────────────────────────────────────────────


async def upsert_club(
    session: AsyncSession, external_id: int, name: str, currency: str = "USD"
) -> None:
    stmt = (
        insert(Club)
        .values(external_id=external_id, name=name, currency=currency)
        .on_conflict_do_update(
            index_elements=["external_id"],
            set_={"name": name, "currency": currency},
        )
    )
    await session.execute(stmt)


async def list_clubs(session: AsyncSession) -> list[ClubOut]:
    result = await session.execute(select(Club).order_by(Club.name))
    clubs = result.scalars().all()
    return [ClubOut.model_validate(c) for c in clubs]


async def get_club(session: AsyncSession, club_id: uuid.UUID) -> ClubOut | None:
    result = await session.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    return ClubOut.model_validate(club) if club else None


# ── Agent ─────────────────────────────────────────────────────────────────────


async def upsert_agent(session: AsyncSession, payload: IngestAgentPayload) -> None:
    # Resolve club internal id
    club_row = await session.execute(
        select(Club.id).where(Club.external_id == payload.club_external_id)
    )
    club_id = club_row.scalar_one_or_none()
    if club_id is None:
        raise ValueError(f"Club with external_id={payload.club_external_id} not found")

    parent_id: uuid.UUID | None = None
    if payload.parent_agent_external_id is not None:
        parent_row = await session.execute(
            select(Agent.id).where(Agent.external_id == payload.parent_agent_external_id)
        )
        parent_id = parent_row.scalar_one_or_none()

    values: dict[str, Any] = {
        "external_id": payload.external_id,
        "club_id": club_id,
        "parent_agent_id": parent_id,
        "username": payload.username,
        "display_name": payload.display_name,
        "commission_rate": payload.commission_rate,
        "is_active": payload.is_active,
    }
    stmt = (
        insert(Agent)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["external_id"],
            set_={k: v for k, v in values.items() if k != "external_id"},
        )
    )
    await session.execute(stmt)


# ── Player ────────────────────────────────────────────────────────────────────


async def upsert_player(session: AsyncSession, payload: IngestPlayerPayload) -> None:
    club_row = await session.execute(
        select(Club.id).where(Club.external_id == payload.club_external_id)
    )
    club_id = club_row.scalar_one_or_none()
    if club_id is None:
        raise ValueError(f"Club with external_id={payload.club_external_id} not found")

    agent_id: uuid.UUID | None = None
    if payload.agent_external_id is not None:
        agent_row = await session.execute(
            select(Agent.id).where(Agent.external_id == payload.agent_external_id)
        )
        agent_id = agent_row.scalar_one_or_none()

    values: dict[str, Any] = {
        "external_id": payload.external_id,
        "club_id": club_id,
        "agent_id": agent_id,
        "username": payload.username,
        "display_name": payload.display_name,
        "country_code": payload.country_code,
        "is_active": payload.is_active,
        "is_stub": False,
    }
    stmt = (
        insert(Player)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["external_id"],
            set_={k: v for k, v in values.items() if k != "external_id"},
        )
    )
    await session.execute(stmt)


async def get_or_create_stub_player(
    session: AsyncSession, club_id: uuid.UUID, username: str
) -> uuid.UUID:
    """
    Return the internal UUID of the player with the given username in this club.
    If not found, create a stub player record and return its id.
    Stubs are flagged with is_stub=True and enriched on the next player sync.
    """
    row = await session.execute(
        select(Player.id).where(Player.club_id == club_id, Player.username == username)
    )
    player_id = row.scalar_one_or_none()
    if player_id is not None:
        return player_id

    # Create stub — use a deterministic synthetic negative external_id.
    # hashlib.sha256 is process-stable (unlike Python's hash() which is
    # randomized per-process by PYTHONHASHSEED).
    digest = int(hashlib.sha256(f"{club_id}:{username}".encode()).hexdigest()[:8], 16)
    stub = Player(
        club_id=club_id,
        username=username,
        is_active=True,
        is_stub=True,
        external_id=-(digest % (2**31)),
    )
    session.add(stub)
    await session.flush()
    return stub.id


async def list_players(
    session: AsyncSession,
    club_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    sort_by: str = "username",
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[PlayerOut]:
    # Subquery: hand count per player
    hand_count_sq = (
        select(HandPlayer.player_id, func.count().label("hand_count"))
        .group_by(HandPlayer.player_id)
        .subquery()
    )

    q = select(Player, func.coalesce(hand_count_sq.c.hand_count, 0).label("hand_count")).outerjoin(
        hand_count_sq, Player.id == hand_count_sq.c.player_id
    )
    if club_id:
        q = q.where(Player.club_id == club_id)
    if agent_id:
        q = q.where(Player.agent_id == agent_id)
    if is_active is not None:
        q = q.where(Player.is_active == is_active)

    count_q = select(func.count()).select_from(Player)
    if club_id:
        count_q = count_q.where(Player.club_id == club_id)
    if agent_id:
        count_q = count_q.where(Player.agent_id == agent_id)
    if is_active is not None:
        count_q = count_q.where(Player.is_active == is_active)
    total: int = await session.scalar(count_q) or 0

    order = (
        func.coalesce(hand_count_sq.c.hand_count, 0).desc()
        if sort_by == "hand_count"
        else Player.username
    )
    q = q.order_by(order).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    rows = result.all()

    items = []
    for row in rows:
        player, hand_count = row[0], row[1]
        out = PlayerOut.model_validate(player)
        out.hand_count = hand_count
        items.append(out)

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


async def get_player(session: AsyncSession, player_id: uuid.UUID) -> PlayerDetailOut | None:
    result = await session.execute(
        select(Player)
        .options(selectinload(Player.agent), selectinload(Player.club))
        .where(Player.id == player_id)
    )
    player = result.scalar_one_or_none()
    return PlayerDetailOut.model_validate(player) if player else None


async def get_player_sample(session: AsyncSession, player_id: uuid.UUID) -> PlayerSampleOut:
    # Join hand_players → hands → game_sessions for all hands the player participated in
    base = (
        select(Hand)
        .join(HandPlayer, HandPlayer.hand_id == Hand.id)
        .where(HandPlayer.player_id == player_id)
    )

    agg = await session.execute(
        select(
            func.count().label("hand_count"),
            func.min(Hand.hand_started_at).label("first_hand_at"),
            func.max(Hand.hand_started_at).label("last_hand_at"),
            func.max(Hand.updated_at).label("last_updated_at"),
        ).select_from(base.subquery())
    )
    row = agg.one()

    # Count tournament hands: hands linked to a non-CASH game session
    tournament_sq = (
        select(func.count())
        .select_from(HandPlayer)
        .join(Hand, Hand.id == HandPlayer.hand_id)
        .join(GameSession, GameSession.id == Hand.game_session_id)
        .where(
            HandPlayer.player_id == player_id,
            GameSession.tournament_format != TournamentFormat.CASH,
        )
    )
    tournament_count: int = await session.scalar(tournament_sq) or 0

    return PlayerSampleOut(
        hand_count=row.hand_count or 0,
        tournament_count=tournament_count,
        first_hand_at=row.first_hand_at,
        last_hand_at=row.last_hand_at,
        last_updated_at=row.last_updated_at,
    )
