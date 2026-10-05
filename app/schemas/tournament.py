from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.hand import HandDetailOut


class TournamentOut(BaseModel):
    id: str
    table_name: str
    tournament_format: str | None = None
    first_hand_at: datetime
    last_hand_at: datetime
    hand_count: int
    hero_net_bb: float | None = None


class HandCoachingOut(BaseModel):
    """Legacy simple coaching output (kept for backward compat)."""

    spot_type: str
    hero_action: str
    recommended_action: str
    explanation: str
    severity: str  # good | small_mistake | big_mistake | neutral
    ev_label: str  # +EV | neutral | losing_chips


class HandAnalysisOut(BaseModel):
    """
    Rich analysis output from hand_analysis_engine.analyze_hand().

    confidence values:  inferred | speculative | observed | derived
    mistake_severity:   good | none | minor | major | critical
    ev_label:           +EV | neutral | -EV | unknown
    backing:            heuristic | range-based estimate | solver-backed
    """

    spot_type: str
    hero_action: str
    recommended_action: str
    mistake_severity: str
    explanation: str
    key_factors: list[str]
    confidence: str
    ev_label: str
    backing: str
    range_context: str = ""
    hero_range_position: str = "unknown"
    exploit_adjustment: str = ""
    adjustment_reason: str = ""
    villain_profile: str = (
        ""  # "tight-passive" | "loose-passive" | ... | "balanced" | "unknown" | ""
    )
    villain_profile_confidence: str = ""  # "low" | "medium" | "high" | ""


class TournamentHandOut(BaseModel):
    hand_index: int
    total_hands: int
    hero_player_id: uuid.UUID
    coaching: HandCoachingOut | None = None
    analysis: HandAnalysisOut | None = None
    hand: HandDetailOut
