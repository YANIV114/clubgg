"""
Real-spot drills from a player's own hands (DB read only).

Re-parses each stored hand's raw_text (the source of truth) and hands the
result to the pure drill logic in app.analysis.drills.
"""

from __future__ import annotations

import random
import uuid
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.drills import Recommendation, SpotVsRaise, find_spot_vs_raise, recommend_vs_raise
from app.features.normalize_hand import normalize_hand_players
from app.ingestion.hand_parser import HandHistoryParser
from app.models.hand import Hand, HandPlayer


@dataclass(frozen=True)
class DrillSpot:
    spot: SpotVsRaise
    recommendation: Recommendation

    @property
    def was_mistake(self) -> bool:
        return self.spot.hero_action not in self.recommendation.acceptable


@dataclass(frozen=True)
class VsRaiseDrills:
    total_spots: int
    mistakes: int
    mistakes_by_position: dict[str, int]
    # Balanced by correct answer: about half "fold", half "call"/"3-bet", with the
    # player's real mistakes first inside each half (random order within groups).  Most real
    # mistakes are calls that should fold, so an unbalanced set would reward
    # answering "fold" every time.
    spots: list[DrillSpot]


async def vs_raise_drills(
    session: AsyncSession,
    player_id: uuid.UUID,
    username: str,
    *,
    limit: int = 12,
    scan: int = 5000,
) -> VsRaiseDrills:
    hand_ids = select(HandPlayer.hand_id).where(HandPlayer.player_id == player_id)
    rows = (
        await session.execute(
            select(Hand.raw_text)
            .where(Hand.id.in_(hand_ids), Hand.raw_text.is_not(None))
            .order_by(Hand.hand_started_at.desc())
            .limit(scan)
        )
    ).scalars()

    parser = HandHistoryParser()
    found: list[DrillSpot] = []
    for raw_text in rows:
        try:
            hand = parser.parse(raw_text)
        except ValueError:
            continue
        normalize_hand_players(
            hand["players"], Decimal(str(hand["stakes_bb"])), hand.get("button_seat")
        )
        spot = find_spot_vs_raise(hand, username)
        if spot is None:
            continue
        rec = recommend_vs_raise(spot.position, spot.opener_position, spot.canonical)
        found.append(DrillSpot(spot=spot, recommendation=rec))

    mistakes = [d for d in found if d.was_mistake]
    return VsRaiseDrills(
        total_spots=len(found),
        mistakes=len(mistakes),
        mistakes_by_position=dict(Counter(d.spot.position for d in mistakes)),
        spots=_balanced(found, limit),
    )


def _balanced(found: list[DrillSpot], limit: int) -> list[DrillSpot]:
    def mistakes_first(items: list[DrillSpot]) -> list[DrillSpot]:
        # Shuffle within each group so every session is a fresh set.
        wrong = [d for d in items if d.was_mistake]
        right = [d for d in items if not d.was_mistake]
        random.shuffle(wrong)
        random.shuffle(right)
        return wrong + right

    folds = mistakes_first([d for d in found if d.recommendation.best == "fold"])
    plays = mistakes_first([d for d in found if d.recommendation.best != "fold"])
    n_plays = min(len(plays), limit // 2)
    picked = plays[:n_plays] + folds[: limit - n_plays]
    if len(picked) < limit:  # one side ran short: top up from the other
        picked += plays[n_plays : n_plays + limit - len(picked)]
    return picked
