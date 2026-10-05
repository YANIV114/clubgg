"""
Tests for HandHistoryParser — no DB required.

Fixture hands (see tests/fixtures/sample_hand_history.txt):

  #98765001  NLH $0.50/$1.00  — Charlie folds preflop, Alice wins without showdown
  #98765002  NLH $1.00/$2.00  — Both reach showdown; Bob wins with KK full
  #98765003  NLH $1.00/$2.00/$0.25 antes — Alice all-in preflop; auto-runout to river
  #98765004  NLH $0.50/$1.00  — Alice shows, Bob mucks at showdown
  #98765005  NLH $0.50/$1.00  — Three-way; Bob all-in creates main/side pot split
"""
from decimal import Decimal

import pytest

from app.ingestion.hand_parser import HandHistoryParser, _HAND_BLOCK_RE


@pytest.fixture
def parser() -> HandHistoryParser:
    return HandHistoryParser()


@pytest.fixture
def hand_blocks(sample_hand_history_text: str) -> list[str]:
    return [b.strip() for b in _HAND_BLOCK_RE.split(sample_hand_history_text) if b.strip()]


# ── Fixture sanity ────────────────────────────────────────────────────────────


class TestFixtureSanity:
    def test_splits_five_hands(self, hand_blocks: list[str]) -> None:
        assert len(hand_blocks) == 5

    def test_hand_ids_are_sequential(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        ids = [parser.parse(b)["external_id"] for b in hand_blocks]
        assert ids == ["98765001", "98765002", "98765003", "98765004", "98765005"]


# ── Hand #98765001 — basic hand, no showdown ──────────────────────────────────


class TestHand1Basic:
    """Charlie folds preflop; Alice wins from main pot without showdown."""

    @pytest.fixture
    def result(self, parser: HandHistoryParser, hand_blocks: list[str]) -> dict:
        return parser.parse(hand_blocks[0])

    def test_game_type(self, result: dict) -> None:
        assert result["game_type"] == "NLH"

    def test_stakes(self, result: dict) -> None:
        assert Decimal(result["stakes_sb"]) == Decimal("0.50")
        assert Decimal(result["stakes_bb"]) == Decimal("1.00")
        assert result["stakes_ante"] is None

    def test_club_id(self, result: dict) -> None:
        assert result["club_external_id"] == 42

    def test_table_name(self, result: dict) -> None:
        assert result["table_name"] == "Ruby 3"

    def test_button_seat(self, result: dict) -> None:
        assert result["button_seat"] == 2

    def test_three_players(self, result: dict) -> None:
        usernames = {p["player_username"] for p in result["players"]}
        assert usernames == {"Alice", "Bob", "Charlie"}

    def test_seat_numbers(self, result: dict) -> None:
        seats = {p["player_username"]: p["seat_number"] for p in result["players"]}
        assert seats == {"Alice": 1, "Bob": 2, "Charlie": 3}

    def test_starting_stacks(self, result: dict) -> None:
        stacks = {p["player_username"]: Decimal(p["starting_stack"]) for p in result["players"]}
        assert stacks["Alice"] == Decimal("150.00")
        assert stacks["Bob"] == Decimal("95.50")
        assert stacks["Charlie"] == Decimal("200.00")

    def test_total_pot(self, result: dict) -> None:
        assert Decimal(result["total_pot"]) == Decimal("16.00")

    def test_rake(self, result: dict) -> None:
        assert Decimal(result["total_rake"]) == Decimal("0.80")

    def test_board(self, result: dict) -> None:
        assert result["board_cards"] == "Ah Kd 2c Ts"

    def test_winner_username_stripped_of_seat_prefix(self, result: dict) -> None:
        # Regression: _WINNER_RE must strip "Seat N: " so we get "Alice", not "Seat 1: Alice"
        assert len(result["winners"]) == 1
        assert result["winners"][0]["player_username"] == "Alice"

    def test_winner_amount(self, result: dict) -> None:
        assert Decimal(result["winners"][0]["amount_won"]) == Decimal("15.20")

    def test_winner_pot_type(self, result: dict) -> None:
        # "main pot" normalised to "main"
        assert result["winners"][0]["pot_type"] == "main"

    def test_no_showdown_winner_has_no_hand_description(self, result: dict) -> None:
        # Alice won without showing — no winning_hand_description
        assert result["winners"][0]["winning_hand_description"] is None

    def test_actions_include_blinds(self, result: dict) -> None:
        action_types = [a["action_type"] for a in result["actions"]]
        assert "POST_SB" in action_types
        assert "POST_BB" in action_types

    def test_actions_include_fold_raise_call(self, result: dict) -> None:
        action_types = {a["action_type"] for a in result["actions"]}
        assert {"FOLD", "RAISE", "CALL"}.issubset(action_types)

    def test_ingestion_source(self, result: dict) -> None:
        assert result["ingestion_source"] == "file"

    def test_raw_text_stored(self, result: dict) -> None:
        assert "98765001" in result["raw_text"]

    # saw_flop
    def test_charlie_folded_preflop_did_not_see_flop(self, result: dict) -> None:
        charlie = next(p for p in result["players"] if p["player_username"] == "Charlie")
        assert charlie["saw_flop"] is False

    def test_alice_saw_flop(self, result: dict) -> None:
        alice = next(p for p in result["players"] if p["player_username"] == "Alice")
        assert alice["saw_flop"] is True

    def test_bob_saw_flop(self, result: dict) -> None:
        bob = next(p for p in result["players"] if p["player_username"] == "Bob")
        assert bob["saw_flop"] is True

    # No showdown → did_show False for all
    def test_no_player_showed(self, result: dict) -> None:
        assert all(p["did_show"] is False for p in result["players"])

    def test_no_player_has_hole_cards(self, result: dict) -> None:
        assert all(p["hole_cards"] is None for p in result["players"])


# ── Hand #98765002 — showdown, two shows ──────────────────────────────────────


class TestHand2Showdown:
    """Both Charlie and Bob go to showdown; Bob wins with KK full."""

    @pytest.fixture
    def result(self, parser: HandHistoryParser, hand_blocks: list[str]) -> dict:
        return parser.parse(hand_blocks[1])

    def test_hand_id(self, result: dict) -> None:
        assert result["external_id"] == "98765002"

    def test_stakes_bb(self, result: dict) -> None:
        assert Decimal(result["stakes_bb"]) == Decimal("2.00")

    def test_both_players_did_show(self, result: dict) -> None:
        for p in result["players"]:
            assert p["did_show"] is True, f"{p['player_username']} should have did_show=True"

    def test_hole_cards_populated(self, result: dict) -> None:
        cards = {p["player_username"]: p["hole_cards"] for p in result["players"]}
        assert cards["Charlie"] == "Js 5h"
        assert cards["Bob"] == "Kd Ks"

    def test_winner_username(self, result: dict) -> None:
        assert result["winners"][0]["player_username"] == "Bob"

    def test_winner_amount(self, result: dict) -> None:
        assert Decimal(result["winners"][0]["amount_won"]) == Decimal("215.00")

    def test_winning_hand_description_from_show_line(self, result: dict) -> None:
        # Bob's winner record should carry his hand description from the SHOW line
        winner = result["winners"][0]
        assert winner["winning_hand_description"] == "Full House, Kings full of Jacks"

    def test_show_actions_stored(self, result: dict) -> None:
        show_actions = [a for a in result["actions"] if a["action_type"] == "SHOW"]
        usernames = {a["player_username"] for a in show_actions}
        assert usernames == {"Charlie", "Bob"}

    def test_show_actions_have_showdown_street(self, result: dict) -> None:
        show_actions = [a for a in result["actions"] if a["action_type"] == "SHOW"]
        assert all(a["street"] == "SHOWDOWN" for a in show_actions)

    def test_all_players_saw_flop(self, result: dict) -> None:
        for p in result["players"]:
            assert p["saw_flop"] is True

    def test_total_pot(self, result: dict) -> None:
        assert Decimal(result["total_pot"]) == Decimal("220.00")


# ── Hand #98765003 — antes + all-in preflop ───────────────────────────────────


class TestHand3AntesAllin:
    """
    $1.00/$2.00/$0.25 ante.  Alice shoves for $50 all-in preflop;
    Bob folds; Charlie calls.  Auto-runout — no actions on FLOP/TURN/RIVER.
    """

    @pytest.fixture
    def result(self, parser: HandHistoryParser, hand_blocks: list[str]) -> dict:
        return parser.parse(hand_blocks[2])

    def test_hand_id(self, result: dict) -> None:
        assert result["external_id"] == "98765003"

    def test_antes_parsed(self, result: dict) -> None:
        assert Decimal(result["stakes_ante"]) == Decimal("0.25")

    def test_ante_actions_stored(self, result: dict) -> None:
        ante_actions = [a for a in result["actions"] if a["action_type"] == "POST_ANTE"]
        usernames = {a["player_username"] for a in ante_actions}
        assert usernames == {"Alice", "Bob", "Charlie"}

    def test_all_in_detected(self, result: dict) -> None:
        allin_actions = [a for a in result["actions"] if a["is_all_in"] is True]
        assert any(a["player_username"] == "Alice" for a in allin_actions)

    def test_bob_folded_preflop(self, result: dict) -> None:
        bob = next(p for p in result["players"] if p["player_username"] == "Bob")
        assert bob["saw_flop"] is False

    def test_alice_saw_flop(self, result: dict) -> None:
        # Alice was all-in preflop — she sees the runout
        alice = next(p for p in result["players"] if p["player_username"] == "Alice")
        assert alice["saw_flop"] is True

    def test_charlie_saw_flop(self, result: dict) -> None:
        charlie = next(p for p in result["players"] if p["player_username"] == "Charlie")
        assert charlie["saw_flop"] is True

    def test_alice_hole_cards_from_showdown(self, result: dict) -> None:
        alice = next(p for p in result["players"] if p["player_username"] == "Alice")
        assert alice["hole_cards"] == "Ah Kc"

    def test_charlie_hole_cards_from_showdown(self, result: dict) -> None:
        charlie = next(p for p in result["players"] if p["player_username"] == "Charlie")
        assert charlie["hole_cards"] == "7h 7d"

    def test_winner_is_alice(self, result: dict) -> None:
        assert result["winners"][0]["player_username"] == "Alice"

    def test_winning_hand_description(self, result: dict) -> None:
        assert result["winners"][0]["winning_hand_description"] == "a pair of Kings"

    def test_total_pot(self, result: dict) -> None:
        assert Decimal(result["total_pot"]) == Decimal("100.00")


# ── Hand #98765004 — show + muck at showdown ─────────────────────────────────


class TestHand4ShowMuck:
    """Alice shows; Bob mucks. Both reached showdown."""

    @pytest.fixture
    def result(self, parser: HandHistoryParser, hand_blocks: list[str]) -> dict:
        return parser.parse(hand_blocks[3])

    def test_hand_id(self, result: dict) -> None:
        assert result["external_id"] == "98765004"

    def test_alice_did_show(self, result: dict) -> None:
        alice = next(p for p in result["players"] if p["player_username"] == "Alice")
        assert alice["did_show"] is True

    def test_bob_did_not_show(self, result: dict) -> None:
        # Bob mucked — did_show must remain False
        bob = next(p for p in result["players"] if p["player_username"] == "Bob")
        assert bob["did_show"] is False

    def test_alice_hole_cards(self, result: dict) -> None:
        alice = next(p for p in result["players"] if p["player_username"] == "Alice")
        assert alice["hole_cards"] == "Jc Ts"

    def test_bob_hole_cards_none(self, result: dict) -> None:
        # Muck → hole_cards stays None
        bob = next(p for p in result["players"] if p["player_username"] == "Bob")
        assert bob["hole_cards"] is None

    def test_muck_action_stored(self, result: dict) -> None:
        muck_actions = [a for a in result["actions"] if a["action_type"] == "MUCK"]
        assert len(muck_actions) == 1
        assert muck_actions[0]["player_username"] == "Bob"
        assert muck_actions[0]["street"] == "SHOWDOWN"

    def test_show_action_stored(self, result: dict) -> None:
        show_actions = [a for a in result["actions"] if a["action_type"] == "SHOW"]
        assert any(a["player_username"] == "Alice" for a in show_actions)

    def test_winning_hand_description_on_winner(self, result: dict) -> None:
        winner = result["winners"][0]
        assert winner["player_username"] == "Alice"
        assert winner["winning_hand_description"] == "a straight, Seven to Jack"

    def test_bob_mucked_cards_in_summary_not_captured_as_winner(self, result: dict) -> None:
        # Summary line "Seat 2: Bob mucked [Ks Kh]" must NOT create a winner entry
        winner_usernames = {w["player_username"] for w in result["winners"]}
        assert "Bob" not in winner_usernames

    def test_board_has_five_cards(self, result: dict) -> None:
        assert result["board_cards"] == "7c 8d 9h Td 2s"


# ── Hand #98765005 — side pot + main pot ─────────────────────────────────────


class TestHand5SidePot:
    """
    Bob has only $3 stack — goes all-in for less.
    Alice wins side pot; Bob wins main pot.
    Charlie shows but loses both pots.
    """

    @pytest.fixture
    def result(self, parser: HandHistoryParser, hand_blocks: list[str]) -> dict:
        return parser.parse(hand_blocks[4])

    def test_hand_id(self, result: dict) -> None:
        assert result["external_id"] == "98765005"

    def test_two_winners(self, result: dict) -> None:
        assert len(result["winners"]) == 2

    def test_alice_wins_side_pot(self, result: dict) -> None:
        alice_wins = [w for w in result["winners"] if w["player_username"] == "Alice"]
        assert len(alice_wins) == 1
        assert alice_wins[0]["pot_type"] == "side"
        assert Decimal(alice_wins[0]["amount_won"]) == Decimal("13.50")

    def test_bob_wins_main_pot(self, result: dict) -> None:
        bob_wins = [w for w in result["winners"] if w["player_username"] == "Bob"]
        assert len(bob_wins) == 1
        assert bob_wins[0]["pot_type"] == "main"
        assert Decimal(bob_wins[0]["amount_won"]) == Decimal("8.50")

    def test_charlie_is_not_a_winner(self, result: dict) -> None:
        winner_usernames = {w["player_username"] for w in result["winners"]}
        assert "Charlie" not in winner_usernames

    def test_bob_all_in_action(self, result: dict) -> None:
        allin_actions = [a for a in result["actions"] if a["is_all_in"] is True]
        assert any(a["player_username"] == "Bob" for a in allin_actions)

    def test_all_three_showed(self, result: dict) -> None:
        show_actions = {a["player_username"] for a in result["actions"] if a["action_type"] == "SHOW"}
        assert show_actions == {"Alice", "Charlie", "Bob"}

    def test_all_players_saw_flop(self, result: dict) -> None:
        # No preflop folds; hand goes to showdown
        for p in result["players"]:
            assert p["saw_flop"] is True


# ── Action ordering ───────────────────────────────────────────────────────────


class TestActionOrdering:
    """action_order must be monotonically increasing across all streets."""

    def test_action_order_monotonically_increasing(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        for block in hand_blocks:
            result = parser.parse(block)
            orders = [a["action_order"] for a in result["actions"]]
            assert orders == list(range(len(orders))), (
                f"action_order is not monotonically increasing for hand "
                f"{result['external_id']}: {orders}"
            )

    def test_showdown_actions_after_street_actions(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        # Hand 2: SHOW actions must come after all RIVER actions
        result = parser.parse(hand_blocks[1])
        river_orders = [a["action_order"] for a in result["actions"] if a["street"] == "RIVER"]
        show_orders = [a["action_order"] for a in result["actions"] if a["action_type"] == "SHOW"]
        if river_orders and show_orders:
            assert max(river_orders) < min(show_orders)


# ── GGPoker tournament format ─────────────────────────────────────────────────

# Synthetic hand in the GGPoker/ClubGG tournament export format. The ante is
# not in the header (only "Level14(600/1,200)"); it appears only as
# "posts the ante" lines in the preamble.
_GG_TOURNAMENT_HAND = """\
Poker Hand #tour_900000001: Tournament #1000001, Test GTD NLH No Limit - Level14(600/1,200) - 2026/04/18 23:23:51
Table '' 8-max Seat #2 is the button
Seat 1: aaaa1111 (50,000 in chips)
Seat 2: bbbb2222 (40,000 in chips)
Seat 4: cccc3333 (30,000 in chips)
Seat 5: Hero (16,200 in chips)
aaaa1111: posts the ante 180
bbbb2222: posts the ante 180
cccc3333: posts the ante 180
Hero: posts the ante 180
cccc3333: posts small blind 600
Hero: posts big blind 1,200
*** HOLE CARDS ***
Dealt to aaaa1111
Dealt to bbbb2222
Dealt to cccc3333
Dealt to Hero [Qh 4h]
aaaa1111: folds
bbbb2222: raises 1,440 to 2,640
cccc3333: folds
Hero: folds
bbbb2222 collected 4,560 from pot
*** SUMMARY ***
Total pot 4,560
Seat 1: aaaa1111 folded before Flop
Seat 2: bbbb2222 won (4,560)
Seat 4: cccc3333(small blind) folded before Flop
Seat 5: Hero(big blind) folded before Flop
"""


class TestGGTournamentFormat:
    def test_blinds_parsed_from_level(self, parser: HandHistoryParser) -> None:
        result = parser.parse(_GG_TOURNAMENT_HAND)
        assert Decimal(result["stakes_sb"]) == Decimal("600")
        assert Decimal(result["stakes_bb"]) == Decimal("1200")

    def test_ante_taken_from_post_ante_lines(self, parser: HandHistoryParser) -> None:
        result = parser.parse(_GG_TOURNAMENT_HAND)
        assert result["stakes_ante"] is not None
        assert Decimal(result["stakes_ante"]) == Decimal("180")

    def test_ante_posts_recorded_as_actions(self, parser: HandHistoryParser) -> None:
        result = parser.parse(_GG_TOURNAMENT_HAND)
        antes = [a for a in result["actions"] if a["action_type"] == "POST_ANTE"]
        assert len(antes) == 4


# ── Invalid input ─────────────────────────────────────────────────────────────


class TestInvalidInput:
    def test_invalid_block_raises(self, parser: HandHistoryParser) -> None:
        with pytest.raises(ValueError, match="Could not parse hand header"):
            parser.parse("this is not a valid hand history block")
