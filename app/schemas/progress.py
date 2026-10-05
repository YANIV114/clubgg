"""Pydantic output schemas for ``app.features.progress``."""

import uuid
from decimal import Decimal

from pydantic import BaseModel


class PeriodMetricOut(BaseModel):
    key: str
    label: str
    value: Decimal | None
    n: int
    ci_low: Decimal | None  # 95% Wilson interval
    ci_high: Decimal | None
    normal_low: Decimal  # approximate normal range (tournaments with antes)
    normal_high: Decimal


class PeriodOut(BaseModel):
    label: str
    hands: int
    metrics: list[PeriodMetricOut]


class ComparisonOut(BaseModel):
    key: str
    label: str
    before: Decimal | None
    before_n: int
    after: Decimal | None
    after_n: int
    significant: bool
    verdict: str


class PlayerProgressOut(BaseModel):
    player_id: uuid.UUID
    periods: list[PeriodOut]
    comparison: list[ComparisonOut]
    latest_label: str | None
    short_stack_excluded: int
