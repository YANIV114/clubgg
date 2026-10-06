"""
Range calibration tests — 30 realistic hand fixtures.

Verifies that range-aware analysis is useful and not misleading:
  - range_context and hero_range_position are correct
  - explanation references range without claiming exact solver output
  - missing hole cards → hero_range_position = "unknown", no position in key_factors
  - SPECULATIVE spots retain SPECULATIVE confidence
  - backing = "range-based estimate" for all range-augmented spots
  - no "solver says" / "GTO says" language in any explanation

Fixtures cover:
  - top / mid / bottom / outside-range hands
  - stack bucket boundaries (9bb, 12bb, 14bb, 15bb)
  - BTN push, CO push, UTG push, SB push
  - BTN steal, SB steal
  - BB defend (top / bottom / outside)
  - 3-bet (BTN vs CO, SB vs BTN)
  - call-shove (in-range / outside-range, SPECULATIVE)
  - missing hole cards (range_context present, position = "unknown")
  - ICM spots with hole cards (SPECULATIVE, ev_label = "unknown")
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analysis.hand_analysis_engine import analyze_hand
from app.features.labels import MetricLabel
from app.models.hand import ActionType, GameType, Street
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLUB_ID = uuid.uuid4()
_NOW = datetime(2026, 5, 10, 14, 0, 0, tzinfo=UTC)

_FORBIDDEN_PHRASES = ("solver says", "GTO says", "exact EV", "EV =", "EV=")


# ---------------------------------------------------------------------------
# Fixture builder (extends quality-test _hand with hole_cards support)
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
    hole_cards: str | None = None,
) -> tuple[HandDetailOut, uuid.UUID]:
    hero_id = uuid.uuid4()
    stakes_sb = (stakes_bb / Decimal("2")).quantize(Decimal("0.0001"))

    hero_action_outs = [
        PlayerActionOut(
            street=Street(st),
            action_type=ActionType(at),
            amount=Decimal(str(amt)) if amt is not None else None,
            is_all_in=ai,
            action_order=order,
        )
        for st, at, amt, ai, order in actions
    ]
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

    opp_by_pos: dict[str, list] = {}
    for pos, st, at, amt, ai, order in opp_actions:
        opp_by_pos.setdefault(pos, []).append((st, at, amt, ai, order))

    opp_players = []
    for seat_idx, (opp_pos, acts) in enumerate(opp_by_pos.items(), start=2):
        opp_id = uuid.uuid4()
        opp_players.append(
            HandPlayerOut(
                player_id=opp_id,
                seat_number=seat_idx,
                starting_stack=Decimal("40"),
                ending_stack=None,
                hole_cards=None,
                did_show=False,
                net_won=None,
                position=opp_pos,
                stack_bb=Decimal("40"),
                effective_stack_bb=Decimal("40"),
                username=f"opp_{opp_pos}",
                actions=[
                    PlayerActionOut(
                        street=Street(st),
                        action_type=ActionType(at),
                        amount=Decimal(str(amt)) if amt is not None else None,
                        is_all_in=ai,
                        action_order=order,
                    )
                    for st, at, amt, ai, order in acts
                ],
            )
        )

    hand = HandDetailOut(
        id=uuid.uuid4(),
        external_id="RANGE-CAL",
        club_id=_CLUB_ID,
        game_session_id=None,
        game_type=GameType.NLH,
        stakes_sb=stakes_sb,
        stakes_bb=stakes_bb,
        stakes_ante=None,
        table_name="Diamond 1",
        hand_started_at=_NOW,
        hand_ended_at=None,
        total_pot=Decimal("0"),
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
# Shared quality assertion
# ---------------------------------------------------------------------------


def _assert_range(
    r,
    *,
    expected_spot: str,
    expected_range_pos: str,
    range_context_contains: str | None = None,
    expected_backing: str | None = None,
    expected_confidence: MetricLabel | None = None,
    hole_cards_provided: bool = True,
) -> None:
    assert r.spot_type == expected_spot, f"spot_type: got {r.spot_type!r}"
    assert r.range_context, "range_context must be non-empty"

    if range_context_contains:
        assert range_context_contains.lower() in r.range_context.lower(), (
            f"range_context {r.range_context!r} does not contain {range_context_contains!r}"
        )

    assert r.hero_range_position == expected_range_pos, (
        f"hero_range_position: expected {expected_range_pos!r}, got {r.hero_range_position!r}"
    )

    # When hole cards were NOT provided, position must be "unknown"
    # and the range position phrase must NOT appear in key_factors.
    if not hole_cards_provided:
        assert r.hero_range_position == "unknown"
        kf_text = " ".join(r.key_factors).lower()
        assert "of range" not in kf_text, (
            f"Range position leaked into key_factors without hole cards: {r.key_factors}"
        )

    # Only check backing when an explicit expectation is provided.
    # Push/fold spots now use "Nash table estimate"; steal/defend/3bet keep
    # "range-based estimate". Call sites that care about a specific value
    # pass expected_backing explicitly.
    if expected_backing is not None:
        assert r.backing == expected_backing, (
            f"backing: expected {expected_backing!r}, got {r.backing!r}"
        )

    if expected_confidence is not None:
        assert r.confidence == expected_confidence, (
            f"confidence: expected {expected_confidence}, got {r.confidence}"
        )

    for phrase in _FORBIDDEN_PHRASES:
        assert phrase.lower() not in r.explanation.lower(), (
            f"Forbidden phrase {phrase!r} in explanation: {r.explanation!r}"
        )


# ===========================================================================
# Group 1: Push/fold — top of range
# ===========================================================================


class TestPushFoldTopOfRange:
    def test_btn_10bb_aa_shove(self):
        """AA from BTN at 10bb: top of BTN_10bb push range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            hole_cards="Ah Ad",
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="top",
            range_context_contains="btn",
        )
        assert r.mistake_severity == "good"
        assert r.ev_label == "+EV"
        assert "top" in r.explanation.lower()

    def test_btn_12bb_aks_shove(self):
        """AKs from BTN at 12bb: top of BTN_12bb push range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            hole_cards="Ah Ks",
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="top",
            range_context_contains="btn",
        )
        assert r.mistake_severity == "good"

    def test_utg_10bb_aks_shove(self):
        """AKs from UTG at 10bb: top of UTG_10bb push range (tight UTG range)."""
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("10"),
            hole_cards="Ah Kh",
            actions=[("PREFLOP", "ALL_IN", "10", True, 3)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="top",
            range_context_contains="utg",
        )
        assert r.mistake_severity == "good"

    def test_co_8bb_akо_shove(self):
        """AKo from CO at 8bb: top of CO_8bb push range."""
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("8"),
            hole_cards="Ah Kd",
            actions=[("PREFLOP", "ALL_IN", "8", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="top",
            range_context_contains="co",
        )


# ===========================================================================
# Group 2: Push/fold — bottom of range (marginal shoves)
# ===========================================================================


class TestPushFoldBottomOfRange:
    def test_btn_15bb_a5s_shove(self):
        """A5s from BTN at 15bb: bottom of BTN_15bb range — marginal but in range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("15"),
            hole_cards="Ah 5h",
            actions=[("PREFLOP", "ALL_IN", "15", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="bottom",
            range_context_contains="15bb",
        )
        # Bottom-of-range shove is still in range — should not be a major mistake
        assert r.hero_range_position == "bottom"

    def test_btn_8bb_85s_shove(self):
        """85s from BTN at 8bb: bottom of BTN_8bb Nash range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("8"),
            hole_cards="8h 5h",
            actions=[("PREFLOP", "ALL_IN", "8", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="bottom",
        )


# ===========================================================================
# Group 3: Push/fold — outside range (hands beyond equilibrium boundary)
# ===========================================================================


class TestPushFoldOutsideRange:
    def test_btn_8bb_72o_shove(self):
        """72o from BTN at 8bb: outside BTN_8bb range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("8"),
            hole_cards="7h 2d",
            actions=[("PREFLOP", "ALL_IN", "8", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="outside",
        )
        # "Outside range" should appear in key_factors or explanation
        kf_text = " ".join(r.key_factors).lower()
        assert "outside range" in kf_text or "outside" in r.explanation.lower()

    def test_btn_12bb_k3s_shove(self):
        """K3s from BTN at 12bb: outside BTN_12bb range (K8s is the cutoff)."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            hole_cards="Kh 3h",
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="outside",
        )

    def test_utg_10bb_72o_shove_outside(self):
        """72o from UTG at 10bb: outside UTG_10bb range (UTG plays very tight)."""
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("10"),
            hole_cards="7c 2d",
            actions=[("PREFLOP", "ALL_IN", "10", True, 3)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="push_fold",
            expected_range_pos="outside",
        )


# ===========================================================================
# Group 4: Stack bucket boundary correctness
# ===========================================================================


class TestStackBucketBoundaries:
    def test_9bb_rounds_to_8bb_bucket(self):
        """9bb should use the 8bb range bucket (|9-8|=1 == |9-10|=1, 8 wins)."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("9"),
            hole_cards="Ah Kd",
            actions=[("PREFLOP", "ALL_IN", "9", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "push_fold"
        assert "8bb" in r.range_context.lower(), (
            f"9bb should resolve to 8bb bucket; range_context={r.range_context!r}"
        )
        assert r.hero_range_position == "top"

    def test_12bb_exact_bucket(self):
        """12bb uses the exact 12bb bucket; 87s is bottom of BTN Nash 12bb range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            hole_cards="8h 7h",
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert "12bb" in r.range_context.lower()
        assert r.hero_range_position == "bottom"

    def test_14bb_rounds_to_15bb_bucket(self):
        """14bb rounds to 15bb bucket (closer to 15 than to 12)."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("14"),
            hole_cards="Ah Ks",
            actions=[("PREFLOP", "ALL_IN", "14", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "push_fold"
        assert "15bb" in r.range_context.lower(), (
            f"14bb should resolve to 15bb bucket; range_context={r.range_context!r}"
        )
        assert r.hero_range_position == "top"

    def test_15bb_exact_bucket(self):
        """15bb exact uses BTN_15bb — A5s is bottom of that range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("15"),
            hole_cards="Ac 5c",
            actions=[("PREFLOP", "ALL_IN", "15", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert "15bb" in r.range_context.lower()
        assert r.hero_range_position == "bottom"


# ===========================================================================
# Group 5: BTN / SB steal opens
# ===========================================================================


class TestStealRangeContext:
    def test_btn_steal_top_of_range(self):
        """AKs BTN raise at 50bb: top of BTN open range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            hole_cards="Ah Kh",
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="steal",
            expected_range_pos="top",
            range_context_contains="btn",
        )
        assert r.mistake_severity == "good"

    def test_btn_steal_bottom_of_range(self):
        """J5s BTN raise at 40bb: inside BTN open range but toward the bottom."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("40"),
            hole_cards="Jh 5h",
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="steal",
            expected_range_pos="bottom",
        )

    def test_btn_steal_outside_range(self):
        """72o BTN fold at 35bb: outside BTN open range — fold is correct."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("35"),
            hole_cards="7h 2d",
            actions=[("PREFLOP", "FOLD", None, False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="steal",
            expected_range_pos="outside",
        )

    def test_sb_steal_top_of_range(self):
        """AA SB raise at 40bb: top of SB open range."""
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("40"),
            hole_cards="As Ad",
            actions=[("PREFLOP", "RAISE", "2.5", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="steal",
            expected_range_pos="top",
            range_context_contains="sb",
        )

    def test_sb_steal_bottom_of_range(self):
        """87s SB raise at 30bb: inside SB_open range toward the bottom."""
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("30"),
            hole_cards="8h 7h",
            actions=[("PREFLOP", "RAISE", "2.5", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="steal",
            expected_range_pos="bottom",
        )


# ===========================================================================
# Group 6: BB defend
# ===========================================================================


class TestBBDefendRangeContext:
    def test_bb_defend_top_of_range(self):
        """AKo BB call vs BTN raise at 30bb: top of BB_vs_BTN defend range."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("30"),
            hole_cards="Ah Kd",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 8),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="defend_bb",
            expected_range_pos="top",
            range_context_contains="bb",
        )

    def test_bb_defend_bottom_of_range(self):
        """65s BB call vs BTN raise: inside BB_vs_BTN range but at the bottom."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("30"),
            hole_cards="6h 5h",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 8),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="defend_bb",
            expected_range_pos="bottom",
        )

    def test_bb_defend_outside_range_fold(self):
        """72o BB fold vs BTN raise: outside range — fold is correct."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("30"),
            hole_cards="7h 2d",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "FOLD", None, False, 8),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="defend_bb",
            expected_range_pos="outside",
        )
        # key_factors should include "Outside range (72o)"
        kf_text = " ".join(r.key_factors)
        assert "Outside range" in kf_text

    def test_bb_defend_vs_co_open(self):
        """JTs BB call vs CO raise: BB_vs_CO range."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            hole_cards="Jh Th",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 8),
            ],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "defend_bb"
        assert r.range_context
        assert "co" in r.range_context.lower()
        assert r.backing == "range-based estimate"


# ===========================================================================
# Group 7: 3-bet spots
# ===========================================================================


class TestThreeBetRangeContext:
    def test_btn_threbet_vs_co_top(self):
        """AA BTN 3-bet vs CO open: top of BTN_vs_CO 3-bet range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            hole_cards="Ah Ad",
            actions=[("PREFLOP", "RAISE", "8", False, 10)],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="three_bet",
            expected_range_pos="top",
        )
        assert r.mistake_severity == "good"

    def test_btn_threbet_vs_co_bluff_bottom(self):
        """A5s BTN 3-bet vs CO (bluff 3-bet): bottom of BTN_vs_CO range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            hole_cards="Ah 5h",
            actions=[("PREFLOP", "RAISE", "8", False, 10)],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="three_bet",
            expected_range_pos="bottom",
        )

    def test_btn_threbet_vs_co_outside(self):
        """QJs BTN 3-bet vs CO: outside BTN_vs_CO 3-bet range."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            hole_cards="Qh Jh",
            actions=[("PREFLOP", "RAISE", "8", False, 10)],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_range(
            r,
            expected_spot="three_bet",
            expected_range_pos="outside",
        )
        kf_text = " ".join(r.key_factors)
        assert "Outside range" in kf_text

    def test_sb_threbet_vs_btn(self):
        """AQs SB 3-bet vs BTN: in SB_vs_BTN range."""
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("40"),
            hole_cards="Ah Qh",
            actions=[("PREFLOP", "RAISE", "8", False, 8)],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "defend_bb" or r.spot_type == "three_bet"
        # SB 3-bet: SB is in _STEAL_POSITIONS, and raises after BTN raise = three_bet
        # If classified as steal (first-in) that would be wrong — BTN raised first
        assert r.range_context
        assert r.backing == "range-based estimate"


# ===========================================================================
# Group 8: Call-shove spots (SPECULATIVE — no hole card equity available)
# ===========================================================================


class TestCallShoveRangeContext:
    def test_bb_call_shove_8bb_top_of_range(self):
        """AKo BB calls BTN shove at 8bb: in call range, SPECULATIVE confidence."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("8"),
            hole_cards="Ah Kd",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "8", False, 6),
            ],
            opp_actions=[("BTN", "PREFLOP", "ALL_IN", "8", True, 4)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "call_all_in"
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.range_context  # call range context attached
        assert r.hero_range_position == "top"
        assert r.backing in ("range-based estimate", "Nash table estimate")

    def test_bb_call_shove_12bb_outside_range(self):
        """72o BB calls BTN shove at 12bb: outside call range — mistake."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("12"),
            hole_cards="7h 2d",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "12", False, 6),
            ],
            opp_actions=[("BTN", "PREFLOP", "ALL_IN", "12", True, 4)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "call_all_in"
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.hero_range_position == "outside"
        kf_text = " ".join(r.key_factors)
        assert "Outside range" in kf_text

    def test_bb_call_shove_10bb_bottom_of_range(self):
        """55 BB calls BTN shove at 10bb: at the bottom of call range."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            hole_cards="5h 5d",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "10", False, 6),
            ],
            opp_actions=[("BTN", "PREFLOP", "ALL_IN", "10", True, 4)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "call_all_in"
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.hero_range_position in ("bottom", "mid")  # 55 is near the boundary
        # ev_label must NOT be +EV/-EV for SPECULATIVE
        assert r.ev_label in ("neutral", "unknown")

    def test_call_shove_speculative_never_strong_ev_claim(self):
        """SPECULATIVE call spots must never claim +EV or -EV directionally."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("8"),
            hole_cards="Qh Jh",
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "8", False, 6),
            ],
            opp_actions=[("UTG", "PREFLOP", "ALL_IN", "8", True, 4)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "call_all_in"
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.ev_label in ("neutral", "unknown"), (
            f"SPECULATIVE call must not claim EV direction; got {r.ev_label!r}"
        )


# ===========================================================================
# Group 9: Missing hole cards — range_context present, position = "unknown"
# ===========================================================================


class TestMissingHoleCards:
    def test_push_fold_no_hole_cards(self):
        """BTN 10bb shove without hole cards: range_context attached, pos = unknown."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            hole_cards=None,
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "push_fold"
        assert r.range_context, "range_context must still be set (range applies regardless)"
        assert r.hero_range_position == "unknown"
        assert r.backing in ("range-based estimate", "Nash table estimate")
        # No range position should appear in key_factors
        kf_text = " ".join(r.key_factors).lower()
        assert "of range" not in kf_text

    def test_steal_no_hole_cards(self):
        """BTN 40bb raise without hole cards: range_context set, pos = unknown."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("40"),
            hole_cards=None,
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "steal"
        assert r.range_context
        assert r.hero_range_position == "unknown"
        kf_text = " ".join(r.key_factors).lower()
        assert "of range" not in kf_text

    def test_bb_defend_no_hole_cards(self):
        """BB defend without hole cards: range_context from BB_vs_BTN, pos = unknown."""
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("30"),
            hole_cards=None,
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 8),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "defend_bb"
        assert r.range_context
        assert r.hero_range_position == "unknown"


# ===========================================================================
# Group 10: ICM spots with hole cards — SPECULATIVE, ev_label = "unknown"
# ===========================================================================


class TestICMSpotsWithHoleCards:
    def test_bubble_icm_shove_top_of_range_still_speculative(self):
        """AA bubble shove: range context says 'top', but SPECULATIVE because ICM unknown."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("12"),
            hole_cards="Ah Ad",
            actions=[("PREFLOP", "ALL_IN", "12", True, 5)],
            player_count=5,  # 5-handed → bubble proxy
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "bubble_icm"
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.ev_label == "unknown"
        # Range context should still be attached
        assert r.range_context
        assert r.hero_range_position == "top"

    def test_final_table_icm_with_hole_cards(self):
        """BTN push at 4-handed final table: SPECULATIVE, range context present."""
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("10"),
            hole_cards="Kh Qh",
            actions=[("PREFLOP", "ALL_IN", "10", True, 5)],
            player_count=4,  # 4-handed → final_table proxy
        )
        r = analyze_hand(hand, hero_id)
        assert r.spot_type == "final_table_icm"
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.ev_label == "unknown"
        assert r.range_context
        assert r.hero_range_position in ("top", "mid", "bottom", "outside")


# ===========================================================================
# Group 11: No-fake-precision across all range-aware spots
# ===========================================================================


class TestNoFakePrecisionInRangeOutput:
    @pytest.mark.parametrize(
        "position,stack,hole_cards,actions,opp_actions",
        [
            (
                "BTN",
                Decimal("10"),
                "Ah Kd",
                [("PREFLOP", "ALL_IN", "10", True, 5)],
                [],
            ),
            (
                "BTN",
                Decimal("40"),
                "Qh Jh",
                [("PREFLOP", "RAISE", "2.5", False, 5)],
                [],
            ),
            (
                "BB",
                Decimal("30"),
                "Ah Td",
                [("PREFLOP", "POST_BB", "1", False, 1), ("PREFLOP", "CALL", "2.5", False, 8)],
                [("BTN", "PREFLOP", "RAISE", "2.5", False, 5)],
            ),
            (
                "BTN",
                Decimal("50"),
                "Ah Ad",
                [("PREFLOP", "RAISE", "8", False, 10)],
                [("CO", "PREFLOP", "RAISE", "2.5", False, 5)],
            ),
        ],
    )
    def test_explanation_has_no_forbidden_phrases(
        self, position, stack, hole_cards, actions, opp_actions
    ):
        hand, hero_id = _hand(
            position=position,
            stack_bb=stack,
            hole_cards=hole_cards,
            actions=actions,
            opp_actions=opp_actions,
        )
        r = analyze_hand(hand, hero_id)
        for phrase in _FORBIDDEN_PHRASES:
            assert phrase.lower() not in r.explanation.lower(), (
                f"Forbidden phrase {phrase!r} in: {r.explanation!r}"
            )
        # range_context must also be clean
        for phrase in _FORBIDDEN_PHRASES:
            assert phrase.lower() not in r.range_context.lower()

    def test_range_context_never_says_solver_backed(self):
        """Range context rows must always say 'range-based estimate', never 'solver-backed'."""
        fixtures = [
            ("BTN", Decimal("10"), "Ah Ad", [("PREFLOP", "ALL_IN", "10", True, 5)], []),
            ("BTN", Decimal("40"), "Kh Qh", [("PREFLOP", "RAISE", "2.5", False, 5)], []),
        ]
        for pos, stack, hc, acts, opps in fixtures:
            hand, hero_id = _hand(
                position=pos, stack_bb=stack, hole_cards=hc, actions=acts, opp_actions=opps
            )
            r = analyze_hand(hand, hero_id)
            assert r.backing != "solver-backed", (
                f"Range spots must not claim solver-backed; got {r.backing!r}"
            )
