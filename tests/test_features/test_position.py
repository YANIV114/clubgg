"""Tests for position normalization."""
import pytest

from app.features.labels import MetricLabel
from app.features.position import (
    IP_POSITIONS,
    Position,
    _clockwise_sort,
    compute_position,
    is_in_position,
    is_out_of_position,
    position_from_offset,
)


class TestClockwiseSort:
    def test_simple(self) -> None:
        assert _clockwise_sort([1, 2, 3, 4, 5, 6], 3) == [3, 4, 5, 6, 1, 2]

    def test_anchor_at_start(self) -> None:
        assert _clockwise_sort([1, 2, 3, 4], 1) == [1, 2, 3, 4]

    def test_anchor_at_end(self) -> None:
        assert _clockwise_sort([1, 2, 3, 4], 4) == [4, 1, 2, 3]

    def test_single_seat(self) -> None:
        assert _clockwise_sort([5], 5) == [5]

    def test_anchor_not_in_seats_raises(self) -> None:
        with pytest.raises(ValueError):
            _clockwise_sort([1, 2, 3], 9)


class TestComputePosition:
    # ── 6-max ─────────────────────────────────────────────────────────────

    def test_6max_button(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(3, button_seat=3, active_seats=seats)
        assert result.value == Position.BTN
        assert result.label == MetricLabel.OBSERVED

    def test_6max_sb(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(4, button_seat=3, active_seats=seats)
        assert result.value == Position.SB

    def test_6max_bb(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(5, button_seat=3, active_seats=seats)
        assert result.value == Position.BB

    def test_6max_utg(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(6, button_seat=3, active_seats=seats)
        assert result.value == Position.UTG

    def test_6max_hj(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(1, button_seat=3, active_seats=seats)
        assert result.value == Position.HJ

    def test_6max_co(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(2, button_seat=3, active_seats=seats)
        assert result.value == Position.CO

    # ── Wrap-around (button at seat 6, UTG at seat 3) ────────────────────

    def test_6max_button_at_max_seat(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(6, button_seat=6, active_seats=seats)
        assert result.value == Position.BTN

    def test_6max_sb_wraps(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        result = compute_position(1, button_seat=6, active_seats=seats)
        assert result.value == Position.SB

    # ── 9-max ─────────────────────────────────────────────────────────────

    def test_9max_utg(self) -> None:
        seats = list(range(1, 10))
        # button=5, then 6=SB, 7=BB, 8=UTG, 9=UTG1, 1=UTG2, 2=LJ, 3=HJ, 4=CO
        result = compute_position(8, button_seat=5, active_seats=seats)
        assert result.value == Position.UTG

    def test_9max_co(self) -> None:
        seats = list(range(1, 10))
        result = compute_position(4, button_seat=5, active_seats=seats)
        assert result.value == Position.CO

    def test_9max_hj(self) -> None:
        seats = list(range(1, 10))
        result = compute_position(3, button_seat=5, active_seats=seats)
        assert result.value == Position.HJ

    # ── Heads-up ─────────────────────────────────────────────────────────

    def test_hu_btn(self) -> None:
        result = compute_position(1, button_seat=1, active_seats=[1, 2])
        assert result.value == Position.BTN

    def test_hu_bb(self) -> None:
        result = compute_position(2, button_seat=1, active_seats=[1, 2])
        assert result.value == Position.BB

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_seat_not_in_active_returns_unknown(self) -> None:
        result = compute_position(9, button_seat=1, active_seats=[1, 2, 3])
        assert result.value == Position.UNKNOWN

    def test_all_positions_are_observed(self) -> None:
        seats = [1, 2, 3, 4, 5, 6]
        for seat in seats:
            result = compute_position(seat, button_seat=1, active_seats=seats)
            assert result.label == MetricLabel.OBSERVED


class TestPositionHelpers:
    def test_is_in_position_btn(self) -> None:
        assert is_in_position(Position.BTN) is True

    def test_is_in_position_co(self) -> None:
        assert is_in_position(Position.CO) is True

    def test_is_in_position_utg(self) -> None:
        assert is_in_position(Position.UTG) is False

    def test_is_out_of_position_bb(self) -> None:
        assert is_out_of_position(Position.BB) is True

    def test_is_out_of_position_btn(self) -> None:
        assert is_out_of_position(Position.BTN) is False

    def test_position_from_offset_6max(self) -> None:
        assert position_from_offset(0, 6) == Position.BTN
        assert position_from_offset(5, 6) == Position.CO
        assert position_from_offset(1, 6) == Position.SB
