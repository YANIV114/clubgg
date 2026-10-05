"""
Tests for app/analysis/nash_pushfold.py and its integration with hand_analysis_engine.py

All tests are pure — no database fixture needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.analysis.hand_analysis_engine import HandAnalysisResult, analyze_hand
from app.analysis.nash_pushfold import (
    NASH_BACKING,
    NASH_CALL_RANGES,
    NASH_SHOVE_RANGES,
    classify_hand_nash,
    get_nash_call_range,
    get_nash_shove_range,
)
from app.features.labels import MetricLabel
from app.models.hand import ActionType, GameType, Street
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLUB_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_NOW = datetime(2024, 1, 15, 22, 31, 7, tzinfo=UTC)

_POSITIONS = ("BTN", "CO", "HJ", "UTG", "SB")
_DEPTHS = (5, 8, 10, 12, 15)


# ---------------------------------------------------------------------------
# Fixture helper (mirrors test_hand_analysis_engine.py helper)
# ---------------------------------------------------------------------------


def _hand(
    *,
    position: str,
    stack_bb: Decimal,
    actions: list[tuple],
    player_count: int = 6,
    opp_actions: list[tuple] = (),
    stakes_bb: Decimal = Decimal("1"),
    hole_cards: str | None = None,
    opp_stack_bb: Decimal = Decimal("25"),
) -> tuple[HandDetailOut, uuid.UUID]:
    """Build a minimal HandDetailOut + hero_player_id for testing."""
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
        hole_cards=hole_cards,
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
                starting_stack=(opp_stack_bb * stakes_bb).quantize(Decimal("0.0001")),
                ending_stack=None,
                hole_cards=None,
                did_show=False,
                net_won=None,
                position=opp_pos,
                stack_bb=opp_stack_bb,
                effective_stack_bb=opp_stack_bb,
                username=f"opp_{opp_pos}",
                actions=opp_action_outs,
            )
        )

    hand = HandDetailOut(
        id=uuid.uuid4(),
        external_id="NASH-TEST-001",
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
        board_cards=None,
        player_count=player_count,
        ingestion_source="file",
        button_seat=None,
        hand_players=[hero_hp] + opp_players,
        winners=[],
    )
    return hand, hero_id


# ---------------------------------------------------------------------------
# TestNashShoveRanges — raw range dict checks
# ---------------------------------------------------------------------------


class TestNashShoveRanges:
    def test_all_position_depth_keys_exist(self):
        """Every position × depth combination must exist in NASH_SHOVE_RANGES."""
        for pos in _POSITIONS:
            for depth in _DEPTHS:
                key = f"{pos}_{depth}bb"
                assert key in NASH_SHOVE_RANGES, f"Missing key: {key}"

    def test_premiums_in_all_ranges(self):
        """AA, KK, AKs should be in every shove range."""
        for pos in _POSITIONS:
            for depth in _DEPTHS:
                key = f"{pos}_{depth}bb"
                rng = NASH_SHOVE_RANGES[key]
                assert "AA" in rng, f"AA missing from {key}"
                assert "KK" in rng, f"KK missing from {key}"
                assert "AKs" in rng, f"AKs missing from {key}"

    def test_btn_wider_than_utg_at_same_depth(self):
        """BTN ranges must be wider (more combos) than UTG at every depth."""
        for depth in _DEPTHS:
            btn = NASH_SHOVE_RANGES[f"BTN_{depth}bb"]
            utg = NASH_SHOVE_RANGES[f"UTG_{depth}bb"]
            assert len(btn) > len(utg), (
                f"BTN_{depth}bb ({len(btn)}) not wider than UTG_{depth}bb ({len(utg)})"
            )

    def test_co_wider_than_hj_at_same_depth(self):
        """CO ranges must be at least as wide as HJ at every depth."""
        for depth in _DEPTHS:
            co = NASH_SHOVE_RANGES[f"CO_{depth}bb"]
            hj = NASH_SHOVE_RANGES[f"HJ_{depth}bb"]
            assert len(co) >= len(hj), f"CO_{depth}bb ({len(co)}) not >= HJ_{depth}bb ({len(hj)})"

    def test_deeper_stack_tighter_range_btn(self):
        """BTN shove range must narrow monotonically as stack depth increases."""
        depths = list(_DEPTHS)
        sizes = [len(NASH_SHOVE_RANGES[f"BTN_{d}bb"]) for d in depths]
        for i in range(len(sizes) - 1):
            assert sizes[i] > sizes[i + 1], (
                f"BTN_{depths[i]}bb ({sizes[i]}) not wider than BTN_{depths[i + 1]}bb ({sizes[i + 1]})"
            )

    def test_deeper_stack_tighter_range_utg(self):
        """UTG shove range must narrow monotonically as stack depth increases."""
        depths = list(_DEPTHS)
        sizes = [len(NASH_SHOVE_RANGES[f"UTG_{d}bb"]) for d in depths]
        for i in range(len(sizes) - 1):
            assert sizes[i] > sizes[i + 1], (
                f"UTG_{depths[i]}bb ({sizes[i]}) not wider than UTG_{depths[i + 1]}bb ({sizes[i + 1]})"
            )

    def test_btn_5bb_near_any2(self):
        """BTN 5bb should contain at least 130 combos (near any-two)."""
        rng = NASH_SHOVE_RANGES["BTN_5bb"]
        assert len(rng) >= 130, f"BTN_5bb has only {len(rng)} combos, expected >= 130"

    def test_utg_15bb_is_tight(self):
        """UTG 15bb should contain at most 30 combos."""
        rng = NASH_SHOVE_RANGES["UTG_15bb"]
        assert len(rng) <= 30, f"UTG_15bb has {len(rng)} combos, expected <= 30"

    def test_sb_5bb_near_any2(self):
        """SB 5bb heads-up should be near 100% (>= 130 combos)."""
        rng = NASH_SHOVE_RANGES["SB_5bb"]
        assert len(rng) >= 130, f"SB_5bb has only {len(rng)} combos, expected >= 130"

    def test_trash_hand_outside_tight_ranges(self):
        """72o (trash) should not be in UTG tight ranges."""
        for depth in (10, 12, 15):
            rng = NASH_SHOVE_RANGES[f"UTG_{depth}bb"]
            assert "72o" not in rng, f"72o incorrectly in UTG_{depth}bb"

    def test_72o_in_btn_5bb(self):
        """72o should be in BTN 5bb (near any-two)."""
        rng = NASH_SHOVE_RANGES["BTN_5bb"]
        assert "72o" in rng, "72o missing from BTN_5bb (should be near any-two)"

    def test_all_ranges_are_frozensets(self):
        """All expanded ranges must be frozensets of strings."""
        for key, rng in NASH_SHOVE_RANGES.items():
            assert isinstance(rng, frozenset), f"{key} is not a frozenset"
            for hand in rng:
                assert isinstance(hand, str), f"{key}: {hand!r} is not a str"

    def test_ranges_only_contain_valid_hands(self):
        """All hand strings must be 2 or 3 characters (canonical form)."""
        for key, rng in NASH_SHOVE_RANGES.items():
            for hand in rng:
                assert len(hand) in (2, 3), f"{key}: invalid hand string {hand!r}"


# ---------------------------------------------------------------------------
# TestNashCallRanges — raw range dict checks
# ---------------------------------------------------------------------------


class TestNashCallRanges:
    def test_bb_vs_btn_call_range_exists_at_8bb(self):
        assert "BB_vs_BTN_8bb" in NASH_CALL_RANGES

    def test_aa_in_every_call_range(self):
        """AA must be in every call range — it's always a call."""
        for key, rng in NASH_CALL_RANGES.items():
            assert "AA" in rng, f"AA missing from call range {key}"

    def test_kk_in_every_call_range(self):
        """KK must be in every call range."""
        for key, rng in NASH_CALL_RANGES.items():
            assert "KK" in rng, f"KK missing from call range {key}"

    def test_bb_vs_utg_tighter_than_bb_vs_btn(self):
        """BB should call tighter vs UTG (tighter shover) than vs BTN at same depth."""
        for depth in (8, 10):
            btn_rng = NASH_CALL_RANGES.get(f"BB_vs_BTN_{depth}bb", frozenset())
            utg_rng = NASH_CALL_RANGES.get(f"BB_vs_UTG_{depth}bb", frozenset())
            if btn_rng and utg_rng:
                assert len(btn_rng) > len(utg_rng), (
                    f"BB_vs_BTN_{depth}bb ({len(btn_rng)}) not wider than "
                    f"BB_vs_UTG_{depth}bb ({len(utg_rng)})"
                )

    def test_deeper_stack_tighter_call_bb_vs_btn(self):
        """BB call range vs BTN should narrow as stack depth increases."""
        depths = (5, 8, 10, 12, 15)
        sizes = [len(NASH_CALL_RANGES[f"BB_vs_BTN_{d}bb"]) for d in depths]
        for i in range(len(sizes) - 1):
            assert sizes[i] > sizes[i + 1], (
                f"BB_vs_BTN_{depths[i]}bb ({sizes[i]}) not wider than "
                f"BB_vs_BTN_{depths[i + 1]}bb ({sizes[i + 1]})"
            )

    def test_call_ranges_are_frozensets(self):
        for key, rng in NASH_CALL_RANGES.items():
            assert isinstance(rng, frozenset), f"{key} is not a frozenset"

    def test_trash_not_in_deep_call_ranges(self):
        """72o should not be in any call range."""
        for key, rng in NASH_CALL_RANGES.items():
            assert "72o" not in rng, f"72o incorrectly in call range {key}"


