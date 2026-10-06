"""
Leak report service.

Loads a player's recent hands from the DB with full detail, runs per-hand
analysis via hand_analysis_engine, and passes the results to leak_finder
to detect behavioral patterns.

Separation of concerns
----------------------
- DB loading (this module) stays in services/
- Per-hand analysis (analyze_hand) stays in analysis/
- Pattern detection (find_leaks) stays in analysis/
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analysis.hand_analysis_engine import analyze_hand
from app.analysis.leak_finder import AnalyzedHandRecord, LeakReport, find_leaks
from app.analysis.stats_aggregator import aggregate_all_players
from app.models.hand import Hand, HandPlayer
from app.schemas.hand import HandDetailOut


async def build_leak_report(
    session: AsyncSession,
    player_id: uuid.UUID,
    limit: int = 500,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> LeakReport:
    """
    Load recent hands, analyze each, and return a LeakReport.

    Parameters
    ----------
    session:    Async DB session.
    player_id:  The hero player UUID.
    limit:      Maximum number of recent hands to analyze.
    from_date:  Optional lower bound on hand_started_at.
    to_date:    Optional upper bound on hand_started_at.

    Returns
    -------
    LeakReport — always returns, never raises.
    """
    hero_hand_ids = select(HandPlayer.hand_id).where(HandPlayer.player_id == player_id)

    q = (
        select(Hand)
        .options(
            selectinload(Hand.hand_players).options(
                selectinload(HandPlayer.actions),
                selectinload(HandPlayer.player),
            ),
            selectinload(Hand.winners),
        )
        .where(Hand.id.in_(hero_hand_ids))
        .order_by(Hand.hand_started_at.desc())
        .limit(limit)
    )
    if from_date is not None:
        q = q.where(Hand.hand_started_at >= from_date)
    if to_date is not None:
        q = q.where(Hand.hand_started_at <= to_date)

    result = await session.execute(q)
    hands = result.scalars().all()

    if not hands:
        return find_leaks([], player_id)

    hand_details: list[HandDetailOut] = [HandDetailOut.model_validate(h) for h in hands]
    opponent_stats = aggregate_all_players(hand_details)

    analyzed: list[AnalyzedHandRecord] = []
    for hand_detail in hand_details:
        hero_hp = next(
            (hp for hp in hand_detail.hand_players if hp.player_id == player_id),
            None,
        )
        if hero_hp is None:
            continue

        analysis_result = analyze_hand(hand_detail, player_id, opponent_stats=opponent_stats)
        analyzed.append(
            AnalyzedHandRecord(
                hand_external_id=hand_detail.external_id,
                result=analysis_result,
                position=hero_hp.position,
                stack_bb=hero_hp.stack_bb,
            )
        )

    return find_leaks(analyzed, player_id)
