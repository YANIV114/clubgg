"""
Tournament grouping and review service.

Groups a player's hands into tournament sessions using:
  1. game_session_id when present (exact session match)
  2. (table_name, calendar_date, club_id[:8]) fallback for hands without a session
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import date

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.types import Date

from app.analysis.coaching import coach_hand
from app.analysis.hand_analysis_engine import analyze_hand
from app.models.hand import Hand, HandPlayer
from app.schemas.hand import HandDetailOut
from app.schemas.tournament import (
    HandAnalysisOut,
    HandCoachingOut,
    TournamentHandOut,
    TournamentOut,
)

# ── Tournament ID encoding ────────────────────────────────────────────────────


def _encode_tid(group: dict) -> str:
    raw = json.dumps(group, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_tid(tid: str) -> dict:
    pad = (4 - len(tid) % 4) % 4
    return json.loads(base64.urlsafe_b64decode(tid + "=" * pad))


def _hand_date(dt) -> str:  # type: ignore[type-arg]
    return dt.strftime("%Y%m%d")


# ── List tournaments ──────────────────────────────────────────────────────────


async def list_tournaments(
    session: AsyncSession,
    player_id: uuid.UUID,
) -> list[TournamentOut]:
    result = await session.execute(
        select(HandPlayer)
        .where(HandPlayer.player_id == player_id)
        .options(selectinload(HandPlayer.hand))
        .join(HandPlayer.hand)
        .order_by(Hand.hand_started_at.asc())
    )
    hero_hps = result.scalars().all()

    groups: dict[str, list[tuple]] = {}
    group_meta: dict[str, dict] = {}

    for hero_hp in hero_hps:
        hand = hero_hp.hand
        if hand.game_session_id is not None:
            tid = _encode_tid({"t": "sess", "id": str(hand.game_session_id)})
        else:
            tbl = hand.table_name or "Unknown"
            dt_str = _hand_date(hand.hand_started_at)
            cl_str = str(hand.club_id)[:8]
            tid = _encode_tid({"cl": cl_str, "dt": dt_str, "t": "day", "tbl": tbl})

        if tid not in groups:
            groups[tid] = []
            group_meta[tid] = {
                "table_name": hand.table_name or "Unknown",
                "first_hand_at": hand.hand_started_at,
                "last_hand_at": hand.hand_started_at,
            }
        groups[tid].append((hand, hero_hp))
        meta = group_meta[tid]
        if hand.hand_started_at < meta["first_hand_at"]:
            meta["first_hand_at"] = hand.hand_started_at
        if hand.hand_started_at > meta["last_hand_at"]:
            meta["last_hand_at"] = hand.hand_started_at

    out: list[TournamentOut] = []
    for tid, items in groups.items():
        meta = group_meta[tid]
        total_net = None
        ref_bb = None
        for hand, hero_hp in items:
            if hero_hp.net_won is not None and hand.stakes_bb:
                if total_net is None:
                    total_net = hand.stakes_bb * 0  # Decimal zero with same scale
                if ref_bb is None:
                    ref_bb = hand.stakes_bb
                total_net = total_net + hero_hp.net_won

        hero_net_bb: float | None = None
        if total_net is not None and ref_bb and ref_bb != 0:
            hero_net_bb = round(float(total_net / ref_bb), 1)

        out.append(
            TournamentOut(
                id=tid,
                table_name=meta["table_name"],
                first_hand_at=meta["first_hand_at"],
                last_hand_at=meta["last_hand_at"],
                hand_count=len(items),
                hero_net_bb=hero_net_bb,
            )
        )

    out.sort(key=lambda t: t.last_hand_at, reverse=True)
    return out


# ── Tournament hands + review ─────────────────────────────────────────────────


async def get_tournament_hands(
    session: AsyncSession,
    player_id: uuid.UUID,
    tournament_id: str,
) -> list[TournamentHandOut] | None:
    """Return all hands for a tournament group in chronological order with coaching."""
    try:
        group = _decode_tid(tournament_id)
    except Exception:
        return None

    hero_hand_ids_q = select(HandPlayer.hand_id).where(HandPlayer.player_id == player_id)

    q = (
        select(Hand)
        .options(
            selectinload(Hand.hand_players).options(
                selectinload(HandPlayer.actions),
                selectinload(HandPlayer.player),
            ),
            selectinload(Hand.winners),
        )
        .where(Hand.id.in_(hero_hand_ids_q))
        .order_by(Hand.hand_started_at.asc())
    )

    group_type = group.get("t")
    if group_type == "sess":
        try:
            session_id = uuid.UUID(group["id"])
        except (ValueError, KeyError):
            return None
        q = q.where(Hand.game_session_id == session_id)
    elif group_type == "day":
        tbl = group.get("tbl", "")
        dt_str = group.get("dt", "")
        cl_str = group.get("cl", "")
        try:
            target_date = date(int(dt_str[:4]), int(dt_str[4:6]), int(dt_str[6:8]))
        except (ValueError, IndexError):
            return None
        q = q.where(Hand.table_name == tbl)
        q = q.where(cast(Hand.hand_started_at, Date) == target_date)
        # Narrow to the correct club via the first 8 chars of club_id
        if cl_str:
            q = q.where(cast(Hand.club_id, UUID(as_uuid=False)).like(f"{cl_str}%"))
    else:
        return None

    result = await session.execute(q)
    hands = result.scalars().all()

    # Phase 1: validate all hands upfront
    hand_details: list[HandDetailOut] = [HandDetailOut.model_validate(h) for h in hands]

    # Phase 2: aggregate opponent stats once across all hands
    all_stats = aggregate_all_players(hand_details)

    # Phase 3: analyze each hand using pre-computed stats
    total = len(hand_details)
    out: list[TournamentHandOut] = []
    for idx, hand_detail in enumerate(hand_details):
        hero_in_hand = any(hp.player_id == player_id for hp in hand_detail.hand_players)
        coaching: HandCoachingOut | None = (
            coach_hand(hand_detail, player_id) if hero_in_hand else None
        )
        analysis: HandAnalysisOut | None = None
        if hero_in_hand:
            r = analyze_hand(hand_detail, player_id, opponent_stats=all_stats)
            analysis = HandAnalysisOut(
                spot_type=r.spot_type,
                hero_action=r.hero_action,
                recommended_action=r.recommended_action,
                mistake_severity=r.mistake_severity,
                explanation=r.explanation,
                key_factors=list(r.key_factors),
                confidence=str(r.confidence),
                ev_label=r.ev_label,
                backing=r.backing,
                range_context=r.range_context,
                hero_range_position=r.hero_range_position,
                exploit_adjustment=r.exploit_adjustment,
                adjustment_reason=r.adjustment_reason,
                villain_profile=r.villain_profile,
                villain_profile_confidence=r.villain_profile_confidence,
            )
        out.append(
            TournamentHandOut(
                hand_index=idx + 1,
                total_hands=total,
                hero_player_id=player_id,
                coaching=coaching,
                analysis=analysis,
                hand=hand_detail,
            )
        )
    return out
