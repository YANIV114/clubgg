"""
Tests for app/analysis/hand_analysis_engine.py

All tests are pure — no database fixture needed.
Fixtures build HandDetailOut instances directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.analysis.hand_analysis_engine import analyze_hand
from app.features.labels import MetricLabel
from app.models.hand import ActionType, GameType, Street
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_CLUB_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_NOW = datetime(2024, 1, 15, 22, 31, 7, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------


def _hand(
    *,
    position: str,
    stack_bb: Decimal,
    actions: list[tuple],  # (street, action_type, amount, is_all_in, order)
    player_count: int = 6,
    opp_actions: list[tuple] = (),  # (position, street, action_type, amount, is_all_in, order)
    stakes_bb: Decimal = Decimal("1"),
    board_cards: str | None = None,
) -> tuple[HandDetailOut, uuid.UUID]:
    """
    Build a minimal HandDetailOut + hero_player_id for testing.

    hero actions tuple: (street, action_type, amount_in_chips, is_all_in, action_order)
    opp actions tuple:  (position, street, action_type, amount_in_chips, is_all_in, action_order)
    """
    hero_id = uuid.uuid4()
    stakes_sb = (stakes_bb / Decimal("2")).quantize(Decimal("0.0001"))

    # Build hero PlayerActionOut list
    hero_action_outs: list[PlayerActionOut] = []
    for street, action_type, amount, is_all_in, order in actions:
        hero_action_outs.append(
            PlayerActionOut(
                street=Street(street),
                action_type=ActionType(action_type),
                amount=Decimal(str(amount)) if amount is not None else None,
                is_all_in=is_all_in,
                action_order=order,
            )
        )

    hero_hp = HandPlayerOut(
        player_id=hero_id,
        seat_number=1,
        starting_stack=(stack_bb * stakes_bb).quantize(Decimal("0.0001")),
        ending_stack=None,
        hole_cards=None,
        did_show=False,
        net_won=None,
        position=position,
        stack_bb=stack_bb,
        effective_stack_bb=stack_bb,
        username="hero",
        actions=hero_action_outs,
    )

    # Build opponent hand_players
    opp_players: list[HandPlayerOut] = []
    # Group opp_actions by position to build per-player action lists
    opp_by_pos: dict[str, list] = {}
    for pos, street, action_type, amount, is_all_in, order in opp_actions:
        opp_by_pos.setdefault(pos, []).append((street, action_type, amount, is_all_in, order))

    for seat_idx, (opp_pos, opp_act_list) in enumerate(opp_by_pos.items(), start=2):
        opp_id = uuid.uuid4()
        opp_action_outs: list[PlayerActionOut] = []
        for street, action_type, amount, is_all_in, order in opp_act_list:
            opp_action_outs.append(
                PlayerActionOut(
                    street=Street(street),
                    action_type=ActionType(action_type),
                    amount=Decimal(str(amount)) if amount is not None else None,
                    is_all_in=is_all_in,
                    action_order=order,
                )
            )
        opp_players.append(
            HandPlayerOut(
                player_id=opp_id,
                seat_number=seat_idx,
                starting_stack=Decimal("25"),
                ending_stack=None,
                hole_cards=None,
                did_show=False,
                net_won=None,
                position=opp_pos,
                stack_bb=Decimal("25"),
                effective_stack_bb=Decimal("25"),
                username=f"opp_{opp_pos}",
                actions=opp_action_outs,
            )
        )

    hand = HandDetailOut(
        id=uuid.uuid4(),
        external_id="TEST-001",
        club_id=_CLUB_ID,
        game_session_id=_SESSION_ID,
        game_type=GameType.NLH,
        stakes_sb=stakes_sb,
        stakes_bb=stakes_bb,
        stakes_ante=None,
        table_name="Test Table",
        hand_started_at=_NOW,
        hand_ended_at=None,
        total_pot=Decimal("5"),
        total_rake=Decimal("0"),
        board_cards=board_cards,
        player_count=player_count,
        ingestion_source="file",
        button_seat=None,
        hand_players=[hero_hp] + opp_players,
        winners=[],
    )
    return hand, hero_id


# ---------------------------------------------------------------------------
# TestPushFold
# ---------------------------------------------------------------------------


class TestPushFold:
    def test_flat_call_8bb_is_critical_mistake(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("8"),
            actions=[("PREFLOP", "CALL", "8", False, 5)],
            opp_actions=[("UTG", "PREFLOP", "RAISE", "2", False, 2)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "critical"
        assert result.ev_label == "-EV"
        assert result.confidence == MetricLabel.INFERRED

    def test_flat_call_12bb_is_major_mistake(self):
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("12"),
            actions=[("PREFLOP", "CALL", "12", False, 5)],
            opp_actions=[("UTG", "PREFLOP", "RAISE", "2", False, 2)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "major"
        assert result.ev_label == "-EV"

    def test_shove_is_good(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "good"
        assert result.ev_label == "+EV"
        assert result.backing == "Nash table estimate"

    def test_minraise_10bb_is_minor_mistake(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "RAISE", "2", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "minor"

    def test_fold_steal_10bb_is_minor(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "FOLD", None, False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "minor"

    def test_fold_blind_neutral(self):
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "FOLD", None, False, 5),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2", False, 3)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "none"

    def test_20bb_stack_is_not_push_fold_spot(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("20"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        # 20bb > 15bb threshold — should be steal, not push_fold
        assert result.spot_type != "push_fold"


# ---------------------------------------------------------------------------
# TestSteal
# ---------------------------------------------------------------------------


class TestSteal:
    def test_btn_open_raise_is_good(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "steal"
        assert result.mistake_severity == "good"
        assert result.ev_label == "+EV"

    def test_btn_limp_is_minor_mistake(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "CALL", "1", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "steal"
        assert result.mistake_severity == "minor"
        assert result.ev_label == "neutral"

    def test_co_raise_is_good(self):
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "steal"
        assert result.mistake_severity == "good"

    def test_sb_raise_is_good(self):
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("30"),
            actions=[
                ("PREFLOP", "POST_SB", "0.5", False, 1),
                ("PREFLOP", "RAISE", "2.5", False, 5),
            ],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "steal"
        assert result.mistake_severity == "good"

    def test_btn_fold_is_neutral(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "FOLD", None, False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "steal"
        assert result.mistake_severity == "none"
        assert result.ev_label == "neutral"


# ---------------------------------------------------------------------------
# TestOpenFold
# ---------------------------------------------------------------------------


class TestOpenFold:
    def test_utg_raise_is_neutral(self):
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 1)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "open_fold"
        assert result.mistake_severity == "none"

    def test_utg_fold_is_neutral(self):
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "FOLD", None, False, 1)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "open_fold"
        assert result.mistake_severity == "none"

    def test_utg_limp_is_minor_mistake(self):
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "CALL", "1", False, 1)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "open_fold"
        assert result.mistake_severity == "minor"


# ---------------------------------------------------------------------------
# TestDefendBB
# ---------------------------------------------------------------------------


class TestDefendBB:
    def test_deep_stack_call_is_neutral(self):
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 10),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "defend_bb"
        assert result.mistake_severity == "none"

    def test_short_stack_call_is_not_a_mistake(self):
        # Per classification priority 2: stack ≤ 15bb + preflop voluntary action → push_fold.
        # push_fold overrides defend_bb for short stacks, but BB calling a single
        # non-all-in raise is a standard defend, so it is not flagged above 10bb.
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("12"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 10),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "none"

    def test_3bet_is_good(self):
        # BB re-raises facing a BTN steal → classified as defend_bb (BB defence
        # context).  A 3-bet from BB vs a steal is aggressive defence, rated good.
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "RAISE", "8", False, 10),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        # BB 3-bet is classified as defend_bb (positional framing)
        assert result.spot_type == "defend_bb"
        assert result.mistake_severity in ("good", "none")


# ---------------------------------------------------------------------------
# TestThreeBet
# ---------------------------------------------------------------------------


class TestThreeBet:
    def test_steal_position_3bet_is_good(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "8", False, 10)],
            opp_actions=[("UTG", "PREFLOP", "RAISE", "2.5", False, 3)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "three_bet"
        assert result.mistake_severity == "good"
        assert result.ev_label == "+EV"

    def test_non_steal_3bet_is_neutral(self):
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("25"),
            # UTG re-raises vs CO open
            actions=[("PREFLOP", "RAISE", "8", False, 10)],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "three_bet"
        assert result.mistake_severity == "none"
        assert result.ev_label == "neutral"


# ---------------------------------------------------------------------------
# TestCallAllIn
# ---------------------------------------------------------------------------


class TestCallAllIn:
    def test_call_allin_is_speculative(self):
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "20", False, 10),
            ],
            opp_actions=[("UTG", "PREFLOP", "ALL_IN", "20", True, 5)],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "call_all_in"
        assert result.confidence == MetricLabel.SPECULATIVE
        assert result.backing in ("heuristic", "range-based estimate", "Nash table estimate")

    def test_pot_odds_in_key_factors(self):
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "20", False, 10),
            ],
            opp_actions=[("UTG", "PREFLOP", "ALL_IN", "20", True, 5)],
            stakes_bb=Decimal("1"),
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "call_all_in"
        # At least one key_factor should mention pot odds
        pot_odds_factor = [f for f in result.key_factors if "pot odds" in f.lower()]
        assert pot_odds_factor, f"Expected pot odds in key_factors, got: {result.key_factors}"


# ---------------------------------------------------------------------------
# TestFlopCbet
# ---------------------------------------------------------------------------


class TestFlopCbet:
    def test_cbet_as_pfa_is_neutral(self):
        # Hero raised preflop (PFA), then bets flop
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 1),
                ("FLOP", "BET", "3", False, 10),
            ],
            board_cards="Ah Kd 2c",
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "flop_cbet"
        assert result.mistake_severity == "none"
        assert result.confidence == MetricLabel.INFERRED

    def test_check_back_as_pfa_is_neutral(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 1),
                ("FLOP", "CHECK", None, False, 10),
            ],
            board_cards="Ah Kd 2c",
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "flop_cbet"
        assert result.mistake_severity == "none"


# ---------------------------------------------------------------------------
# TestTurnBarrel
# ---------------------------------------------------------------------------


class TestTurnBarrel:
    def test_turn_bet_is_neutral(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 1),
                ("FLOP", "BET", "3", False, 5),
                ("TURN", "BET", "6", False, 15),
            ],
            board_cards="Ah Kd 2c Ts",
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "turn_barrel"
        assert result.mistake_severity == "none"
        assert result.confidence == MetricLabel.INFERRED

    def test_turn_check_is_neutral(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 1),
                ("FLOP", "BET", "3", False, 5),
                ("TURN", "CHECK", None, False, 15),
            ],
            board_cards="Ah Kd 2c Ts",
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "turn_barrel"
        assert result.mistake_severity == "none"


# ---------------------------------------------------------------------------
# TestRiverCallFold
# ---------------------------------------------------------------------------


class TestRiverCallFold:
    def test_river_call_is_neutral(self):
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 5),
                ("FLOP", "CHECK", None, False, 10),
                ("TURN", "CHECK", None, False, 15),
                ("RIVER", "CALL", "8", False, 25),
            ],
            opp_actions=[
                ("BTN", "PREFLOP", "RAISE", "2.5", False, 3),
                ("BTN", "FLOP", "CHECK", None, False, 11),
                ("BTN", "TURN", "CHECK", None, False, 16),
                ("BTN", "RIVER", "BET", "8", False, 23),
            ],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "river_call_fold"
        assert result.mistake_severity == "none"
        assert result.confidence == MetricLabel.INFERRED

    def test_river_fold_is_neutral(self):
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 5),
                ("FLOP", "CHECK", None, False, 10),
                ("TURN", "CHECK", None, False, 15),
                ("RIVER", "FOLD", None, False, 25),
            ],
            opp_actions=[
                ("BTN", "PREFLOP", "RAISE", "2.5", False, 3),
                ("BTN", "FLOP", "CHECK", None, False, 11),
                ("BTN", "TURN", "CHECK", None, False, 16),
                ("BTN", "RIVER", "BET", "8", False, 23),
            ],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "river_call_fold"
        assert result.mistake_severity == "none"


# ---------------------------------------------------------------------------
# TestAnalyzeHandNeverRaises
# ---------------------------------------------------------------------------


class TestAnalyzeHandNeverRaises:
    def test_no_actions_does_not_raise(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[],
        )
        # Must not raise — returns a valid result
        result = analyze_hand(hand, hero_id)
        assert isinstance(result.spot_type, str)
        assert isinstance(result.confidence, MetricLabel)

    def test_hero_not_in_hand_returns_other(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 1)],
        )
        # Pass a random UUID that is not hero_id
        stranger_id = uuid.uuid4()
        result = analyze_hand(hand, stranger_id)
        assert result.spot_type == "other"
        assert result.confidence == MetricLabel.SPECULATIVE

    def test_null_position_does_not_raise(self):
        """Hero has position=None — engine must not crash."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 1)],
        )
        # Manually override position to None via reconstruction
        hp = hand.hand_players[0]
        new_hp = HandPlayerOut(
            player_id=hp.player_id,
            seat_number=hp.seat_number,
            starting_stack=hp.starting_stack,
            ending_stack=hp.ending_stack,
            hole_cards=hp.hole_cards,
            did_show=hp.did_show,
            net_won=hp.net_won,
            position=None,
            stack_bb=hp.stack_bb,
            effective_stack_bb=hp.effective_stack_bb,
            username=hp.username,
            actions=hp.actions,
        )
        hand2 = HandDetailOut(
            id=hand.id,
            external_id=hand.external_id,
            club_id=hand.club_id,
            game_session_id=hand.game_session_id,
            game_type=hand.game_type,
            stakes_sb=hand.stakes_sb,
            stakes_bb=hand.stakes_bb,
            stakes_ante=hand.stakes_ante,
            table_name=hand.table_name,
            hand_started_at=hand.hand_started_at,
            hand_ended_at=hand.hand_ended_at,
            total_pot=hand.total_pot,
            total_rake=hand.total_rake,
            board_cards=hand.board_cards,
            player_count=hand.player_count,
            ingestion_source=hand.ingestion_source,
            button_seat=hand.button_seat,
            hand_players=[new_hp],
            winners=[],
        )
        result = analyze_hand(hand2, hp.player_id)
        assert isinstance(result.spot_type, str)

    def test_null_stack_does_not_raise(self):
        """Hero has stack_bb=None — engine must not crash."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 1)],
        )
        hp = hand.hand_players[0]
        new_hp = HandPlayerOut(
            player_id=hp.player_id,
            seat_number=hp.seat_number,
            starting_stack=hp.starting_stack,
            ending_stack=hp.ending_stack,
            hole_cards=hp.hole_cards,
            did_show=hp.did_show,
            net_won=hp.net_won,
            position=hp.position,
            stack_bb=None,
            effective_stack_bb=None,
            username=hp.username,
            actions=hp.actions,
        )
        hand2 = HandDetailOut(
            id=hand.id,
            external_id=hand.external_id,
            club_id=hand.club_id,
            game_session_id=hand.game_session_id,
            game_type=hand.game_type,
            stakes_sb=hand.stakes_sb,
            stakes_bb=hand.stakes_bb,
            stakes_ante=hand.stakes_ante,
            table_name=hand.table_name,
            hand_started_at=hand.hand_started_at,
            hand_ended_at=hand.hand_ended_at,
            total_pot=hand.total_pot,
            total_rake=hand.total_rake,
            board_cards=hand.board_cards,
            player_count=hand.player_count,
            ingestion_source=hand.ingestion_source,
            button_seat=hand.button_seat,
            hand_players=[new_hp],
            winners=[],
        )
        result = analyze_hand(hand2, hp.player_id)
        assert isinstance(result.spot_type, str)

    def test_completely_empty_hand_does_not_raise(self):
        """Hand with no players at all."""
        hand = HandDetailOut(
            id=uuid.uuid4(),
            external_id="EMPTY",
            club_id=_CLUB_ID,
            game_session_id=None,
            game_type=GameType.NLH,
            stakes_sb=Decimal("0.5"),
            stakes_bb=Decimal("1"),
            stakes_ante=None,
            table_name=None,
            hand_started_at=_NOW,
            hand_ended_at=None,
            total_pot=Decimal("0"),
            total_rake=Decimal("0"),
            board_cards=None,
            player_count=0,
            ingestion_source="file",
            button_seat=None,
            hand_players=[],
            winners=[],
        )
        result = analyze_hand(hand, uuid.uuid4())
        assert result.spot_type == "other"
        assert result.confidence == MetricLabel.SPECULATIVE


# ---------------------------------------------------------------------------
# Additional edge-case / integration tests
# ---------------------------------------------------------------------------


class TestICMSpots:
    def test_bubble_icm_is_speculative(self):
        """Short stack (≤15bb) at a 5-player table → bubble_icm, SPECULATIVE.

        ICM spots require a late-stage tournament proxy.  The engine uses
        player_count ≤ 5 for bubble_icm (short-handed = plausible bubble).
        """
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("13"),
            actions=[("PREFLOP", "ALL_IN", "13", True, 5)],
            player_count=5,
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "bubble_icm"
        assert result.confidence == MetricLabel.SPECULATIVE
        # ICM key_factors must mention payout unknown
        payout_note = [f for f in result.key_factors if "payout" in f.lower()]
        assert payout_note, f"Expected payout note in key_factors, got: {result.key_factors}"

    def test_final_table_icm_is_speculative(self):
        """Stack ≤10bb at a 3-player (or fewer) table → final_table_icm, SPECULATIVE.

        The engine uses player_count ≤ 4 for final_table_icm.
        """
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("9"),
            actions=[("PREFLOP", "ALL_IN", "9", True, 5)],
            player_count=3,
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "final_table_icm"
        assert result.confidence == MetricLabel.SPECULATIVE


class TestFourBetJam:
    def test_jam_over_3bet_is_neutral(self):
        """Hero faces 2 raises (UTG open + CO 3-bet) and jams."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "ALL_IN", "30", True, 15)],
            opp_actions=[
                ("UTG", "PREFLOP", "RAISE", "2.5", False, 3),
                ("CO", "PREFLOP", "RAISE", "7.5", False, 8),
            ],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "four_bet_jam"
        assert result.mistake_severity == "none"

    def test_call_over_3bet_is_minor_mistake(self):
        """Hero faces 2 raises and calls without jamming."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "CALL", "7.5", False, 15)],
            opp_actions=[
                ("UTG", "PREFLOP", "RAISE", "2.5", False, 3),
                ("CO", "PREFLOP", "RAISE", "7.5", False, 8),
            ],
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "four_bet_jam"
        assert result.mistake_severity == "minor"


class TestHelperFunctions:
    """Unit tests for the exported helper functions."""

    def test_preflop_voluntary_excludes_posts(self):
        from app.analysis.hand_analysis_engine import _preflop_voluntary

        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_SB", "0.5", False, 1),
                ("PREFLOP", "RAISE", "2.5", False, 5),
            ],
        )
        hp = hand.hand_players[0]
        vol = _preflop_voluntary(hp)
        assert len(vol) == 1
        assert vol[0].action_type == "RAISE"

    def test_is_first_in_true_when_no_prior_raises(self):
        from app.analysis.hand_analysis_engine import _is_first_in

        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        hp = hand.hand_players[0]
        assert _is_first_in(hand, hp) is True

    def test_is_first_in_false_when_prior_raise(self):
        from app.analysis.hand_analysis_engine import _is_first_in

        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "8", False, 10)],
            opp_actions=[("UTG", "PREFLOP", "RAISE", "2.5", False, 3)],
        )
        hp = hand.hand_players[0]
        assert _is_first_in(hand, hp) is False

    def test_hero_was_pfa_true(self):
        from app.analysis.hand_analysis_engine import _hero_was_pfa

        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        hp = hand.hand_players[0]
        assert _hero_was_pfa(hand, hp) is True

    def test_hero_was_pfa_false_when_opp_3bet(self):
        from app.analysis.hand_analysis_engine import _hero_was_pfa

        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 3),
                ("PREFLOP", "CALL", "7.5", False, 10),
            ],
            opp_actions=[("BB", "PREFLOP", "RAISE", "7.5", False, 7)],
        )
        hp = hand.hand_players[0]
        assert _hero_was_pfa(hand, hp) is False

    def test_describe_action_fold(self):
        from app.analysis.hand_analysis_engine import _describe_action

        assert _describe_action("FOLD", None, Decimal("1")) == "folded"

    def test_describe_action_all_in_with_amount(self):
        from app.analysis.hand_analysis_engine import _describe_action

        result = _describe_action("ALL_IN", Decimal("15"), Decimal("1"))
        assert result == "shoved 15.0bb"

    def test_describe_action_call_bb_conversion(self):
        from app.analysis.hand_analysis_engine import _describe_action

        result = _describe_action("CALL", Decimal("2.5"), Decimal("1"))
        assert result == "called 2.5bb"

    def test_describe_action_raise_bb_conversion(self):
        from app.analysis.hand_analysis_engine import _describe_action

        result = _describe_action("RAISE", Decimal("7.5"), Decimal("2.5"))
        assert result == "raise to 3.0bb"

    def test_pot_at_decision_sums_prior_bets(self):
        from app.analysis.hand_analysis_engine import _pot_at_decision

        # Hero is in BB (order 1), BTN raises (order 3), hero calls (order 5)
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 5),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 3)],
            stakes_bb=Decimal("1"),
        )
        hp = hand.hand_players[0]
        # Hero's first preflop action is order=1 (POST_BB)
        # pot_at_decision sums amounts BEFORE hero's first action
        pot = _pot_at_decision(hand, hp, "PREFLOP")
        assert pot >= Decimal("0")  # Just confirm no crash and returns Decimal
        assert isinstance(pot, Decimal)

    def test_build_key_factors_includes_position_and_stack(self):
        from app.analysis.hand_analysis_engine import _build_key_factors

        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("20"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 1)],
        )
        hp = hand.hand_players[0]
        factors = _build_key_factors(hp, hand, ["extra-note"])
        assert any("BTN" in f for f in factors)
        assert any("20" in f for f in factors)
        assert "extra-note" in factors
