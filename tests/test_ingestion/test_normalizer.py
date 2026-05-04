"""
Round-trip tests: HandHistoryParser → normalize_file_hand() → IngestHandPayload.

These tests verify the full conversion pipeline from raw text to the typed
payload consumed by the service layer.  No DB required.
"""
from decimal import Decimal

import pytest

from app.features.normalize_hand import normalize_hand_players
from app.ingestion.hand_parser import HandHistoryParser, _HAND_BLOCK_RE
from app.ingestion.normalizer import normalize_file_hand
from app.models.hand import ActionType, GameType, Street
from app.schemas.ingestion import IngestHandPayload


@pytest.fixture
def parser() -> HandHistoryParser:
    return HandHistoryParser()


@pytest.fixture
def hand_blocks(sample_hand_history_text: str) -> list[str]:
    return [b.strip() for b in _HAND_BLOCK_RE.split(sample_hand_history_text) if b.strip()]


def _normalize(parser: HandHistoryParser, block: str, club_id: str = "42") -> IngestHandPayload:
    """Parse one block, run position enrichment, then normalize."""
    raw = parser.parse(block)
    normalize_hand_players(raw["players"], Decimal(raw["stakes_bb"]), raw.get("button_seat"))
    return normalize_file_hand(raw, club_id)


# ── Hand #98765001 — basic round-trip ─────────────────────────────────────────


class TestNormalizerHand1:
    @pytest.fixture
    def payload(self, parser: HandHistoryParser, hand_blocks: list[str]) -> IngestHandPayload:
        return _normalize(parser, hand_blocks[0])

    def test_returns_ingest_hand_payload(self, payload: IngestHandPayload) -> None:
        assert isinstance(payload, IngestHandPayload)

    def test_external_id(self, payload: IngestHandPayload) -> None:
        assert payload.external_id == "98765001"

    def test_club_external_id(self, payload: IngestHandPayload) -> None:
        assert payload.club_external_id == 42

    def test_game_type_enum(self, payload: IngestHandPayload) -> None:
        assert payload.game_type == GameType.NLH

    def test_stakes(self, payload: IngestHandPayload) -> None:
        assert payload.stakes_sb == Decimal("0.50")
        assert payload.stakes_bb == Decimal("1.00")
        assert payload.stakes_ante is None

    def test_total_pot(self, payload: IngestHandPayload) -> None:
        assert payload.total_pot == Decimal("16.00")

    def test_rake(self, payload: IngestHandPayload) -> None:
        assert payload.total_rake == Decimal("0.80")

    def test_ingestion_source(self, payload: IngestHandPayload) -> None:
        assert payload.ingestion_source == "file"

    def test_players_count(self, payload: IngestHandPayload) -> None:
        assert len(payload.players) == 3

    def test_player_usernames(self, payload: IngestHandPayload) -> None:
        usernames = {p.player_username for p in payload.players}
        assert usernames == {"Alice", "Bob", "Charlie"}

    def test_winner_username(self, payload: IngestHandPayload) -> None:
        assert len(payload.winners) == 1
        assert payload.winners[0].player_username == "Alice"

    def test_winner_pot_type(self, payload: IngestHandPayload) -> None:
        assert payload.winners[0].pot_type == "main"

    def test_winner_amount(self, payload: IngestHandPayload) -> None:
        assert payload.winners[0].amount_won == Decimal("15.20")

    def test_actions_contain_typed_enums(self, payload: IngestHandPayload) -> None:
        action_types = {a.action_type for a in payload.actions}
        assert ActionType.POST_SB in action_types
        assert ActionType.POST_BB in action_types
        assert ActionType.FOLD in action_types

    def test_streets_are_enum_values(self, payload: IngestHandPayload) -> None:
        streets = {a.street for a in payload.actions}
        assert streets.issubset(set(Street))

    def test_button_seat_passed_through(self, payload: IngestHandPayload) -> None:
        assert payload.button_seat == 2

    def test_starting_stacks_are_decimal(self, payload: IngestHandPayload) -> None:
        for p in payload.players:
            assert isinstance(p.starting_stack, Decimal)

    def test_stack_bb_populated(self, payload: IngestHandPayload) -> None:
        # normalize_hand_players() should have computed stack_bb = stack / bb
        for p in payload.players:
            assert p.stack_bb is not None
            assert p.stack_bb > 0


# ── Hand #98765002 — showdown round-trip ─────────────────────────────────────


