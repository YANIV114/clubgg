"""Pydantic output schemas for real-spot drills."""

import uuid
from decimal import Decimal

from pydantic import BaseModel


class DrillRecommendationOut(BaseModel):
    best: str
    acceptable: list[str]
    reason: str
    backing: str


class DrillSpotOut(BaseModel):
    hand_external_id: str
    position: str
    opener_position: str
    raise_to_bb: Decimal
    eff_bb: Decimal
    hole_cards: str
    canonical: str
    hero_action: str  # what the player actually did
    was_mistake: bool
    recommendation: DrillRecommendationOut


class VsRaiseDrillsOut(BaseModel):
    player_id: uuid.UUID
    total_spots: int
    mistakes: int
    mistakes_by_position: dict[str, int]
    spots: list[DrillSpotOut]
