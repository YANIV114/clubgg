"""
Chip results by position and stack depth.

Pure functions — no DB, no IO.  Input is HandRecord with ``net_bb`` set
(net chips won in the hand / big blind), in chronological order.

Results are chip results, not money: in tournaments, chips won ≠ prize EV
(ICM), so these show where chips are won and lost, not ROI.

Uncertainty
-----------
Per-hand results swing by tens of big blinds, so bb/100 over a few hundred
hands is very noisy.  Every rate carries a 95% margin (1.96 × standard
error × 100) and ``significant`` = the margin excludes zero, i.e. the sign
of the result is supported by the sample.  Nothing more is claimed.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.features.labels import MetricLabel
from app.features.player_stats import HandRecord

# Table order for display; positions not listed are appended alphabetically.
_POSITION_ORDER = ["UTG", "UTG1", "UTG2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB"]

_DEPTH_BUCKETS: list[tuple[str, Decimal | None]] = [
    ("<10bb", Decimal("10")),
    ("10–20bb", Decimal("20")),
    ("20–40bb", Decimal("40")),
    ("40bb+", None),
]

_MAX_CURVE_POINTS = 200
# Below this many hands a margin is too unstable to call any result significant.
_MIN_N_SIGNIFICANT = 30
_BB = Decimal("0.1")


@dataclass(frozen=True)
class ResultRate:
    """bb/100 with its 95% margin.  ``value``/``margin`` are None when n is too small."""

    value: Decimal | None
    n: int
    margin: Decimal | None
    significant: bool
    label: MetricLabel = MetricLabel.DERIVED
    source: str = "sum(net chips / big blind) / hands × 100"


@dataclass(frozen=True)
class ResultRow:
    label: str
    hands: int
    total_bb: Decimal
    bb_per_100: ResultRate


@dataclass(frozen=True)
class PlayerResults:
    hand_count: int  # hands with a known result
    hands_without_result: int
    total_bb: Decimal
    bb_per_100: ResultRate
    by_position: list[ResultRow]
    by_depth: list[ResultRow]
    cumulative_bb: list[Decimal]  # running total, downsampled to ≤200 points


def bb_per_100_rate(values: Sequence[Decimal]) -> ResultRate:
    n = len(values)
    if n == 0:
        return ResultRate(value=None, n=0, margin=None, significant=False)
    mean = sum(values, Decimal("0")) / n
    value = (mean * 100).quantize(Decimal("0.1"))
    if n < 2:
        return ResultRate(value=value, n=n, margin=None, significant=False)
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = Decimal(math.sqrt(float(var))) / Decimal(math.sqrt(n))
    margin = (Decimal("1.96") * se * 100).quantize(Decimal("0.1"))
    significant = n >= _MIN_N_SIGNIFICANT and abs(value) > margin
    return ResultRate(value=value, n=n, margin=margin, significant=significant)


def _row(label: str, values: Sequence[Decimal]) -> ResultRow:
    return ResultRow(
        label=label,
        hands=len(values),
        total_bb=sum(values, Decimal("0")).quantize(_BB),
        bb_per_100=bb_per_100_rate(values),
    )


def _depth_label(eff: Decimal) -> str:
    for label, upper in _DEPTH_BUCKETS:
        if upper is None or eff < upper:
            return label
    return _DEPTH_BUCKETS[-1][0]


def _downsample(curve: list[Decimal]) -> list[Decimal]:
    if len(curve) <= _MAX_CURVE_POINTS:
        return curve
    step = len(curve) / (_MAX_CURVE_POINTS - 1)
    idx = [round(i * step) for i in range(_MAX_CURVE_POINTS - 1)]
    return [curve[i] for i in idx] + [curve[-1]]


def compute_results(records: Sequence[HandRecord]) -> PlayerResults:
    """Break chip results down by position and effective stack depth."""
    known = [r for r in records if r.net_bb is not None]
    nets = [r.net_bb for r in known]  # type: ignore[misc]

    by_pos: dict[str, list[Decimal]] = defaultdict(list)
    by_depth: dict[str, list[Decimal]] = defaultdict(list)
    for r in known:
        if r.position:
            by_pos[r.position].append(r.net_bb)  # type: ignore[arg-type]
        if r.effective_stack_bb is not None:
            by_depth[_depth_label(r.effective_stack_bb)].append(r.net_bb)  # type: ignore[arg-type]

    def pos_key(p: str) -> tuple[int, str]:
        return (_POSITION_ORDER.index(p), p) if p in _POSITION_ORDER else (len(_POSITION_ORDER), p)

    curve: list[Decimal] = []
    running = Decimal("0")
    for v in nets:
        running += v
        curve.append(running.quantize(_BB))

    return PlayerResults(
        hand_count=len(known),
        hands_without_result=len(records) - len(known),
        total_bb=sum(nets, Decimal("0")).quantize(_BB),
        bb_per_100=bb_per_100_rate(nets),
        by_position=[_row(p, by_pos[p]) for p in sorted(by_pos, key=pos_key)],
        by_depth=[_row(label, by_depth[label]) for label, _ in _DEPTH_BUCKETS if label in by_depth],
        cumulative_bb=_downsample(curve),
    )
