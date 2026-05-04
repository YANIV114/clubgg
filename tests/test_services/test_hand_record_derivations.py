"""
Unit tests for the three pure derivation functions in hand_service.py:

  _derive_saw_flop(board_cards, hero_actions)
  _derive_reached_showdown(did_show, hero_actions)
  _derive_won_at_showdown(reached_showdown, hero_hp_id, winner_hp_ids)

No DB required.  These helpers encapsulate the exact logic that
hand_records_for_player() uses so we can verify correctness
independently of any async/ORM machinery.

Also contains cross-validation tests that verify the parser's saw_flop
output agrees with what _derive_saw_flop() would compute from board_cards.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.ingestion.hand_parser import HandHistoryParser, _HAND_BLOCK_RE
from app.services.hand_service import (
    _derive_reached_showdown,
    _derive_saw_flop,
    _derive_won_at_showdown,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _action(street: str, action_type: str) -> SimpleNamespace:
    """Build a minimal mock action object with just the two fields we test."""
    return SimpleNamespace(street=street, action_type=action_type)


def _winner(hp_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(hand_player_id=hp_id)


# ── _derive_saw_flop ──────────────────────────────────────────────────────────


class TestDeriveSawFlop:
    """
    Equivalence classes:
      board_cards: None | 2-card (no flop) | 3-card (flop) | 4-card | 5-card
      hero_actions: folded-preflop | did-not-fold-preflop | all-in (no fold)
    """

    def test_no_board_cards_is_false(self) -> None:
        assert _derive_saw_flop(None, []) is False

    def test_empty_board_is_false(self) -> None:
        # Defensive: empty string should never appear in production but must be safe
        assert _derive_saw_flop("", []) is False

    def test_one_card_board_is_false(self) -> None:
        # Shouldn't happen in NLH but must not raise
        assert _derive_saw_flop("Ah", []) is False

    def test_two_card_board_is_false(self) -> None:
        # Partial board — should not happen but must be safe
        assert _derive_saw_flop("Ah Kd", []) is False

    def test_three_card_board_active_player(self) -> None:
        # Flop dealt, player did not fold
        assert _derive_saw_flop("Ah Kd 2c", []) is True

    def test_four_card_board_active_player(self) -> None:
        assert _derive_saw_flop("Ah Kd 2c Ts", []) is True

    def test_five_card_board_active_player(self) -> None:
        assert _derive_saw_flop("Ah Kd 2c Ts 9h", []) is True

    def test_player_folded_preflop_saw_flop_false(self) -> None:
        actions = [_action("PREFLOP", "FOLD")]
        assert _derive_saw_flop("Ah Kd 2c Ts", actions) is False

    def test_player_folded_on_flop_saw_flop_true(self) -> None:
        # FLOP fold ≠ preflop fold — they already saw the flop
        actions = [_action("FLOP", "FOLD")]
        assert _derive_saw_flop("Ah Kd 2c Ts", actions) is True

    def test_player_folded_on_turn_saw_flop_true(self) -> None:
        actions = [_action("TURN", "FOLD")]
        assert _derive_saw_flop("Ah Kd 2c Ts", actions) is True

    def test_all_in_preflop_no_fold_saw_flop_true(self) -> None:
        # All-in player has no FOLD action — they see the runout
        actions = [_action("PREFLOP", "ALL_IN")]
        assert _derive_saw_flop("Ah Kd 2c Ts 9h", actions) is True

    def test_preflop_raise_then_fold_to_3bet(self) -> None:
        # Opened but folded to a 3bet — still a preflop fold
        actions = [_action("PREFLOP", "RAISE"), _action("PREFLOP", "FOLD")]
        assert _derive_saw_flop("Ah Kd 2c Ts", actions) is False

    def test_call_preflop_then_fold_on_flop(self) -> None:
        # Called preflop (saw the flop), then folded on the flop
        actions = [_action("PREFLOP", "CALL"), _action("FLOP", "FOLD")]
        assert _derive_saw_flop("Ah Kd 2c", actions) is True

    def test_blind_post_only_no_further_action(self) -> None:
        # BB who never faced a raise — no fold action, saw the flop
        actions = [_action("PREFLOP", "POST_BB")]
        assert _derive_saw_flop("Ah Kd 2c", actions) is True


# ── _derive_reached_showdown ──────────────────────────────────────────────────


class TestDeriveReachedShowdown:
    """
    Paths to True:
      - did_show=True (set for explicit shows by both parser and API)
      - SHOWDOWN-street SHOW action
      - SHOWDOWN-street MUCK action

    Paths to False:
      - did_show=False AND no SHOWDOWN actions
      - SHOWDOWN action with wrong street
      - Non-showdown action
    """

    def test_folded_player_no_showdown(self) -> None:
        actions = [_action("PREFLOP", "FOLD")]
        assert _derive_reached_showdown(False, actions) is False

    def test_did_show_true_no_actions(self) -> None:
        # API path: API sets did_show=True, no explicit action stored
        assert _derive_reached_showdown(True, []) is True

    def test_show_action_did_show_false(self) -> None:
        # Parser stores SHOW action before _enrich sets did_show
        # In practice did_show=True for SHOW, but the action alone is sufficient
        actions = [_action("SHOWDOWN", "SHOW")]
        assert _derive_reached_showdown(False, actions) is True

    def test_muck_action_did_show_false(self) -> None:
        actions = [_action("SHOWDOWN", "MUCK")]
        assert _derive_reached_showdown(False, actions) is True

    def test_show_action_wrong_street_does_not_count(self) -> None:
        # A hypothetical action named SHOW on a non-showdown street must not fire
        actions = [_action("RIVER", "SHOW")]
        assert _derive_reached_showdown(False, actions) is False

    def test_muck_action_wrong_street_does_not_count(self) -> None:
        actions = [_action("FLOP", "MUCK")]
        assert _derive_reached_showdown(False, actions) is False

    def test_both_did_show_and_show_action(self) -> None:
        # Redundant but must not raise
        actions = [_action("SHOWDOWN", "SHOW")]
        assert _derive_reached_showdown(True, actions) is True

    def test_no_actions_no_show_is_false(self) -> None:
        assert _derive_reached_showdown(False, []) is False

    def test_only_street_actions_no_showdown(self) -> None:
        actions = [
            _action("PREFLOP", "RAISE"),
            _action("FLOP", "BET"),
            _action("TURN", "BET"),
            _action("RIVER", "BET"),
        ]
        assert _derive_reached_showdown(False, actions) is False


# ── _derive_won_at_showdown ───────────────────────────────────────────────────


class TestDeriveWonAtShowdown:
    """
    Matrix: reached_showdown × (hero in winners or not)

    Additional cases:
      - Side-pot winner who won but didn't reach showdown (uncontested)
      - Chop pot (both players win)
      - Player reached showdown but lost
    """

    def test_reached_showdown_and_is_winner(self) -> None:
        hp_id = uuid.uuid4()
        assert _derive_won_at_showdown(True, hp_id, {hp_id}) is True

    def test_reached_showdown_and_not_winner(self) -> None:
        hp_id = uuid.uuid4()
        other = uuid.uuid4()
        assert _derive_won_at_showdown(True, hp_id, {other}) is False

    def test_did_not_reach_showdown_but_wins_uncontested(self) -> None:
        # Player wins when everyone else folds — no showdown, has a winner record.
        # reached_showdown=False so won_at_showdown must be False.
        hp_id = uuid.uuid4()
        assert _derive_won_at_showdown(False, hp_id, {hp_id}) is False

    def test_did_not_reach_showdown_not_in_winners(self) -> None:
        hp_id = uuid.uuid4()
        assert _derive_won_at_showdown(False, hp_id, set()) is False

    def test_chop_pot_both_win(self) -> None:
        hp1 = uuid.uuid4()
        hp2 = uuid.uuid4()
        assert _derive_won_at_showdown(True, hp1, {hp1, hp2}) is True
        assert _derive_won_at_showdown(True, hp2, {hp1, hp2}) is True

    def test_side_pot_winner_who_reached_showdown(self) -> None:
        # Alice wins side pot and reached showdown — True
        alice = uuid.uuid4()
        bob = uuid.uuid4()
        winner_ids = {alice, bob}  # both won something
        assert _derive_won_at_showdown(True, alice, winner_ids) is True

    def test_player_reached_showdown_and_lost_side_pot(self) -> None:
        # Charlie reaches showdown (shows cards) but wins nothing
        charlie = uuid.uuid4()
        alice = uuid.uuid4()
        assert _derive_won_at_showdown(True, charlie, {alice}) is False

    def test_empty_winner_set(self) -> None:
        hp_id = uuid.uuid4()
        assert _derive_won_at_showdown(True, hp_id, set()) is False


# ── Cross-validation: parser vs. board_cards derivation ──────────────────────


class TestSawFlopCrossValidation:
    """
    The parser derives saw_flop from streets_dealt + preflop-fold detection.
    The DB bridge derives saw_flop from board_cards + preflop-fold detection.

    Both paths must agree on every fixture hand.  This test catches any
    divergence between the two implementations.
    """

    @pytest.fixture
    def parser(self) -> HandHistoryParser:
        return HandHistoryParser()

    @pytest.fixture
    def hand_blocks(self, sample_hand_history_text: str) -> list[str]:
        return [
            b.strip() for b in _HAND_BLOCK_RE.split(sample_hand_history_text) if b.strip()
        ]

    def test_saw_flop_agrees_across_all_fixture_hands(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        for block in hand_blocks:
            result = parser.parse(block)
            board = result.get("board_cards")
            preflop_folds = {
                a["player_username"]
                for a in result["actions"]
                if a["street"] == "PREFLOP" and a["action_type"] == "FOLD"
            }
            for p in result["players"]:
                # Simulate what _derive_saw_flop does, using the parser's
                # action list as a proxy for hero_hp.actions
                mock_actions = [
                    _action(a["street"], a["action_type"])
                    for a in result["actions"]
                    if a["player_username"] == p["player_username"]
                ]
                expected = _derive_saw_flop(board, mock_actions)
                actual = p["saw_flop"]
                assert actual == expected, (
                    f"Hand {result['external_id']}: {p['player_username']}: "
                    f"parser saw_flop={actual}, board-based={expected}, "
                    f"board={board!r}, preflop_folds={preflop_folds}"
                )

    def test_reached_showdown_agrees_with_action_list(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        """
        _derive_reached_showdown(did_show, actions) should equal
        did_show OR (player has SHOW/MUCK in SHOWDOWN street).
        These are tautologically equal by definition but this test
        validates that the parser actually writes the right actions.
        """
        for block in hand_blocks:
            result = parser.parse(block)
            for p in result["players"]:
                username = p["player_username"]
                mock_actions = [
                    _action(a["street"], a["action_type"])
                    for a in result["actions"]
                    if a["player_username"] == username
                ]
                derived = _derive_reached_showdown(p["did_show"], mock_actions)
                # Manual check: did they have a SHOW or MUCK action?
                has_sd_action = any(
                    a.street == "SHOWDOWN" and a.action_type in ("SHOW", "MUCK")
                    for a in mock_actions
                )
                expected = p["did_show"] or has_sd_action
                assert derived == expected, (
                    f"Hand {result['external_id']}: {username}: "
                    f"derived={derived}, expected={expected}"
                )

    def test_won_at_showdown_fixture_hand5(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        """
        Hand #98765005 (3-way, side pot):
          - Alice: wins side pot, reached showdown → won_at_showdown=True
          - Bob:   wins main pot, reached showdown → won_at_showdown=True
          - Charlie: reached showdown, lost → won_at_showdown=False
        Using simulated UUIDs for winner IDs.
        """
        result = parser.parse(hand_blocks[4])
        # Assign fake UUIDs to players in order
        hp_ids = {p["player_username"]: uuid.uuid4() for p in result["players"]}
        # Winners from parser output
        winner_ids = {hp_ids[w["player_username"]] for w in result["winners"]}

        for p in result["players"]:
            username = p["player_username"]
            mock_actions = [
                _action(a["street"], a["action_type"])
                for a in result["actions"]
                if a["player_username"] == username
            ]
            reached_sd = _derive_reached_showdown(p["did_show"], mock_actions)
            won_at_sd = _derive_won_at_showdown(reached_sd, hp_ids[username], winner_ids)

            if username == "Alice":
                assert reached_sd is True
                assert won_at_sd is True
            elif username == "Bob":
                assert reached_sd is True
                assert won_at_sd is True
            elif username == "Charlie":
                assert reached_sd is True
                assert won_at_sd is False  # showed cards but lost both pots
