"""
Tests for the leak detection engine.

Strategy: build PlayerStats instances directly from HandRecord lists so tests
cover the full detect path without mocking internals.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.analysis.leak_engine import (
    Leak,
    _cap_severity,
    _confidence_for_n,
    run_leak_detection,
)
from app.features.labels import MetricLabel
from app.features.player_stats import HandRecord, compute_player_stats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAYER_ID = uuid.uuid4()


def _rec(
    *,
    hand_id: str = "H0",
    position: str | None = "BTN",
    vpip: bool = False,
    pfr: bool = False,
    had_3bet_opportunity: bool = False,
    three_bet: bool = False,
    faced_3bet: bool = False,
    folded_to_3bet: bool = False,
    saw_flop: bool = False,
    reached_showdown: bool = False,
    won_at_showdown: bool = False,
) -> HandRecord:
    return HandRecord(
        hand_external_id=hand_id,
        position=position,
        stack_bb=Decimal("25.00"),
        effective_stack_bb=Decimal("22.00"),
        vpip=vpip,
        pfr=pfr,
        had_3bet_opportunity=had_3bet_opportunity,
        three_bet=three_bet,
        faced_3bet=faced_3bet,
        folded_to_3bet=folded_to_3bet,
        saw_flop=saw_flop,
        reached_showdown=reached_showdown,
        won_at_showdown=won_at_showdown,
        had_steal_opportunity=False,
        stole=False,
        faced_steal=False,
        folded_to_steal=False,
        re_steal_opportunity=False,
        attempted_resteal=False,
        folded_bb_to_btn_open=False,
        folded_sb_to_btn_open=False,
        faced_btn_open_as_bb=False,
        faced_co_open_as_bb=False,
        open_position=None,
        defender_position=None,
    )


def _stats(hands: list[HandRecord]) -> tuple[object, list[HandRecord]]:
    """Return (PlayerStats, hands) tuple for run_leak_detection."""
    return compute_player_stats(player_id=_PLAYER_ID, hands=hands), hands


def _leak_names(leaks: list[Leak]) -> list[str]:
    return [lk.name for lk in leaks]


# ---------------------------------------------------------------------------
# Helpers: _confidence_for_n, _cap_severity
# ---------------------------------------------------------------------------


class TestConfidenceForN:
    def test_zero_returns_speculative(self) -> None:
        label, note = _confidence_for_n(0)
        assert label == MetricLabel.SPECULATIVE

    def test_one_returns_speculative(self) -> None:
        label, _ = _confidence_for_n(1)
        assert label == MetricLabel.SPECULATIVE

    def test_four_returns_speculative(self) -> None:
        label, _ = _confidence_for_n(4)
        assert label == MetricLabel.SPECULATIVE

    def test_five_returns_inferred(self) -> None:
        label, note = _confidence_for_n(5)
        assert label == MetricLabel.INFERRED
        assert "low" in note

    def test_nineteen_returns_inferred_with_note(self) -> None:
        label, note = _confidence_for_n(19)
        assert label == MetricLabel.INFERRED
        assert note != ""

    def test_twenty_returns_inferred_no_note(self) -> None:
        label, note = _confidence_for_n(20)
        assert label == MetricLabel.INFERRED
        assert note == ""


class TestCapSeverity:
    def test_speculative_critical_capped_to_major(self) -> None:
        assert _cap_severity("critical", MetricLabel.SPECULATIVE) == "major"

    def test_speculative_major_unchanged(self) -> None:
        assert _cap_severity("major", MetricLabel.SPECULATIVE) == "major"

    def test_inferred_critical_unchanged(self) -> None:
        assert _cap_severity("critical", MetricLabel.INFERRED) == "critical"

    def test_inferred_minor_unchanged(self) -> None:
        assert _cap_severity("minor", MetricLabel.INFERRED) == "minor"


# ---------------------------------------------------------------------------
# Empty / zero-hand cases
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_no_hands_returns_empty(self) -> None:
        st, hands = _stats([])
        assert run_leak_detection(st, hands) == []

    def test_no_leaks_when_stats_are_clean(self) -> None:
        # Player who raises 30% of time and only VPIP 32% → gap 2pp, no leak
        hands = [
            _rec(hand_id=f"H{i}", vpip=True, pfr=True) for i in range(30)
        ] + [_rec(hand_id=f"F{i}") for i in range(70)]
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "vpip-pfr-gap" not in _leak_names(leaks)


# ---------------------------------------------------------------------------
# vpip-pfr-gap
# ---------------------------------------------------------------------------


class TestVpipPfrGap:
    def test_large_gap_produces_leak(self) -> None:
        # 50% VPIP, 20% PFR → gap 30pp, should be critical
        hands = (
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(20)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(30)]
            + [_rec(hand_id=f"F{i}") for i in range(50)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        names = _leak_names(leaks)
        assert "vpip-pfr-gap" in names

    def test_large_gap_is_critical_with_good_sample(self) -> None:
        hands = (
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(20)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(30)]
            + [_rec(hand_id=f"F{i}") for i in range(50)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        gap_leak = next(lk for lk in leaks if lk.name == "vpip-pfr-gap")
        assert gap_leak.severity == "critical"
        assert gap_leak.confidence == MetricLabel.INFERRED

    def test_small_gap_no_leak(self) -> None:
        # 25% VPIP, 22% PFR → gap 3pp
        hands = (
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(22)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(3)]
            + [_rec(hand_id=f"F{i}") for i in range(75)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "vpip-pfr-gap" not in _leak_names(leaks)

    def test_gap_with_tiny_sample_is_speculative(self) -> None:
        # 3 hands total — below reliable threshold
        hands = [
            _rec(hand_id="H1", vpip=True, pfr=False),
            _rec(hand_id="H2", vpip=True, pfr=False),
            _rec(hand_id="H3"),
        ]
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        gap_leaks = [lk for lk in leaks if lk.name == "vpip-pfr-gap"]
        if gap_leaks:
            # If emitted, must be speculative and capped at major
            assert gap_leaks[0].confidence == MetricLabel.SPECULATIVE
            assert gap_leaks[0].severity != "critical"

    def test_evidence_includes_hand_ids(self) -> None:
        hands = (
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(20)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(30)]
            + [_rec(hand_id=f"F{i}") for i in range(50)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        gap_leak = next(lk for lk in leaks if lk.name == "vpip-pfr-gap")
        combined = " ".join(gap_leak.evidence)
        assert "C0" in combined  # a call-not-raise hand ID


# ---------------------------------------------------------------------------
# low-3bet-frequency
# ---------------------------------------------------------------------------


class TestLow3bet:
    def test_very_low_3bet_produces_leak(self) -> None:
        # 2 3bets in 50 opportunities → 4%, below threshold
        hands = (
            [_rec(hand_id=f"T{i}", had_3bet_opportunity=True, three_bet=True, pfr=True) for i in range(2)]
            + [_rec(hand_id=f"N{i}", had_3bet_opportunity=True, three_bet=False) for i in range(48)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-3bet-frequency" in _leak_names(leaks)

    def test_adequate_3bet_no_leak(self) -> None:
        # 8 3bets in 80 opportunities → 10%
        hands = (
            [_rec(hand_id=f"T{i}", had_3bet_opportunity=True, three_bet=True, pfr=True) for i in range(8)]
            + [_rec(hand_id=f"N{i}", had_3bet_opportunity=True, three_bet=False) for i in range(72)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-3bet-frequency" not in _leak_names(leaks)

    def test_no_3bet_opportunities_no_leak(self) -> None:
        hands = [_rec(hand_id=f"H{i}") for i in range(50)]
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-3bet-frequency" not in _leak_names(leaks)

    def test_below_major_threshold_is_major(self) -> None:
        # 1/50 = 2% (below 4% major threshold)
        hands = (
            [_rec(hand_id="T0", had_3bet_opportunity=True, three_bet=True, pfr=True)]
            + [_rec(hand_id=f"N{i}", had_3bet_opportunity=True) for i in range(49)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        lk = next((l for l in leaks if l.name == "low-3bet-frequency"), None)
        assert lk is not None
        assert lk.severity == "major"


# ---------------------------------------------------------------------------
# overfold-to-3bet
# ---------------------------------------------------------------------------


class TestOverfoldTo3bet:
    def test_high_fold_rate_produces_leak(self) -> None:
        # 16/20 faced-3bets folded → 80%
        hands = (
            [_rec(hand_id=f"F{i}", faced_3bet=True, folded_to_3bet=True, pfr=True) for i in range(16)]
            + [_rec(hand_id=f"C{i}", faced_3bet=True, folded_to_3bet=False, pfr=True) for i in range(4)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "overfold-to-3bet" in _leak_names(leaks)

    def test_high_fold_rate_is_critical_with_good_sample(self) -> None:
        hands = (
            [_rec(hand_id=f"F{i}", faced_3bet=True, folded_to_3bet=True, pfr=True) for i in range(18)]
            + [_rec(hand_id=f"C{i}", faced_3bet=True, folded_to_3bet=False, pfr=True) for i in range(2)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        lk = next(l for l in leaks if l.name == "overfold-to-3bet")
        assert lk.severity == "critical"

    def test_low_fold_rate_no_leak(self) -> None:
        # 10/20 faced-3bets folded → 50%
        hands = (
            [_rec(hand_id=f"F{i}", faced_3bet=True, folded_to_3bet=True, pfr=True) for i in range(10)]
            + [_rec(hand_id=f"C{i}", faced_3bet=True, folded_to_3bet=False, pfr=True) for i in range(10)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "overfold-to-3bet" not in _leak_names(leaks)

    def test_fold_hand_ids_in_evidence(self) -> None:
        hands = (
            [_rec(hand_id=f"F{i}", faced_3bet=True, folded_to_3bet=True, pfr=True) for i in range(16)]
            + [_rec(hand_id=f"C{i}", faced_3bet=True, folded_to_3bet=False, pfr=True) for i in range(4)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        lk = next(l for l in leaks if l.name == "overfold-to-3bet")
        combined = " ".join(lk.evidence)
        assert "F0" in combined


# ---------------------------------------------------------------------------
# low-wtsd
# ---------------------------------------------------------------------------


class TestLowWtsd:
    def test_very_low_wtsd_produces_leak(self) -> None:
        # 3/30 saw flop reach showdown → 10%
        hands = (
            [_rec(hand_id=f"S{i}", saw_flop=True, reached_showdown=True) for i in range(3)]
            + [_rec(hand_id=f"N{i}", saw_flop=True, reached_showdown=False) for i in range(27)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-wtsd" in _leak_names(leaks)

    def test_adequate_wtsd_no_leak(self) -> None:
        # 8/25 → 32%
        hands = (
            [_rec(hand_id=f"S{i}", saw_flop=True, reached_showdown=True) for i in range(8)]
            + [_rec(hand_id=f"N{i}", saw_flop=True, reached_showdown=False) for i in range(17)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-wtsd" not in _leak_names(leaks)

    def test_no_flops_seen_no_wtsd_leak(self) -> None:
        hands = [_rec(hand_id=f"H{i}") for i in range(50)]
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-wtsd" not in _leak_names(leaks)


# ---------------------------------------------------------------------------
# Positional detectors
# ---------------------------------------------------------------------------


class TestPositionalLeaks:
    def test_btn_overfold_to_3bet_produces_leak(self) -> None:
        hands = (
            [
                _rec(hand_id=f"F{i}", position="BTN", faced_3bet=True, folded_to_3bet=True, pfr=True)
                for i in range(14)
            ]
            + [
                _rec(hand_id=f"C{i}", position="BTN", faced_3bet=True, folded_to_3bet=False, pfr=True)
                for i in range(6)
            ]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "overfold-to-3bet-btn" in _leak_names(leaks)

    def test_co_overfold_to_3bet_produces_leak(self) -> None:
        hands = (
            [
                _rec(hand_id=f"F{i}", position="CO", faced_3bet=True, folded_to_3bet=True, pfr=True)
                for i in range(14)
            ]
            + [
                _rec(hand_id=f"C{i}", position="CO", faced_3bet=True, folded_to_3bet=False, pfr=True)
                for i in range(6)
            ]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "overfold-to-3bet-co" in _leak_names(leaks)

    def test_btn_low_3bet_produces_leak(self) -> None:
        hands = (
            [_rec(hand_id=f"T{i}", position="BTN", had_3bet_opportunity=True, three_bet=True, pfr=True) for i in range(2)]
            + [_rec(hand_id=f"N{i}", position="BTN", had_3bet_opportunity=True) for i in range(48)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "low-3bet-btn" in _leak_names(leaks)

    def test_position_none_not_counted_in_positional(self) -> None:
        # All hands have position=None → positional dict is empty → no positional leak
        hands = (
            [
                _rec(hand_id=f"F{i}", position=None, faced_3bet=True, folded_to_3bet=True, pfr=True)
                for i in range(20)
            ]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert "overfold-to-3bet-btn" not in _leak_names(leaks)
        assert "overfold-to-3bet-co" not in _leak_names(leaks)


# ---------------------------------------------------------------------------
# Output ordering and structure
# ---------------------------------------------------------------------------


class TestOutputOrdering:
    def test_critical_leaks_come_before_major(self) -> None:
        # Build a player with both a critical gap leak and a minor low-3bet leak
        hands = (
            # 50% VPIP, 15% PFR → 35pp gap (critical)
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(15)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(35)]
            + [_rec(hand_id=f"F{i}") for i in range(50)]
            # 5% 3bet (minor)
            + [_rec(hand_id=f"T{i}", had_3bet_opportunity=True, three_bet=True, pfr=True) for i in range(4)]
            + [_rec(hand_id=f"N{i}", had_3bet_opportunity=True) for i in range(76)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        assert len(leaks) >= 2
        sev_order = {"critical": 0, "major": 1, "minor": 2}
        for a, b in zip(leaks, leaks[1:]):
            assert sev_order[a.severity] <= sev_order[b.severity]

    def test_all_leaks_have_required_fields(self) -> None:
        hands = (
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(20)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(30)]
            + [_rec(hand_id=f"F{i}") for i in range(50)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        for lk in leaks:
            assert lk.name
            assert lk.description
            assert isinstance(lk.evidence, list)
            assert lk.confidence in (MetricLabel.INFERRED, MetricLabel.SPECULATIVE)
            assert lk.severity in ("critical", "major", "minor")
            assert lk.frequency.value is not None
            assert lk.limitations
            assert lk.suggested_fix

    def test_speculative_severity_never_critical(self) -> None:
        # 2 folded-to-3bet hands out of 3 → speculative
        hands = (
            [_rec(hand_id=f"F{i}", faced_3bet=True, folded_to_3bet=True, pfr=True) for i in range(4)]
            + [_rec(hand_id="C0", faced_3bet=True, folded_to_3bet=False, pfr=True)]
        )
        st, hs = _stats(hands)
        leaks = run_leak_detection(st, hs)
        for lk in leaks:
            if lk.confidence == MetricLabel.SPECULATIVE:
                assert lk.severity != "critical"

    def test_run_without_hands_parameter(self) -> None:
        hands = (
            [_rec(hand_id=f"V{i}", vpip=True, pfr=True) for i in range(20)]
            + [_rec(hand_id=f"C{i}", vpip=True, pfr=False) for i in range(30)]
            + [_rec(hand_id=f"F{i}") for i in range(50)]
        )
        st, _ = _stats(hands)
        # Should not raise even with no hands (no hand ID evidence)
        leaks = run_leak_detection(st)
        assert any(lk.name == "vpip-pfr-gap" for lk in leaks)
