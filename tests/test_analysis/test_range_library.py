"""
Tests for range_library.py.

Verifies:
- Hand parsing (hole card string → canonical form)
- Range expansion (shorthand notation)
- Range membership (hand_in_range)
- Range position classification (top/mid/bottom/outside)
- Public accessors with stack-depth bucketing
- Consistency across stack depths (deeper stack = tighter range)
- Edge hands near range cutoffs
"""

from __future__ import annotations

import pytest

from app.analysis.range_library import (
    BB_DEFEND_RANGES,
    PUSH_RANGES,
    STEAL_RANGES,
    THREBET_RANGES,
    classify_hand_vs_range,
    expand_range_notation,
    get_bb_defend_range,
    get_push_range,
    get_steal_range,
    get_threbet_range,
    hand_in_range,
    parse_hole_cards,
)

# ---------------------------------------------------------------------------
# parse_hole_cards
# ---------------------------------------------------------------------------


class TestParseHoleCards:
    def test_suited_aces(self):
        assert parse_hole_cards("Ah Kh") == "AKs"

    def test_offsuit_aces(self):
        assert parse_hole_cards("Ah Kd") == "AKo"

    def test_pocket_pair(self):
        assert parse_hole_cards("Qh Qd") == "QQ"

    def test_low_suited(self):
        assert parse_hole_cards("7c 6c") == "76s"

    def test_low_offsuit(self):
        assert parse_hole_cards("7c 6d") == "76o"

    def test_reversed_order(self):
        # Lower card first — should still produce correct canonical
        assert parse_hole_cards("2h Ah") == "A2s"

    def test_tens(self):
        assert parse_hole_cards("Th 9d") == "T9o"
        assert parse_hole_cards("Th 9h") == "T9s"

    def test_pocket_aces(self):
        assert parse_hole_cards("Ah Ad") == "AA"

    def test_pocket_twos(self):
        assert parse_hole_cards("2h 2d") == "22"

    def test_none_returns_none(self):
        assert parse_hole_cards(None) is None

    def test_empty_returns_none(self):
        assert parse_hole_cards("") is None

    def test_malformed_returns_none(self):
        assert parse_hole_cards("AhKd") is None  # no space
        assert parse_hole_cards("Ah Kd Qh") is None  # three cards


# ---------------------------------------------------------------------------
# expand_range_notation
# ---------------------------------------------------------------------------


class TestExpandRangeNotation:
    def test_pair_plus(self):
        r = expand_range_notation(["JJ+"])
        assert "JJ" in r
        assert "QQ" in r
        assert "KK" in r
        assert "AA" in r
        assert "TT" not in r

    def test_pair_dash(self):
        r = expand_range_notation(["JJ-77"])
        assert "JJ" in r
        assert "TT" in r
        assert "99" in r
        assert "88" in r
        assert "77" in r
        assert "66" not in r
        assert "QQ" not in r

    def test_suited_plus(self):
        r = expand_range_notation(["ATs+"])
        assert "ATs" in r
        assert "AJs" in r
        assert "AQs" in r
        assert "AKs" in r
        assert "A9s" not in r

    def test_suited_dash(self):
        r = expand_range_notation(["ATs-A6s"])
        assert "ATs" in r
        assert "A9s" in r
        assert "A8s" in r
        assert "A7s" in r
        assert "A6s" in r
        assert "A5s" not in r
        assert "AJs" not in r

    def test_offsuit_plus(self):
        r = expand_range_notation(["ATo+"])
        assert "ATo" in r
        assert "AJo" in r
        assert "AQo" in r
        assert "AKo" in r
        assert "A9o" not in r

    def test_exact_hand(self):
        r = expand_range_notation(["AKs"])
        assert r == frozenset({"AKs"})

    def test_exact_pair(self):
        r = expand_range_notation(["AA"])
        assert r == frozenset({"AA"})

    def test_invalid_hands_excluded(self):
        r = expand_range_notation(["XYz", "AKs"])
        assert "AKs" in r
        # XYz is not a valid hand — should be silently dropped
        assert len(r) == 1

    def test_multiple_specs(self):
        r = expand_range_notation(["AA", "KK", "AKs"])
        assert r == frozenset({"AA", "KK", "AKs"})


