"""Tests for player statistics computation."""
import uuid
from decimal import Decimal

import pytest

from app.features.labels import MetricLabel
from app.features.player_stats import (
    HandRecord,
    PlayerStats,
    PositionalStats,
    compute_player_stats,
    hand_record_from_actions,
)
from app.models.hand import ActionType


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_PLAYER_ID = uuid.uuid4()


def _rec(
    *,
    position: str | None = "BTN",
    stack_bb: str = "25.00",
    vpip: bool = False,
    pfr: bool = False,
    had_3bet_opportunity: bool = False,
    three_bet: bool = False,
    faced_3bet: bool = False,
    folded_to_3bet: bool = False,
    saw_flop: bool = False,
    reached_showdown: bool = False,
    won_at_showdown: bool = False,
    hand_id: str = "H1",
) -> HandRecord:
    """Minimal HandRecord factory for tests."""
    return HandRecord(
        hand_external_id=hand_id,
        position=position,
        stack_bb=Decimal(stack_bb),
        effective_stack_bb=Decimal(stack_bb),
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


def _action(
    hand_player_id: str,
    action_type: str,
    order: int,
) -> dict:
    return {
        "hand_player_id": hand_player_id,
        "action_type": action_type,
        "action_order": order,
    }


# ---------------------------------------------------------------------------
# _rate / labeling
# ---------------------------------------------------------------------------


class TestRateLabeling:
    def test_all_stats_labeled_inferred(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec(vpip=True)])
        assert stats.vpip.label == MetricLabel.INFERRED
        assert stats.pfr.label == MetricLabel.INFERRED
        assert stats.three_bet_pct.label == MetricLabel.INFERRED
        assert stats.fold_to_3bet.label == MetricLabel.INFERRED
        assert stats.wtsd.label == MetricLabel.INFERRED
        assert stats.wsd.label == MetricLabel.INFERRED

    def test_zero_denominator_returns_none_value(self) -> None:
        # No hands at all → every rate has n=0, value=None
        stats = compute_player_stats(_PLAYER_ID, [])
        assert stats.vpip.value is None
        assert stats.vpip.n == 0
        assert stats.three_bet_pct.value is None

    def test_confidence_note_when_n_lt_5(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec(vpip=True)] * 3)
        assert "very low" in stats.vpip.confidence_note

    def test_confidence_note_when_n_lt_20(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec(vpip=True)] * 10)
        assert "low" in stats.vpip.confidence_note

    def test_no_confidence_note_at_20(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec(vpip=True)] * 20)
        assert stats.vpip.confidence_note == ""

    def test_is_reliable_false_below_20(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec(vpip=True)] * 10)
        assert stats.vpip.is_reliable() is False

    def test_is_reliable_true_at_20(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec(vpip=True)] * 20)
        assert stats.vpip.is_reliable() is True

    def test_source_contains_counts(self) -> None:
        hands = [_rec(vpip=True)] * 3
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert "3" in stats.vpip.source


# ---------------------------------------------------------------------------
# compute_player_stats — aggregate rates
# ---------------------------------------------------------------------------


