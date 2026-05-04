"""
Unit tests for steal/defend detection in hand_record_from_actions().

Tests cover:
- had_steal_opportunity for BTN, CO, SB
- stole flag
- faced_steal from various raiser positions
- folded_to_steal, attempted_resteal
- position-specific flags (folded_bb_to_btn_open, etc.)
- backward compatibility when no "position" key in action dicts
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.features.player_stats import hand_record_from_actions, HandRecord


# ── Helpers ───────────────────────────────────────────────────────────────────


def _a(hp_id: str, action_type: str, order: int, position: str | None = None) -> dict:
    """Build a preflop action dict."""
    d: dict = {"hand_player_id": hp_id, "action_type": action_type, "action_order": order}
    if position is not None:
        d["position"] = position
    return d


_STACK = Decimal("100")


def _record(
    player_position: str | None,
    all_actions: list[dict],
    hero_id: str = "hero",
    saw_flop: bool = False,
) -> HandRecord:
    return hand_record_from_actions(
        hand_external_id="test_hand",
        player_position=player_position,
        player_stack_bb=_STACK,
        player_effective_stack_bb=_STACK,
        this_hand_player_id=hero_id,
        all_preflop_actions=all_actions,
        saw_flop=saw_flop,
        reached_showdown=False,
        won_at_showdown=False,
    )


# ── Common action sequences ───────────────────────────────────────────────────
# Pre-built building blocks for realistic 6-max hand scenarios


def _posts_and_folds_to(hero_order: int) -> list[dict]:
    """
    SB/BB post, then everyone between them and hero folds.
    Returns a list of actions up to (not including) hero's action.
    """
    return [
        _a("sb", "POST_SB", 1, "SB"),
        _a("bb", "POST_BB", 2, "BB"),
        _a("utg", "FOLD", 3, "UTG"),
        _a("hj", "FOLD", 4, "HJ"),
        _a("co", "FOLD", 5, "CO"),
    ][:hero_order - 1]  # trim to whatever comes before hero


# ── Steal opportunity tests ───────────────────────────────────────────────────


class TestHadStealOpportunity:
    def test_btn_with_unopened_pot_has_opportunity(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("hero", "RAISE", 6, "BTN"),
            _a("sb", "FOLD", 7, "SB"),
            _a("bb", "FOLD", 8, "BB"),
        ]
        rec = _record("BTN", actions)
        assert rec.had_steal_opportunity is True

    def test_co_with_unopened_pot_has_opportunity(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("hero", "RAISE", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("sb", "FOLD", 7, "SB"),
            _a("bb", "FOLD", 8, "BB"),
        ]
        rec = _record("CO", actions)
        assert rec.had_steal_opportunity is True

    def test_sb_with_unopened_pot_has_opportunity(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("hero", "RAISE", 7, "SB"),
            _a("bb", "FOLD", 8, "BB"),
        ]
        rec = _record("SB", actions)
        assert rec.had_steal_opportunity is True

    def test_utg_no_steal_opportunity(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("hero", "RAISE", 3, "UTG"),
        ]
        rec = _record("UTG", actions)
        assert rec.had_steal_opportunity is False

    def test_hj_no_steal_opportunity(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hero", "RAISE", 4, "HJ"),
        ]
        rec = _record("HJ", actions)
        assert rec.had_steal_opportunity is False

    def test_btn_after_utg_raise_no_steal_opportunity(self) -> None:
        """UTG raised before BTN — pot is not unopened."""
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "RAISE", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("hero", "CALL", 6, "BTN"),
        ]
        rec = _record("BTN", actions)
        assert rec.had_steal_opportunity is False

    def test_btn_after_co_raise_no_steal_opportunity(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "RAISE", 5, "CO"),
            _a("hero", "FOLD", 6, "BTN"),
        ]
        rec = _record("BTN", actions)
        assert rec.had_steal_opportunity is False


# ── Stole flag ────────────────────────────────────────────────────────────────


class TestStole:
    def test_btn_raises_unopened_stole_true(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("hero", "RAISE", 6, "BTN"),
            _a("sb", "FOLD", 7, "SB"),
            _a("bb", "FOLD", 8, "BB"),
        ]
        rec = _record("BTN", actions)
        assert rec.stole is True
        assert rec.open_position == "BTN"

    def test_btn_folds_with_opportunity_stole_false(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("hero", "FOLD", 6, "BTN"),
        ]
        rec = _record("BTN", actions)
        assert rec.had_steal_opportunity is True
        assert rec.stole is False
        assert rec.open_position is None

    def test_co_raises_stole_true(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("hero", "RAISE", 5, "CO"),
        ]
        rec = _record("CO", actions)
        assert rec.stole is True

    def test_sb_raises_stole_true(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("hero", "RAISE", 7, "SB"),
        ]
        rec = _record("SB", actions)
        assert rec.stole is True

    def test_utg_raise_not_a_steal(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("hero", "RAISE", 3, "UTG"),
        ]
        rec = _record("UTG", actions)
        assert rec.stole is False


# ── Faced steal ───────────────────────────────────────────────────────────────


class TestFacedSteal:
    def test_bb_faces_btn_raise_faced_steal(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "RAISE", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "FOLD", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is True

    def test_bb_faces_co_raise_faced_steal(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "RAISE", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "FOLD", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is True

    def test_bb_faces_sb_raise_faced_steal(self) -> None:
        actions = [
            _a("sb_player", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("sb_player", "RAISE", 7, "SB"),
            _a("hero", "FOLD", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is True

    def test_bb_faces_utg_raise_no_steal(self) -> None:
        """UTG is not a steal position."""
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "RAISE", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "FOLD", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is False

    def test_sb_faces_btn_raise_faced_steal(self) -> None:
        actions = [
            _a("hero", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "RAISE", 6, "BTN"),
            _a("hero", "FOLD", 7, "SB"),
        ]
        rec = _record("SB", actions, hero_id="hero")
        assert rec.faced_steal is True

    def test_no_faced_steal_when_no_raise(self) -> None:
        """All fold to BB — no raise, so BB doesn't face a steal."""
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "CHECK", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is False