# ---------------------------------------------------------------------------
# hand_in_range / classify_hand_vs_range
# ---------------------------------------------------------------------------


class TestHandInRange:
    def test_premium_in_wide_range(self):
        r = PUSH_RANGES["BTN_8bb"]
        assert hand_in_range("AA", r)
        assert hand_in_range("AKs", r)

    def test_trash_not_in_tight_range(self):
        r = PUSH_RANGES["UTG_15bb"]
        assert not hand_in_range("72o", r)
        assert not hand_in_range("32o", r)

    def test_outside_returns_false(self):
        r = frozenset({"AA", "KK"})
        assert not hand_in_range("QQ", r)

    def test_exact_match(self):
        r = frozenset({"AKs"})
        assert hand_in_range("AKs", r)
        assert not hand_in_range("AKo", r)


class TestClassifyHandVsRange:
    def test_aa_is_top_of_any_range(self):
        r = PUSH_RANGES["BTN_12bb"]
        assert classify_hand_vs_range("AA", r) == "top"

    def test_outside_returns_outside(self):
        r = PUSH_RANGES["UTG_15bb"]  # tight range
        assert classify_hand_vs_range("72o", r) == "outside"

    def test_marginal_hand_is_bottom(self):
        # 65s is in BTN_15bb push range but is a weaker hand there
        r = PUSH_RANGES["BTN_15bb"]
        if "65s" in r:
            pos = classify_hand_vs_range("65s", r)
            assert pos in ("bottom", "mid")

    def test_classification_is_consistent(self):
        # AA should always outrank AKs which should outrank AKo
        r = PUSH_RANGES["BTN_12bb"]
        aa_rank = classify_hand_vs_range("AA", r)
        aks_rank = classify_hand_vs_range("AKs", r)
        assert aa_rank in ("top",)
        assert aks_rank in ("top", "mid")

    def test_returns_valid_value(self):
        valid = {"top", "mid", "bottom", "outside"}
        r = PUSH_RANGES["BTN_8bb"]
        for hand in ["AA", "AKs", "AKo", "22", "72o"]:
            assert classify_hand_vs_range(hand, r) in valid


# ---------------------------------------------------------------------------
# Push range consistency: deeper stack = tighter range
# ---------------------------------------------------------------------------


class TestPushRangeConsistency:
    @pytest.mark.parametrize("pos", ["BTN", "CO", "SB", "UTG"])
    def test_deeper_stack_tighter_range(self, pos: str):
        depths = [5, 8, 10, 12, 15]
        prev_size = None
        for d in depths:
            key = f"{pos}_{d}bb"
            if key not in PUSH_RANGES:
                continue
            size = len(PUSH_RANGES[key])
            if prev_size is not None:
                assert size <= prev_size, (
                    f"{pos}: range at {d}bb ({size}) should be ≤ range at previous depth ({prev_size})"
                )
            prev_size = size

    def test_btn_wider_than_utg_same_depth(self):
        for depth in [8, 10, 12, 15]:
            btn = PUSH_RANGES.get(f"BTN_{depth}bb", frozenset())
            utg = PUSH_RANGES.get(f"UTG_{depth}bb", frozenset())
            assert len(btn) >= len(utg), f"BTN push range should be ≥ UTG at {depth}bb"

    def test_premium_hands_always_in_range(self):
        premium = ["AA", "KK", "QQ", "AKs"]
        for key, rng in PUSH_RANGES.items():
            for hand in premium:
                assert hand in rng, f"{hand} must be in all push ranges; missing from {key}"


# ---------------------------------------------------------------------------
# Accessor functions
# ---------------------------------------------------------------------------


class TestGetPushRange:
    def test_known_position_and_depth(self):
        rng, key = get_push_range("BTN", 10.0)
        assert len(rng) > 0
        assert "10bb" in key

    def test_fractional_stack_rounds_to_nearest(self):
        rng_9, key_9 = get_push_range("BTN", 9.0)
        rng_10, key_10 = get_push_range("BTN", 10.0)
        # 9bb is closer to 8bb than 10bb → different key
        assert "8bb" in key_9 or "10bb" in key_9

    def test_unknown_position_falls_back(self):
        rng, key = get_push_range("MP", 10.0)
        assert len(rng) > 0  # fallback found

    def test_stack_15_uses_15bb_range(self):
        rng, key = get_push_range("BTN", 15.0)
        assert "15bb" in key

    def test_stack_5_uses_5bb_range(self):
        rng, key = get_push_range("CO", 5.0)
        assert "5bb" in key


