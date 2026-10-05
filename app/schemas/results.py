"""
Pydantic output schemas for ``app.features.results``.

Thin 1-to-1 serialisation of the PlayerResults dataclasses.
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ResultRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: Decimal | None  # bb/100
    n: int
    margin: Decimal | None  # ± bb/100 at 95%
    significant: bool  # margin excludes zero
    label: str
    source: str


class ResultRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    hands: int
    total_bb: Decimal
    bb_per_100: ResultRateOut


class PlayerResultsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: uuid.UUID
    hand_count: int
    hands_without_result: int
    total_bb: Decimal
    bb_per_100: ResultRateOut
    by_position: list[ResultRowOut]
    by_depth: list[ResultRowOut]
    cumulative_bb: list[Decimal]