# ---------------------------------------------------------------------------
# TestGetNashShoveRange — accessor function
# ---------------------------------------------------------------------------


class TestGetNashShoveRange:
    def test_known_position_and_depth_returns_correct_key(self):
        rng, key = get_nash_shove_range("BTN", 10.0)
        assert key == "BTN_10bb"
        assert len(rng) > 0
        assert "AA" in rng

    def test_returns_frozenset_and_str_tuple(self):
        result = get_nash_shove_range("CO", 8.0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        rng, key = result
        assert isinstance(rng, frozenset)
        assert isinstance(key, str)

    def test_9bb_rounds_to_8bb(self):
        _, key = get_nash_shove_range("BTN", 9.0)
        assert key == "BTN_8bb"

    def test_7bb_rounds_to_8bb(self):
        _, key = get_nash_shove_range("BTN", 7.0)
        assert key == "BTN_8bb"

    def test_6bb_rounds_to_5bb(self):
        _, key = get_nash_shove_range("BTN", 6.0)
        assert key == "BTN_5bb"

    def test_14bb_rounds_to_15bb(self):
        _, key = get_nash_shove_range("BTN", 14.0)
        assert key == "BTN_15bb"

    def test_11bb_rounds_to_10bb(self):
        _, key = get_nash_shove_range("UTG", 11.0)
        assert key == "UTG_10bb"

    def test_unknown_position_falls_back_non_empty(self):
        """An unknown position should return a non-empty range (fallback to UTG)."""
        rng, key = get_nash_shove_range("MP2", 10.0)
        assert len(rng) > 0
        assert key != ""

    def test_unknown_position_returns_utg_fallback(self):
        """Unknown positions should fall back to UTG (tightest)."""
        _, key = get_nash_shove_range("UNKNOWN_POS", 10.0)
        assert "10bb" in key

    def test_all_positions_return_nonempty(self):
        for pos in _POSITIONS:
            for depth in (5.0, 8.0, 10.0, 12.0, 15.0):
                rng, key = get_nash_shove_range(pos, depth)
                assert len(rng) > 0, f"Empty range for {pos} at {depth}bb"
                assert key != "", f"Empty key for {pos} at {depth}bb"

    def test_case_insensitive(self):
        rng_upper, key_upper = get_nash_shove_range("BTN", 10.0)
        rng_lower, key_lower = get_nash_shove_range("btn", 10.0)
        assert rng_upper == rng_lower
        assert key_upper == key_lower

    def test_exact_depth_boundaries(self):
        """Exact depth values should return their own key."""
        for pos in ("BTN", "UTG"):
            for depth in (5, 8, 10, 12, 15):
                _, key = get_nash_shove_range(pos, float(depth))
                assert key == f"{pos}_{depth}bb", f"Expected {pos}_{depth}bb, got {key}"


# ---------------------------------------------------------------------------
# TestGetNashCallRange — accessor function
# ---------------------------------------------------------------------------


class TestGetNashCallRange:
    def test_bb_vs_btn_10bb_returns_known_range(self):
        rng, key = get_nash_call_range("BB", "BTN", 10.0)
        assert key == "BB_vs_BTN_10bb"
        assert "AA" in rng
        assert "KK" in rng

    def test_bb_vs_utg_8bb(self):
        rng, key = get_nash_call_range("BB", "UTG", 8.0)
        assert key == "BB_vs_UTG_8bb"
        assert "AA" in rng

    def test_returns_frozenset_and_str_tuple(self):
        result = get_nash_call_range("BB", "BTN", 8.0)
        assert isinstance(result, tuple)
        rng, key = result
        assert isinstance(rng, frozenset)
        assert isinstance(key, str)

    def test_unknown_villain_position_falls_back(self):
        """Unknown villain position should fall back to a non-empty range."""
        rng, key = get_nash_call_range("BB", "UNKNOWN_POS", 10.0)
        assert len(rng) > 0
        assert key != ""

    def test_unknown_villain_falls_back_to_btn(self):
        """Unknown villain falls back to BTN call range (widest shover assumption)."""
        _, key_unknown = get_nash_call_range("BB", "DEADPOS", 10.0)
        _, key_btn = get_nash_call_range("BB", "BTN", 10.0)
        assert key_unknown == key_btn

    def test_case_insensitive(self):
        rng_upper, key_upper = get_nash_call_range("BB", "BTN", 10.0)
        rng_lower, key_lower = get_nash_call_range("bb", "btn", 10.0)
        assert rng_upper == rng_lower
        assert key_upper == key_lower

    def test_9bb_rounds_correctly(self):
        _, key = get_nash_call_range("BB", "BTN", 9.0)
        assert "8bb" in key

    def test_sb_vs_btn_8bb_exists(self):
        rng, key = get_nash_call_range("SB", "BTN", 8.0)
        assert key == "SB_vs_BTN_8bb"
        assert len(rng) > 0


# ---------------------------------------------------------------------------
# TestClassifyHandNash
# ---------------------------------------------------------------------------


class TestClassifyHandNash:
    def test_aa_is_top_in_any_range(self):
        for pos in _POSITIONS:
            for depth in _DEPTHS:
                rng = NASH_SHOVE_RANGES[f"{pos}_{depth}bb"]
                result = classify_hand_nash("AA", rng)
                assert result == "top", f"AA should be 'top' in {pos}_{depth}bb, got {result!r}"

    def test_72o_outside_tight_utg_range(self):
        for depth in (10, 12, 15):
            rng = NASH_SHOVE_RANGES[f"UTG_{depth}bb"]
            result = classify_hand_nash("72o", rng)
            assert result == "outside", f"72o should be 'outside' UTG_{depth}bb, got {result!r}"

    def test_72o_in_btn_5bb(self):
        """72o is in BTN 5bb (any-two), classify_hand_nash should return non-outside."""
        rng = NASH_SHOVE_RANGES["BTN_5bb"]
        result = classify_hand_nash("72o", rng)
        assert result in ("top", "mid", "bottom"), f"72o should be in BTN_5bb range, got {result!r}"

    def test_returns_valid_classification(self):
        valid = {"top", "mid", "bottom", "outside"}
        rng = NASH_SHOVE_RANGES["BTN_10bb"]
        for hand in ("AA", "KK", "AKs", "AKo", "22", "72o", "32o"):
            result = classify_hand_nash(hand, rng)
            assert result in valid, f"classify_hand_nash({hand!r}) returned {result!r}"

    def test_hand_outside_empty_range(self):
        """Any hand vs empty range is 'outside'."""
        result = classify_hand_nash("AA", frozenset())
        assert result == "outside"

    def test_kk_is_top_in_tight_ranges(self):
        """KK should be in the top third of UTG tight ranges."""
        for depth in (12, 15):
            rng = NASH_SHOVE_RANGES[f"UTG_{depth}bb"]
            result = classify_hand_nash("KK", rng)
            assert result == "top", f"KK should be 'top' in UTG_{depth}bb, got {result!r}"

    def test_bottom_hand_in_wide_range(self):
        """A very weak hand that is technically in BTN_5bb should be 'bottom'."""
        rng = NASH_SHOVE_RANGES["BTN_5bb"]
        # 32o is trash but in BTN_5bb any-two range
        assert "32o" in rng
        result = classify_hand_nash("32o", rng)
        assert result == "bottom"


# ---------------------------------------------------------------------------
# TestNashIntegration — hand analysis engine uses Nash tables
# ---------------------------------------------------------------------------


class TestNashIntegration:
    def test_btn_10bb_shove_backing_is_nash(self):
        """BTN push_fold shove at 10bb should use Nash table backing."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert result.backing == NASH_BACKING, f"Expected Nash backing, got {result.backing!r}"

    def test_btn_10bb_range_context_contains_nash(self):
        """range_context should mention 'Nash' for push_fold spots."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert "Nash" in result.range_context, (
            f"'Nash' not in range_context: {result.range_context!r}"
        )

    def test_btn_10bb_key_factors_include_nash_table(self):
        """key_factors should include 'Nash table: BTN_10bb' entry."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert any("Nash table: BTN_10bb" in f for f in result.key_factors), (
            f"'Nash table: BTN_10bb' not found in key_factors: {result.key_factors}"
        )

    def test_btn_10bb_with_hole_cards_explanation_mentions_nash(self):
        """Explanation should reference Nash range when hole cards are known."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
            player_count=6,
            hole_cards="Ah Kd",  # AKo — top of range
        )
        result = analyze_hand(hand, hero_id)
        # Explanation should reference Nash shove range
        assert "Nash" in result.explanation, f"'Nash' not in explanation: {result.explanation!r}"

    def test_utg_8bb_shove_backing_is_nash(self):
        """UTG push_fold shove at 8bb should use Nash table backing."""
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("8"),
            actions=[("PREFLOP", "ALL_IN", "8", True, 5)],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert result.backing == NASH_BACKING

    def test_bb_call_allin_10bb_vs_btn_backing_is_nash(self):
        """BB call_all_in at 10bb vs BTN shove should use Nash call range."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "10", False, 10),
            ],
            opp_actions=[
                ("BTN", "PREFLOP", "ALL_IN", "10", True, 5),
            ],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "call_all_in"
        assert result.backing == NASH_BACKING, (
            f"Expected Nash backing for call_all_in, got {result.backing!r}"
        )

    def test_bb_call_allin_range_context_contains_nash(self):
        """call_all_in range_context should mention 'Nash'."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "10", False, 10),
            ],
            opp_actions=[
                ("BTN", "PREFLOP", "ALL_IN", "10", True, 5),
            ],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert "Nash" in result.range_context, (
            f"'Nash' not in range_context: {result.range_context!r}"
        )

    def _call_vs_shove(self, hero_bb: str, shover_bb: str) -> HandAnalysisResult:
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal(hero_bb),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", shover_bb, False, 10),
            ],
            opp_actions=[("BTN", "PREFLOP", "ALL_IN", shover_bb, True, 5)],
            opp_stack_bb=Decimal(shover_bb),
            hole_cards="7h 2c",
        )
        return analyze_hand(hand, hero_id)

    def test_call_allin_depth_is_effective_stack(self):
        """Deep hero vs 10bb shover: the call is a 10bb spot, not a 40bb one."""
        result = self._call_vs_shove(hero_bb="40", shover_bb="10")
        assert "10bb" in result.range_context, result.range_context
        assert result.hero_range_position == "outside"

    def test_call_allin_not_judged_when_effective_stack_too_deep(self):
        """Nash tables stop at 15bb; a 30bb-effective call must not be judged by them."""
        result = self._call_vs_shove(hero_bb="57", shover_bb="30")
        assert result.spot_type == "call_all_in"
        assert result.hero_range_position == "unknown"
        assert result.backing != NASH_BACKING

    def test_call_allin_not_judged_vs_tiny_shove(self):
        """Calling a 2bb shove is a pot-odds call; the 5bb table would over-flag it."""
        result = self._call_vs_shove(hero_bb="57", shover_bb="2")
        assert result.hero_range_position == "unknown"

    def test_call_allin_multiway_not_judged(self):
        """Overcalling a shove after another caller isn't a heads-up Nash spot."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "10", False, 10),
            ],
            opp_actions=[
                ("UTG", "PREFLOP", "ALL_IN", "10", True, 5),
                ("CO", "PREFLOP", "CALL", "10", False, 7),
            ],
            opp_stack_bb=Decimal("10"),
            hole_cards="Qh Jc",
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "call_all_in"
        assert result.hero_range_position == "unknown"

    def test_call_allin_uses_shover_before_hero(self):
        """A player who goes all-in after hero's call is not the shover hero faced."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "10", False, 10),
            ],
            # CO listed first so it precedes BTN in hand_players.
            opp_actions=[
                ("CO", "PREFLOP", "ALL_IN", "10", True, 12),
                ("BTN", "PREFLOP", "ALL_IN", "10", True, 5),
                ("SB", "PREFLOP", "FOLD", None, False, 6),
            ],
            opp_stack_bb=Decimal("10"),
            hole_cards="Qh Jc",
        )
        result = analyze_hand(hand, hero_id)
        assert "vs BTN" in result.range_context, result.range_context

    def _call_raise(self, position: str, hero_bb: str) -> HandAnalysisResult:
        hero_actions = [("PREFLOP", "CALL", "2.2", False, 10)]
        if position == "BB":
            hero_actions.insert(0, ("PREFLOP", "POST_BB", "1", False, 1))
        hand, hero_id = _hand(
            position=position,
            stack_bb=Decimal(hero_bb),
            actions=hero_actions,
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.2", False, 5)],
            player_count=8,
        )
        return analyze_hand(hand, hero_id)

    def test_bb_calling_single_raise_at_13bb_is_not_a_mistake(self):
        """BB defend by calling a min-raise is standard at 13bb (pot odds + antes)."""
        result = self._call_raise("BB", "13")
        assert result.mistake_severity not in ("critical", "major")

    def test_bb_calling_single_raise_at_8bb_is_minor(self):
        result = self._call_raise("BB", "8")
        assert result.mistake_severity == "minor"

    def test_non_blind_flat_call_short_is_still_a_mistake(self):
        result = self._call_raise("CO", "12")
        assert result.mistake_severity in ("critical", "major")

    def test_bubble_icm_spot_stays_speculative_with_nash(self):
        """bubble_icm spots must stay SPECULATIVE even when Nash range is used."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
            player_count=5,  # triggers bubble_icm
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "bubble_icm"
        assert result.confidence == MetricLabel.SPECULATIVE, (
            f"bubble_icm should be SPECULATIVE, got {result.confidence}"
        )

    def test_final_table_icm_spot_stays_speculative_with_nash(self):
        """final_table_icm spots must stay SPECULATIVE even when Nash range is used."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
            player_count=3,  # triggers final_table_icm
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "final_table_icm"
        assert result.confidence == MetricLabel.SPECULATIVE, (
            f"final_table_icm should be SPECULATIVE, got {result.confidence}"
        )

    def test_bubble_icm_ev_label_is_unknown(self):
        """bubble_icm ev_label must not claim +EV or -EV (ICM unknown)."""
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("12"),
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
            player_count=5,
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "bubble_icm"
        assert result.ev_label == "unknown", (
            f"bubble_icm ev_label should be 'unknown', got {result.ev_label!r}"
        )

    def test_push_fold_backing_is_nash_not_range_based(self):
        """push_fold backing should be Nash table estimate, not range-based estimate."""
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("8"),
            actions=[("PREFLOP", "ALL_IN", "8", True, 5)],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "push_fold"
        assert result.backing == NASH_BACKING
        assert result.backing != "range-based estimate"

    def test_steal_spot_does_not_use_nash(self):
        """Steal spots (deep stack) should not use Nash backing (Nash is push/fold only)."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("30"),  # deep — steal, not push/fold
            actions=[("PREFLOP", "RAISE", "3", False, 5)],
            player_count=6,
        )
        result = analyze_hand(hand, hero_id)
        assert result.spot_type == "steal"
        assert result.backing != NASH_BACKING, "Steal spots should not use Nash backing"


# ---------------------------------------------------------------------------
# TestNashNoOverclaiming — epistemic integrity checks
# ---------------------------------------------------------------------------


class TestNashNoOverclaiming:
    def _get_push_fold_result(self, position: str = "BTN", depth: float = 10.0):
        hand, hero_id = _hand(
            position=position,
            stack_bb=Decimal(str(int(depth))),
            actions=[("PREFLOP", "ALL_IN", str(int(depth)), True, 5)],
            player_count=6,
        )
        return analyze_hand(hand, hero_id)

    def _get_bubble_icm_result(self):
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
            player_count=5,
        )
        return analyze_hand(hand, hero_id)

    def test_backing_is_not_solver_backed(self):
        """No analysis result should claim 'solver-backed' backing."""
        result = self._get_push_fold_result()
        assert result.backing != "solver-backed", (
            f"backing must not claim solver-backed, got {result.backing!r}"
        )

    def test_gto_says_not_in_explanation(self):
        """Explanations must not use 'GTO says'."""
        for pos in ("BTN", "UTG", "CO"):
            result = self._get_push_fold_result(pos)
            assert "GTO says" not in result.explanation, (
                f"'GTO says' found in explanation for {pos}: {result.explanation!r}"
            )

    def test_exact_ev_not_in_explanation(self):
        """Explanations must not claim 'exact EV'."""
        result = self._get_push_fold_result()
        assert "exact EV" not in result.explanation, (
            f"'exact EV' found in explanation: {result.explanation!r}"
        )

    def test_speculative_spot_ev_label_not_plus_ev(self):
        """SPECULATIVE spots (ICM) must not claim +EV."""
        result = self._get_bubble_icm_result()
        assert result.confidence == MetricLabel.SPECULATIVE
        assert result.ev_label != "+EV", "SPECULATIVE bubble_icm should not have '+EV' ev_label"

    def test_nash_backing_constant_value(self):
        """NASH_BACKING must equal 'Nash table estimate' (not 'solver output')."""
        assert NASH_BACKING == "Nash table estimate"
        assert "solver" not in NASH_BACKING.lower()

    def test_push_fold_explanation_no_solver_language(self):
        """Push/fold explanations must not contain solver language."""
        forbidden = ["solver", "GTO says", "exact EV", "equilibrium EV"]
        for pos in ("BTN", "UTG", "SB"):
            result = self._get_push_fold_result(pos)
            for phrase in forbidden:
                assert phrase.lower() not in result.explanation.lower(), (
                    f"Forbidden phrase {phrase!r} found in explanation for {pos}: "
                    f"{result.explanation!r}"
                )

    def test_nash_module_does_not_import_engine(self):
        """nash_pushfold must not import from hand_analysis_engine (one-way dependency)."""
        import importlib
        import sys

        # Remove cached module if present
        mod_name = "app.analysis.nash_pushfold"
        if mod_name in sys.modules:
            module = sys.modules[mod_name]
        else:
            module = importlib.import_module(mod_name)

        # Check the module's __dict__ for engine imports
        source_file = module.__file__ or ""
        with open(source_file) as f:
            source = f.read()
        assert "hand_analysis_engine" not in source, (
            "nash_pushfold.py must not import from hand_analysis_engine"
        )
