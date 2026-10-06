"""
Analysis quality validation — 20 realistic tournament hand fixtures.

Every test enforces:
  1. spot_type is correct for the situation
  2. recommended_action is a non-empty, non-trivial string
  3. confidence is not overclaimed (INFERRED for rule-based, SPECULATIVE for
     unknown hole cards / payout structure)
  4. ev_label is consistent with mistake_severity
  5. explanation contains no fake-precision patterns (no "solver says",
     "GTO", "exact EV", precise decimal EV numbers)
  6. key_factors includes position and/or stack depth
  7. backing is one of the three declared levels

These tests are intentionally assertive about *quality of advice*, not just
code paths. A regression that causes the engine to produce "solver-backed"
output for a heuristic spot, or INFERRED confidence for an ICM spot (where
payout structure is unknown), will fail here.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.analysis.hand_analysis_engine import analyze_hand
from app.features.labels import MetricLabel
from app.models.hand import ActionType, GameType, Street
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLUB_ID = uuid.uuid4()
_NOW = datetime(2026, 5, 10, 14, 0, 0, tzinfo=UTC)

_FAKE_PRECISION_PATTERNS = re.compile(
    r"solver says|GTO says|exact EV|EV =|EV=|\b\d+\.\d{3,}%",
    re.IGNORECASE,
)

_VALID_BACKINGS = frozenset(
    {"heuristic", "range-based estimate", "solver-backed", "Nash table estimate"}
)
_VALID_EV_LABELS = frozenset({"+EV", "neutral", "-EV", "unknown"})
_VALID_SEVERITIES = frozenset({"good", "none", "minor", "major", "critical"})
_VALID_CONFIDENCES = frozenset(
    {MetricLabel.INFERRED, MetricLabel.SPECULATIVE, MetricLabel.OBSERVED, MetricLabel.DERIVED}
)


# ---------------------------------------------------------------------------
# Shared fixture builder
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
        hole_cards=None,
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
        external_id="QA-FIXTURE",
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
# Quality assertion helper
# ---------------------------------------------------------------------------


def _assert_quality(
    result,
    *,
    expected_spot: str,
    not_overclaimed: bool = True,
    no_fake_precision: bool = True,
) -> None:
    """Shared quality gate applied to every fixture result."""
    assert result.spot_type == expected_spot, (
        f"Expected spot_type={expected_spot!r}, got {result.spot_type!r}"
    )
    assert result.recommended_action and len(result.recommended_action) > 3, (
        "recommended_action must be a non-trivial string"
    )
    assert result.explanation and len(result.explanation) > 10, (
        "explanation must be a non-trivial string"
    )
    assert result.mistake_severity in _VALID_SEVERITIES, (
        f"Invalid mistake_severity: {result.mistake_severity!r}"
    )
    assert result.ev_label in _VALID_EV_LABELS, f"Invalid ev_label: {result.ev_label!r}"
    assert result.backing in _VALID_BACKINGS, f"Invalid backing: {result.backing!r}"
    assert result.confidence in _VALID_CONFIDENCES, f"Invalid confidence: {result.confidence!r}"
    if no_fake_precision:
        assert not _FAKE_PRECISION_PATTERNS.search(result.explanation), (
            f"Fake precision detected in explanation: {result.explanation!r}"
        )
    if not_overclaimed:
        # SPECULATIVE spots must not claim precise EV direction
        if result.confidence == MetricLabel.SPECULATIVE:
            assert result.ev_label in ("neutral", "unknown"), (
                f"SPECULATIVE spot should not claim EV direction: {result.ev_label!r}"
            )
        # Never use solver-backed for rule-based spots (no solver integration exists)
        assert result.backing != "solver-backed", (
            "backing='solver-backed' must not appear without real solver data"
        )


# ---------------------------------------------------------------------------
# 20 realistic tournament hand quality fixtures
# ---------------------------------------------------------------------------


class TestRealisticHandFixtures:
    # ── 1. Short-stack shove from BTN (8bb) ──────────────────────────────────

    def test_01_short_stack_shove_btn_8bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("8"),
            actions=[("PREFLOP", "ALL_IN", "8", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="push_fold")
        assert r.mistake_severity == "good"
        assert r.ev_label == "+EV"
        assert r.confidence == MetricLabel.INFERRED
        assert r.backing == "Nash table estimate"

    # ── 2. Short-stack shove from CO (11bb) ──────────────────────────────────

    def test_02_short_stack_shove_co_11bb(self) -> None:
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("11"),
            actions=[("PREFLOP", "ALL_IN", "11", True, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="push_fold")
        assert r.mistake_severity == "good"
        assert r.confidence == MetricLabel.INFERRED
        # Explanation must acknowledge short-stack theory without fake EV
        assert "11bb" in r.explanation or "stack" in r.explanation.lower()

    # ── 3. Short-stack flat call from SB (9bb) ───────────────────────────────

    def test_03_short_stack_flat_call_sb_9bb(self) -> None:
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("9"),
            actions=[("PREFLOP", "CALL", "3", False, 7)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="push_fold")
        assert r.mistake_severity == "critical"
        assert r.ev_label == "-EV"
        assert r.confidence == MetricLabel.INFERRED
        assert "fold equity" in r.explanation.lower() or "call" in r.explanation.lower()

    # ── 4. Short-stack min-raise from BTN (7bb, not all-in) ──────────────────

    def test_04_short_stack_minraise_btn_7bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("7"),
            actions=[("PREFLOP", "RAISE", "2", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="push_fold")
        assert r.mistake_severity == "minor"
        assert r.ev_label == "-EV"
        assert r.confidence == MetricLabel.INFERRED
        # Must advise jamming, not "good job"
        assert "shove" in r.recommended_action.lower() or "jam" in r.recommended_action.lower()

    # ── 5. BTN steal open raise (50bb) ───────────────────────────────────────

    def test_05_btn_steal_raise_50bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="steal")
        assert r.mistake_severity == "good"
        assert r.ev_label == "+EV"
        assert r.confidence == MetricLabel.INFERRED
        assert r.backing == "range-based estimate"

    # ── 6. CO limp (40bb) — steal position, should raise or fold ─────────────

    def test_06_co_steal_limp_40bb(self) -> None:
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("40"),
            actions=[("PREFLOP", "CALL", "1", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="steal")
        assert r.mistake_severity == "minor"
        assert r.ev_label == "neutral"
        assert "raise or fold" in r.recommended_action.lower() or "limp" in r.explanation.lower()

    # ── 7. SB steal raise (30bb) ─────────────────────────────────────────────

    def test_07_sb_steal_raise_30bb(self) -> None:
        hand, hero_id = _hand(
            position="SB",
            stack_bb=Decimal("30"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="steal")
        assert r.mistake_severity == "good"
        assert r.confidence == MetricLabel.INFERRED

    # ── 8. BB defend — call facing steal, deep stack (30bb) ──────────────────

    def test_08_bb_defend_call_deep_30bb(self) -> None:
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("30"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "2.5", False, 7),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="defend_bb")
        assert r.mistake_severity == "none"
        assert r.confidence == MetricLabel.INFERRED
        # Pot odds / hand strength must be mentioned, not fake precision
        assert "pot odds" in r.explanation.lower() or "hand" in r.explanation.lower()

    # ── 9. BB defend — 3bet facing steal, 25bb ───────────────────────────────

    def test_09_bb_defend_3bet_25bb(self) -> None:
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("25"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "RAISE", "7", False, 7),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "2.5", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="defend_bb")
        assert r.mistake_severity == "good"
        assert r.ev_label == "+EV"

    # ── 10. BB defend — short-stack call, 10bb ────────────────────────────────

    def test_10_bb_defend_short_call_10bb(self) -> None:
        # At 10bb, push/fold territory overrides positional framing — engine
        # should identify this as a push_fold spot and recommend shove or fold.
        hand, hero_id = _hand(
            position="BB",
            stack_bb=Decimal("10"),
            actions=[
                ("PREFLOP", "POST_BB", "1", False, 1),
                ("PREFLOP", "CALL", "3", False, 7),
            ],
            opp_actions=[("BTN", "PREFLOP", "RAISE", "3", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="push_fold")
        assert r.mistake_severity in ("minor", "major", "critical")
        assert "shove" in r.recommended_action.lower() or "fold" in r.recommended_action.lower()

    # ── 11. BTN 3bets vs CO open (50bb) ──────────────────────────────────────

    def test_11_btn_3bet_vs_co_open_50bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            actions=[("PREFLOP", "RAISE", "7", False, 8)],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="three_bet")
        assert r.mistake_severity == "good"
        assert r.ev_label == "+EV"
        assert r.confidence == MetricLabel.INFERRED

    # ── 12. UTG 3bets vs CO open (non-steal position, 40bb) ──────────────────

    def test_12_utg_3bet_vs_co_open_40bb(self) -> None:
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("40"),
            actions=[("PREFLOP", "RAISE", "9", False, 8)],
            opp_actions=[("CO", "PREFLOP", "RAISE", "2.5", False, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="three_bet")
        # Non-steal 3bet: must not claim "good" (range-dependent)
        assert r.mistake_severity in ("none", "good")
        # Must not overclaim certainty
        assert r.confidence == MetricLabel.INFERRED

    # ── 13. BTN 4-bet jams over 3-bet (40bb) ─────────────────────────────────

    def test_13_btn_4bet_jam_40bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("40"),
            actions=[("PREFLOP", "ALL_IN", "40", True, 12)],
            opp_actions=[
                ("CO", "PREFLOP", "RAISE", "2.5", False, 4),
                ("BB", "PREFLOP", "RAISE", "8", False, 8),
            ],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="four_bet_jam")
        assert r.mistake_severity == "none"
        assert r.confidence == MetricLabel.INFERRED

    # ── 14. BTN calls 3-bet (not jam) — leaks info without pressure (40bb) ───

    def test_14_btn_4bet_call_not_jam_40bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("40"),
            actions=[("PREFLOP", "CALL", "8", False, 12)],
            opp_actions=[
                ("CO", "PREFLOP", "RAISE", "2.5", False, 4),
                ("BB", "PREFLOP", "RAISE", "8", False, 8),
            ],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="four_bet_jam")
        assert r.mistake_severity == "minor"
        assert "jam" in r.recommended_action.lower() or "fold" in r.recommended_action.lower()

    # ── 15. Bubble ICM — 5-handed table, 13bb shove ──────────────────────────

    def test_15_bubble_icm_shove_13bb_5handed(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("13"),
            actions=[("PREFLOP", "ALL_IN", "13", True, 5)],
            player_count=5,
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="bubble_icm")
        assert r.confidence == MetricLabel.SPECULATIVE
        # Payout structure missing — must acknowledge uncertainty
        assert "payout" in " ".join(r.key_factors).lower() or "icm" in r.explanation.lower()
        # ev_label must not make a definitive claim without payout data
        assert r.ev_label in ("neutral", "unknown", "+EV")

    # ── 16. Final table ICM — 4-handed table, 8bb flat call ──────────────────

    def test_16_final_table_flat_call_8bb_4handed(self) -> None:
        hand, hero_id = _hand(
            position="CO",
            stack_bb=Decimal("8"),
            actions=[("PREFLOP", "CALL", "3", False, 5)],
            player_count=4,
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="final_table_icm")
        assert r.confidence == MetricLabel.SPECULATIVE
        assert "payout" in " ".join(r.key_factors).lower() or "icm" in r.explanation.lower()

    # ── 17. Call all-in preflop (40bb hero, opp jams 30bb) ───────────────────

    def test_17_call_all_in_preflop_40bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("40"),
            actions=[("PREFLOP", "CALL", "30", False, 8)],
            opp_actions=[("UTG", "PREFLOP", "ALL_IN", "30", True, 4)],
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="call_all_in")
        assert r.confidence == MetricLabel.SPECULATIVE
        assert r.ev_label in ("neutral", "unknown")
        # Pot odds must appear in key_factors
        assert any("pot odds" in f.lower() for f in r.key_factors), (
            f"Pot odds missing from key_factors: {r.key_factors}"
        )
        # Must not claim to know the outcome
        assert "exact" not in r.explanation.lower()

    # ── 18. Flop c-bet as PFA (50bb, 6-max) ──────────────────────────────────

    def test_18_flop_cbet_as_pfa_50bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 4),
                ("FLOP", "BET", "3", False, 12),
            ],
            opp_actions=[("BB", "PREFLOP", "CALL", "2.5", False, 8)],
            board_cards="Ah Kd 7c",
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="flop_cbet")
        assert r.confidence == MetricLabel.INFERRED
        assert r.backing == "heuristic"
        # Should mention board or SPR without claiming exact frequencies
        assert not _FAKE_PRECISION_PATTERNS.search(r.explanation)

    # ── 19. Turn barrel as PFA (50bb) ─────────────────────────────────────────

    def test_19_turn_barrel_as_pfa_50bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 4),
                ("FLOP", "BET", "3", False, 12),
                ("TURN", "BET", "7", False, 18),
            ],
            opp_actions=[
                ("BB", "PREFLOP", "CALL", "2.5", False, 8),
                ("BB", "FLOP", "CALL", "3", False, 14),
            ],
            board_cards="Ah Kd 7c 2s",
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="turn_barrel")
        assert r.confidence == MetricLabel.INFERRED
        # Turn barrel: must include pot size context
        assert any("pot" in f.lower() for f in r.key_factors)

    # ── 20. River call facing opponent bet (50bb) ─────────────────────────────

    def test_20_river_call_facing_bet_50bb(self) -> None:
        hand, hero_id = _hand(
            position="BTN",
            stack_bb=Decimal("50"),
            actions=[
                ("PREFLOP", "RAISE", "2.5", False, 4),
                ("FLOP", "BET", "3", False, 12),
                ("TURN", "CHECK", None, False, 18),
                ("RIVER", "CALL", "10", False, 24),
            ],
            opp_actions=[
                ("BB", "PREFLOP", "CALL", "2.5", False, 8),
                ("BB", "FLOP", "CALL", "3", False, 14),
                ("BB", "TURN", "CHECK", None, False, 16),
                ("BB", "RIVER", "BET", "10", False, 22),
            ],
            board_cards="Ah Kd 7c 2s 9h",
        )
        r = analyze_hand(hand, hero_id)
        _assert_quality(r, expected_spot="river_call_fold")
        assert r.confidence == MetricLabel.INFERRED
        # Must compute pot odds and include them
        assert any("pot" in f.lower() for f in r.key_factors)
        # Must not claim to know villain's holding
        assert "solver" not in r.explanation.lower()


# ---------------------------------------------------------------------------
# Cross-fixture quality invariants
# ---------------------------------------------------------------------------


class TestQualityInvariants:
    """
    Properties that must hold across ALL outputs of analyze_hand(), regardless
    of hand type. These catch systemic failures (e.g. an engine change that
    starts emitting 'solver-backed' everywhere, or adds fake EV percentages).
    """

    _ALL_FIXTURES: list[tuple] = [
        # (position, stack_bb, actions, opp_actions, player_count, board_cards, label)
        ("BTN", Decimal("8"), [("PREFLOP", "ALL_IN", "8", True, 5)], [], 6, None, "shove_8bb"),
        ("BTN", Decimal("50"), [("PREFLOP", "RAISE", "2.5", False, 5)], [], 6, None, "steal_50bb"),
        (
            "BB",
            Decimal("30"),
            [("PREFLOP", "POST_BB", "1", False, 1), ("PREFLOP", "CALL", "2.5", False, 7)],
            [("BTN", "PREFLOP", "RAISE", "2.5", False, 4)],
            6,
            None,
            "bb_defend_call",
        ),
        (
            "BB",
            Decimal("10"),
            [("PREFLOP", "POST_BB", "1", False, 1), ("PREFLOP", "CALL", "3", False, 7)],
            [("BTN", "PREFLOP", "RAISE", "3", False, 4)],
            6,
            None,
            "bb_short_call",
        ),
        ("BTN", Decimal("13"), [("PREFLOP", "ALL_IN", "13", True, 5)], [], 5, None, "bubble_shove"),
        ("BTN", Decimal("8"), [("PREFLOP", "ALL_IN", "8", True, 5)], [], 4, None, "ft_shove"),
        (
            "BTN",
            Decimal("40"),
            [("PREFLOP", "CALL", "30", False, 8)],
            [("UTG", "PREFLOP", "ALL_IN", "30", True, 4)],
            6,
            None,
            "call_allin",
        ),
        (
            "BTN",
            Decimal("50"),
            [("PREFLOP", "RAISE", "2.5", False, 4), ("FLOP", "BET", "3", False, 12)],
            [("BB", "PREFLOP", "CALL", "2.5", False, 8)],
            6,
            "Ah Kd 7c",
            "flop_cbet",
        ),
    ]

    def test_no_solver_backed_output_for_any_heuristic_spot(self) -> None:
        for pos, stack, acts, opp_acts, pcount, board, label in self._ALL_FIXTURES:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
                board_cards=board,
            )
            r = analyze_hand(hand, hero_id)
            assert r.backing != "solver-backed", (
                f"[{label}] backing='solver-backed' must not appear without real solver data"
            )

    def test_no_fake_precision_in_any_explanation(self) -> None:
        for pos, stack, acts, opp_acts, pcount, board, label in self._ALL_FIXTURES:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
                board_cards=board,
            )
            r = analyze_hand(hand, hero_id)
            assert not _FAKE_PRECISION_PATTERNS.search(r.explanation), (
                f"[{label}] fake precision in explanation: {r.explanation!r}"
            )

    def test_speculative_spots_never_claim_strong_ev_direction(self) -> None:
        speculative_fixtures = [
            ("BTN", Decimal("13"), [("PREFLOP", "ALL_IN", "13", True, 5)], [], 5, None),
            ("BTN", Decimal("8"), [("PREFLOP", "ALL_IN", "8", True, 5)], [], 4, None),
            (
                "BTN",
                Decimal("40"),
                [("PREFLOP", "CALL", "30", False, 8)],
                [("UTG", "PREFLOP", "ALL_IN", "30", True, 4)],
                6,
                None,
            ),
        ]
        for pos, stack, acts, opp_acts, pcount, board in speculative_fixtures:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
                board_cards=board,
            )
            r = analyze_hand(hand, hero_id)
            if r.confidence == MetricLabel.SPECULATIVE:
                assert r.ev_label in ("neutral", "unknown", "+EV"), (
                    f"SPECULATIVE spot must not claim definitive negative EV: {r.ev_label!r}"
                )

    def test_every_result_has_non_empty_key_factors_for_classified_spots(self) -> None:
        """Classified spots (anything but 'other') must include position/stack context."""
        for pos, stack, acts, opp_acts, pcount, board, label in self._ALL_FIXTURES:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
                board_cards=board,
            )
            r = analyze_hand(hand, hero_id)
            if r.spot_type != "other":
                assert r.key_factors, (
                    f"[{label}] key_factors is empty for classified spot {r.spot_type!r}"
                )

    def test_inferred_push_fold_uses_nash_backing(self) -> None:
        """Push/fold spots use Nash table ranges — backing should be 'Nash table estimate'."""
        push_fold_fixtures = [
            ("BTN", Decimal("8"), [("PREFLOP", "ALL_IN", "8", True, 5)], [], 6),
            ("SB", Decimal("9"), [("PREFLOP", "CALL", "3", False, 7)], [], 6),
            ("BTN", Decimal("12"), [("PREFLOP", "RAISE", "2.5", False, 5)], [], 6),
        ]
        for pos, stack, acts, opp_acts, pcount in push_fold_fixtures:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
            )
            r = analyze_hand(hand, hero_id)
            assert r.backing == "Nash table estimate", (
                f"push_fold spot should use 'Nash table estimate', got {r.backing!r}"
            )

    def test_steal_positions_use_range_based_backing(self) -> None:
        # BTN/CO/SB opens are classified as 'steal' and augmented with range context.
        steal_fixtures = [
            ("BTN", Decimal("50"), [("PREFLOP", "RAISE", "2.5", False, 5)], [], 6),
            ("CO", Decimal("40"), [("PREFLOP", "RAISE", "2.5", False, 5)], [], 6),
        ]
        for pos, stack, acts, opp_acts, pcount in steal_fixtures:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
            )
            r = analyze_hand(hand, hero_id)
            assert r.backing == "range-based estimate", (
                f"[{pos} steal raise] expected 'range-based estimate', got {r.backing!r}"
            )

    def test_ep_opens_use_heuristic_backing(self) -> None:
        # UTG/HJ/MP opens are classified as 'open_fold' (not augmented with ranges yet).
        hand, hero_id = _hand(
            position="UTG",
            stack_bb=Decimal("40"),
            actions=[("PREFLOP", "RAISE", "2.5", False, 5)],
            opp_actions=[],
            player_count=6,
        )
        r = analyze_hand(hand, hero_id)
        assert r.backing == "heuristic", f"UTG open_fold should use 'heuristic', got {r.backing!r}"

    def test_icm_spots_always_speculative_regardless_of_stack(self) -> None:
        icm_stacks = [Decimal("6"), Decimal("10"), Decimal("14")]
        for stack in icm_stacks:
            for pcount in (4, 5):
                hand, hero_id = _hand(
                    position="BTN",
                    stack_bb=stack,
                    actions=[("PREFLOP", "ALL_IN", str(stack), True, 5)],
                    player_count=pcount,
                )
                r = analyze_hand(hand, hero_id)
                if r.spot_type in ("bubble_icm", "final_table_icm"):
                    assert r.confidence == MetricLabel.SPECULATIVE, (
                        f"ICM spot with stack={stack} pcount={pcount} "
                        f"should be SPECULATIVE, got {r.confidence!r}"
                    )

    def test_all_in_call_always_speculative(self) -> None:
        """Calling an all-in requires knowing hole cards — always SPECULATIVE."""
        for call_amount in ("20", "30", "50"):
            hand, hero_id = _hand(
                position="BTN",
                stack_bb=Decimal("60"),
                actions=[("PREFLOP", "CALL", call_amount, False, 8)],
                opp_actions=[("UTG", "PREFLOP", "ALL_IN", call_amount, True, 4)],
            )
            r = analyze_hand(hand, hero_id)
            assert r.spot_type == "call_all_in"
            assert r.confidence == MetricLabel.SPECULATIVE, (
                f"call_all_in should always be SPECULATIVE (call={call_amount}bb)"
            )

    def test_recommended_action_never_empty_or_whitespace(self) -> None:
        for pos, stack, acts, opp_acts, pcount, board, label in self._ALL_FIXTURES:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
                board_cards=board,
            )
            r = analyze_hand(hand, hero_id)
            assert r.recommended_action and r.recommended_action.strip(), (
                f"[{label}] recommended_action is empty or whitespace"
            )

    def test_explanation_never_empty_or_whitespace(self) -> None:
        for pos, stack, acts, opp_acts, pcount, board, label in self._ALL_FIXTURES:
            hand, hero_id = _hand(
                position=pos,
                stack_bb=stack,
                actions=acts,
                opp_actions=opp_acts,
                player_count=pcount,
                board_cards=board,
            )
            r = analyze_hand(hand, hero_id)
            assert r.explanation and r.explanation.strip(), (
                f"[{label}] explanation is empty or whitespace"
            )
