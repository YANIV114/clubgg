"""
Pydantic output schemas for the analytics layer.

These schemas serialize the pure-Python dataclasses produced by
``app.features.player_stats`` into JSON-safe form.  They are intentionally
thin — each field maps 1-to-1 to the source dataclass field.
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LabeledMetricOut(BaseModel):
    """Serialised form of ``features.labels.LabeledMetric``."""

    model_config = ConfigDict(from_attributes=True)

    value: Decimal | None
    label: str  # MetricLabel StrEnum value e.g. "inferred"
    source: str
    n: int | None
    confidence_note: str


class PositionalStatsOut(BaseModel):
    """Serialised form of ``features.player_stats.PositionalStats``."""

    model_config = ConfigDict(from_attributes=True)

    position: str
    n_hands: int
    vpip: LabeledMetricOut
    pfr: LabeledMetricOut
    three_bet_pct: LabeledMetricOut
    fold_to_3bet: LabeledMetricOut
    steal_pct: LabeledMetricOut
    fold_to_steal: LabeledMetricOut


class PlayerStatsOut(BaseModel):
    """
    Serialised form of ``features.player_stats.PlayerStats``.

    All rate fields carry an epistemic label (``inferred`` for rates computed
    from a sample).  Consumers should check ``is_reliable`` client-side using
    ``n >= 20`` as the default threshold.
    """

    model_config = ConfigDict(from_attributes=True)

    player_id: uuid.UUID
    player_name: str | None = None
    hand_count: int
    vpip: LabeledMetricOut
    pfr: LabeledMetricOut
    three_bet_pct: LabeledMetricOut
    fold_to_3bet: LabeledMetricOut
    wtsd: LabeledMetricOut
    wsd: LabeledMetricOut
    steal_pct: LabeledMetricOut
    btn_steal_pct: LabeledMetricOut
    co_steal_pct: LabeledMetricOut
    sb_steal_pct: LabeledMetricOut
    fold_to_steal: LabeledMetricOut
    bb_fold_to_steal: LabeledMetricOut
    sb_fold_to_steal: LabeledMetricOut
    bb_fold_to_btn_open: LabeledMetricOut
    bb_fold_to_co_open: LabeledMetricOut
    resteal_pct: LabeledMetricOut
    positional: dict[str, PositionalStatsOut]
    # ── Postflop stats ────────────────────────────────────────────────────────
    cbet_pct: LabeledMetricOut
    fold_to_flop_bet: LabeledMetricOut
    turn_barrel_pct: LabeledMetricOut
    fold_to_turn_bet: LabeledMetricOut
    delayed_cbet_pct: LabeledMetricOut
    check_raise_pct: LabeledMetricOut
    aggression_factor: LabeledMetricOut
