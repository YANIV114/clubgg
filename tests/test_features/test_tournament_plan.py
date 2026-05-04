"""
Unit tests for the tournament plan builder (app.features.tournament_plan).

All tests are pure Python — no DB, no HTTP.

Coverage:
- build_tournament_plan returns correct structure for all stage/format combos
- study priorities sourced correctly from leaks vs stage vs format
- reliability note reflects hand count
- stage guidance picks the right text and appends leak-driven addons
- format note injected only for relevant formats
- empty leaks handled gracefully
- unrecognised stage/format silently ignored
- top_leaks capped at 3
- urgency mapping from leak priority
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.features.labels import inferred
from app.features.leaks import (
    Category,
    Confidence,
    Frequency,
    Leak,
    Severity,
)
from app.features.player_stats import PlayerStats
from app.features.tournament_plan import (
    _SOURCE_FORMAT,
    _SOURCE_LEAK,
    _SOURCE_STAGE,
    _URGENCY_IMMEDIATE,
    _URGENCY_LONG_TERM,
    _URGENCY_THIS_WEEK,
    build_tournament_plan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PID = uuid.uuid4()


def _lm(value: float | None, n: int = 50):
    v = Decimal(str(value)) if value is not None else None
    return inferred(v, source="test", n=n)


def _null():
    return _lm(None, 0)


def _make_stats(
    *,
    hand_count: int = 200,
    vpip: float = 0.25,
    pfr: float = 0.18,
    three_bet: float = 0.07,
    fold_to_3bet: float = 0.58,
    wtsd: float = 0.32,
    wsd: float = 0.50,
    steal_pct: float | None = 0.45,
    steal_n: int = 50,
    btn_steal: float | None = 0.55,
    btn_n: int = 30,
    cbet_pct: float | None = 0.55,
    cbet_n: int = 50,
    aggression_factor: float | None = 2.0,
    af_n: int = 40,
) -> PlayerStats:
    null = _null()
    return PlayerStats(
        player_id=_PID,
        hand_count=hand_count,
        vpip=_lm(vpip, hand_count),
        pfr=_lm(pfr, hand_count),
        three_bet_pct=_lm(three_bet, 80),
        fold_to_3bet=_lm(fold_to_3bet, 40),
        wtsd=_lm(wtsd, 80),
        wsd=_lm(wsd, 25),
        steal_pct=_lm(steal_pct, steal_n),
        btn_steal_pct=_lm(btn_steal, btn_n),
        co_steal_pct=null,
        sb_steal_pct=null,
        fold_to_steal=null,
        bb_fold_to_steal=null,
        sb_fold_to_steal=null,
        bb_fold_to_btn_open=null,
        bb_fold_to_co_open=null,
        resteal_pct=null,
        positional={},
        cbet_pct=_lm(cbet_pct, cbet_n),
        fold_to_flop_bet=null,
        turn_barrel_pct=null,
        fold_to_turn_bet=null,
        delayed_cbet_pct=null,
        check_raise_pct=null,
        aggression_factor=_lm(aggression_factor, af_n),
    )


def _make_leak(
    leak_id: str = "vpip_too_loose",
    priority: int = 7,
    severity: Severity = Severity.HIGH,
    category: Category = Category.PREFLOP,
) -> Leak:
    return Leak(
        leak_id=leak_id,
        category=category,
        title=f"Test leak: {leak_id}",
        explanation="Explanation.",
        evidence="Evidence line.",
        confidence=Confidence.HIGH,
        severity=severity,
        frequency=Frequency.COMMON,
        priority=priority,
        sample_size=50,
        limitations="Limitations.",
        suggested_fix="Concrete fix action.",
    )


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


class TestBuildTournamentPlanStructure:
    def test_returns_correct_player_id(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage=None)
        assert plan.player_id == _PID

    def test_hand_count_echoed(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(hand_count=150), [], stage=None)
        assert plan.hand_count == 150

    def test_stage_echoed_when_valid(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="bubble")
        assert plan.stage == "bubble"

    def test_stage_none_when_unrecognised(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="UNKNOWN_STAGE")
        assert plan.stage is None

    def test_format_echoed_when_valid(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="PKO")
        assert plan.tournament_format == "PKO"

    def test_format_none_when_unrecognised(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="MYSTERY")
        assert plan.tournament_format is None

    def test_stack_bb_echoed(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stack_bb=Decimal("22.5"))
        assert plan.stack_bb == Decimal("22.5")

    def test_players_remaining_echoed(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], players_remaining=9)
        assert plan.players_remaining == 9

    def test_top_leaks_capped_at_three(self) -> None:
        leaks = [_make_leak(leak_id=f"leak_{i}", priority=10 - i) for i in range(6)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        assert len(plan.top_leaks) == 3

    def test_top_leaks_are_highest_priority(self) -> None:
        leaks = [_make_leak(leak_id=f"leak_{i}", priority=10 - i) for i in range(5)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        assert plan.top_leaks[0].leak_id == "leak_0"
        assert plan.top_leaks[1].leak_id == "leak_1"

    def test_no_leaks_returns_empty_top_leaks(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [])
        assert plan.top_leaks == []


# ---------------------------------------------------------------------------
# Reliability note
# ---------------------------------------------------------------------------


class TestReliabilityNote:
    def test_zero_hands(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(hand_count=0), [])
        assert "No hands" in plan.reliability_note

    def test_very_small_sample(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(hand_count=20), [])
        assert "speculative" in plan.reliability_note.lower()

    def test_small_sample(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(hand_count=100), [])
        assert "low-confidence" in plan.reliability_note.lower()

    def test_sufficient_sample_with_leaks(self) -> None:
        leaks = [_make_leak()]
        plan = build_tournament_plan(_PID, _make_stats(hand_count=300), leaks)
        assert "200" not in plan.reliability_note or "300" in plan.reliability_note

    def test_sufficient_sample_no_leaks(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(hand_count=300), [])
        assert "no statistically supported leaks" in plan.reliability_note.lower()


# ---------------------------------------------------------------------------
# Stage guidance
# ---------------------------------------------------------------------------


class TestStageGuidance:
    def test_early_stage_contains_deep_stacked(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="early")
        assert "deep-stacked" in plan.stage_guidance.lower()

    def test_bubble_stage_contains_icm(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="bubble")
        assert "icm" in plan.stage_guidance.lower()

    def test_final_table_contains_pay_jump(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="final_table")
        assert "pay" in plan.stage_guidance.lower()

    def test_itm_stage_present(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="itm")
        assert plan.stage_guidance  # non-empty

    def test_middle_stage_present(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="middle")
        assert plan.stage_guidance

    def test_none_stage_fallback(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage=None)
        assert plan.stage_guidance  # non-empty fallback

    def test_stage_case_insensitive(self) -> None:
        plan_lower = build_tournament_plan(_PID, _make_stats(), [], stage="bubble")
        plan_upper = build_tournament_plan(_PID, _make_stats(), [], stage="BUBBLE")
        assert plan_lower.stage_guidance == plan_upper.stage_guidance

    def test_bubble_addon_for_fold_to_3bet_leak(self) -> None:
        leaks = [_make_leak(leak_id="fold_to_3bet_too_high", priority=8)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks, stage="bubble")
        assert "3bet" in plan.stage_guidance.lower()


# ---------------------------------------------------------------------------
# Format note
# ---------------------------------------------------------------------------


class TestFormatNote:
    def test_pko_format_note_non_empty(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="PKO")
        assert "bounty" in plan.format_note.lower()

    def test_satellite_format_note_non_empty(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="SATELLITE")
        assert plan.format_note

    def test_spin_format_note_non_empty(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="SPIN")
        assert "push" in plan.format_note.lower() or "hyper" in plan.format_note.lower()

    def test_freezeout_format_note_empty(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="FREEZEOUT")
        assert plan.format_note == ""

    def test_cash_format_note_empty(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="CASH")
        assert plan.format_note == ""

    def test_none_format_note_empty(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format=None)
        assert plan.format_note == ""


# ---------------------------------------------------------------------------
# Study priorities
# ---------------------------------------------------------------------------


class TestStudyPriorities:
    def test_leak_driven_priorities_have_detected_leak_source(self) -> None:
        leaks = [_make_leak(leak_id="vpip_too_loose", priority=8)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        leak_priorities = [p for p in plan.study_priorities if p.source == _SOURCE_LEAK]
        assert len(leak_priorities) == 1
        assert leak_priorities[0].leak_id == "vpip_too_loose"

    def test_leak_priority_action_uses_suggested_fix(self) -> None:
        leaks = [_make_leak()]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        lp = next(p for p in plan.study_priorities if p.source == _SOURCE_LEAK)
        assert "Concrete fix action." in lp.action

    def test_up_to_three_leak_driven_priorities(self) -> None:
        leaks = [_make_leak(leak_id=f"l{i}", priority=9 - i) for i in range(5)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        leak_ps = [p for p in plan.study_priorities if p.source == _SOURCE_LEAK]
        assert len(leak_ps) == 3

    def test_pko_format_adds_format_priority(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="PKO")
        fmt_ps = [p for p in plan.study_priorities if p.source == _SOURCE_FORMAT]
        assert len(fmt_ps) == 1
        assert "bounty" in fmt_ps[0].action.lower()

    def test_satellite_format_adds_format_priority(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="SATELLITE")
        fmt_ps = [p for p in plan.study_priorities if p.source == _SOURCE_FORMAT]
        assert len(fmt_ps) == 1

    def test_no_format_priority_for_freezeout(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], tournament_format="FREEZEOUT")
        fmt_ps = [p for p in plan.study_priorities if p.source == _SOURCE_FORMAT]
        assert len(fmt_ps) == 0

    def test_bubble_adds_stage_priority(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="bubble")
        stage_ps = [p for p in plan.study_priorities if p.source == _SOURCE_STAGE]
        assert len(stage_ps) >= 1

    def test_ranks_are_sequential_from_one(self) -> None:
        leaks = [_make_leak(leak_id=f"l{i}", priority=9 - i) for i in range(3)]
        plan = build_tournament_plan(
            _PID, _make_stats(), leaks, stage="bubble", tournament_format="PKO"
        )
        ranks = [p.rank for p in plan.study_priorities]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_no_leaks_no_format_still_returns_stage_priority(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="bubble")
        assert len(plan.study_priorities) >= 1


# ---------------------------------------------------------------------------
# Urgency mapping
# ---------------------------------------------------------------------------


class TestUrgency:
    def test_high_priority_leak_maps_to_immediate(self) -> None:
        leaks = [_make_leak(priority=8)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        lp = next(p for p in plan.study_priorities if p.source == _SOURCE_LEAK)
        assert lp.urgency == _URGENCY_IMMEDIATE

    def test_medium_priority_leak_maps_to_this_week(self) -> None:
        leaks = [_make_leak(priority=5)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        lp = next(p for p in plan.study_priorities if p.source == _SOURCE_LEAK)
        assert lp.urgency == _URGENCY_THIS_WEEK

    def test_low_priority_leak_maps_to_long_term(self) -> None:
        leaks = [_make_leak(priority=2)]
        plan = build_tournament_plan(_PID, _make_stats(), leaks)
        lp = next(p for p in plan.study_priorities if p.source == _SOURCE_LEAK)
        assert lp.urgency == _URGENCY_LONG_TERM


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_leaks_no_crash(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(), [], stage="bubble")
        assert plan is not None
        assert plan.top_leaks == []

    def test_zero_hands_no_crash(self) -> None:
        plan = build_tournament_plan(_PID, _make_stats(hand_count=0), [])
        assert plan is not None

    def test_all_none_context_no_crash(self) -> None:
        plan = build_tournament_plan(
            _PID,
            _make_stats(),
            [],
            tournament_format=None,
            stage=None,
            stack_bb=None,
            players_remaining=None,
        )
        assert plan is not None
        assert plan.format_note == ""

    def test_final_table_with_low_steal_rate_adds_stage_priority(self) -> None:
        stats = _make_stats(steal_pct=0.25, steal_n=20, btn_steal=0.25, btn_n=15)
        plan = build_tournament_plan(_PID, stats, [], stage="final_table")
        stage_ps = [p for p in plan.study_priorities if p.source == _SOURCE_STAGE]
        assert len(stage_ps) >= 1
        assert any("steal" in p.action.lower() for p in stage_ps)