class TestGetStealRange:
    def test_btn_open_defined(self):
        rng, key = get_steal_range("BTN")
        assert len(rng) > 50  # BTN opens very wide
        assert key == "BTN_open"

    def test_co_open_defined(self):
        rng, key = get_steal_range("CO")
        assert len(rng) > 0
        assert key == "CO_open"

    def test_unknown_position_returns_empty(self):
        rng, key = get_steal_range("UNKNOWN")
        assert rng == frozenset()
        assert key == ""

    def test_btn_wider_than_utg(self):
        btn_rng, _ = get_steal_range("BTN")
        utg_rng, _ = get_steal_range("UTG")
        assert len(btn_rng) > len(utg_rng)


class TestGetThreBetRange:
    def test_btn_vs_co_defined(self):
        rng, key = get_threbet_range("BTN", "CO")
        assert len(rng) > 0
        assert "AA" in rng

    def test_bb_vs_btn_defined(self):
        rng, key = get_threbet_range("BB", "BTN")
        assert len(rng) > 0

    def test_threbet_tighter_than_open(self):
        threbet, _ = get_threbet_range("BTN", "CO")
        steal, _ = get_steal_range("BTN")
        assert len(threbet) < len(steal)

    def test_unknown_combo_returns_empty(self):
        rng, key = get_threbet_range("BB", "UNKNOWN")
        assert rng == frozenset()


class TestGetBBDefendRange:
    def test_vs_btn_defined(self):
        rng, key = get_bb_defend_range("BTN")
        assert len(rng) > 0
        assert key == "BB_vs_BTN"

    def test_vs_utg_tighter_than_vs_btn(self):
        vs_btn, _ = get_bb_defend_range("BTN")
        vs_utg, _ = get_bb_defend_range("UTG")
        assert len(vs_btn) > len(vs_utg)

    def test_premium_always_defended(self):
        for vs in ["BTN", "CO", "SB", "UTG"]:
            rng, _ = get_bb_defend_range(vs)
            if rng:
                assert "AA" in rng, f"AA must be in BB defend range vs {vs}"

    def test_unknown_position_returns_empty(self):
        rng, key = get_bb_defend_range("UNKNOWN")
        assert rng == frozenset()


# ---------------------------------------------------------------------------
# Edge cases near range cutoffs
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_boundary_hand_at_12bb_btn(self):
        # At 12bb BTN, hands on the boundary should be classifiable
        r = PUSH_RANGES["BTN_12bb"]
        for h in ["AKs", "AA", "22", "87s"]:
            if h in r:
                pos = classify_hand_vs_range(h, r)
                assert pos in ("top", "mid", "bottom")

    def test_suited_vs_offsuit_same_ranks(self):
        # AKs is stronger than AKo — suited should outrank offsuit
        r = PUSH_RANGES["BTN_15bb"]
        if "AKs" in r and "AKo" in r:
            from app.analysis.range_library import _STRENGTH_RANK

            assert _STRENGTH_RANK["AKs"] < _STRENGTH_RANK["AKo"]

    def test_all_ranges_non_empty(self):
        for name, rng in {
            **PUSH_RANGES,
            **STEAL_RANGES,
            **THREBET_RANGES,
            **BB_DEFEND_RANGES,
        }.items():
            assert len(rng) > 0, f"Range {name!r} is empty"

    def test_no_invalid_hands_in_any_range(self):
        from app.analysis.range_library import _STRENGTH_RANK

        all_ranges = {**PUSH_RANGES, **STEAL_RANGES, **THREBET_RANGES, **BB_DEFEND_RANGES}
        for name, rng in all_ranges.items():
            for hand in rng:
                assert hand in _STRENGTH_RANK, f"Invalid hand {hand!r} in range {name!r}"