class TestComputePlayerStats:
    def test_empty_hands(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [])
        assert stats.hand_count == 0
        assert stats.vpip.value is None
        assert stats.positional == {}

    def test_hand_count(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [_rec()] * 7)
        assert stats.hand_count == 7

    def test_player_id_preserved(self) -> None:
        pid = uuid.uuid4()
        stats = compute_player_stats(pid, [])
        assert stats.player_id == pid

    def test_vpip_rate(self) -> None:
        # 3 vpip out of 5 = 0.6000
        hands = [_rec(vpip=True)] * 3 + [_rec(vpip=False)] * 2
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.vpip.value == Decimal("0.6000")
        assert stats.vpip.n == 5

    def test_pfr_rate(self) -> None:
        hands = [_rec(pfr=True)] * 2 + [_rec(pfr=False)] * 8
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.pfr.value == Decimal("0.2000")
        assert stats.pfr.n == 10

    def test_three_bet_pct_denominator_is_opportunities(self) -> None:
        # 2 three-bets out of 5 opportunities (out of 10 total hands)
        three_bet_hands = [_rec(had_3bet_opportunity=True, three_bet=True)] * 2
        opps_no_3bet = [_rec(had_3bet_opportunity=True, three_bet=False)] * 3
        no_opps = [_rec(had_3bet_opportunity=False)] * 5
        stats = compute_player_stats(_PLAYER_ID, three_bet_hands + opps_no_3bet + no_opps)
        assert stats.three_bet_pct.n == 5  # denominator = opportunities, not total
        assert stats.three_bet_pct.value == Decimal("0.4000")

    def test_fold_to_3bet_denominator_is_faced_3bet(self) -> None:
        # 3 folds out of 4 times facing a 3bet
        folded = [_rec(faced_3bet=True, folded_to_3bet=True)] * 3
        called = [_rec(faced_3bet=True, folded_to_3bet=False)] * 1
        no_exposure = [_rec(faced_3bet=False)] * 10
        stats = compute_player_stats(_PLAYER_ID, folded + called + no_exposure)
        assert stats.fold_to_3bet.n == 4
        assert stats.fold_to_3bet.value == Decimal("0.7500")

    def test_wtsd_denominator_is_saw_flop(self) -> None:
        saw_and_sd = [_rec(saw_flop=True, reached_showdown=True)] * 4
        saw_no_sd = [_rec(saw_flop=True, reached_showdown=False)] * 6
        no_flop = [_rec(saw_flop=False)] * 5
        stats = compute_player_stats(_PLAYER_ID, saw_and_sd + saw_no_sd + no_flop)
        assert stats.wtsd.n == 10  # saw_flop count
        assert stats.wtsd.value == Decimal("0.4000")

    def test_wsd_denominator_is_reached_showdown(self) -> None:
        won = [_rec(saw_flop=True, reached_showdown=True, won_at_showdown=True)] * 3
        lost = [_rec(saw_flop=True, reached_showdown=True, won_at_showdown=False)] * 7
        stats = compute_player_stats(_PLAYER_ID, won + lost)
        assert stats.wsd.n == 10
        assert stats.wsd.value == Decimal("0.3000")

    def test_zero_3bet_opportunities(self) -> None:
        # All hands lack 3bet opportunity → three_bet_pct is None
        hands = [_rec(had_3bet_opportunity=False)] * 10
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.three_bet_pct.value is None
        assert stats.three_bet_pct.n == 0

    def test_zero_showdowns(self) -> None:
        hands = [_rec(saw_flop=True, reached_showdown=False)] * 10
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.wsd.value is None
        assert stats.wsd.n == 0

    def test_rounding_four_decimal_places(self) -> None:
        # 1/3 = 0.3333...
        hands = [_rec(vpip=True)] * 1 + [_rec(vpip=False)] * 2
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.vpip.value == Decimal("0.3333")

    def test_full_vpip_rate_is_one(self) -> None:
        hands = [_rec(vpip=True)] * 5
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.vpip.value == Decimal("1.0000")

    def test_zero_vpip_rate_is_zero(self) -> None:
        hands = [_rec(vpip=False)] * 5
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.vpip.value == Decimal("0.0000")


# ---------------------------------------------------------------------------
# Positional breakdown
# ---------------------------------------------------------------------------


class TestPositionalBreakdown:
    def test_groups_by_position(self) -> None:
        hands = (
            [_rec(position="BTN", vpip=True)] * 3
            + [_rec(position="BB", vpip=False)] * 5
        )
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert "BTN" in stats.positional
        assert "BB" in stats.positional

    def test_position_none_excluded(self) -> None:
        hands = [_rec(position=None)] * 5
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.positional == {}

    def test_mixed_none_and_known_positions(self) -> None:
        hands = [_rec(position="BTN")] * 3 + [_rec(position=None)] * 5
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert set(stats.positional.keys()) == {"BTN"}
        assert stats.positional["BTN"].n_hands == 3

    def test_positional_vpip_computed_per_position(self) -> None:
        btn_hands = [_rec(position="BTN", vpip=True)] * 4 + [_rec(position="BTN", vpip=False)] * 1
        bb_hands = [_rec(position="BB", vpip=True)] * 1 + [_rec(position="BB", vpip=False)] * 4
        stats = compute_player_stats(_PLAYER_ID, btn_hands + bb_hands)
        assert stats.positional["BTN"].vpip.value == Decimal("0.8000")
        assert stats.positional["BB"].vpip.value == Decimal("0.2000")

    def test_positional_stat_n_reflects_position_count(self) -> None:
        hands = [_rec(position="CO")] * 7
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.positional["CO"].n_hands == 7
        assert stats.positional["CO"].vpip.n == 7

    def test_positional_all_stats_labeled_inferred(self) -> None:
        hands = [_rec(position="BTN")] * 5
        stats = compute_player_stats(_PLAYER_ID, hands)
        ps = stats.positional["BTN"]
        assert ps.vpip.label == MetricLabel.INFERRED
        assert ps.pfr.label == MetricLabel.INFERRED
        assert ps.three_bet_pct.label == MetricLabel.INFERRED
        assert ps.fold_to_3bet.label == MetricLabel.INFERRED

    def test_positional_zero_3bet_opp(self) -> None:
        hands = [_rec(position="UTG", had_3bet_opportunity=False)] * 5
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.positional["UTG"].three_bet_pct.value is None

    def test_multiple_positions(self) -> None:
        hands = [_rec(position=pos) for pos in ["BTN", "CO", "BB", "SB", "UTG"]]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert set(stats.positional.keys()) == {"BTN", "CO", "BB", "SB", "UTG"}