# ── Fold and position-specific flags ─────────────────────────────────────────


class TestFoldedToSteal:
    def test_bb_folds_to_btn_all_flags(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "RAISE", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "FOLD", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is True
        assert rec.folded_to_steal is True
        assert rec.faced_btn_open_as_bb is True
        assert rec.folded_bb_to_btn_open is True
        assert rec.faced_co_open_as_bb is False
        assert rec.defender_position is None  # folded → not a defender

    def test_bb_calls_btn_no_fold_flags(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "RAISE", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "CALL", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is True
        assert rec.folded_to_steal is False
        assert rec.folded_bb_to_btn_open is False
        assert rec.defender_position == "BB"

    def test_bb_raises_vs_btn_resteal_flags(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "RAISE", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "RAISE", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_steal is True
        assert rec.attempted_resteal is True
        assert rec.re_steal_opportunity is True
        assert rec.folded_to_steal is False
        assert rec.folded_bb_to_btn_open is False

    def test_bb_faces_co_open_flags(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "RAISE", 5, "CO"),
            _a("btn", "FOLD", 6, "BTN"),
            _a("sb_other", "FOLD", 7, "SB"),
            _a("hero", "FOLD", 8, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.faced_co_open_as_bb is True
        assert rec.faced_btn_open_as_bb is False
        assert rec.folded_bb_to_btn_open is False
        assert rec.folded_to_steal is True

    def test_sb_folds_to_btn_flags(self) -> None:
        actions = [
            _a("hero", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("btn", "RAISE", 6, "BTN"),
            _a("hero", "FOLD", 7, "SB"),
        ]
        rec = _record("SB", actions, hero_id="hero")
        assert rec.faced_steal is True
        assert rec.folded_to_steal is True
        assert rec.folded_sb_to_btn_open is True
        assert rec.folded_bb_to_btn_open is False  # hero is SB not BB


# ── Backward compatibility ────────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Action dicts without 'position' key → all steal flags False."""

    def test_no_position_key_steal_opportunity_still_works(self) -> None:
        """
        had_steal_opportunity uses player_position (passed directly), not the
        action dict's "position" key.  So BTN steal detection still works even
        without position keys in action dicts.
        """
        actions = [
            {"hand_player_id": "sb", "action_type": "POST_SB", "action_order": 1},
            {"hand_player_id": "bb", "action_type": "POST_BB", "action_order": 2},
            {"hand_player_id": "utg", "action_type": "FOLD", "action_order": 3},
            {"hand_player_id": "hj", "action_type": "FOLD", "action_order": 4},
            {"hand_player_id": "co", "action_type": "FOLD", "action_order": 5},
            {"hand_player_id": "hero", "action_type": "RAISE", "action_order": 6},
            {"hand_player_id": "sb", "action_type": "FOLD", "action_order": 7},
            {"hand_player_id": "bb", "action_type": "FOLD", "action_order": 8},
        ]
        rec = _record("BTN", actions)
        # Steal opportunity & stole still work — uses player_position, not action dicts
        assert rec.had_steal_opportunity is True
        assert rec.stole is True

    def test_no_position_key_faced_steal_is_false(self) -> None:
        """
        faced_steal requires knowing the raiser's position from action dicts.
        Without the "position" key on the raiser's action, first_raiser_pos=None
        and None is not in _STEAL_POSITIONS, so faced_steal is False.
        """
        actions = [
            {"hand_player_id": "sb", "action_type": "POST_SB", "action_order": 1},
            {"hand_player_id": "hero", "action_type": "POST_BB", "action_order": 2},
            {"hand_player_id": "utg", "action_type": "FOLD", "action_order": 3},
            {"hand_player_id": "hj", "action_type": "FOLD", "action_order": 4},
            {"hand_player_id": "co", "action_type": "FOLD", "action_order": 5},
            # BTN raises but no "position" key
            {"hand_player_id": "btn", "action_type": "RAISE", "action_order": 6},
            {"hand_player_id": "sb", "action_type": "FOLD", "action_order": 7},
            {"hand_player_id": "hero", "action_type": "FOLD", "action_order": 8},
        ]
        rec = _record("BB", actions, hero_id="hero")
        # Can't detect raiser position → faced_steal is False (safe fallback)
        assert rec.faced_steal is False
        assert rec.folded_to_steal is False
        assert rec.attempted_resteal is False
        assert rec.faced_btn_open_as_bb is False

    def test_mixed_position_and_no_position(self) -> None:
        """Only the raiser's action has a position key — still works."""
        actions = [
            {"hand_player_id": "sb", "action_type": "POST_SB", "action_order": 1},
            {"hand_player_id": "bb", "action_type": "POST_BB", "action_order": 2},
            {"hand_player_id": "utg", "action_type": "FOLD", "action_order": 3},
            {"hand_player_id": "hj", "action_type": "FOLD", "action_order": 4},
            {"hand_player_id": "co", "action_type": "FOLD", "action_order": 5},
            # BTN raise WITH position key
            {"hand_player_id": "btn", "action_type": "RAISE", "action_order": 6, "position": "BTN"},
            {"hand_player_id": "sb", "action_type": "FOLD", "action_order": 7},
            # Hero (BB) folds — no position key on hero's action, but player_position is "BB"
            {"hand_player_id": "hero", "action_type": "FOLD", "action_order": 8},
        ]
        rec = _record("BB", actions, hero_id="hero")
        # first_raiser_pos should come from BTN's action's "position" key
        assert rec.faced_steal is True
        assert rec.folded_to_steal is True
        assert rec.faced_btn_open_as_bb is True


# ── open_position / defender_position ────────────────────────────────────────


class TestDerivedPositionFields:
    def test_open_position_set_when_stole(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("hero", "RAISE", 6, "BTN"),
        ]
        rec = _record("BTN", actions)
        assert rec.open_position == "BTN"

    def test_open_position_none_when_folded(self) -> None:
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("hj", "FOLD", 4, "HJ"),
            _a("co", "FOLD", 5, "CO"),
            _a("hero", "FOLD", 6, "BTN"),
        ]
        rec = _record("BTN", actions)
        assert rec.open_position is None

    def test_defender_position_set_when_called_steal(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("co", "FOLD", 4, "CO"),
            _a("btn", "RAISE", 5, "BTN"),
            _a("sb_other", "FOLD", 6, "SB"),
            _a("hero", "CALL", 7, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.defender_position == "BB"

    def test_defender_position_none_when_folded_steal(self) -> None:
        actions = [
            _a("sb_other", "POST_SB", 1, "SB"),
            _a("hero", "POST_BB", 2, "BB"),
            _a("utg", "FOLD", 3, "UTG"),
            _a("co", "FOLD", 4, "CO"),
            _a("btn", "RAISE", 5, "BTN"),
            _a("sb_other", "FOLD", 6, "SB"),
            _a("hero", "FOLD", 7, "BB"),
        ]
        rec = _record("BB", actions, hero_id="hero")
        assert rec.defender_position is None


# ── 3-handed scenario ─────────────────────────────────────────────────────────


class TestThreeHandedScenario:
    """Verify flags work correctly in a 3-player hand."""

    def test_btn_steal_opportunity_3handed(self) -> None:
        # 3-handed: BTN, SB, BB
        actions = [
            _a("sb", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("hero", "RAISE", 3, "BTN"),
            _a("sb", "FOLD", 4, "SB"),
            _a("bb", "FOLD", 5, "BB"),
        ]
        rec = _record("BTN", actions)
        assert rec.had_steal_opportunity is True
        assert rec.stole is True

    def test_sb_steal_opportunity_3handed(self) -> None:
        actions = [
            _a("hero", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("btn", "FOLD", 3, "BTN"),
            _a("hero", "RAISE", 4, "SB"),
            _a("bb", "FOLD", 5, "BB"),
        ]
        rec = _record("SB", actions, hero_id="hero")
        assert rec.had_steal_opportunity is True
        assert rec.stole is True

    def test_sb_faces_btn_steal_3handed(self) -> None:
        actions = [
            _a("hero", "POST_SB", 1, "SB"),
            _a("bb", "POST_BB", 2, "BB"),
            _a("btn", "RAISE", 3, "BTN"),
            _a("hero", "FOLD", 4, "SB"),
        ]
        rec = _record("SB", actions, hero_id="hero")
        assert rec.faced_steal is True
        assert rec.folded_to_steal is True
