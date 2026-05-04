from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player
from app.models.user_player_link import UserPlayerLink


async def link_player(
    session: AsyncSession,
    user_id: uuid.UUID,
    player_id: uuid.UUID,
    is_primary: bool = True,
) -> UserPlayerLink:
    existing = await session.scalar(
        select(UserPlayerLink).where(
            UserPlayerLink.user_id == user_id,
            UserPlayerLink.player_id == player_id,
        )
    )
    if existing:
        if is_primary and not existing.is_primary:
            await session.execute(
                update(UserPlayerLink)
                .where(UserPlayerLink.user_id == user_id)
                .values(is_primary=False)
            )
            existing.is_primary = True
            await session.flush()
        return existing

    if is_primary:
        await session.execute(
            update(UserPlayerLink).where(UserPlayerLink.user_id == user_id).values(is_primary=False)
        )

    link = UserPlayerLink(user_id=user_id, player_id=player_id, is_primary=is_primary)
    session.add(link)
    await session.flush()
    return link


async def get_linked_players(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[tuple[UserPlayerLink, Player]]:
    rows = await session.execute(
        select(UserPlayerLink, Player)
        .join(Player, Player.id == UserPlayerLink.player_id)
        .where(UserPlayerLink.user_id == user_id)
        .order_by(UserPlayerLink.is_primary.desc(), UserPlayerLink.created_at)
    )
    return list(rows.all())


async def get_primary_player(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Player | None:
    return await session.scalar(
        select(Player)
        .join(UserPlayerLink, UserPlayerLink.player_id == Player.id)
        .where(
            UserPlayerLink.user_id == user_id,
            UserPlayerLink.is_primary == True,  # noqa: E712
        )
    )


async def is_player_linked(
    session: AsyncSession,
    user_id: uuid.UUID,
    player_id: uuid.UUID,
) -> bool:
    result = await session.scalar(
        select(UserPlayerLink).where(
            UserPlayerLink.user_id == user_id,
            UserPlayerLink.player_id == player_id,
        )
    )
    return result is not None
