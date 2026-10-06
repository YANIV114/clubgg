"""
Pydantic output schemas for ``app.features.results``.

Thin 1-to-1 serialisation of the PlayerResults dataclasses.
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.stats import LabeledMetricOut


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


class TournamentSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tournament_id: str
    name: str | None
    format_hint: str | None  # inferred from the name only
    hands: int
    first_level: int | None
    last_level: int | None
    entries: int
    busts: int
    ended_busted: bool
    total_bb: Decimal


class PhaseRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    hands: int
    total_bb: Decimal
    bb_per_100: ResultRateOut
    vpip: LabeledMetricOut
    pfr: LabeledMetricOut
    three_bet_pct: LabeledMetricOut


class PlayerTournamentsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: uuid.UUID
    tournaments: list[TournamentSummaryOut]
    phases: list[PhaseRowOut]
    hands_without_tournament: int
