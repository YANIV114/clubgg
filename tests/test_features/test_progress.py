"""Tests for play progress over time (app.features.progress)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.features.progress import compute_progress, wilson_interval
from tests.test_features.test_tournament_leaks import _record


def _r(month: int, vpip=False, pfr=False, eff=50, day=1):
    return dataclasses.replace(
        _record(eff, vpip=vpip, pfr=pfr),
        played_at=datetime(2026, month, day, 20, 0, tzinfo=UTC),
    )


def _metric(period, key):
    return next(m for m in period.metrics if m.key == key)


class TestWilson:
    def test_bounds_contain_estimate(self):
        lo, hi = wilson_interval(30, 100)
        assert lo < Decimal("0.30") < hi

    def test_narrows_with_sample(self):
        lo1, hi1 = wilson_interval(3, 10)
        lo2, hi2 = wilson_interval(300, 1000)
        assert (hi2 - lo2) < (hi1 - lo1)

    def test_zero_n(self):
        assert wilson_interval(0, 0) == (None, None)

    def test_extremes_stay_in_unit_range(self):
        lo, hi = wilson_interval(0, 5)
        assert lo == 0 and 0 < hi <= 1


class TestPeriods:
    def test_grouped_by_month_in_order(self):
        res = compute_progress(uuid.uuid4(), [_r(4), _r(4), _r(9), _r(10)])
        assert [p.label for p in res.periods] == ["2026-04", "2026-09", "2026-10"]
        assert [p.hands for p in res.periods] == [2, 1, 1]

    def test_short_stack_hands_excluded(self):
        res = compute_progress(uuid.uuid4(), [_r(4), _r(4, eff=12)])
        assert res.periods[0].hands == 1
        assert res.short_stack_excluded == 1

    def test_hands_without_date_skipped(self):
        undated = dataclasses.replace(_record(50), played_at=None)
        res = compute_progress(uuid.uuid4(), [_r(4), undated])
        assert sum(p.hands for p in res.periods) == 1

    def test_calls_preflop_is_vpip_minus_pfr(self):
        recs = [_r(4, vpip=True, pfr=False)] * 3 + [_r(4, vpip=True, pfr=True)] + [_r(4)] * 6
        calls = _metric(compute_progress(uuid.uuid4(), recs).periods[0], "calls_preflop")
        assert calls.value == Decimal("0.3000")
        assert calls.n == 10
        assert calls.ci_low < calls.value < calls.ci_high


class TestComparison:
    def test_significant_drop_reported_as_improvement(self):
        # Calling preflop falls from 40% to 10% over large samples.
        before = [_r(4, vpip=True)] * 400 + [_r(4)] * 600
        after = [_r(9, vpip=True)] * 30 + [_r(9)] * 270
        cmp = {c.key: c for c in compute_progress(uuid.uuid4(), before + after).comparison}
        calls = cmp["calls_preflop"]
        assert calls.significant is True
        assert calls.verdict == "improved"

    def test_small_sample_not_significant(self):
        before = [_r(4, vpip=True)] * 4 + [_r(4)] * 6
        after = [_r(9, vpip=True)] * 1 + [_r(9)] * 4
        cmp = {c.key: c for c in compute_progress(uuid.uuid4(), before + after).comparison}
        assert cmp["calls_preflop"].significant is False
        assert cmp["calls_preflop"].verdict == "not enough evidence"

    def test_moving_toward_normal_range_is_improvement(self):
        # PFR 10% -> 20%: from below the normal range into it.
        before = [_r(4, vpip=True, pfr=True)] * 100 + [_r(4)] * 900
        after = [_r(9, vpip=True, pfr=True)] * 60 + [_r(9)] * 240
        cmp = {c.key: c for c in compute_progress(uuid.uuid4(), before + after).comparison}
        assert cmp["pfr"].verdict == "improved"

    def test_overshooting_the_range_is_worse(self):
        # PFR 15% -> 40%: overshoots the normal range by more than it was below it.
        before = [_r(4, vpip=True, pfr=True)] * 150 + [_r(4)] * 850
        after = [_r(9, vpip=True, pfr=True)] * 120 + [_r(9)] * 180
        cmp = {c.key: c for c in compute_progress(uuid.uuid4(), before + after).comparison}
        assert cmp["pfr"].verdict == "worse"

    def test_no_comparison_with_one_period(self):
        assert compute_progress(uuid.uuid4(), [_r(4)] * 5).comparison == []
