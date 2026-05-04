"""
Pydantic output schemas for the leak detection layer.

Maps 1-to-1 to the dataclasses in ``app.features.leaks``.
"""

import uuid

from pydantic import BaseModel, ConfigDict


class LeakExampleOut(BaseModel):
    """One real hand that demonstrates a detected leak pattern."""

    model_config = ConfigDict(from_attributes=True)

    hand_external_id: str
    position: str | None
    stack_bb: str | None
    effective_stack_bb: str | None
    board_cards: str | None
    situation: str
    why_weak: str
    stronger_line: str


class LeakOut(BaseModel):
    """Serialised form of ``features.leaks.Leak``."""

    model_config = ConfigDict(from_attributes=True)

    leak_id: str
    category: str
    title: str
    explanation: str
    evidence: str
    confidence: str
    severity: str
    frequency: str
    priority: int
    sample_size: int
    limitations: str
    suggested_fix: str
    examples: list[LeakExampleOut] = []


class PlayerLeaksOut(BaseModel):
    """
    Full leak analysis response for a single player.

    ``leaks`` is sorted by priority descending (highest urgency first).
    ``analysis_note`` provides context on sample reliability.
    """

    model_config = ConfigDict(from_attributes=True)

    player_id: uuid.UUID
    hand_count: int
    leaks: list[LeakOut]
    analysis_note: str
