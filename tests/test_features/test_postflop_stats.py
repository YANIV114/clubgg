"""
Tests for postflop stat computation and leak detection.

Coverage:
- _compute_postflop_flags: c-bet, faced-flop-bet, turn barrel, faced-turn-bet,
  delayed c-bet, check-raise, and aggression-factor components.
- compute_player_stats: postflop aggregate fields propagate correctly.
- LeakDetector: all five new postflop rules fire/silence correctly.

Design principles applied:
- No DB: all tests use pure HandRecord / action-dict inputs.
- Realistic action trees with concrete action_order integers.
- Each scenario is a minimal hand that exercises exactly one flag.
- False-positive protection: verify each rule does NOT fire on in-range stats.
- Small-sample protection: verify INSUFFICIENT silence for n below low threshold.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.features.labels import MetricLabel, inferred
from app.features.leaks import (
    _AF_N,
    _CBET_N,
    _FOLD_FLOP_N,
    _FOLD_TURN_N,
    LeakDetector,
    Severity,
)
from app.features.player_stats import (
    HandRecord,
    PlayerStats,
    _compute_postflop_flags,
    compute_player_stats,
    hand_record_from_actions,
)

# ---------------------------------------------------------------------------
# Shared IDs and constants
# ---------------------------------------------------------------------------

_HERO = "hero-hp-id"
_OPP = "opp-hp-id"
_STACK = Decimal("100")
_PLAYER_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Action-dict builders
# ---------------------------------------------------------------------------


def _pf(hp_id: str, action_type: str, order: int, position: str | None = None) -> dict:
    d: dict = {"hand_player_id": hp_id, "action_type": action_type, "action_order": order}
    if position is not None:
        d["position"] = position
    return d


def _posta(hp_id: str, action_type: str, order: int, street: str) -> dict:
    return {
        "hand_player_id": hp_id,
        "action_type": action_type,
        "action_order": order,
        "street": street,
    }


# Helpers for specific streets
def _flop(hp_id: str, action_type: str, order: int) -> dict:
    return _posta(hp_id, action_type, order, "FLOP")


def _turn(hp_id: str, action_type: str, order: int) -> dict:
    return _posta(hp_id, action_type, order, "TURN")


def _river(hp_id: str, action_type: str, order: int) -> dict:
    return _posta(hp_id, action_type, order, "RIVER")


# ---------------------------------------------------------------------------
# Minimal preflop action sequences
# ---------------------------------------------------------------------------

# Hero opens preflop (PFR=True) and everyone else calls/folds
_HERO_OPEN_PF = [
    _pf("sb", "POST_SB", 1, "SB"),
    _pf("bb", "POST_BB", 2, "BB"),
    _pf(_HERO, "RAISE", 3, "BTN"),
    _pf("sb", "FOLD", 4, "SB"),
    _pf("bb", "CALL", 5, "BB"),
]

# Hero calls preflop (PFR=False, VPIP=True)
_HERO_CALL_PF = [
    _pf("sb", "POST_SB", 1, "SB"),
    _pf("bb", "POST_BB", 2, "BB"),
    _pf(_OPP, "RAISE", 3, "BTN"),
    _pf(_HERO, "CALL", 4, "BB"),
]


# ---------------------------------------------------------------------------
# _compute_postflop_flags: unit tests
# ---------------------------------------------------------------------------


class TestCbet:
    def test_cbet_fires_when_hero_first_to_bet_flop(self) -> None:
        postflop = [
            _flop("bb", "CHECK", 10),
            _flop(_HERO, "BET", 11),
            _flop("bb", "FOLD", 12),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet_opportunity"] is True
        assert flags["cbet"] is True

    def test_cbet_false_when_hero_checks_flop(self) -> None:
        postflop = [
            _flop("bb", "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet_opportunity"] is True
        assert flags["cbet"] is False

    def test_cbet_false_when_opponent_bets_first(self) -> None:
        # Opponent donk-bets before hero acts
        postflop = [
            _flop("bb", "BET", 10),
            _flop(_HERO, "CALL", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet"] is False

    def test_cbet_opportunity_false_when_not_pfr(self) -> None:
        postflop = [
            _flop(_HERO, "CHECK", 10),
            _flop(_OPP, "BET", 11),
            _flop(_HERO, "FOLD", 12),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet_opportunity"] is False
        assert flags["cbet"] is False

    def test_no_postflop_actions_returns_all_false(self) -> None:
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=[]
        )
        assert flags["cbet_opportunity"] is False
        assert flags["cbet"] is False

    def test_saw_flop_false_returns_all_false(self) -> None:
        postflop = [_flop(_HERO, "BET", 10)]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=False, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet_opportunity"] is False
        assert flags["cbet"] is False

    def test_raise_on_flop_counts_as_cbet(self) -> None:
        # Hero bets the flop with a RAISE action (valid BET type)
        postflop = [
            _flop(_HERO, "RAISE", 10),
            _flop(_OPP, "FOLD", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet"] is True


class TestFacedFlopBet:
    def test_faced_flop_bet_and_folded(self) -> None:
        postflop = [
            _flop(_OPP, "BET", 10),
            _flop(_HERO, "FOLD", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_flop_bet"] is True
        assert flags["folded_to_flop_bet"] is True

    def test_faced_flop_bet_and_called(self) -> None:
        postflop = [
            _flop(_OPP, "BET", 10),
            _flop(_HERO, "CALL", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_flop_bet"] is True
        assert flags["folded_to_flop_bet"] is False

    def test_faced_flop_bet_and_raised(self) -> None:
        postflop = [
            _flop(_OPP, "BET", 10),
            _flop(_HERO, "RAISE", 11),
            _flop(_OPP, "FOLD", 12),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_flop_bet"] is True
        assert flags["folded_to_flop_bet"] is False

    def test_no_bet_on_flop_not_facing_bet(self) -> None:
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_flop_bet"] is False
        assert flags["folded_to_flop_bet"] is False

    def test_hero_bets_first_not_facing_flop_bet(self) -> None:
        # Hero bets, opponent folds — hero did NOT face a bet
        postflop = [
            _flop(_HERO, "BET", 10),
            _flop(_OPP, "FOLD", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_flop_bet"] is False


class TestTurnBarrel:
    def test_turn_barrel_fires(self) -> None:
        # Hero c-bets flop, then bets turn
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "BET", 11),
            _flop(_OPP, "CALL", 12),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "BET", 21),
            _turn(_OPP, "FOLD", 22),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["cbet"] is True
        assert flags["turn_barrel_opportunity"] is True
        assert flags["turn_barreled"] is True

    def test_turn_barrel_opportunity_but_checks_turn(self) -> None:
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "BET", 11),
            _flop(_OPP, "CALL", 12),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "CHECK", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["turn_barrel_opportunity"] is True
        assert flags["turn_barreled"] is False

    def test_no_turn_barrel_opportunity_when_no_cbet(self) -> None:
        # Hero checked the flop — no c-bet → no barrel opportunity
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
            _turn(_OPP, "BET", 20),
            _turn(_HERO, "CALL", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["turn_barrel_opportunity"] is False

    def test_no_turn_barrel_when_opponent_leads_turn(self) -> None:
        # Hero c-bets flop, but opponent donk-bets the turn
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "BET", 11),
            _flop(_OPP, "CALL", 12),
            _turn(_OPP, "BET", 20),  # opponent leads
            _turn(_HERO, "CALL", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["turn_barrel_opportunity"] is True
        assert flags["turn_barreled"] is False


class TestFacedTurnBet:
    def test_faced_turn_bet_and_folded(self) -> None:
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
            _turn(_OPP, "BET", 20),
            _turn(_HERO, "FOLD", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_turn_bet"] is True
        assert flags["folded_to_turn_bet"] is True

    def test_faced_turn_bet_and_called(self) -> None:
        postflop = [
            _turn(_OPP, "BET", 20),
            _turn(_HERO, "CALL", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_turn_bet"] is True
        assert flags["folded_to_turn_bet"] is False

    def test_no_turn_actions_no_faced_turn_bet(self) -> None:
        postflop = [
            _flop(_OPP, "BET", 10),
            _flop(_HERO, "CALL", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["faced_turn_bet"] is False


class TestDelayedCbet:
    def test_delayed_cbet_fires(self) -> None:
        # PF raiser checks flop (check-check), then bets turn
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "BET", 21),
            _turn(_OPP, "FOLD", 22),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["delayed_cbet_opportunity"] is True
        assert flags["delayed_cbet"] is True

    def test_delayed_cbet_opportunity_but_checks_turn(self) -> None:
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "CHECK", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["delayed_cbet_opportunity"] is True
        assert flags["delayed_cbet"] is False

    def test_no_delayed_cbet_when_flop_had_bet(self) -> None:
        # Flop was not check-check (someone bet) → not a delayed c-bet spot
        postflop = [
            _flop(_OPP, "BET", 10),
            _flop(_HERO, "CALL", 11),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "BET", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["delayed_cbet_opportunity"] is False
        assert flags["delayed_cbet"] is False

    def test_no_delayed_cbet_when_not_pfr(self) -> None:
        postflop = [
            _flop(_OPP, "CHECK", 10),
            _flop(_HERO, "CHECK", 11),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "BET", 21),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["delayed_cbet_opportunity"] is False


class TestCheckRaise:
    def test_check_raise_on_flop(self) -> None:
        postflop = [
            _flop(_HERO, "CHECK", 10),
            _flop(_OPP, "BET", 11),
            _flop(_HERO, "RAISE", 12),
            _flop(_OPP, "FOLD", 13),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["check_raise_opportunity"] is True
        assert flags["check_raised"] is True

    def test_check_call_is_opportunity_but_not_check_raise(self) -> None:
        postflop = [
            _flop(_HERO, "CHECK", 10),
            _flop(_OPP, "BET", 11),
            _flop(_HERO, "CALL", 12),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["check_raise_opportunity"] is True
        assert flags["check_raised"] is False

    def test_check_raise_on_turn(self) -> None:
        postflop = [
            _flop(_HERO, "BET", 10),  # hero bets flop (c-bet)
            _flop(_OPP, "CALL", 11),
            _turn(_HERO, "CHECK", 20),
            _turn(_OPP, "BET", 21),
            _turn(_HERO, "RAISE", 22),
            _turn(_OPP, "FOLD", 23),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["check_raise_opportunity"] is True
        assert flags["check_raised"] is True

    def test_no_check_raise_when_hero_bets_first(self) -> None:
        postflop = [
            _flop(_HERO, "BET", 10),
            _flop(_OPP, "FOLD", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["check_raise_opportunity"] is False
        assert flags["check_raised"] is False

    def test_no_check_raise_when_no_opponent_bet_after_check(self) -> None:
        # Hero and opponent both check down
        postflop = [
            _flop(_HERO, "CHECK", 10),
            _flop(_OPP, "CHECK", 11),
        ]
        flags = _compute_postflop_flags(
            pfr=False, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["check_raise_opportunity"] is False


class TestAggressionFactor:
    def test_af_components_counted_across_streets(self) -> None:
        postflop = [
            _flop(_HERO, "BET", 10),  # bet (aggression)
            _flop(_OPP, "CALL", 11),
            _turn(_HERO, "BET", 20),  # bet (aggression)
            _turn(_OPP, "CALL", 21),
            _river(_HERO, "CHECK", 30),
            _river(_OPP, "BET", 31),
            _river(_HERO, "CALL", 32),  # call (passive)
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["postflop_bets_raises"] == 2
        assert flags["postflop_calls"] == 1

    def test_raises_count_as_aggression(self) -> None:
        postflop = [
            _flop(_OPP, "BET", 10),
            _flop(_HERO, "RAISE", 11),  # raise (aggression)
            _flop(_OPP, "CALL", 12),
            _turn(_OPP, "CHECK", 20),
            _turn(_HERO, "BET", 21),  # bet (aggression)
        ]
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=postflop
        )
        assert flags["postflop_bets_raises"] == 2
        assert flags["postflop_calls"] == 0

    def test_no_postflop_action_returns_zeros(self) -> None:
        flags = _compute_postflop_flags(
            pfr=True, saw_flop=True, hero_id=_HERO, all_postflop_actions=[]
        )
        assert flags["postflop_bets_raises"] == 0
        assert flags["postflop_calls"] == 0


# ---------------------------------------------------------------------------
# compute_player_stats: postflop aggregation
# ---------------------------------------------------------------------------


def _make_rec(
    *,
    pfr: bool = False,
    saw_flop: bool = False,
    cbet_opportunity: bool = False,
    cbet: bool = False,
    faced_flop_bet: bool = False,
    folded_to_flop_bet: bool = False,
    turn_barrel_opportunity: bool = False,
    turn_barreled: bool = False,
    faced_turn_bet: bool = False,
    folded_to_turn_bet: bool = False,
    delayed_cbet_opportunity: bool = False,
    delayed_cbet: bool = False,
    check_raise_opportunity: bool = False,
    check_raised: bool = False,
    postflop_bets_raises: int = 0,
    postflop_calls: int = 0,
    hand_id: str = "H1",
) -> HandRecord:
    """Minimal HandRecord for postflop stat testing."""
    return HandRecord(
        hand_external_id=hand_id,
        position="BTN",
        stack_bb=Decimal("50"),
        effective_stack_bb=Decimal("50"),
        vpip=pfr,
        pfr=pfr,
        had_3bet_opportunity=False,
        three_bet=False,
        faced_3bet=False,
        folded_to_3bet=False,
        saw_flop=saw_flop,
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
        cbet_opportunity=cbet_opportunity,
        cbet=cbet,
        faced_flop_bet=faced_flop_bet,
        folded_to_flop_bet=folded_to_flop_bet,
        turn_barrel_opportunity=turn_barrel_opportunity,
        turn_barreled=turn_barreled,
        faced_turn_bet=faced_turn_bet,
        folded_to_turn_bet=folded_to_turn_bet,
        delayed_cbet_opportunity=delayed_cbet_opportunity,
        delayed_cbet=delayed_cbet,
        check_raise_opportunity=check_raise_opportunity,
        check_raised=check_raised,
        postflop_bets_raises=postflop_bets_raises,
        postflop_calls=postflop_calls,
    )


class TestComputePlayerStatsPostflop:
    def test_cbet_pct_computed_correctly(self) -> None:
        hands = [
            _make_rec(cbet_opportunity=True, cbet=True),
            _make_rec(cbet_opportunity=True, cbet=True),
            _make_rec(cbet_opportunity=True, cbet=False),
        ]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.cbet_pct.value == Decimal("0.6667")
        assert stats.cbet_pct.n == 3

    def test_cbet_pct_none_when_no_opportunities(self) -> None:
        hands = [_make_rec(pfr=False)]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.cbet_pct.value is None
        assert stats.cbet_pct.n == 0

    def test_fold_to_flop_bet_computed_correctly(self) -> None:
        hands = [
            _make_rec(faced_flop_bet=True, folded_to_flop_bet=True),
            _make_rec(faced_flop_bet=True, folded_to_flop_bet=True),
            _make_rec(faced_flop_bet=True, folded_to_flop_bet=False),
            _make_rec(faced_flop_bet=True, folded_to_flop_bet=False),
        ]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.fold_to_flop_bet.value == Decimal("0.5000")
        assert stats.fold_to_flop_bet.n == 4

    def test_turn_barrel_pct_computed_correctly(self) -> None:
        hands = [
            _make_rec(turn_barrel_opportunity=True, turn_barreled=True),
            _make_rec(turn_barrel_opportunity=True, turn_barreled=False),
        ]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.turn_barrel_pct.value == Decimal("0.5000")
        assert stats.turn_barrel_pct.n == 2

    def test_aggression_factor_computed_correctly(self) -> None:
        # 3 bets+raises across 2 hands / 1 call = AF 3.0
        hands = [
            _make_rec(postflop_bets_raises=2, postflop_calls=1),
            _make_rec(postflop_bets_raises=1, postflop_calls=0),
        ]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.aggression_factor.value == Decimal("3.0000")
        assert stats.aggression_factor.n == 1  # denominator = total calls

    def test_aggression_factor_none_when_never_called(self) -> None:
        # Player only bet/raised, never called postflop → AF undefined
        hands = [_make_rec(postflop_bets_raises=3, postflop_calls=0)]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.aggression_factor.value is None
        assert stats.aggression_factor.n == 0

    def test_check_raise_pct_computed_correctly(self) -> None:
        hands = [
            _make_rec(check_raise_opportunity=True, check_raised=True),
            _make_rec(check_raise_opportunity=True, check_raised=False),
            _make_rec(check_raise_opportunity=True, check_raised=False),
        ]
        stats = compute_player_stats(_PLAYER_ID, hands)
        assert stats.check_raise_pct.value == Decimal("0.3333")
        assert stats.check_raise_pct.n == 3

    def test_all_postflop_stats_labeled_inferred(self) -> None:
        hands = [_make_rec(cbet_opportunity=True, cbet=True)]
        stats = compute_player_stats(_PLAYER_ID, hands)
        for field in (
            stats.cbet_pct,
            stats.fold_to_flop_bet,
            stats.turn_barrel_pct,
            stats.fold_to_turn_bet,
            stats.delayed_cbet_pct,
            stats.check_raise_pct,
            stats.aggression_factor,
        ):
            assert field.label == MetricLabel.INFERRED

    def test_empty_hands_all_postflop_stats_none(self) -> None:
        stats = compute_player_stats(_PLAYER_ID, [])
        for field in (
            stats.cbet_pct,
            stats.fold_to_flop_bet,
            stats.turn_barrel_pct,
            stats.fold_to_turn_bet,
            stats.delayed_cbet_pct,
            stats.check_raise_pct,
            stats.aggression_factor,
        ):
            assert field.value is None
            assert field.n == 0


# ---------------------------------------------------------------------------
# hand_record_from_actions: integration with postflop flags
# ---------------------------------------------------------------------------


class TestHandRecordFromActionsPostflop:
    def _build(
        self,
        pfr_actions: list[dict],
        postflop_actions: list[dict],
        saw_flop: bool = True,
    ) -> HandRecord:
        return hand_record_from_actions(
            hand_external_id="test",
            player_position="BTN",
            player_stack_bb=_STACK,
            player_effective_stack_bb=_STACK,
            this_hand_player_id=_HERO,
            all_preflop_actions=pfr_actions,
            all_postflop_actions=postflop_actions,
            saw_flop=saw_flop,
            reached_showdown=False,
            won_at_showdown=False,
        )

    def test_cbet_set_when_hero_raises_preflop_and_bets_flop(self) -> None:
        rec = self._build(
            pfr_actions=_HERO_OPEN_PF,
            postflop_actions=[
                _flop("bb", "CHECK", 10),
                _flop(_HERO, "BET", 11),
            ],
        )
        assert rec.pfr is True
        assert rec.cbet_opportunity is True
        assert rec.cbet is True

    def test_no_postflop_arg_leaves_flags_false(self) -> None:
        # Omitting all_postflop_actions → all postflop flags stay False
        rec = hand_record_from_actions(
            hand_external_id="test",
            player_position="BTN",
            player_stack_bb=_STACK,
            player_effective_stack_bb=_STACK,
            this_hand_player_id=_HERO,
            all_preflop_actions=_HERO_OPEN_PF,
            saw_flop=True,
            reached_showdown=False,
            won_at_showdown=False,
        )
        assert rec.cbet_opportunity is False
        assert rec.cbet is False

    def test_not_pfr_no_cbet_opportunity(self) -> None:
        rec = self._build(
            pfr_actions=_HERO_CALL_PF,
            postflop_actions=[
                _flop(_OPP, "BET", 10),
                _flop(_HERO, "FOLD", 11),
            ],
        )
        assert rec.pfr is False
        assert rec.cbet_opportunity is False
        assert rec.faced_flop_bet is True
        assert rec.folded_to_flop_bet is True


# ---------------------------------------------------------------------------
# LeakDetector: postflop rules
# ---------------------------------------------------------------------------


def _lm(value: float | None, n: int):
    v = Decimal(str(value)) if value is not None else None
    return inferred(value=v, source="test", n=n)


def _null():
    return _lm(None, 0)


def _make_postflop_stats(
    *,
    cbet_pct: float | None = 0.55,
    cbet_n: int = 50,
    fold_to_flop_bet: float | None = 0.45,
    fold_flop_n: int = 50,
    turn_barrel_pct: float | None = 0.50,
    turn_barrel_n: int = 30,
    fold_to_turn_bet: float | None = 0.50,
    fold_turn_n: int = 30,
    delayed_cbet_pct: float | None = 0.40,
    delayed_cbet_n: int = 20,
    check_raise_pct: float | None = 0.15,
    check_raise_n: int = 20,
    aggression_factor: float | None = 2.0,
    af_n: int = 40,
) -> PlayerStats:
    """Build a PlayerStats with configurable postflop fields and neutral preflop defaults."""
    null = _null()
    return PlayerStats(
        player_id=uuid.uuid4(),
        hand_count=200,
        vpip=_lm(0.25, 200),
        pfr=_lm(0.18, 200),
        three_bet_pct=_lm(0.07, 100),
        fold_to_3bet=_lm(0.58, 50),
        wtsd=_lm(0.32, 80),
        wsd=_lm(0.50, 25),
        steal_pct=null,
        btn_steal_pct=null,
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
        fold_to_flop_bet=_lm(fold_to_flop_bet, fold_flop_n),
        turn_barrel_pct=_lm(turn_barrel_pct, turn_barrel_n),
        fold_to_turn_bet=_lm(fold_to_turn_bet, fold_turn_n),
        delayed_cbet_pct=_lm(delayed_cbet_pct, delayed_cbet_n),
        check_raise_pct=_lm(check_raise_pct, check_raise_n),
        aggression_factor=_lm(aggression_factor, af_n),
    )


class TestCbetTooHigh:
    det = LeakDetector()

    def _rule(self, stats: PlayerStats):
        return self.det._cbet_too_high(stats)

    def test_fires_medium_severity_above_75(self) -> None:
        leak = self._rule(_make_postflop_stats(cbet_pct=0.80, cbet_n=50))
        assert leak is not None
        assert leak.leak_id == "cbet_too_high"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_88(self) -> None:
        leak = self._rule(_make_postflop_stats(cbet_pct=0.92, cbet_n=50))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_fire_at_baseline(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=0.60, cbet_n=50)) is None

    def test_no_fire_at_threshold(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=0.75, cbet_n=50)) is None

    def test_no_fire_insufficient_sample(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=0.90, cbet_n=_CBET_N["low"] - 1)) is None

    def test_no_fire_when_none_value(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=None, cbet_n=0)) is None


class TestCbetTooLow:
    det = LeakDetector()

    def _rule(self, stats: PlayerStats):
        return self.det._cbet_too_low(stats)

    def test_fires_medium_severity_below_38(self) -> None:
        leak = self._rule(_make_postflop_stats(cbet_pct=0.30, cbet_n=50))
        assert leak is not None
        assert leak.leak_id == "cbet_too_low"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_below_22(self) -> None:
        leak = self._rule(_make_postflop_stats(cbet_pct=0.15, cbet_n=50))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_fire_at_baseline(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=0.55, cbet_n=50)) is None

    def test_no_fire_at_threshold(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=0.38, cbet_n=50)) is None

    def test_no_fire_insufficient_sample(self) -> None:
        assert self._rule(_make_postflop_stats(cbet_pct=0.10, cbet_n=_CBET_N["low"] - 1)) is None


class TestFoldToFlopBetTooHigh:
    det = LeakDetector()

    def _rule(self, stats: PlayerStats):
        return self.det._fold_to_flop_bet_too_high(stats)

    def test_fires_medium_severity_above_60(self) -> None:
        leak = self._rule(_make_postflop_stats(fold_to_flop_bet=0.68, fold_flop_n=50))
        assert leak is not None
        assert leak.leak_id == "fold_to_flop_bet_too_high"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_75(self) -> None:
        leak = self._rule(_make_postflop_stats(fold_to_flop_bet=0.82, fold_flop_n=50))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_fire_at_baseline(self) -> None:
        assert self._rule(_make_postflop_stats(fold_to_flop_bet=0.45, fold_flop_n=50)) is None

    def test_no_fire_at_threshold(self) -> None:
        assert self._rule(_make_postflop_stats(fold_to_flop_bet=0.60, fold_flop_n=50)) is None

    def test_no_fire_insufficient_sample(self) -> None:
        assert (
            self._rule(
                _make_postflop_stats(fold_to_flop_bet=0.80, fold_flop_n=_FOLD_FLOP_N["low"] - 1)
            )
            is None
        )


class TestFoldToTurnBetTooHigh:
    det = LeakDetector()

    def _rule(self, stats: PlayerStats):
        return self.det._fold_to_turn_bet_too_high(stats)

    def test_fires_medium_severity_above_65(self) -> None:
        leak = self._rule(_make_postflop_stats(fold_to_turn_bet=0.72, fold_turn_n=30))
        assert leak is not None
        assert leak.leak_id == "fold_to_turn_bet_too_high"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_above_80(self) -> None:
        leak = self._rule(_make_postflop_stats(fold_to_turn_bet=0.85, fold_turn_n=30))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_fire_at_baseline(self) -> None:
        assert self._rule(_make_postflop_stats(fold_to_turn_bet=0.50, fold_turn_n=30)) is None

    def test_no_fire_insufficient_sample(self) -> None:
        assert (
            self._rule(
                _make_postflop_stats(fold_to_turn_bet=0.85, fold_turn_n=_FOLD_TURN_N["low"] - 1)
            )
            is None
        )


class TestTooPassivePostflop:
    det = LeakDetector()

    def _rule(self, stats: PlayerStats):
        return self.det._too_passive_postflop(stats)

    def test_fires_medium_severity_below_1(self) -> None:
        leak = self._rule(_make_postflop_stats(aggression_factor=0.80, af_n=40))
        assert leak is not None
        assert leak.leak_id == "too_passive_postflop"
        assert leak.severity == Severity.MEDIUM

    def test_fires_high_severity_below_0_5(self) -> None:
        leak = self._rule(_make_postflop_stats(aggression_factor=0.30, af_n=40))
        assert leak is not None
        assert leak.severity == Severity.HIGH

    def test_no_fire_at_baseline(self) -> None:
        assert self._rule(_make_postflop_stats(aggression_factor=2.0, af_n=40)) is None

    def test_no_fire_at_exactly_1(self) -> None:
        assert self._rule(_make_postflop_stats(aggression_factor=1.0, af_n=40)) is None

    def test_no_fire_insufficient_sample(self) -> None:
        assert (
            self._rule(_make_postflop_stats(aggression_factor=0.2, af_n=_AF_N["low"] - 1)) is None
        )

    def test_no_fire_when_af_is_none(self) -> None:
        assert self._rule(_make_postflop_stats(aggression_factor=None, af_n=0)) is None


# ---------------------------------------------------------------------------
# detect() integration: new rules appear in output, sorted by priority
# ---------------------------------------------------------------------------


class TestDetectIntegration:
    det = LeakDetector()

    def test_cbet_too_high_appears_in_detect_output(self) -> None:
        stats = _make_postflop_stats(cbet_pct=0.92, cbet_n=50)
        leaks = self.det.detect(stats)
        ids = [l.leak_id for l in leaks]
        assert "cbet_too_high" in ids

    def test_cbet_too_low_appears_in_detect_output(self) -> None:
        stats = _make_postflop_stats(cbet_pct=0.15, cbet_n=50)
        leaks = self.det.detect(stats)
        ids = [l.leak_id for l in leaks]
        assert "cbet_too_low" in ids

    def test_fold_to_flop_bet_appears_in_detect_output(self) -> None:
        stats = _make_postflop_stats(fold_to_flop_bet=0.82, fold_flop_n=50)
        leaks = self.det.detect(stats)
        ids = [l.leak_id for l in leaks]
        assert "fold_to_flop_bet_too_high" in ids

    def test_too_passive_postflop_appears_in_detect_output(self) -> None:
        stats = _make_postflop_stats(aggression_factor=0.30, af_n=40)
        leaks = self.det.detect(stats)
        ids = [l.leak_id for l in leaks]
        assert "too_passive_postflop" in ids

    def test_detect_returns_sorted_by_priority_descending(self) -> None:
        stats = _make_postflop_stats(cbet_pct=0.92, cbet_n=50, aggression_factor=0.30, af_n=40)
        leaks = self.det.detect(stats)
        priorities = [l.priority for l in leaks]
        assert priorities == sorted(priorities, reverse=True)

    def test_no_postflop_leaks_when_all_in_range(self) -> None:
        stats = _make_postflop_stats(
            cbet_pct=0.58,
            fold_to_flop_bet=0.45,
            fold_to_turn_bet=0.50,
            aggression_factor=2.0,
        )
        leaks = self.det.detect(stats)
        postflop_ids = {
            "cbet_too_high",
            "cbet_too_low",
            "fold_to_flop_bet_too_high",
            "fold_to_turn_bet_too_high",
            "too_passive_postflop",
        }
        assert not any(l.leak_id in postflop_ids for l in leaks)
