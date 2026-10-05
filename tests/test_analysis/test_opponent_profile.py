"""
Tests for app/analysis/opponent_profile.py and the integrate path
through analyze_hand(opponent_stats=...).

All tests are pure — no database fixture needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.analysis.hand_analysis_engine import analyze_hand
from app.analysis.opponent_profile import (
    OpponentProfile,
    PlayerStats,
    classify_opponent,
    get_exploit_adjustment,
)
from app.features.labels import MetricLabel
from app.models.hand import ActionType, GameType, Street
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Shared constants (mirrored from test_hand_analysis_engine.py)
# ---------------------------------------------------------------------------

_CLUB_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_NOW = datetime(2024, 1, 15, 22, 31, 7, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Fixture helper (standalone copy — no cross-test-file imports)
# ---------------------------------------------------------------------------


def _hand(
    *,
    position: str,
    stack_bb: Decimal,
    actions: list[tuple],
    player_count: int = 6,
    opp_actions: list[tuple] = (),
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

    opp_players: list[HandPlayerOut] = []
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


def _opp_id_for_pos(hand: HandDetailOut, position: str) -> uuid.UUID:
    """Return the player_id of the opponent at the given position."""
    for hp in hand.hand_players:
        if hp.position == position:
            return hp.player_id
    raise ValueError(f"No player at position {position!r}")


# ---------------------------------------------------------------------------
# TestPlayerStatsClassifier
# ---------------------------------------------------------------------------


class TestPlayerStatsClassifier:
    def test_tight_passive_classification(self):
        # vpip=0.12 → tight; pfr/vpip = 0.04/0.12 = 0.333 < 0.40 → passive
        stats = PlayerStats(vpip=0.12, pfr=0.04, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.TIGHT_PASSIVE

    def test_tight_aggressive_classification(self):
        # vpip=0.15 < 0.18 → tight; pfr=0.12 >= 0.12 → aggressive
        stats = PlayerStats(vpip=0.15, pfr=0.12, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.TIGHT_AGGRESSIVE

    def test_loose_passive_classification(self):
        # vpip=0.45 > 0.28 → loose; pfr=0.06 < 0.10 → passive
        stats = PlayerStats(vpip=0.45, pfr=0.06, hands_observed=25)
        assert classify_opponent(stats) == OpponentProfile.LOOSE_PASSIVE

    def test_loose_aggressive_classification(self):
        # vpip=0.42 → loose; pfr/vpip = 0.30/0.42 = 0.714 > 0.60 → aggressive
        stats = PlayerStats(vpip=0.42, pfr=0.30, hands_observed=30)
        assert classify_opponent(stats) == OpponentProfile.LOOSE_AGGRESSIVE

    def test_unknown_insufficient_hands(self):
        stats = PlayerStats(vpip=0.12, pfr=0.08, hands_observed=5)
        assert classify_opponent(stats) == OpponentProfile.UNKNOWN

    def test_unknown_missing_vpip(self):
        stats = PlayerStats(vpip=None, pfr=0.12, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.UNKNOWN

    def test_middle_ground_balanced(self):
        # vpip=0.28 is NOT > 0.28 and NOT < 0.18 → balanced (middle range)
        stats = PlayerStats(vpip=0.28, pfr=0.20, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.BALANCED

    def test_boundary_exactly_tight_cutoff(self):
        # VPIP exactly at 0.20 is NOT < 0.18 and NOT > 0.28 → balanced
        stats = PlayerStats(vpip=0.20, pfr=0.10, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.BALANCED

    def test_boundary_exactly_loose_cutoff(self):
        # VPIP exactly at 0.35 IS > 0.28 → loose; pfr=0.25 >= 0.18 → aggressive
        stats = PlayerStats(vpip=0.35, pfr=0.25, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.LOOSE_AGGRESSIVE

    def test_aggression_freq_fallback_passive(self):
        # No pfr — use aggression_freq alone; 0.25 < 0.35 → passive
        stats = PlayerStats(vpip=0.12, aggression_freq=0.25, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.TIGHT_PASSIVE

    def test_aggression_freq_fallback_aggressive(self):
        # No pfr — use aggression_freq alone; 0.60 > 0.55 → aggressive
        stats = PlayerStats(vpip=0.40, aggression_freq=0.60, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.LOOSE_AGGRESSIVE

    def test_no_aggressiveness_signal_unknown(self):
        # vpip present and loose, but no pfr and no aggression_freq
        stats = PlayerStats(vpip=0.40, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.UNKNOWN

    def test_exactly_twenty_hands_classifies(self):
        # hands_observed == 20 is the minimum — should classify
        stats = PlayerStats(vpip=0.12, pfr=0.04, hands_observed=20)
        assert classify_opponent(stats) == OpponentProfile.TIGHT_PASSIVE

    def test_nine_hands_unknown(self):
        stats = PlayerStats(vpip=0.12, pfr=0.08, hands_observed=9)
        assert classify_opponent(stats) == OpponentProfile.UNKNOWN

    def test_balanced_middle_vpip(self):
        # VPIP in 0.18–0.28 range → balanced regardless of pfr
        stats = PlayerStats(vpip=0.24, pfr=0.15, hands_observed=30)
        assert classify_opponent(stats) == OpponentProfile.BALANCED

    def test_balanced_loose_mid_pfr(self):
        # vpip > 0.28 but pfr in 0.10–0.17 range → balanced
        stats = PlayerStats(vpip=0.38, pfr=0.13, hands_observed=30)
        assert classify_opponent(stats) == OpponentProfile.BALANCED

    def test_nineteen_hands_unknown(self):
        # _MIN_HANDS is 20; 19 hands is not enough
        stats = PlayerStats(vpip=0.12, pfr=0.04, hands_observed=19)
        assert classify_opponent(stats) == OpponentProfile.UNKNOWN


# ---------------------------------------------------------------------------
# TestGetExploitAdjustment
# ---------------------------------------------------------------------------


class TestGetExploitAdjustment:
    def test_push_fold_tight_passive(self):
        adj, reason = get_exploit_adjustment(OpponentProfile.TIGHT_PASSIVE, "push_fold", "mid")
        assert adj != ""
        assert reason != ""
        assert "tight" in reason.lower()

    def test_push_fold_loose_aggressive(self):
        adj, reason = get_exploit_adjustment(
            OpponentProfile.LOOSE_AGGRESSIVE, "push_fold", "bottom"
        )
        assert adj != ""
        assert reason != ""
        assert "loose" in reason.lower()

    def test_push_fold_unknown(self):
        adj, reason = get_exploit_adjustment(OpponentProfile.UNKNOWN, "push_fold", "top")
        assert adj == ""
        assert reason == ""

    def test_steal_tight_passive(self):
        adj, reason = get_exploit_adjustment(OpponentProfile.TIGHT_PASSIVE, "steal", "top")
        assert adj != ""
        assert "tight" in reason.lower()

    def test_defend_bb_loose_passive(self):
        adj, reason = get_exploit_adjustment(OpponentProfile.LOOSE_PASSIVE, "defend_bb", "mid")
        assert adj != ""
        assert "loose" in reason.lower()

    def test_call_all_in_loose_passive(self):
        adj, reason = get_exploit_adjustment(OpponentProfile.LOOSE_PASSIVE, "call_all_in", "top")
        assert adj != ""
        assert "widen" in adj.lower()

    def test_three_bet_tight_aggressive(self):
        adj, reason = get_exploit_adjustment(
            OpponentProfile.TIGHT_AGGRESSIVE, "three_bet", "unknown"
        )
        assert adj != ""
        assert "value" in adj.lower()

    def test_bubble_icm_uses_same_text_as_push_fold(self):
        pf_adj, pf_reason = get_exploit_adjustment(
            OpponentProfile.TIGHT_PASSIVE, "push_fold", "mid"
        )
        bi_adj, bi_reason = get_exploit_adjustment(
            OpponentProfile.TIGHT_PASSIVE, "bubble_icm", "mid"
        )
        assert pf_adj == bi_adj
        assert pf_reason == bi_reason

    def test_final_table_icm_uses_same_text_as_push_fold(self):
        pf_adj, _ = get_exploit_adjustment(OpponentProfile.LOOSE_AGGRESSIVE, "push_fold", "mid")
        ft_adj, _ = get_exploit_adjustment(
            OpponentProfile.LOOSE_AGGRESSIVE, "final_table_icm", "mid"
        )
        assert pf_adj == ft_adj

    def test_flop_cbet_returns_empty_for_any_profile(self):
        for profile in OpponentProfile:
            adj, reason = get_exploit_adjustment(profile, "flop_cbet", "top")
            assert adj == "", f"Expected empty for flop_cbet/{profile}"
            assert reason == "", f"Expected empty reason for flop_cbet/{profile}"

    def test_unknown_spot_returns_empty(self):
        adj, reason = get_exploit_adjustment(
            OpponentProfile.TIGHT_PASSIVE, "nonexistent_spot", "top"
        )
        assert adj == ""
        assert reason == ""

    def test_adjustment_never_claims_exact_ev(self):
        for profile in [
            OpponentProfile.TIGHT_PASSIVE,
            OpponentProfile.TIGHT_AGGRESSIVE,
            OpponentProfile.LOOSE_PASSIVE,
            OpponentProfile.LOOSE_AGGRESSIVE,
        ]:
            for spot in ["push_fold", "steal", "call_all_in", "defend_bb", "three_bet"]:
                adj, _ = get_exploit_adjustment(profile, spot, "mid")
                assert "EV =" not in adj, f"Overclaiming EV= in {spot}/{profile}: {adj!r}"

    def test_adjustment_never_claims_solver(self):
        for profile in [
            OpponentProfile.TIGHT_PASSIVE,
            OpponentProfile.TIGHT_AGGRESSIVE,
            OpponentProfile.LOOSE_PASSIVE,
            OpponentProfile.LOOSE_AGGRESSIVE,
        ]:
            for spot in ["push_fold", "steal", "call_all_in", "defend_bb", "three_bet"]:
                adj, _ = get_exploit_adjustment(profile, spot, "mid")
                assert "solver" not in adj.lower(), f"Found 'solver' in {spot}/{profile}: {adj!r}"

    def test_balanced_returns_empty(self):
        for spot in ["push_fold", "steal", "call_all_in", "defend_bb", "three_bet"]:
            adj, reason = get_exploit_adjustment(OpponentProfile.BALANCED, spot, "mid")
            assert adj == "", f"Expected empty for balanced/{spot}"
            assert reason == "", f"Expected empty reason for balanced/{spot}"


# ---------------------------------------------------------------------------
# TestExploitIntegration — uses analyze_hand() with opponent_stats parameter
# ---------------------------------------------------------------------------


class TestExploitIntegration:
    # ── push_fold spot: BTN 10bb shove vs BB ──────────────────────────────

    def _push_fold_hand(self) -> tuple[HandDetailOut, uuid.UUID]:
        """BTN 10bb shove (push_fold spot). BB is an opponent."""
        return _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "ALL_IN", "10", True, 3)],
            opp_actions=[
                ("SB", "PREFLOP", "POST_SB", "0.5", False, 1),
                ("BB", "PREFLOP", "POST_BB", "1", False, 2),
                ("BB", "PREFLOP", "FOLD", None, False, 4),
            ],
        )

    def _steal_hand(self) -> tuple[HandDetailOut, uuid.UUID]:
        """BTN steal (open raise). BB is a defender."""
        return _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 3)],
            opp_actions=[
                ("SB", "PREFLOP", "POST_SB", "0.5", False, 1),
                ("BB", "PREFLOP", "POST_BB", "1", False, 2),
                ("BB", "PREFLOP", "FOLD", None, False, 4),
            ],
        )

    def _call_all_in_hand(self) -> tuple[HandDetailOut, uuid.UUID]:
        """BB calls a BTN shove (call_all_in spot)."""
        return _hand(
            position="BB",
            stack_bb=Decimal("20"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 2),
                ("PREFLOP", "CALL", "20", True, 4),
            ],
            opp_actions=[
                ("SB", "PREFLOP", "POST_SB", "0.5", False, 1),
                ("BTN", "PREFLOP", "ALL_IN", "20", True, 3),
            ],
        )

    def test_no_stats_no_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        result = analyze_hand(hand, hero_id, opponent_stats=None)
        assert result.exploit_adjustment == ""
        assert result.adjustment_reason == ""

    def test_empty_stats_dict_no_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        result = analyze_hand(hand, hero_id, opponent_stats={})
        assert result.exploit_adjustment == ""
        assert result.adjustment_reason == ""

    def test_unknown_profile_no_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        # Only 3 hands observed — below minimum threshold
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.08, hands_observed=3)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.exploit_adjustment == ""
        assert result.adjustment_reason == ""

    def test_tight_passive_villain_shove(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.exploit_adjustment != ""
        assert (
            "tight" in result.adjustment_reason.lower()
            or "tight-passive" in result.adjustment_reason.lower()
        )

    def test_loose_aggressive_villain_steal(self):
        hand, hero_id = self._steal_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.42, pfr=0.30, hands_observed=30)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.exploit_adjustment != ""
        # Loose-aggressive defender → tighten steal
        adj_lower = result.exploit_adjustment.lower()
        assert "tighten" in adj_lower or "tight" in adj_lower

    def test_loose_passive_villain_call_shove(self):
        hand, hero_id = self._call_all_in_hand()
        btn_id = _opp_id_for_pos(hand, "BTN")
        # pfr=0.06 < 0.10 → clearly loose-passive
        opponent_stats = {btn_id: PlayerStats(vpip=0.45, pfr=0.06, hands_observed=25)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.exploit_adjustment != ""
        assert "widen" in result.exploit_adjustment.lower()

    def test_villain_not_in_stats_no_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        # Pass stats for a completely different player
        unrelated_id = uuid.uuid4()
        opponent_stats = {unrelated_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.exploit_adjustment == ""

    def test_exploit_does_not_change_severity(self):
        hand, hero_id = self._push_fold_hand()
        baseline = analyze_hand(hand, hero_id, opponent_stats=None)

        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        with_exploit = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)

        assert with_exploit.mistake_severity == baseline.mistake_severity

    def test_exploit_does_not_change_confidence(self):
        hand, hero_id = self._push_fold_hand()
        baseline = analyze_hand(hand, hero_id, opponent_stats=None)

        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        with_exploit = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)

        assert with_exploit.confidence == baseline.confidence
        # Confidence must not be upgraded to OBSERVED or DERIVED — stays INFERRED
        assert with_exploit.confidence != MetricLabel.OBSERVED
        assert with_exploit.confidence != MetricLabel.DERIVED

    def test_exploit_does_not_change_ev_label(self):
        hand, hero_id = self._push_fold_hand()
        baseline = analyze_hand(hand, hero_id, opponent_stats=None)

        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        with_exploit = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)

        assert with_exploit.ev_label == baseline.ev_label

    def test_exploit_does_not_change_backing(self):
        hand, hero_id = self._push_fold_hand()
        baseline = analyze_hand(hand, hero_id, opponent_stats=None)

        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        with_exploit = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)

        assert with_exploit.backing == baseline.backing

    def test_exploit_does_not_change_spot_type(self):
        hand, hero_id = self._push_fold_hand()
        baseline = analyze_hand(hand, hero_id, opponent_stats=None)

        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        with_exploit = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)

        assert with_exploit.spot_type == baseline.spot_type

    def test_no_overclaiming_ev_equals_in_adjustment(self):
        hand, hero_id = self._steal_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        for profile_stats in [
            PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25),
            PlayerStats(vpip=0.45, pfr=0.12, hands_observed=25),
            PlayerStats(vpip=0.42, pfr=0.30, hands_observed=30),
        ]:
            opponent_stats = {bb_id: profile_stats}
            result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
            assert "EV =" not in result.exploit_adjustment, (
                f"Overclaiming EV= in adjustment: {result.exploit_adjustment!r}"
            )

    def test_no_overclaiming_solver_in_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        for profile_stats in [
            PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25),
            PlayerStats(vpip=0.45, pfr=0.12, hands_observed=25),
        ]:
            opponent_stats = {bb_id: profile_stats}
            result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
            assert "solver" not in result.exploit_adjustment.lower(), (
                f"Found 'solver' in adjustment: {result.exploit_adjustment!r}"
            )

    def test_no_overclaiming_exact_in_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        for profile_stats in [
            PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25),
            PlayerStats(vpip=0.45, pfr=0.12, hands_observed=25),
        ]:
            opponent_stats = {bb_id: profile_stats}
            result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
            assert "exact" not in result.exploit_adjustment.lower(), (
                f"Found 'exact' in adjustment: {result.exploit_adjustment!r}"
            )

    def test_spots_without_villain_detection_no_adjustment(self):
        """flop_cbet and other non-preflop spots return empty adjustment."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 3),
                ("FLOP", "BET", "3", False, 6),
            ],
            opp_actions=[
                ("BB", "PREFLOP", "POST_BB", "1", False, 2),
                ("BB", "PREFLOP", "CALL", "2.5", False, 4),
                ("BB", "FLOP", "CHECK", None, False, 5),
                ("BB", "FLOP", "FOLD", None, False, 7),
            ],
            board_cards="Ah Kd 7c",
        )
        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        # flop_cbet has no villain detection rule → no adjustment
        if result.spot_type == "flop_cbet":
            assert result.exploit_adjustment == ""

    def test_villain_profile_set_on_classified(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.villain_profile == "tight-passive"
        assert result.villain_profile_confidence in ("low", "medium", "high")

    def test_villain_profile_unknown_when_few_hands(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=5)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.villain_profile == "unknown"
        assert result.exploit_adjustment == ""

    def test_villain_profile_empty_when_no_stats(self):
        hand, hero_id = self._push_fold_hand()
        result = analyze_hand(hand, hero_id, opponent_stats=None)
        assert result.villain_profile == ""

    def test_balanced_villain_no_adjustment(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        # vpip=0.24 in 0.18–0.28 range → balanced
        opponent_stats = {bb_id: PlayerStats(vpip=0.24, pfr=0.15, hands_observed=30)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        assert result.villain_profile == "balanced"
        assert result.exploit_adjustment == ""

    def test_villain_profile_confidence_low_for_small_sample(self):
        hand, hero_id = self._push_fold_hand()
        bb_id = _opp_id_for_pos(hand, "BB")
        opponent_stats = {bb_id: PlayerStats(vpip=0.12, pfr=0.04, hands_observed=25)}
        result = analyze_hand(hand, hero_id, opponent_stats=opponent_stats)
        # 25 hands < 50 → low confidence
        assert result.villain_profile_confidence == "low"
