"""
Tournament-aware leak detection: ante baselines and the short-stack filter.

Tournament hands with antes give the blinds better pot odds, so correct
blind defence is wider than in cash games. Hands below MIN_EFFECTIVE_BB are
push/fold spots and are excluded from stat-based leak detection.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.features.leaks import (
    CASH_BASELINES,
    MIN_EFFECTIVE_BB,
    MTT_ANTE_BASELINES,
    LeakDetector,
    analyze_leaks,
)
from app.features.player_stats import HandRecord
from tests.test_features.test_leaks import _make_stats


def _ids(leaks) -> set[str]:
    return {lk.leak_id for lk in leaks}


def _record(
    eff_bb: float | None = 50,
    *,
    has_ante: bool = True,
    vpip: bool = False,
    pfr: bool = False,
) -> HandRecord:
    bb = Decimal(str(eff_bb)) if eff_bb is not None else None
    return HandRecord(
        hand_external_id=f"h{uuid.uuid4().hex[:8]}",
        position="CO",
        stack_bb=bb,
        effective_stack_bb=bb,
        vpip=vpip,
        pfr=pfr,
        had_3bet_opportunity=False,
        three_bet=False,
        faced_3bet=False,
        folded_to_3bet=False,
        saw_flop=False,
        reached_showdown=False,
        won_at_showdown=False,
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
        has_ante=has_ante,
    )


# ── Baselines ─────────────────────────────────────────────────────────────────


class TestAnteBaselines:
    def test_default_detector_uses_cash_baselines(self) -> None:
        assert LeakDetector().baselines is CASH_BASELINES

    def test_wide_bb_defence_is_a_leak_in_cash_only(self) -> None:
        # Folding 34% of BBs to steals: too loose for cash, normal with antes.
        stats = _make_stats(bb_fold_to_steal=0.34, bb_fold_to_steal_n=86)
        assert "bb_defending_too_loose" in _ids(LeakDetector().detect(stats))
        assert "bb_defending_too_loose" not in _ids(
            LeakDetector(MTT_ANTE_BASELINES).detect(stats)
        )

    def test_bb_overfolding_flagged_earlier_with_antes(self) -> None:
        # Folding 60%: within cash range, but too tight given ante pot odds.
        stats = _make_stats(bb_fold_to_steal=0.60, bb_fold_to_steal_n=86)
        assert "bb_overfolding_vs_steals" not in _ids(LeakDetector().detect(stats))
        assert "bb_overfolding_vs_steals" in _ids(
            LeakDetector(MTT_ANTE_BASELINES).detect(stats)
        )

    def test_bb_vs_btn_overfolding_flagged_earlier_with_antes(self) -> None:
        stats = _make_stats(bb_fold_to_btn_open=0.58, bb_fold_to_btn_open_n=40)
        assert "bb_overfolding_vs_btn" not in _ids(LeakDetector().detect(stats))
        assert "bb_overfolding_vs_btn" in _ids(LeakDetector(MTT_ANTE_BASELINES).detect(stats))

    def test_sb_folding_more_is_normal_with_antes(self) -> None:
        # SB with antes plays mostly 3-bet-or-fold, so folds more often.
        stats = _make_stats(sb_fold_to_steal=0.76, sb_fold_to_steal_n=40)
        assert "sb_overfolding_vs_steals" in _ids(LeakDetector().detect(stats))
        assert "sb_overfolding_vs_steals" not in _ids(
            LeakDetector(MTT_ANTE_BASELINES).detect(stats)
        )

    def test_evidence_quotes_the_active_baseline(self) -> None:
        stats = _make_stats(bb_fold_to_steal=0.60, bb_fold_to_steal_n=86)
        leak = next(
            lk
            for lk in LeakDetector(MTT_ANTE_BASELINES).detect(stats)
            if lk.leak_id == "bb_overfolding_vs_steals"
        )
        assert MTT_ANTE_BASELINES.bb_fold_to_steal_range in leak.evidence


# ── analyze_leaks ─────────────────────────────────────────────────────────────


class TestAnalyzeLeaks:
    def test_short_stack_hands_excluded(self) -> None:
        records = [_record(50)] * 30 + [_record(12)] * 10
        result = analyze_leaks(uuid.uuid4(), records)
        assert result.total_hands == 40
        assert result.short_stack_excluded == 10
        assert result.stats.hand_count == 30

    def test_threshold_is_inclusive(self) -> None:
        records = [_record(float(MIN_EFFECTIVE_BB))]
        assert analyze_leaks(uuid.uuid4(), records).short_stack_excluded == 0

    def test_unknown_stack_kept(self) -> None:
        # Unknown depth can't be classified as push/fold, so it stays in.
        result = analyze_leaks(uuid.uuid4(), [_record(None)])
        assert result.short_stack_excluded == 0
        assert result.stats.hand_count == 1

    def test_ante_hands_select_tournament_baselines(self) -> None:
        records = [_record(50, has_ante=True)] * 8 + [_record(50, has_ante=False)] * 2
        assert analyze_leaks(uuid.uuid4(), records).baselines is MTT_ANTE_BASELINES

    def test_no_ante_selects_cash_baselines(self) -> None:
        records = [_record(50, has_ante=False)] * 10
        assert analyze_leaks(uuid.uuid4(), records).baselines is CASH_BASELINES

    def test_empty_records(self) -> None:
        result = analyze_leaks(uuid.uuid4(), [])
        assert result.total_hands == 0
        assert result.leaks == []
        assert result.baselines is CASH_BASELINES

    def test_note_mentions_excluded_short_stack_hands(self) -> None:
        records = [_record(50)] * 120 + [_record(8)] * 15
        result = analyze_leaks(uuid.uuid4(), records)
        assert "15" in result.note
        assert "20bb" in result.note