# ---------------------------------------------------------------------------
# hand_record_from_actions
# ---------------------------------------------------------------------------


class TestHandRecordFromActions:
    """Tests for the factory that computes HandRecord flags from raw actions."""

    _HERO = "hero-hp-id"
    _VILLAIN = "villain-hp-id"

    def _hero_action(self, action_type: str, order: int) -> dict:
        return _action(self._HERO, action_type, order)

    def _villain_action(self, action_type: str, order: int) -> dict:
        return _action(self._VILLAIN, action_type, order)

    def _make_record(
        self,
        preflop_actions: list[dict],
        saw_flop: bool = False,
        reached_showdown: bool = False,
        won_at_showdown: bool = False,
    ) -> HandRecord:
        return hand_record_from_actions(
            hand_external_id="H1",
            player_position="BTN",
            player_stack_bb=Decimal("25"),
            player_effective_stack_bb=Decimal("20"),
            this_hand_player_id=self._HERO,
            all_preflop_actions=preflop_actions,
            saw_flop=saw_flop,
            reached_showdown=reached_showdown,
            won_at_showdown=won_at_showdown,
        )

    # -- VPIP ----------------------------------------------------------------

    def test_vpip_call(self) -> None:
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.CALL, 2),
        ]
        rec = self._make_record(actions)
        assert rec.vpip is True

    def test_vpip_raise(self) -> None:
        actions = [self._hero_action(ActionType.RAISE, 1)]
        rec = self._make_record(actions)
        assert rec.vpip is True

    def test_vpip_all_in(self) -> None:
        actions = [self._hero_action(ActionType.ALL_IN, 1)]
        rec = self._make_record(actions)
        assert rec.vpip is True

    def test_vpip_false_fold_only(self) -> None:
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.FOLD, 2),
        ]
        rec = self._make_record(actions)
        assert rec.vpip is False

    def test_vpip_false_bb_check_no_raise(self) -> None:
        # BB posts, hero checks (no raise) — VPIP = False
        actions = [
            self._hero_action(ActionType.POST_BB, 1),
            self._hero_action(ActionType.CHECK, 2),
        ]
        rec = self._make_record(actions)
        assert rec.vpip is False

    def test_vpip_false_post_only(self) -> None:
        actions = [self._hero_action(ActionType.POST_SB, 1)]
        rec = self._make_record(actions)
        assert rec.vpip is False

    # -- PFR -----------------------------------------------------------------

    def test_pfr_raise(self) -> None:
        actions = [self._hero_action(ActionType.RAISE, 1)]
        rec = self._make_record(actions)
        assert rec.pfr is True

    def test_pfr_false_call_only(self) -> None:
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.CALL, 2),
        ]
        rec = self._make_record(actions)
        assert rec.pfr is False

    def test_pfr_false_fold(self) -> None:
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.FOLD, 2),
        ]
        rec = self._make_record(actions)
        assert rec.pfr is False

    # -- 3bet opportunity ----------------------------------------------------

    def test_had_3bet_opportunity_true(self) -> None:
        # Villain raises before hero acts
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.CALL, 2),
        ]
        rec = self._make_record(actions)
        assert rec.had_3bet_opportunity is True

    def test_had_3bet_opportunity_false_hero_opens(self) -> None:
        # Hero is first to act — no prior raise
        actions = [self._hero_action(ActionType.RAISE, 1)]
        rec = self._make_record(actions)
        assert rec.had_3bet_opportunity is False

    def test_had_3bet_opportunity_false_no_actions(self) -> None:
        rec = self._make_record([])
        assert rec.had_3bet_opportunity is False

    def test_had_3bet_opportunity_false_villain_raises_after_hero(self) -> None:
        # Hero acts first, villain raises after — that's hero being 3bet, not having opp
        actions = [
            self._hero_action(ActionType.RAISE, 1),
            self._villain_action(ActionType.RAISE, 2),
            self._hero_action(ActionType.FOLD, 3),
        ]
        rec = self._make_record(actions)
        assert rec.had_3bet_opportunity is False  # hero opened, didn't face open

    # -- Three-bet -----------------------------------------------------------

    def test_three_bet_true(self) -> None:
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.RAISE, 2),
        ]
        rec = self._make_record(actions)
        assert rec.three_bet is True

    def test_three_bet_false_called_open(self) -> None:
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.CALL, 2),
        ]
        rec = self._make_record(actions)
        assert rec.three_bet is False

    def test_three_bet_false_no_opportunity(self) -> None:
        actions = [self._hero_action(ActionType.RAISE, 1)]
        rec = self._make_record(actions)
        assert rec.three_bet is False

    # -- Faced 3bet / folded to 3bet -----------------------------------------

    def test_faced_3bet_true(self) -> None:
        # Hero opens, villain re-raises
        actions = [
            self._hero_action(ActionType.RAISE, 1),
            self._villain_action(ActionType.RAISE, 2),
            self._hero_action(ActionType.FOLD, 3),
        ]
        rec = self._make_record(actions)
        assert rec.faced_3bet is True

    def test_faced_3bet_false_not_open_raiser(self) -> None:
        # Hero calls an open — does not face a 3bet (faces a 2bet)
        actions = [
            self._villain_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.CALL, 2),
        ]
        rec = self._make_record(actions)
        assert rec.faced_3bet is False

    def test_folded_to_3bet_true(self) -> None:
        actions = [
            self._hero_action(ActionType.RAISE, 1),
            self._villain_action(ActionType.RAISE, 2),
            self._hero_action(ActionType.FOLD, 3),
        ]
        rec = self._make_record(actions)
        assert rec.folded_to_3bet is True

    def test_folded_to_3bet_false_called(self) -> None:
        actions = [
            self._hero_action(ActionType.RAISE, 1),
            self._villain_action(ActionType.RAISE, 2),
            self._hero_action(ActionType.CALL, 3),
        ]
        rec = self._make_record(actions)
        assert rec.folded_to_3bet is False

    def test_folded_to_3bet_false_four_bet(self) -> None:
        actions = [
            self._hero_action(ActionType.RAISE, 1),
            self._villain_action(ActionType.RAISE, 2),
            self._hero_action(ActionType.RAISE, 3),  # 4bet
        ]
        rec = self._make_record(actions)
        assert rec.folded_to_3bet is False

    def test_folded_to_3bet_false_when_no_3bet(self) -> None:
        actions = [self._hero_action(ActionType.RAISE, 1)]
        rec = self._make_record(actions)
        assert rec.faced_3bet is False
        assert rec.folded_to_3bet is False

    # -- Passthrough fields --------------------------------------------------

    def test_saw_flop_passed_through(self) -> None:
        rec = self._make_record([], saw_flop=True)
        assert rec.saw_flop is True

    def test_reached_showdown_passed_through(self) -> None:
        rec = self._make_record([], reached_showdown=True)
        assert rec.reached_showdown is True

    def test_won_at_showdown_passed_through(self) -> None:
        rec = self._make_record([], won_at_showdown=True)
        assert rec.won_at_showdown is True

    def test_position_preserved(self) -> None:
        rec = hand_record_from_actions(
            hand_external_id="H1",
            player_position="CO",
            player_stack_bb=Decimal("30"),
            player_effective_stack_bb=Decimal("25"),
            this_hand_player_id=self._HERO,
            all_preflop_actions=[],
            saw_flop=False,
            reached_showdown=False,
            won_at_showdown=False,
        )
        assert rec.position == "CO"

    def test_empty_actions(self) -> None:
        rec = self._make_record([])
        assert rec.vpip is False
        assert rec.pfr is False
        assert rec.had_3bet_opportunity is False
        assert rec.three_bet is False
        assert rec.faced_3bet is False
        assert rec.folded_to_3bet is False

    def test_action_order_respected(self) -> None:
        # Hero raises at order=5 (early), villain raises at order=10 (after hero)
        # hero_opens, then villain 3bets — hero faced_3bet=True
        actions = [
            self._hero_action(ActionType.RAISE, 5),
            self._villain_action(ActionType.RAISE, 10),
            self._hero_action(ActionType.FOLD, 15),
        ]
        rec = self._make_record(actions)
        assert rec.pfr is True
        assert rec.faced_3bet is True
        assert rec.folded_to_3bet is True

    def test_faced_3bet_and_fold_with_interleaved_action_order(self) -> None:
        # Hero raised at order 1, hero folded at order 2, villain raises at order 3.
        # Even though hero folded before the villain's raise, the faced_3bet flag fires
        # because faced_3bet checks only whether *another player raised after hero's first raise*.
        # folded_to_3bet fires because hero's fold (order 2) is after hero's first raise (order 1).
        # This is a known limitation documented in hand_record_from_actions docstring.
        actions = [
            self._hero_action(ActionType.RAISE, 1),
            self._hero_action(ActionType.FOLD, 2),
            self._villain_action(ActionType.RAISE, 3),
        ]
        rec = self._make_record(actions)
        assert rec.pfr is True
        assert rec.faced_3bet is True
        assert rec.folded_to_3bet is True
