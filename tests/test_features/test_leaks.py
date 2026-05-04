"""
Unit tests for the leak detection engine (app.features.leaks).

Tests use synthetic PlayerStats built from scratch — no DB required.
Each rule method is tested independently, plus overall detector behaviour.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.features.labels import inferred
from app.features.leaks import (
    _VPIP_N,
    Category,
    Confidence,
    Frequency,
    Leak,
    LeakDetector,
    Severity,
    _compute_priority,
    _confidence,
    _pct,
    analysis_note,
)
from app.features.player_stats import PlayerStats, PositionalStats

# ── Helpers ───────────────────────────────────────────────────────────────────


def _lm(value: float | None, n: int):
    """Create an inferred LabeledMetric with a Decimal (or None) value."""
    v = Decimal(str(value)) if value is not None else None
    return inferred(value=v, source="test", n=n)


def _pos_stats(
    vpip: float | None = 0.25,
    n: int = 50,
    position: str = "BB",
    pfr: float | None = None,
    steal_pct: float | None = None,
    fold_to_steal: float | None = None,
    steal_n: int = 0,
) -> PositionalStats:
    lm = _lm(vpip, n)
    null = _lm(None, 0)
    return PositionalStats(
        position=position,
        n_hands=n,
        vpip=lm,
        pfr=_lm(pfr, n) if pfr is not None else null,
        three_bet_pct=null,
        fold_to_3bet=null,
        steal_pct=_lm(steal_pct, steal_n),
        fold_to_steal=_lm(fold_to_steal, steal_n),
    )


def _make_stats(
    *,
    vpip: float | None = 0.25,
    vpip_n: int = 100,
    pfr: float | None = 0.18,
    pfr_n: int = 100,
    three_bet: float | None = 0.07,
    three_bet_n: int = 100,
    fold_to_3bet: float | None = 0.58,
    fold_to_3bet_n: int = 50,
    wtsd: float | None = 0.32,
    wtsd_n: int = 80,
    wsd: float | None = 0.50,
    wsd_n: int = 25,
    # steal stats
    steal_pct: float | None = None,
    steal_pct_n: int = 0,
    btn_steal_pct: float | None = None,
    btn_steal_pct_n: int = 0,
    co_steal_pct: float | None = None,
    co_steal_pct_n: int = 0,
    sb_steal_pct: float | None = None,
    sb_steal_pct_n: int = 0,
    # defend stats
    fold_to_steal: float | None = None,
    fold_to_steal_n: int = 0,
    bb_fold_to_steal: float | None = None,
    bb_fold_to_steal_n: int = 0,
    sb_fold_to_steal: float | None = None,
    sb_fold_to_steal_n: int = 0,
    bb_fold_to_btn_open: float | None = None,
    bb_fold_to_btn_open_n: int = 0,
    bb_fold_to_co_open: float | None = None,
    bb_fold_to_co_open_n: int = 0,
    resteal_pct: float | None = None,
    resteal_pct_n: int = 0,
    positional: dict | None = None,
    # postflop stats (default to None/0 so existing tests don't trigger new rules)
    cbet_pct: float | None = None,
    cbet_pct_n: int = 0,
    fold_to_flop_bet: float | None = None,
    fold_to_flop_bet_n: int = 0,
    turn_barrel_pct: float | None = None,
    turn_barrel_pct_n: int = 0,
    fold_to_turn_bet: float | None = None,
    fold_to_turn_bet_n: int = 0,
    delayed_cbet_pct: float | None = None,
    delayed_cbet_pct_n: int = 0,
    check_raise_pct: float | None = None,
    check_raise_pct_n: int = 0,
    aggression_factor: float | None = None,
    aggression_factor_n: int = 0,
) -> PlayerStats:
    """Build a synthetic PlayerStats with configurable per-field values."""
    if positional is None:
        positional = {}
    return PlayerStats(
        player_id=uuid.uuid4(),
        hand_count=vpip_n,
        vpip=_lm(vpip, vpip_n),
        pfr=_lm(pfr, pfr_n),
        three_bet_pct=_lm(three_bet, three_bet_n),
        fold_to_3bet=_lm(fold_to_3bet, fold_to_3bet_n),
        wtsd=_lm(wtsd, wtsd_n),
        wsd=_lm(wsd, wsd_n),
        steal_pct=_lm(steal_pct, steal_pct_n),
        btn_steal_pct=_lm(btn_steal_pct, btn_steal_pct_n),
        co_steal_pct=_lm(co_steal_pct, co_steal_pct_n),
        sb_steal_pct=_lm(sb_steal_pct, sb_steal_pct_n),
        fold_to_steal=_lm(fold_to_steal, fold_to_steal_n),
        bb_fold_to_steal=_lm(bb_fold_to_steal, bb_fold_to_steal_n),
        sb_fold_to_steal=_lm(sb_fold_to_steal, sb_fold_to_steal_n),
        bb_fold_to_btn_open=_lm(bb_fold_to_btn_open, bb_fold_to_btn_open_n),
        bb_fold_to_co_open=_lm(bb_fold_to_co_open, bb_fold_to_co_open_n),
        resteal_pct=_lm(resteal_pct, resteal_pct_n),
        positional=positional,
        cbet_pct=_lm(cbet_pct, cbet_pct_n),
        fold_to_flop_bet=_lm(fold_to_flop_bet, fold_to_flop_bet_n),
        turn_barrel_pct=_lm(turn_barrel_pct, turn_barrel_pct_n),
        fold_to_turn_bet=_lm(fold_to_turn_bet, fold_to_turn_bet_n),
        delayed_cbet_pct=_lm(delayed_cbet_pct, delayed_cbet_pct_n),
        check_raise_pct=_lm(check_raise_pct, check_raise_pct_n),
        aggression_factor=_lm(aggression_factor, aggression_factor_n),
    )


# ── Pure helper tests ─────────────────────────────────────────────────────────


class TestConfidenceHelper:
    def test_high_confidence(self) -> None:
        assert _confidence(150, _VPIP_N) is Confidence.HIGH

    def test_medium_confidence(self) -> None:
        assert _confidence(50, _VPIP_N) is Confidence.MEDIUM

    def test_low_confidence(self) -> None:
        assert _confidence(15, _VPIP_N) is Confidence.LOW

    def test_insufficient_none(self) -> None:
        assert _confidence(None, _VPIP_N) is Confidence.INSUFFICIENT

    def test_insufficient_below_low(self) -> None:
        assert _confidence(5, _VPIP_N) is Confidence.INSUFFICIENT

    def test_boundary_exactly_high(self) -> None:
        assert _confidence(_VPIP_N["high"], _VPIP_N) is Confidence.HIGH

    def test_boundary_one_below_medium(self) -> None:
        assert _confidence(_VPIP_N["medium"] - 1, _VPIP_N) is Confidence.LOW


class TestPctHelper:
    def test_normal(self) -> None:
        assert _pct(Decimal("0.35")) == "35.0%"

    def test_none(self) -> None:
        assert _pct(None) == "N/A"

    def test_zero(self) -> None:
        assert _pct(Decimal("0")) == "0.0%"

    def test_one(self) -> None:
        assert _pct(Decimal("1.0")) == "100.0%"


class TestComputePriority:
    def test_high_high_is_ten(self) -> None:
        assert _compute_priority(Severity.HIGH, Confidence.HIGH) == 10

    def test_high_medium_above_medium_high(self) -> None:
        p_hm = _compute_priority(Severity.HIGH, Confidence.MEDIUM)
        p_mh = _compute_priority(Severity.MEDIUM, Confidence.HIGH)
        # HIGH severity with MEDIUM confidence > MEDIUM severity with HIGH confidence
        assert p_hm >= p_mh

    def test_low_low_is_small(self) -> None:
        assert _compute_priority(Severity.LOW, Confidence.LOW) <= 3

    def test_all_scores_in_range(self) -> None:
        for sev in Severity:
            for conf in [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]:
                p = _compute_priority(sev, conf)
                assert 1 <= p <= 10, f"{sev}+{conf} → {p}"


# ── Per-rule tests ────────────────────────────────────────────────────────────


class TestVpipTooLoose:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._vpip_too_loose(stats)

    def test_fires_medium_severity_above_38(self) -> None:
        leak = self._rule(_make_stats(vpip=0.45, vpip_n=100))
        assert leak is not None
        assert leak.leak_id == "vpip_too_loose"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_50(self) -> None:
        leak = self._rule(_make_stats(vpip=0.55, vpip_n=100))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_normal_vpip(self) -> None:
        assert self._rule(_make_stats(vpip=0.27)) is None

    def test_no_leak_at_boundary_38(self) -> None:
        assert self._rule(_make_stats(vpip=0.38)) is None

    def test_insufficient_data_returns_none(self) -> None:
        assert self._rule(_make_stats(vpip=0.60, vpip_n=5)) is None

    def test_low_confidence_at_small_n(self) -> None:
        leak = self._rule(_make_stats(vpip=0.50, vpip_n=15))
        assert leak is not None
        assert leak.confidence == Confidence.LOW

    def test_category_is_preflop(self) -> None:
        leak = self._rule(_make_stats(vpip=0.45, vpip_n=100))
        assert leak is not None
        assert leak.category == Category.PREFLOP

    def test_frequency_is_per_hand(self) -> None:
        leak = self._rule(_make_stats(vpip=0.45, vpip_n=100))
        assert leak is not None
        assert leak.frequency == Frequency.PER_HAND


class TestVpipTooTight:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._vpip_too_tight(stats)

    def test_fires_at_15_pct(self) -> None:
        leak = self._rule(_make_stats(vpip=0.15, vpip_n=100))
        assert leak is not None
        assert leak.leak_id == "vpip_too_tight"

    def test_fires_high_severity_below_12(self) -> None:
        leak = self._rule(_make_stats(vpip=0.10, vpip_n=100))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_fires_low_severity_between_12_and_18(self) -> None:
        leak = self._rule(_make_stats(vpip=0.15, vpip_n=100))
        assert leak is not None
        assert leak.severity == Severity.LOW

    def test_no_leak_at_normal_vpip(self) -> None:
        assert self._rule(_make_stats(vpip=0.25)) is None

    def test_no_leak_at_boundary_18(self) -> None:
        assert self._rule(_make_stats(vpip=0.18)) is None

    def test_insufficient_data_returns_none(self) -> None:
        assert self._rule(_make_stats(vpip=0.10, vpip_n=3)) is None


class TestPfrTooPassive:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._pfr_too_passive(stats)

    def test_fires_on_low_abs_pfr(self) -> None:
        leak = self._rule(_make_stats(pfr=0.10, pfr_n=100))
        assert leak is not None
        assert leak.leak_id == "pfr_too_passive"

    def test_fires_on_low_ratio(self) -> None:
        # VPIP=0.40, PFR=0.16 → ratio=0.40 < 0.55
        stats = _make_stats(vpip=0.40, vpip_n=100, pfr=0.16, pfr_n=100)
        leak = self._rule(stats)
        assert leak is not None

    def test_high_severity_when_both_conditions_met(self) -> None:
        # Low abs PFR AND low ratio
        stats = _make_stats(vpip=0.35, vpip_n=100, pfr=0.10, pfr_n=100)
        leak = self._rule(stats)
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_medium_severity_only_one_condition(self) -> None:
        # Only ratio is low
        stats = _make_stats(vpip=0.40, vpip_n=100, pfr=0.18, pfr_n=100)
        leak = self._rule(stats)
        assert leak is not None
        assert leak.severity == Severity.MEDIUM

    def test_no_leak_for_normal_pfr(self) -> None:
        stats = _make_stats(vpip=0.26, pfr=0.19, pfr_n=100)
        assert self._rule(stats) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(pfr=0.08, pfr_n=5)) is None


class TestFoldTo3betTooHigh:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._fold_to_3bet_too_high(stats)

    def test_fires_above_68_pct(self) -> None:
        leak = self._rule(_make_stats(fold_to_3bet=0.75, fold_to_3bet_n=50))
        assert leak is not None
        assert leak.leak_id == "fold_to_3bet_too_high"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_80(self) -> None:
        leak = self._rule(_make_stats(fold_to_3bet=0.85, fold_to_3bet_n=50))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_normal_fold(self) -> None:
        assert self._rule(_make_stats(fold_to_3bet=0.60)) is None

    def test_no_leak_at_boundary_68(self) -> None:
        assert self._rule(_make_stats(fold_to_3bet=0.68)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(fold_to_3bet=0.90, fold_to_3bet_n=3)) is None

    def test_frequency_is_common(self) -> None:
        leak = self._rule(_make_stats(fold_to_3bet=0.80, fold_to_3bet_n=50))
        assert leak is not None
        assert leak.frequency == Frequency.COMMON


class TestThreeBetTooLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._three_bet_too_low(stats)

    def test_fires_below_4_pct(self) -> None:
        leak = self._rule(_make_stats(three_bet=0.02, three_bet_n=100))
        assert leak is not None
        assert leak.leak_id == "three_bet_too_low"
        assert leak.severity == Severity.LOW

    def test_no_leak_at_normal(self) -> None:
        assert self._rule(_make_stats(three_bet=0.07)) is None

    def test_no_leak_at_boundary_4(self) -> None:
        assert self._rule(_make_stats(three_bet=0.04)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(three_bet=0.01, three_bet_n=5)) is None


class TestThreeBetTooHigh:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._three_bet_too_high(stats)

    def test_fires_above_14_pct(self) -> None:
        leak = self._rule(_make_stats(three_bet=0.18, three_bet_n=100))
        assert leak is not None
        assert leak.leak_id == "three_bet_too_high"
        assert leak.severity == Severity.MEDIUM

    def test_no_leak_at_normal(self) -> None:
        assert self._rule(_make_stats(three_bet=0.07)) is None

    def test_no_leak_at_boundary_14(self) -> None:
        assert self._rule(_make_stats(three_bet=0.14)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(three_bet=0.20, three_bet_n=5)) is None


class TestWtsdTooHigh:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._wtsd_too_high(stats)

    def test_fires_medium_severity_above_40(self) -> None:
        leak = self._rule(_make_stats(wtsd=0.45, wtsd_n=60))
        assert leak is not None
        assert leak.leak_id == "wtsd_too_high"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_50(self) -> None:
        leak = self._rule(_make_stats(wtsd=0.55, wtsd_n=60))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_normal(self) -> None:
        assert self._rule(_make_stats(wtsd=0.32)) is None

    def test_no_leak_at_boundary_40(self) -> None:
        assert self._rule(_make_stats(wtsd=0.40)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(wtsd=0.55, wtsd_n=5)) is None

    def test_category_is_postflop(self) -> None:
        leak = self._rule(_make_stats(wtsd=0.45, wtsd_n=60))
        assert leak is not None
        assert leak.category == Category.POSTFLOP


class TestWtsdTooLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._wtsd_too_low(stats)

    def test_fires_below_22_pct(self) -> None:
        leak = self._rule(_make_stats(wtsd=0.18, wtsd_n=60))
        assert leak is not None
        assert leak.leak_id == "wtsd_too_low"

    def test_no_leak_at_normal(self) -> None:
        assert self._rule(_make_stats(wtsd=0.30)) is None

    def test_no_leak_at_boundary_22(self) -> None:
        assert self._rule(_make_stats(wtsd=0.22)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(wtsd=0.10, wtsd_n=3)) is None


class TestWsdSuspiciouslyLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._wsd_suspiciously_low(stats)

    def test_fires_below_42_pct(self) -> None:
        leak = self._rule(_make_stats(wsd=0.35, wsd_n=20))
        assert leak is not None
        assert leak.leak_id == "wsd_suspiciously_low"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_below_30(self) -> None:
        leak = self._rule(_make_stats(wsd=0.25, wsd_n=20))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_normal(self) -> None:
        assert self._rule(_make_stats(wsd=0.50)) is None

    def test_no_leak_at_boundary_42(self) -> None:
        assert self._rule(_make_stats(wsd=0.42)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(wsd=0.20, wsd_n=2)) is None

    def test_suppressed_when_wtsd_very_low(self) -> None:
        # wtsd < 0.12 → sample is unreliable, suppress wsd leak
        stats = _make_stats(wtsd=0.08, wtsd_n=60, wsd=0.20, wsd_n=5)
        # wsd_n=5 is already insufficient but check wtsd guard separately
        # Use wsd_n=10 so confidence would otherwise pass
        stats2 = _make_stats(wtsd=0.08, wtsd_n=60, wsd=0.20, wsd_n=10)
        assert self._rule(stats2) is None


class TestBbDefendTooTight:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._bb_defend_too_tight(stats)

    def test_fires_when_bb_vpip_low(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.25, n=100)}
        leak = self._rule(_make_stats(positional=pos))
        assert leak is not None
        assert leak.leak_id == "bb_defend_too_tight"

    def test_no_leak_at_normal_bb_vpip(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.45, n=100)}
        assert self._rule(_make_stats(positional=pos)) is None

    def test_no_leak_when_no_bb_position(self) -> None:
        # positional has BTN but not BB
        pos = {"BTN": _pos_stats(vpip=0.50, n=100)}
        assert self._rule(_make_stats(positional=pos)) is None

    def test_insufficient_data(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.20, n=5)}
        assert self._rule(_make_stats(positional=pos)) is None

    def test_frequency_is_situational(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.25, n=100)}
        leak = self._rule(_make_stats(positional=pos))
        assert leak is not None
        assert leak.frequency == Frequency.SITUATIONAL


class TestBbDefendTooLoose:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._bb_defend_too_loose(stats)

    def test_fires_when_bb_vpip_very_high(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.75, n=100)}
        leak = self._rule(_make_stats(positional=pos))
        assert leak is not None
        assert leak.leak_id == "bb_defend_too_loose"

    def test_no_leak_at_normal_bb_vpip(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.45, n=100)}
        assert self._rule(_make_stats(positional=pos)) is None

    def test_no_leak_when_no_bb_position(self) -> None:
        assert self._rule(_make_stats(positional={})) is None

    def test_insufficient_data(self) -> None:
        pos = {"BB": _pos_stats(vpip=0.80, n=5)}
        assert self._rule(_make_stats(positional=pos)) is None


# ── Steal / defend rule tests ─────────────────────────────────────────────────


class TestBtnStealTooLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._btn_steal_too_low(stats)

    def test_fires_medium_severity_between_35_and_50(self) -> None:
        leak = self._rule(_make_stats(btn_steal_pct=0.40, btn_steal_pct_n=40))
        assert leak is not None
        assert leak.leak_id == "btn_steal_too_low"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_below_35(self) -> None:
        leak = self._rule(_make_stats(btn_steal_pct=0.25, btn_steal_pct_n=40))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_50_pct(self) -> None:
        assert self._rule(_make_stats(btn_steal_pct=0.50, btn_steal_pct_n=40)) is None

    def test_no_leak_above_50(self) -> None:
        assert self._rule(_make_stats(btn_steal_pct=0.65, btn_steal_pct_n=40)) is None

    def test_insufficient_data_returns_none(self) -> None:
        assert self._rule(_make_stats(btn_steal_pct=0.20, btn_steal_pct_n=3)) is None

    def test_category_is_preflop(self) -> None:
        leak = self._rule(_make_stats(btn_steal_pct=0.40, btn_steal_pct_n=40))
        assert leak is not None
        assert leak.category == Category.PREFLOP

    def test_frequency_is_common(self) -> None:
        leak = self._rule(_make_stats(btn_steal_pct=0.40, btn_steal_pct_n=40))
        assert leak is not None
        assert leak.frequency == Frequency.COMMON


class TestCoStealTooLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._co_steal_too_low(stats)

    def test_fires_below_28(self) -> None:
        leak = self._rule(_make_stats(co_steal_pct=0.20, co_steal_pct_n=40))
        assert leak is not None
        assert leak.leak_id == "co_steal_too_low"
        assert leak.severity == Severity.MEDIUM

    def test_no_leak_at_28(self) -> None:
        assert self._rule(_make_stats(co_steal_pct=0.28, co_steal_pct_n=40)) is None

    def test_no_leak_above_28(self) -> None:
        assert self._rule(_make_stats(co_steal_pct=0.35, co_steal_pct_n=40)) is None

    def test_insufficient_data_returns_none(self) -> None:
        assert self._rule(_make_stats(co_steal_pct=0.10, co_steal_pct_n=2)) is None


class TestSbStealTooLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._sb_steal_too_low(stats)

    def test_fires_below_35(self) -> None:
        leak = self._rule(_make_stats(sb_steal_pct=0.25, sb_steal_pct_n=40))
        assert leak is not None
        assert leak.leak_id == "sb_steal_too_low"
        assert leak.severity == Severity.MEDIUM

    def test_no_leak_at_35(self) -> None:
        assert self._rule(_make_stats(sb_steal_pct=0.35, sb_steal_pct_n=40)) is None

    def test_frequency_is_situational(self) -> None:
        leak = self._rule(_make_stats(sb_steal_pct=0.20, sb_steal_pct_n=40))
        assert leak is not None
        assert leak.frequency == Frequency.SITUATIONAL

    def test_insufficient_data_returns_none(self) -> None:
        assert self._rule(_make_stats(sb_steal_pct=0.10, sb_steal_pct_n=3)) is None


class TestBbOverfoldingVsSteals:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._bb_overfolding_vs_steals(stats)

    def test_fires_medium_severity_between_68_and_80(self) -> None:
        leak = self._rule(_make_stats(bb_fold_to_steal=0.75, bb_fold_to_steal_n=40))
        assert leak is not None
        assert leak.leak_id == "bb_overfolding_vs_steals"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_80(self) -> None:
        leak = self._rule(_make_stats(bb_fold_to_steal=0.85, bb_fold_to_steal_n=40))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_68(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_steal=0.68, bb_fold_to_steal_n=40)) is None

    def test_no_leak_below_68(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_steal=0.55, bb_fold_to_steal_n=40)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_steal=0.90, bb_fold_to_steal_n=3)) is None

    def test_frequency_is_common(self) -> None:
        leak = self._rule(_make_stats(bb_fold_to_steal=0.75, bb_fold_to_steal_n=40))
        assert leak is not None
        assert leak.frequency == Frequency.COMMON


class TestBbOverfoldingVsBtn:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._bb_overfolding_vs_btn(stats)

    def test_fires_medium_severity_between_72_and_82(self) -> None:
        leak = self._rule(_make_stats(bb_fold_to_btn_open=0.76, bb_fold_to_btn_open_n=40))
        assert leak is not None
        assert leak.leak_id == "bb_overfolding_vs_btn"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_82(self) -> None:
        leak = self._rule(_make_stats(bb_fold_to_btn_open=0.85, bb_fold_to_btn_open_n=40))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_leak_at_72(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_btn_open=0.72, bb_fold_to_btn_open_n=40)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_btn_open=0.90, bb_fold_to_btn_open_n=3)) is None


class TestSbOverfoldingVsSteals:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._sb_overfolding_vs_steals(stats)

    def test_fires_above_72(self) -> None:
        leak = self._rule(_make_stats(sb_fold_to_steal=0.78, sb_fold_to_steal_n=40))
        assert leak is not None
        assert leak.leak_id == "sb_overfolding_vs_steals"
        assert leak.severity == Severity.MEDIUM

    def test_no_leak_at_72(self) -> None:
        assert self._rule(_make_stats(sb_fold_to_steal=0.72, sb_fold_to_steal_n=40)) is None

    def test_frequency_is_situational(self) -> None:
        leak = self._rule(_make_stats(sb_fold_to_steal=0.80, sb_fold_to_steal_n=40))
        assert leak is not None
        assert leak.frequency == Frequency.SITUATIONAL

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(sb_fold_to_steal=0.85, sb_fold_to_steal_n=3)) is None


class TestBbDefendingTooLoose:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._bb_defending_too_loose(stats)

    def test_fires_below_38(self) -> None:
        leak = self._rule(_make_stats(bb_fold_to_steal=0.25, bb_fold_to_steal_n=40))
        assert leak is not None
        assert leak.leak_id == "bb_defending_too_loose"
        assert leak.severity == Severity.LOW

    def test_no_leak_at_38(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_steal=0.38, bb_fold_to_steal_n=40)) is None

    def test_no_leak_above_38(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_steal=0.55, bb_fold_to_steal_n=40)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(bb_fold_to_steal=0.20, bb_fold_to_steal_n=3)) is None


class TestRestealTooLow:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._resteal_too_low(stats)

    def test_fires_below_8_pct(self) -> None:
        leak = self._rule(_make_stats(resteal_pct=0.04, resteal_pct_n=30))
        assert leak is not None
        assert leak.leak_id == "resteal_too_low"
        assert leak.severity == Severity.MEDIUM

    def test_no_leak_at_8_pct(self) -> None:
        assert self._rule(_make_stats(resteal_pct=0.08, resteal_pct_n=30)) is None

    def test_no_leak_above_8_pct(self) -> None:
        assert self._rule(_make_stats(resteal_pct=0.12, resteal_pct_n=30)) is None

    def test_insufficient_data(self) -> None:
        assert self._rule(_make_stats(resteal_pct=0.02, resteal_pct_n=2)) is None

    def test_frequency_is_common(self) -> None:
        leak = self._rule(_make_stats(resteal_pct=0.04, resteal_pct_n=30))
        assert leak is not None
        assert leak.frequency == Frequency.COMMON


class TestLatePositionPassive:
    detector = LeakDetector()

    def _rule(self, stats: PlayerStats) -> Leak | None:
        return self.detector._late_position_passive(stats)

    def _make_with_pos(self, btn_pfr: float, btn_n: int, co_pfr: float, co_n: int) -> PlayerStats:
        pos = {
            "BTN": _pos_stats(vpip=0.50, n=btn_n, position="BTN", pfr=btn_pfr),
            "CO": _pos_stats(vpip=0.40, n=co_n, position="CO", pfr=co_pfr),
        }
        return _make_stats(positional=pos)

    def test_fires_when_btn_pfr_equals_co_pfr(self) -> None:
        leak = self._rule(self._make_with_pos(btn_pfr=0.30, btn_n=50, co_pfr=0.30, co_n=50))
        assert leak is not None
        assert leak.leak_id == "late_position_passive"

    def test_fires_when_btn_pfr_lower_than_co_pfr(self) -> None:
        leak = self._rule(self._make_with_pos(btn_pfr=0.25, btn_n=50, co_pfr=0.30, co_n=50))
        assert leak is not None

    def test_fires_when_btn_pfr_not_4pct_above_co(self) -> None:
        # BTN PFR = CO PFR + 3% → within 4% margin → leak fires
        leak = self._rule(self._make_with_pos(btn_pfr=0.33, btn_n=50, co_pfr=0.30, co_n=50))
        assert leak is not None

    def test_no_leak_when_btn_pfr_5pct_above_co(self) -> None:
        leak = self._rule(self._make_with_pos(btn_pfr=0.36, btn_n=50, co_pfr=0.30, co_n=50))
        assert leak is None

    def test_no_leak_when_missing_btn_position(self) -> None:
        pos = {"CO": _pos_stats(vpip=0.40, n=50, position="CO", pfr=0.30)}
        assert self._rule(_make_stats(positional=pos)) is None

    def test_no_leak_when_missing_co_position(self) -> None:
        pos = {"BTN": _pos_stats(vpip=0.50, n=50, position="BTN", pfr=0.30)}
        assert self._rule(_make_stats(positional=pos)) is None

    def test_no_leak_when_no_positional_data(self) -> None:
        assert self._rule(_make_stats(positional={})) is None

    def test_insufficient_data_btn(self) -> None:
        leak = self._rule(self._make_with_pos(btn_pfr=0.25, btn_n=5, co_pfr=0.30, co_n=50))
        assert leak is None

    def test_insufficient_data_co(self) -> None:
        leak = self._rule(self._make_with_pos(btn_pfr=0.25, btn_n=50, co_pfr=0.30, co_n=4))
        assert leak is None

    def test_category_and_severity(self) -> None:
        leak = self._rule(self._make_with_pos(btn_pfr=0.28, btn_n=50, co_pfr=0.30, co_n=50))
        assert leak is not None
        assert leak.category == Category.PREFLOP
        assert leak.severity == Severity.MEDIUM


# ── Detector-level tests ──────────────────────────────────────────────────────


class TestDetectOrdering:
    detector = LeakDetector()

    def test_leaks_sorted_by_priority_descending(self) -> None:
        # Stats with multiple leaks
        stats = _make_stats(
            vpip=0.50,
            vpip_n=100,  # loose → MEDIUM/HIGH
            fold_to_3bet=0.85,
            fold_to_3bet_n=50,  # very high → HIGH
            wtsd=0.55,
            wtsd_n=80,  # very high → HIGH
        )
        leaks = self.detector.detect(stats)
        assert len(leaks) > 1
        priorities = [l.priority for l in leaks]
        assert priorities == sorted(priorities, reverse=True)

    def test_all_leaks_have_required_fields(self) -> None:
        stats = _make_stats(vpip=0.50, vpip_n=100, fold_to_3bet=0.85, fold_to_3bet_n=50)
        leaks = self.detector.detect(stats)
        for leak in leaks:
            assert leak.leak_id
            assert leak.title
            assert leak.explanation
            assert leak.evidence
            assert leak.limitations
            assert leak.suggested_fix
            assert 1 <= leak.priority <= 10

    def test_no_leaks_for_normal_profile(self) -> None:
        """A solid winning player profile produces no leaks."""
        stats = _make_stats(
            vpip=0.26,
            vpip_n=200,
            pfr=0.19,
            pfr_n=200,
            three_bet=0.07,
            three_bet_n=200,
            fold_to_3bet=0.58,
            fold_to_3bet_n=80,
            wtsd=0.32,
            wtsd_n=150,
            wsd=0.52,
            wsd_n=50,
        )
        leaks = self.detector.detect(stats)
        assert leaks == []

    def test_insufficient_data_produces_no_leaks(self) -> None:
        """With tiny sample size, no leaks should be emitted."""
        stats = _make_stats(
            vpip=0.70,
            vpip_n=3,
            pfr=0.05,
            pfr_n=3,
            fold_to_3bet=0.95,
            fold_to_3bet_n=2,
            wtsd=0.80,
            wtsd_n=2,
            wsd=0.10,
            wsd_n=1,
        )
        leaks = self.detector.detect(stats)
        assert leaks == []

    def test_high_priority_leak_is_first(self) -> None:
        """Fold-to-3bet HIGH severity + HIGH confidence should beat VPIP MEDIUM."""
        stats = _make_stats(
            vpip=0.42,
            vpip_n=100,
            fold_to_3bet=0.88,
            fold_to_3bet_n=80,
        )
        leaks = self.detector.detect(stats)
        assert leaks[0].leak_id == "fold_to_3bet_too_high"


# ── Analysis note tests ────────────────────────────────────────────────────────


class TestAnalysisNote:
    def test_zero_hands(self) -> None:
        note = analysis_note(0, 0)
        assert "No hands" in note

    def test_tiny_sample(self) -> None:
        note = analysis_note(5, 0)
        assert "5" in note
        assert "insufficient" in note.lower() or "directional" in note.lower()

    def test_moderate_sample(self) -> None:
        note = analysis_note(50, 2)
        assert "50" in note

    def test_large_sample_no_leaks(self) -> None:
        note = analysis_note(500, 0)
        assert "No" in note or "no" in note

    def test_large_sample_with_leaks(self) -> None:
        note = analysis_note(500, 3)
        assert "3" in note
