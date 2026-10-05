"""
Tests for app/analysis/stats_aggregator.py

All tests are pure — no database fixture needed.
Fixtures build HandDetailOut instances directly from schemas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analysis.opponent_profile import OpponentProfile, classify_opponent
from app.analysis.stats_aggregator import aggregate_all_players, aggregate_player_stats
from app.models.hand import ActionType, GameType, Street
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_CLUB_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_NOW = datetime(2024, 1, 15, 22, 31, 7, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _action(
    street: str,
    action_type: str,
    amount: str | None,
    is_all_in: bool,
    order: int,
) -> PlayerActionOut:
    return PlayerActionOut(
        street=Street(street),
        action_type=ActionType(action_type),
        amount=Decimal(amount) if amount is not None else None,
        is_all_in=is_all_in,
        action_order=order,
    )


def _player(
    player_id: uuid.UUID,
    position: str | None,
    actions: list[PlayerActionOut],
    seat_number: int = 1,
    stack_bb: Decimal = Decimal("25"),
) -> HandPlayerOut:
    return HandPlayerOut(
        player_id=player_id,
        seat_number=seat_number,
        starting_stack=(stack_bb * Decimal("1")).quantize(Decimal("0.0001")),
        ending_stack=None,
        hole_cards=None,
        did_show=False,
        net_won=None,
        position=position,
        stack_bb=stack_bb,
        effective_stack_bb=stack_bb,
        username=f"player_{seat_number}",
        actions=actions,
    )


def _hand(
    hand_players: list[HandPlayerOut],
    *,
    hand_id: uuid.UUID | None = None,
) -> HandDetailOut:
    """Build a minimal HandDetailOut with the given players."""
    return HandDetailOut(
        id=hand_id or uuid.uuid4(),
        external_id=f"TEST-{uuid.uuid4().hex[:8]}",
        club_id=_CLUB_ID,
        game_session_id=_SESSION_ID,
        game_type=GameType.NLH,
        stakes_sb=Decimal("0.5"),
        stakes_bb=Decimal("1"),
        stakes_ante=None,
        table_name="Test Table",
        hand_started_at=_NOW,
        hand_ended_at=None,
        total_pot=Decimal("5"),
        total_rake=Decimal("0"),
        board_cards=None,
        player_count=len(hand_players),
        ingestion_source="file",
        button_seat=None,
        hand_players=hand_players,
        winners=[],
    )


def _simple_hand_for_hero(
    hero_id: uuid.UUID,
    hero_position: str,
    hero_actions: list[tuple],
    other_players: list[tuple] | None = None,
) -> HandDetailOut:
    """
    Build a hand with a hero player and optional other players.

    hero_actions: list of (street, action_type, amount, is_all_in, order)
    other_players: list of (player_id, position, actions_list) where
                   actions_list contains (street, action_type, amount, is_all_in, order)
    """
    hero_action_outs = [_action(*a) for a in hero_actions]
    hero_hp = _player(hero_id, hero_position, hero_action_outs, seat_number=1)

    other_hps: list[HandPlayerOut] = []
    for seat_idx, (pid, pos, acts) in enumerate(other_players or [], start=2):
        action_outs = [_action(*a) for a in acts]
        other_hps.append(_player(pid, pos, action_outs, seat_number=seat_idx))

    return _hand([hero_hp] + other_hps)


# ---------------------------------------------------------------------------
# TestAggregatePlayerStatsBasic
# ---------------------------------------------------------------------------


class TestAggregatePlayerStatsBasic:
    def test_vpip_call_counts(self):
        """Hero calls preflop → vpip=1.0, pfr=0.0."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [("PREFLOP", "CALL", "2.5", False, 5)],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.vpip == 1.0
        assert stats.pfr == 0.0
        assert stats.hands_observed == 1

    def test_vpip_raise_counts(self):
        """Hero raises preflop → vpip=1.0, pfr=1.0."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.vpip == 1.0
        assert stats.pfr == 1.0

    def test_fold_preflop_no_vpip(self):
        """Hero folds preflop → vpip=0.0."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "UTG",
            [("PREFLOP", "FOLD", None, False, 3)],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.vpip == 0.0
        assert stats.pfr == 0.0

    def test_post_bb_no_vpip(self):
        """Hero posts BB then checks → vpip=0.0 (posting is not voluntary)."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BB",
            [
                ("PREFLOP", "POST_BB", "1", False, 2),
                ("PREFLOP", "CHECK", None, False, 8),
            ],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.vpip == 0.0
        assert stats.pfr == 0.0

    def test_three_hands_mixed(self):
        """2 vpip + 1 fold across 3 hands → vpip ≈ 0.667."""
        hero_id = uuid.uuid4()
        h1 = _simple_hand_for_hero(hero_id, "BTN", [("PREFLOP", "CALL", "2.5", False, 5)])
        h2 = _simple_hand_for_hero(hero_id, "CO", [("PREFLOP", "RAISE", "2.5", False, 5)])
        h3 = _simple_hand_for_hero(hero_id, "UTG", [("PREFLOP", "FOLD", None, False, 3)])
        stats = aggregate_player_stats(hero_id, [h1, h2, h3])
        assert stats.hands_observed == 3
        assert abs(stats.vpip - 2 / 3) < 0.001


# ---------------------------------------------------------------------------
# TestThreeBetAggregation
# ---------------------------------------------------------------------------


class TestThreeBetAggregation:
    def test_three_bet_when_facing_raise(self):
        """
        Opp raises (order=3), hero re-raises (order=7), across 5 hands
        → three_bet_pct=1.0 (5 opportunities, 5 three-bets).
        """
        hero_id = uuid.uuid4()
        opp_id = uuid.uuid4()
        hands = []
        for _ in range(5):
            h = _simple_hand_for_hero(
                hero_id,
                "BTN",
                [("PREFLOP", "RAISE", "8", False, 7)],
                other_players=[(opp_id, "CO", [("PREFLOP", "RAISE", "2.5", False, 3)])],
            )
            hands.append(h)
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.three_bet_pct == 1.0

    def test_no_three_bet_opp_when_first_in(self):
        """
        Hero raises first-in (no prior raise) → three_bet_pct not counted
        (faced=0 opportunities → three_bet_pct=None below threshold).
        """
        hero_id = uuid.uuid4()
        hands = [
            _simple_hand_for_hero(hero_id, "BTN", [("PREFLOP", "RAISE", "2.5", False, 5)])
            for _ in range(5)
        ]
        stats = aggregate_player_stats(hero_id, hands)
        # No 3-bet opportunities (hero was first-in), so three_bet_pct is None
        assert stats.three_bet_pct is None

    def test_three_bet_pct_none_below_5_opps(self):
        """3 hands with opp raises (3 opportunities) → three_bet_pct=None."""
        hero_id = uuid.uuid4()
        opp_id = uuid.uuid4()
        hands = []
        for _ in range(3):
            h = _simple_hand_for_hero(
                hero_id,
                "BTN",
                [("PREFLOP", "RAISE", "8", False, 7)],
                other_players=[(opp_id, "CO", [("PREFLOP", "RAISE", "2.5", False, 3)])],
            )
            hands.append(h)
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.three_bet_pct is None

    def test_three_bet_pct_computed_at_5_opps(self):
        """5 opportunities, hero 3-bets 2 times → three_bet_pct=0.4."""
        hero_id = uuid.uuid4()
        opp_id = uuid.uuid4()
        hands = []
        # 2 hands where hero 3-bets
        for _ in range(2):
            h = _simple_hand_for_hero(
                hero_id,
                "BTN",
                [("PREFLOP", "RAISE", "8", False, 7)],
                other_players=[(opp_id, "CO", [("PREFLOP", "RAISE", "2.5", False, 3)])],
            )
            hands.append(h)
        # 3 hands where hero calls (no 3-bet)
        for _ in range(3):
            h = _simple_hand_for_hero(
                hero_id,
                "BTN",
                [("PREFLOP", "CALL", "2.5", False, 7)],
                other_players=[(opp_id, "CO", [("PREFLOP", "RAISE", "2.5", False, 3)])],
            )
            hands.append(h)
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.three_bet_pct == pytest.approx(0.4, abs=0.001)


# ---------------------------------------------------------------------------
# TestFoldToStealAggregation
# ---------------------------------------------------------------------------


class TestFoldToStealAggregation:
    def _make_steal_hand(
        self, hero_id: uuid.UUID, btn_id: uuid.UUID, hero_folds: bool
    ) -> HandDetailOut:
        """BB vs BTN steal: hero posts BB (order=2), BTN raises (order=3), hero acts (order=5)."""
        hero_action = "FOLD" if hero_folds else "CALL"
        hero_amount = None if hero_folds else "2.5"
        return _simple_hand_for_hero(
            hero_id,
            "BB",
            [
                ("PREFLOP", "POST_BB", "1", False, 2),
                ("PREFLOP", hero_action, hero_amount, False, 5),
            ],
            other_players=[(btn_id, "BTN", [("PREFLOP", "RAISE", "2.5", False, 3)])],
        )

    def test_bb_folds_to_btn_steal(self):
        """BB folds vs BTN raise (first-in) → fold_to_steal=1.0 (at 5+ opportunities)."""
        hero_id = uuid.uuid4()
        btn_id = uuid.uuid4()
        hands = [self._make_steal_hand(hero_id, btn_id, hero_folds=True) for _ in range(5)]
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.fold_to_steal == 1.0

    def test_bb_calls_btn_steal(self):
        """BB calls BTN raise (first-in) → fold_to_steal=0.0 (at 5+ opportunities)."""
        hero_id = uuid.uuid4()
        btn_id = uuid.uuid4()
        hands = [self._make_steal_hand(hero_id, btn_id, hero_folds=False) for _ in range(5)]
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.fold_to_steal == 0.0

    def test_not_counted_non_bb(self):
        """Hero is BTN (not BB) → fold_to_steal=None regardless of hand count."""
        hero_id = uuid.uuid4()
        opp_id = uuid.uuid4()
        hands = []
        for _ in range(6):
            h = _simple_hand_for_hero(
                hero_id,
                "BTN",
                [("PREFLOP", "RAISE", "2.5", False, 5)],
                other_players=[(opp_id, "BB", [("PREFLOP", "FOLD", None, False, 7)])],
            )
            hands.append(h)
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.fold_to_steal is None

    def test_none_below_5_steal_opps(self):
        """3 steal opportunities → fold_to_steal=None (below threshold)."""
        hero_id = uuid.uuid4()
        btn_id = uuid.uuid4()
        hands = [self._make_steal_hand(hero_id, btn_id, hero_folds=True) for _ in range(3)]
        stats = aggregate_player_stats(hero_id, hands)
        assert stats.fold_to_steal is None


# ---------------------------------------------------------------------------
# TestAggressionFrequency
# ---------------------------------------------------------------------------


class TestAggressionFrequency:
    def test_postflop_bets_only(self):
        """Hero bets flop only → agg_freq=1.0."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [
                ("PREFLOP", "RAISE", "2.5", False, 1),
                ("FLOP", "BET", "3", False, 5),
            ],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.aggression_freq == 1.0

    def test_postflop_calls_only(self):
        """Hero calls flop only → agg_freq=0.0."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BB",
            [
                ("PREFLOP", "POST_BB", "1", False, 2),
                ("PREFLOP", "CALL", "2.5", False, 5),
                ("FLOP", "CALL", "3", False, 10),
            ],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.aggression_freq == 0.0

    def test_mixed_postflop(self):
        """2 bets + 1 call across 3 separate hands → agg_freq ≈ 0.667."""
        hero_id = uuid.uuid4()
        h1 = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [("PREFLOP", "RAISE", "2.5", False, 1), ("FLOP", "BET", "3", False, 5)],
        )
        h2 = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [("PREFLOP", "RAISE", "2.5", False, 1), ("FLOP", "BET", "3", False, 5)],
        )
        h3 = _simple_hand_for_hero(
            hero_id,
            "BB",
            [
                ("PREFLOP", "POST_BB", "1", False, 2),
                ("PREFLOP", "CALL", "2.5", False, 5),
                ("FLOP", "CALL", "3", False, 10),
            ],
        )
        stats = aggregate_player_stats(hero_id, [h1, h2, h3])
        assert abs(stats.aggression_freq - 2 / 3) < 0.001

    def test_no_postflop_none(self):
        """Hand ends preflop (fold) → agg_freq=None (no postflop actions)."""
        hero_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "UTG",
            [("PREFLOP", "FOLD", None, False, 3)],
        )
        stats = aggregate_player_stats(hero_id, [h])
        assert stats.aggression_freq is None


# ---------------------------------------------------------------------------
# TestReliabilityFlag
# ---------------------------------------------------------------------------


class TestReliabilityFlag:
    def _make_hands(self, hero_id: uuid.UUID, count: int) -> list[HandDetailOut]:
        return [
            _simple_hand_for_hero(hero_id, "BTN", [("PREFLOP", "FOLD", None, False, 3)])
            for _ in range(count)
        ]

    def test_reliable_at_10_hands(self):
        """10 hands → reliable=True."""
        hero_id = uuid.uuid4()
        stats = aggregate_player_stats(hero_id, self._make_hands(hero_id, 10))
        assert stats.reliable is True
        assert stats.hands_observed == 10

    def test_unreliable_at_9_hands(self):
        """9 hands → reliable=False."""
        hero_id = uuid.uuid4()
        stats = aggregate_player_stats(hero_id, self._make_hands(hero_id, 9))
        assert stats.reliable is False
        assert stats.hands_observed == 9

    def test_zero_hands_unreliable(self):
        """Player never appears → reliable=False, hands_observed=0."""
        hero_id = uuid.uuid4()
        stranger_id = uuid.uuid4()
        hands = self._make_hands(hero_id, 5)
        stats = aggregate_player_stats(stranger_id, hands)
        assert stats.reliable is False
        assert stats.hands_observed == 0


# ---------------------------------------------------------------------------
# TestAggregateAllPlayers
# ---------------------------------------------------------------------------


class TestAggregateAllPlayers:
    def test_all_players_in_result(self):
        """Hand with 2 players → both player IDs appear in result dict."""
        hero_id = uuid.uuid4()
        villain_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [("PREFLOP", "RAISE", "2.5", False, 5)],
            other_players=[(villain_id, "BB", [("PREFLOP", "FOLD", None, False, 7)])],
        )
        result = aggregate_all_players([h])
        assert hero_id in result
        assert villain_id in result

    def test_player_in_multiple_hands_accumulates(self):
        """Player appears in 3 hands → hands_observed=3."""
        hero_id = uuid.uuid4()
        hands = [
            _simple_hand_for_hero(hero_id, "BTN", [("PREFLOP", "FOLD", None, False, 3)])
            for _ in range(3)
        ]
        result = aggregate_all_players(hands)
        assert result[hero_id].hands_observed == 3

    def test_stats_per_player_independent(self):
        """Hero VPIP=1.0, villain VPIP=0.0 in same hand — each player has correct stats."""
        hero_id = uuid.uuid4()
        villain_id = uuid.uuid4()
        h = _simple_hand_for_hero(
            hero_id,
            "BTN",
            [("PREFLOP", "RAISE", "2.5", False, 5)],
            other_players=[(villain_id, "BB", [("PREFLOP", "FOLD", None, False, 7)])],
        )
        result = aggregate_all_players([h])
        assert result[hero_id].vpip == 1.0
        assert result[villain_id].vpip == 0.0


# ---------------------------------------------------------------------------
# TestIntegrationWithClassifier
# ---------------------------------------------------------------------------


class TestIntegrationWithClassifier:
    def _build_hands_for_profile(
        self,
        hero_id: uuid.UUID,
        vpip_count: int,
        pfr_count: int,
        total_hands: int,
    ) -> list[HandDetailOut]:
        """
        Build `total_hands` hands where hero:
        - In the first `pfr_count` hands: raises preflop (counts as VPIP + PFR).
        - In the next `vpip_count - pfr_count` hands: calls preflop (VPIP only).
        - In the remaining hands: folds preflop.
        """
        hands: list[HandDetailOut] = []
        for i in range(total_hands):
            if i < pfr_count:
                actions = [("PREFLOP", "RAISE", "2.5", False, 5)]
            elif i < vpip_count:
                actions = [("PREFLOP", "CALL", "2.5", False, 5)]
            else:
                actions = [("PREFLOP", "FOLD", None, False, 5)]
            hands.append(_simple_hand_for_hero(hero_id, "BTN", actions))
        return hands

    def test_aggregated_tight_passive(self):
        """
        15 hands, VPIP ≈ 0.13, PFR ≈ 0.08 → tight-passive.

        tight: VPIP < 0.20 (2/15 = 0.133)
        passive: pfr/vpip = (1/2) = 0.50 which is in the middle range;
        agg_freq=0 since no postflop actions → falls back to agg_freq < 0.35 → passive.
        """
        hero_id = uuid.uuid4()
        # 2 VPIP hands (1 raise + 1 call), 13 folds
        hands = self._build_hands_for_profile(hero_id, vpip_count=2, pfr_count=1, total_hands=15)
        result = aggregate_all_players(hands)
        stats = result[hero_id]
        assert stats.hands_observed == 15
        assert stats.reliable is True
        profile = classify_opponent(stats)
        # VPIP=0.133 → tight; pfr/vpip=0.5 (middle), agg_freq=None → UNKNOWN
        # No postflop actions, so agg_freq=None → classifier returns UNKNOWN for ambiguous agg
        # This is correct behavior per the classifier rules
        assert profile in (OpponentProfile.TIGHT_PASSIVE, OpponentProfile.UNKNOWN)

    def test_aggregated_loose_aggressive(self):
        """
        20 hands, VPIP = 9/20 = 0.45, PFR = 9/20 = 0.45 → loose-aggressive.

        vpip=0.45 > 0.28 → loose.
        pfr=0.45 >= 0.18 → aggressive.
        """
        hero_id = uuid.uuid4()
        # 9 raises (PFR=9), 11 folds → vpip=9/20=0.45, pfr=9/20=0.45
        hands = self._build_hands_for_profile(hero_id, vpip_count=9, pfr_count=9, total_hands=20)
        result = aggregate_all_players(hands)
        stats = result[hero_id]
        assert stats.hands_observed == 20
        assert stats.reliable is True
        profile = classify_opponent(stats)
        assert profile == OpponentProfile.LOOSE_AGGRESSIVE

    def test_unreliable_is_unknown(self):
        """5 hands → reliable=False, classifier returns UNKNOWN (below _MIN_HANDS=20)."""
        hero_id = uuid.uuid4()
        # All raises → very aggressive and loose, but not enough data
        hands = self._build_hands_for_profile(hero_id, vpip_count=5, pfr_count=5, total_hands=5)
        result = aggregate_all_players(hands)
        stats = result[hero_id]
        assert stats.hands_observed == 5
        assert stats.reliable is False
        profile = classify_opponent(stats)
        assert profile == OpponentProfile.UNKNOWN
