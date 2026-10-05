"""Tests for chip-result breakdowns (app.features.results)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from app.features.labels import MetricLabel
from app.features.results import compute_results
from tests.test_features.test_tournament_leaks import _record


def _r(net: float | None, position: str | None = "CO", eff: float | None = 50):
    return dataclasses.replace(
        _record(eff),
        position=position,
        net_bb=Decimal(str(net)) if net is not None else None,
    )


def _row(rows, label):
    return next(r for r in rows if r.label == label)


class TestTotals:
    def test_total_and_bb_per_100(self):
        res = compute_results([_r(2), _r(-1), _r(1), _r(-2)])
        assert res.hand_count == 4
        assert res.total_bb == Decimal("0")
        assert res.bb_per_100.value == Decimal("0.0")

    def test_bb_per_100_is_derived_and_carries_n(self):
        res = compute_results([_r(1)] * 10)
        assert res.bb_per_100.label == MetricLabel.DERIVED
        assert res.bb_per_100.n == 10
        assert res.bb_per_100.value == Decimal("100.0")

    def test_hands_without_result_are_skipped(self):
        res = compute_results([_r(5), _r(None)])
        assert res.hand_count == 1
        assert res.hands_without_result == 1

    def test_empty(self):
        res = compute_results([])
        assert res.hand_count == 0
        assert res.bb_per_100.value is None
        assert res.cumulative_bb == []


class TestBreakdowns:
    def test_by_position(self):
        res = compute_results([_r(3, "BTN"), _r(-1, "BTN"), _r(-2, "SB")])
        btn = _row(res.by_position, "BTN")
        assert btn.hands == 2
        assert btn.total_bb == Decimal("2")
        assert _row(res.by_position, "SB").total_bb == Decimal("-2")

    def test_positions_in_table_order(self):
        recs = [_r(0, p) for p in ("BB", "BTN", "UTG", "SB", "CO")]
        labels = [r.label for r in compute_results(recs).by_position]
        assert labels == ["UTG", "CO", "BTN", "SB", "BB"]

    def test_unknown_position_excluded_from_breakdown(self):
        res = compute_results([_r(1, None), _r(1, "CO")])
        assert [r.label for r in res.by_position] == ["CO"]
        assert res.hand_count == 2

    def test_by_depth_buckets(self):
        res = compute_results([_r(1, eff=8), _r(1, eff=15), _r(1, eff=30), _r(1, eff=60)])
        assert [r.label for r in res.by_depth] == ["<10bb", "10–20bb", "20–40bb", "40bb+"]
        assert all(r.hands == 1 for r in res.by_depth)


class TestUncertainty:
    def test_margin_shrinks_with_sample(self):
        small = compute_results([_r(10), _r(-10)] * 5).bb_per_100
        large = compute_results([_r(10), _r(-10)] * 500).bb_per_100
        assert large.margin < small.margin

    def test_noisy_result_not_significant(self):
        # Mean +1bb/hand but huge swings over 20 hands: sign not established.
        res = compute_results([_r(51), _r(-49)] * 10)
        assert res.bb_per_100.value > 0
        assert res.bb_per_100.significant is False

    def test_consistent_result_significant(self):
        res = compute_results([_r(-1.1), _r(-0.9)] * 200)
        assert res.bb_per_100.significant is True

    def test_tiny_sample_never_significant(self):
        # Two identical hands have zero variance; that proves nothing.
        res = compute_results([_r(-0.2), _r(-0.2)])
        assert res.bb_per_100.significant is False

    def test_amounts_rounded(self):
        res = compute_results([_r(1 / 3)] * 3)
        assert res.total_bb == Decimal("1.0")
        assert res.cumulative_bb[-1] == Decimal("1.0")

    def test_single_hand_has_no_margin(self):
        res = compute_results([_r(5)])
        assert res.bb_per_100.margin is None
        assert res.bb_per_100.significant is False


class TestCumulative:
    def test_running_total_in_input_order(self):
        res = compute_results([_r(1), _r(-3), _r(2)])
        assert res.cumulative_bb == [Decimal("1"), Decimal("-2"), Decimal("0")]

    def test_downsampled_but_keeps_final_value(self):
        res = compute_results([_r(1)] * 1000)
        assert len(res.cumulative_bb) <= 200
        assert res.cumulative_bb[-1] == Decimal("1000")
