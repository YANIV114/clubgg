"""
Play progress over time: key preflop frequencies per calendar month.

Pure functions — no DB, no IO.  Input: HandRecord with ``played_at`` set.
Uses the same sample as the stat-based leak engine (hands at
MIN_EFFECTIVE_BB+ effective; push/fold hands excluded).

Honesty rules
-------------
- Every rate carries a 95% Wilson interval.
- The latest month is compared with all earlier months pooled, using a
  two-proportion z-test.  A change is only called "improved"/"worse" when
  it is significant (|z| > 1.96, both samples ≥ 20).
- "Improved" means moved closer to an approximate normal range for
  tournaments with antes — not simply "went up".  Moving within the range
  is reported as "changed (within range)".  The ranges are approximate
  guidelines, not solver output.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.features.leaks import MIN_EFFECTIVE_BB
from app.features.player_stats import HandRecord, compute_player_stats

_Z95 = 1.96
_MIN_N_COMPARE = 20
_Q = Decimal("0.0001")


@dataclass(frozen=True)
class _MetricDef:
    key: str
    label: str
    normal: tuple[Decimal, Decimal]
    # Returns (numerator, denominator) for a sample.
    counts: Callable[[uuid.UUID, Sequence[HandRecord]], tuple[int, int]]


def _from_stat(attr: str) -> Callable[[uuid.UUID, Sequence[HandRecord]], tuple[int, int]]:
    def counts(player_id: uuid.UUID, hands: Sequence[HandRecord]) -> tuple[int, int]:
        m = getattr(compute_player_stats(player_id=player_id, hands=hands), attr)
        n = m.n or 0
        return (round(float(m.value) * n) if m.value is not None else 0), n

    return counts


def _calls_preflop(player_id: uuid.UUID, hands: Sequence[HandRecord]) -> tuple[int, int]:
    return sum(1 for h in hands if h.vpip and not h.pfr), len(hands)


METRICS: list[_MetricDef] = [
    _MetricDef("calls_preflop", "Calls preflop (VPIP − PFR)",
               (Decimal("0.06"), Decimal("0.14")), _calls_preflop),
    _MetricDef("vpip", "VPIP", (Decimal("0.22"), Decimal("0.32")), _from_stat("vpip")),
    _MetricDef("pfr", "PFR", (Decimal("0.17"), Decimal("0.26")), _from_stat("pfr")),
    _MetricDef("three_bet_pct", "3-bet", (Decimal("0.06"), Decimal("0.12")),
               _from_stat("three_bet_pct")),
    _MetricDef("steal_pct", "Steal (BTN/CO/SB)", (Decimal("0.40"), Decimal("0.60")),
               _from_stat("steal_pct")),
    _MetricDef("resteal_pct", "3-bet vs steal", (Decimal("0.08"), Decimal("0.18")),
               _from_stat("resteal_pct")),
    _MetricDef("bb_fold_to_steal", "BB fold to steal", (Decimal("0.25"), Decimal("0.55")),
               _from_stat("bb_fold_to_steal")),
]


@dataclass(frozen=True)
class PeriodMetric:
    key: str
    label: str
    value: Decimal | None
    n: int
    ci_low: Decimal | None
    ci_high: Decimal | None
    normal_low: Decimal
    normal_high: Decimal


@dataclass(frozen=True)
class Period:
    label: str  # "YYYY-MM"
    hands: int
    metrics: list[PeriodMetric]


@dataclass(frozen=True)
class Comparison:
    key: str
    label: str
    before: Decimal | None
    before_n: int
    after: Decimal | None
    after_n: int
    significant: bool
    verdict: str  # improved | worse | changed (within range) | not enough evidence


@dataclass(frozen=True)
class PlayerProgress:
    periods: list[Period]  # chronological
    comparison: list[Comparison]  # latest period vs all earlier; [] with < 2 periods
    latest_label: str | None
    short_stack_excluded: int


def wilson_interval(k: int, n: int) -> tuple[Decimal | None, Decimal | None]:
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + _Z95**2 / n
    centre = (p + _Z95**2 / (2 * n)) / denom
    half = _Z95 * math.sqrt(p * (1 - p) / n + _Z95**2 / (4 * n * n)) / denom
    lo = Decimal(max(0.0, centre - half)).quantize(_Q)
    hi = Decimal(min(1.0, centre + half)).quantize(_Q)
    return lo, hi


def _rate(k: int, n: int) -> Decimal | None:
    return (Decimal(k) / Decimal(n)).quantize(_Q) if n else None


def _distance(v: Decimal, band: tuple[Decimal, Decimal]) -> Decimal:
    lo, hi = band
    return lo - v if v < lo else v - hi if v > hi else Decimal("0")


def _compare(m: _MetricDef, k1: int, n1: int, k2: int, n2: int) -> Comparison:
    before, after = _rate(k1, n1), _rate(k2, n2)
    significant = False
    if n1 >= _MIN_N_COMPARE and n2 >= _MIN_N_COMPARE:
        pooled = (k1 + k2) / (n1 + n2)
        se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
        if se > 0:
            significant = abs(k2 / n2 - k1 / n1) / se > _Z95
    if not significant or before is None or after is None:
        verdict = "not enough evidence"
    else:
        d_before, d_after = _distance(before, m.normal), _distance(after, m.normal)
        verdict = (
            "improved" if d_after < d_before
            else "worse" if d_after > d_before
            else "changed (within range)"
        )
    return Comparison(
        key=m.key, label=m.label, before=before, before_n=n1, after=after, after_n=n2,
        significant=significant, verdict=verdict,
    )


def compute_progress(player_id: uuid.UUID, records: Sequence[HandRecord]) -> PlayerProgress:
    dated = [r for r in records if r.played_at is not None]
    sample = [
        r for r in dated
        if r.effective_stack_bb is None or r.effective_stack_bb >= MIN_EFFECTIVE_BB
    ]
    by_month: dict[str, list[HandRecord]] = {}
    for r in sorted(sample, key=lambda r: r.played_at):  # type: ignore[arg-type, return-value]
        by_month.setdefault(r.played_at.strftime("%Y-%m"), []).append(r)  # type: ignore[union-attr]

    periods: list[Period] = []
    counts: dict[str, dict[str, tuple[int, int]]] = {}
    for label, hands in by_month.items():
        counts[label] = {m.key: m.counts(player_id, hands) for m in METRICS}
        metrics = []
        for m in METRICS:
            k, n = counts[label][m.key]
            lo, hi = wilson_interval(k, n)
            metrics.append(PeriodMetric(
                key=m.key, label=m.label, value=_rate(k, n), n=n, ci_low=lo, ci_high=hi,
                normal_low=m.normal[0], normal_high=m.normal[1],
            ))
        periods.append(Period(label=label, hands=len(hands), metrics=metrics))

    comparison: list[Comparison] = []
    if len(periods) >= 2:
        latest = periods[-1].label
        earlier = [p.label for p in periods[:-1]]
        for m in METRICS:
            k1 = sum(counts[lbl][m.key][0] for lbl in earlier)
            n1 = sum(counts[lbl][m.key][1] for lbl in earlier)
            k2, n2 = counts[latest][m.key]
            comparison.append(_compare(m, k1, n1, k2, n2))

    return PlayerProgress(
        periods=periods,
        comparison=comparison,
        latest_label=periods[-1].label if periods else None,
        short_stack_excluded=len(dated) - len(sample),
    )
