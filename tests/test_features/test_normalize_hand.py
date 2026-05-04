"""Tests for the hand normalization pipeline."""
from decimal import Decimal

import pytest

from app.features.normalize_hand import extract_button_seat, normalize_hand_players
from app.features.position import Position


def _make_player(username: str, seat: int, stack: str) -> dict:
    return {"player_username": username, "seat_number": seat, "starting_stack": stack}


class TestExtractButtonSeat:
    def test_found(self) -> None:
        text = "Table 'Ruby 3' 6-max Seat #3 is the button"
        assert extract_button_seat(text) == 3

    def test_seat_2(self) -> None:
        text = "Table 'Diamond' 9-max Seat #2 is the button"
        assert extract_button_seat(text) == 2

    def test_not_found(self) -> None:
        assert extract_button_seat("no button info here") is None

    def test_none_input(self) -> None:
        assert extract_button_seat(None) is None


class TestNormalizeHandPlayers:
    def _six_max_players(self) -> list[dict]:
        return [
            _make_player("Alice", 1, "150.00"),
            _make_player("Bob", 2, "95.50"),
            _make_player("Charlie", 3, "200.00"),
            _make_player("Dave", 4, "80.00"),
            _make_player("Eve", 5, "120.00"),
            _make_player("Frank", 6, "110.00"),
        ]

    def test_positions_assigned(self) -> None:
        players = self._six_max_players()
        normalize_hand_players(players, Decimal("1.00"), button_seat=1)
        positions = {p["player_username"]: p["position"] for p in players}
        assert positions["Alice"] == "BTN"
        assert positions["Bob"] == "SB"
        assert positions["Charlie"] == "BB"

    def test_stack_bb_computed(self) -> None:
        players = self._six_max_players()
        normalize_hand_players(players, Decimal("2.00"), button_seat=1)
        alice = next(p for p in players if p["player_username"] == "Alice")
        # 150 / 2 = 75.00
        assert Decimal(alice["stack_bb"]) == Decimal("75.00")

    def test_effective_stack_bb_is_min_of_hero_and_deepest_opp(self) -> None:
        players = [
            _make_player("Hero", 1, "100"),
            _make_player("Villain", 2, "50"),
        ]
        normalize_hand_players(players, Decimal("2"), button_seat=1)
        hero = next(p for p in players if p["player_username"] == "Hero")
        # Hero: 100/2=50bb, Villain: 50/2=25bb → eff = min(50, 25) = 25
        assert Decimal(hero["effective_stack_bb"]) == Decimal("25.00")

    def test_unknown_button_seat_gives_none_position(self) -> None:
        players = self._six_max_players()
        normalize_hand_players(players, Decimal("1"), button_seat=None)
        for p in players:
            assert p["position"] is None

    def test_zero_bb_gives_none_stack(self) -> None:
        players = self._six_max_players()
        normalize_hand_players(players, Decimal("0"), button_seat=1)
        for p in players:
            assert p["stack_bb"] is None
            assert p["effective_stack_bb"] is None

    def test_empty_players_returns_empty(self) -> None:
        result = normalize_hand_players([], Decimal("2"), button_seat=1)
        assert result == []

    def test_mutates_in_place(self) -> None:
        players = [_make_player("A", 1, "100")]
        result = normalize_hand_players(players, Decimal("2"), button_seat=1)
        assert result is players
        assert "position" in players[0]
