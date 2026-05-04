"""
Pydantic schemas for POST /players/{id}/tournament-plan.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.leaks import LeakOut


class TournamentPlanRequest(BaseModel):
    """
    Optional tournament context supplied by the caller.

    All fields are optional — the plan degrades gracefully when context is absent.

    tournament_format:
        One of CASH | FREEZEOUT | REENTRY | PKO | SATELLITE | SPIN.
        Unrecognised values are silently ignored.
    stage:
        Current stage of the tournament.
        One of: early | middle | bubble | itm | final_table.
        Unrecognised values are silently ignored.
    stack_bb:
        Hero's current stack in big blinds.  Used for context display only.
    players_remaining:
        Players remaining in the tournament.  Used for context display only.
    limit:
        Maximum number of hands to load for stat computation.
    """

    tournament_format: str | None = Field(
        None, description="FREEZEOUT | PKO | SATELLITE | SPIN | REENTRY | CASH"
    )
    stage: str | None = Field(None, description="early | middle | bubble | itm | final_table")
    stack_bb: Decimal | None = Field(
        None, ge=Decimal("0"), description="Current stack in big blinds"
    )
    players_remaining: int | None = Field(None, ge=1, description="Players still in the tournament")
    limit: int = Field(500, ge=1, le=5000, description="Max hands to load for analysis")


class StudyPriorityOut(BaseModel):
    """One ranked study action derived from the player's detected leaks or stage context."""

    model_config = ConfigDict(from_attributes=True)

    rank: int
    focus_area: str
    action: str
    source: str  # "detected_leak" | "stage_specific" | "format_specific"
    urgency: str  # "immediate" | "this_week" | "long_term"
    leak_id: str | None = None


class TournamentPlanOut(BaseModel):
    """
    Full tournament prep plan for a single player.

    ``top_leaks`` are the highest-priority detected leaks (≤ 3).
    ``study_priorities`` are ranked, concrete study actions derived from those
    leaks plus any applicable stage- or format-specific additions.
    ``reliability_note`` states whether the underlying sample is large enough
    to trust the plan.
    """

    model_config = ConfigDict(from_attributes=True)

    player_id: uuid.UUID
    hand_count: int
    tournament_format: str | None
    stage: str | None
    stack_bb: Decimal | None
    players_remaining: int | None
    reliability_note: str
    stage_guidance: str
    format_note: str
    top_leaks: list[LeakOut]
    study_priorities: list[StudyPriorityOut]