class TestNormalizerHand2Showdown:
    @pytest.fixture
    def payload(self, parser: HandHistoryParser, hand_blocks: list[str]) -> IngestHandPayload:
        return _normalize(parser, hand_blocks[1])

    def test_both_players_did_show(self, payload: IngestHandPayload) -> None:
        for p in payload.players:
            assert p.did_show is True

    def test_hole_cards_set(self, payload: IngestHandPayload) -> None:
        cards = {p.player_username: p.hole_cards for p in payload.players}
        assert cards["Charlie"] == "Js 5h"
        assert cards["Bob"] == "Kd Ks"

    def test_winner_hand_description(self, payload: IngestHandPayload) -> None:
        assert payload.winners[0].winning_hand_description == "Full House, Kings full of Jacks"

    def test_show_actions_as_enum(self, payload: IngestHandPayload) -> None:
        show_actions = [a for a in payload.actions if a.action_type == ActionType.SHOW]
        assert len(show_actions) == 2

    def test_show_actions_street_is_showdown(self, payload: IngestHandPayload) -> None:
        show_actions = [a for a in payload.actions if a.action_type == ActionType.SHOW]
        assert all(a.street == Street.SHOWDOWN for a in show_actions)


# ── Hand #98765003 — antes + all-in round-trip ───────────────────────────────


class TestNormalizerHand3Antes:
    @pytest.fixture
    def payload(self, parser: HandHistoryParser, hand_blocks: list[str]) -> IngestHandPayload:
        return _normalize(parser, hand_blocks[2])

    def test_stakes_ante(self, payload: IngestHandPayload) -> None:
        assert payload.stakes_ante == Decimal("0.25")

    def test_ante_actions_present(self, payload: IngestHandPayload) -> None:
        ante_actions = [a for a in payload.actions if a.action_type == ActionType.POST_ANTE]
        assert len(ante_actions) == 3

    def test_all_in_action_flag(self, payload: IngestHandPayload) -> None:
        allin = [a for a in payload.actions if a.is_all_in]
        assert any(a.player_username == "Alice" for a in allin)

    def test_winner_alice(self, payload: IngestHandPayload) -> None:
        assert payload.winners[0].player_username == "Alice"


# ── Hand #98765004 — muck round-trip ─────────────────────────────────────────


class TestNormalizerHand4Muck:
    @pytest.fixture
    def payload(self, parser: HandHistoryParser, hand_blocks: list[str]) -> IngestHandPayload:
        return _normalize(parser, hand_blocks[3])

    def test_alice_did_show(self, payload: IngestHandPayload) -> None:
        alice = next(p for p in payload.players if p.player_username == "Alice")
        assert alice.did_show is True

    def test_bob_did_not_show(self, payload: IngestHandPayload) -> None:
        bob = next(p for p in payload.players if p.player_username == "Bob")
        assert bob.did_show is False

    def test_muck_action_typed(self, payload: IngestHandPayload) -> None:
        muck_actions = [a for a in payload.actions if a.action_type == ActionType.MUCK]
        assert len(muck_actions) == 1
        assert muck_actions[0].player_username == "Bob"

    def test_winning_hand_description_on_winner(self, payload: IngestHandPayload) -> None:
        assert payload.winners[0].winning_hand_description == "a straight, Seven to Jack"


# ── Hand #98765005 — side pot round-trip ─────────────────────────────────────


class TestNormalizerHand5SidePot:
    @pytest.fixture
    def payload(self, parser: HandHistoryParser, hand_blocks: list[str]) -> IngestHandPayload:
        return _normalize(parser, hand_blocks[4])

    def test_two_winners(self, payload: IngestHandPayload) -> None:
        assert len(payload.winners) == 2

    def test_alice_wins_side(self, payload: IngestHandPayload) -> None:
        alice_wins = [w for w in payload.winners if w.player_username == "Alice"]
        assert alice_wins[0].pot_type == "side"

    def test_bob_wins_main(self, payload: IngestHandPayload) -> None:
        bob_wins = [w for w in payload.winners if w.player_username == "Bob"]
        assert bob_wins[0].pot_type == "main"

    def test_three_show_actions(self, payload: IngestHandPayload) -> None:
        show_actions = [a for a in payload.actions if a.action_type == ActionType.SHOW]
        assert len(show_actions) == 3


# ── club_id fallback ──────────────────────────────────────────────────────────


class TestClubIdFallback:
    """
    When club_external_id is absent from the parser output (shouldn't happen
    in practice but must be safe), normalize_file_hand() falls back to the
    club_id argument.
    """

    def test_club_id_from_argument_when_missing(
        self, parser: HandHistoryParser, hand_blocks: list[str]
    ) -> None:
        raw = parser.parse(hand_blocks[0])
        # Simulate missing club_external_id
        raw["club_external_id"] = 0
        payload = normalize_file_hand(raw, "99")
        assert payload.club_external_id == 99
