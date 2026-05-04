"""
Position normalization.

Computes the seat-relative position label from raw seat numbers.

Model
-----
Seats are numbered 1–N (as in ClubGG).  The button is a specific seat.
Positions are assigned by counting *clockwise* from the button:

  offset 0 → BTN
  offset 1 → SB
  offset 2 → BB
  offset 3..N-3 → early/middle positions (UTG, UTG1, LJ, …)
  offset N-2 → HJ
  offset N-1 → CO

This gives accurate position labels for 2–9 handed tables.

For heads-up:
  offset 0 → BTN (= SB in HU: acts first preflop, last postflop)
  offset 1 → BB

Assumptions:
- Seats passed in are exactly the active seats (no empty seats between them).
  If ClubGG allows gaps, callers should filter to occupied seats first.
- Seat numbers are in clockwise order as dealt by ClubGG (ascending, wrapping
  at the max seat back to seat 1).
- A player whose seat is NOT in active_seats returns Position.UNKNOWN.

Label: OBSERVED — position is directly derivable from seat/button data
in the hand history with no inferential step.
"""
from __future__ import annotations

from enum import StrEnum

from app.features.labels import LabeledMetric, MetricLabel, observed


class Position(StrEnum):
    BTN = "BTN"
    CO = "CO"
    HJ = "HJ"
    LJ = "LJ"       # also called MP in some nomenclatures (9-max position 6)
    MP = "MP"        # 9-max position 5
    UTG2 = "UTG2"    # 9-max position 4  (UTG+2)
    UTG1 = "UTG1"    # position 3 from button in larger tables (UTG+1)
    UTG = "UTG"      # first to act preflop
    BB = "BB"
    SB = "SB"
    UNKNOWN = "UNKNOWN"


# Position label by (table_size, offset_from_button)
# offset = (seat_index_in_sorted_active - button_index) % table_size
_POSITION_MAP: dict[int, dict[int, Position]] = {
    2: {
        0: Position.BTN,   # BTN = SB in HU
        1: Position.BB,
    },
    3: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        # Note: in 3-handed there is no "UTG" — BB is also UTG preflop
    },
    4: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        3: Position.CO,    # CO is UTG in 4-handed
    },
    5: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        3: Position.UTG,
        4: Position.CO,
    },
    6: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        3: Position.UTG,
        4: Position.HJ,
        5: Position.CO,
    },
    7: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        3: Position.UTG,
        4: Position.MP,
        5: Position.HJ,
        6: Position.CO,
    },
    8: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        3: Position.UTG,
        4: Position.UTG1,
        5: Position.MP,
        6: Position.HJ,
        7: Position.CO,
    },
    9: {
        0: Position.BTN,
        1: Position.SB,
        2: Position.BB,
        3: Position.UTG,
        4: Position.UTG1,
        5: Position.UTG2,
        6: Position.LJ,
        7: Position.HJ,
        8: Position.CO,
    },
}

# Positional ordering for analysis (early → late; higher = more positional advantage)
POSITION_ORDER: dict[Position, int] = {
    Position.BB: 0,
    Position.SB: 1,
    Position.BTN: 2,
    Position.CO: 3,
    Position.HJ: 4,
    Position.LJ: 5,
    Position.MP: 6,
    Position.UTG2: 7,
    Position.UTG1: 8,
    Position.UTG: 9,
    Position.UNKNOWN: -1,
}

# Grouped for analysis
IP_POSITIONS = frozenset({Position.BTN, Position.CO, Position.HJ})
EP_POSITIONS = frozenset({Position.UTG, Position.UTG1, Position.UTG2})
BLIND_POSITIONS = frozenset({Position.SB, Position.BB})


def compute_position(
    seat_number: int,
    button_seat: int,
    active_seats: list[int],
) -> LabeledMetric[Position]:
    """
    Compute the position label for a given seat.

    Parameters
    ----------
    seat_number:
        The seat whose position we want.
    button_seat:
        The seat holding the dealer button this hand.
    active_seats:
        All occupied seat numbers at this hand, in clockwise order
        (ascending, with wrap-around if the highest seat precedes seat 1).

    Returns
    -------
    LabeledMetric[Position] with label=OBSERVED.
    Returns Position.UNKNOWN if seat_number is not in active_seats.
    """
    if seat_number not in active_seats:
        return LabeledMetric(
            value=Position.UNKNOWN,
            label=MetricLabel.OBSERVED,
            source="seat not in active seats",
        )

    # Sort seats in clockwise order.
    # ClubGG seats are 1-N, clockwise ascending. Wrap-around handled by
    # rotating so button is always at index 0.
    sorted_seats = _clockwise_sort(active_seats, button_seat)
    n = len(sorted_seats)
    try:
        seat_idx = sorted_seats.index(seat_number)
    except ValueError:
        return LabeledMetric(
            value=Position.UNKNOWN,
            label=MetricLabel.OBSERVED,
            source="seat not found after sort",
        )

    offset = seat_idx  # button is always index 0 after rotation
    position_table = _POSITION_MAP.get(n)
    if position_table is None:
        # Unsupported table size — fall back: anything CO or BTN gets named,
        # rest get UTG
        if offset == 0:
            pos = Position.BTN
        elif offset == n - 1:
            pos = Position.CO
        elif offset == n - 2:
            pos = Position.HJ
        elif offset == 1:
            pos = Position.SB
        elif offset == 2:
            pos = Position.BB
        else:
            pos = Position.UTG
    else:
        pos = position_table.get(offset, Position.UNKNOWN)

    return observed(pos, source=f"seat {seat_number} is offset {offset} from BTN in {n}-handed")


def _clockwise_sort(seats: list[int], anchor: int) -> list[int]:
    """
    Return seats sorted clockwise starting from anchor.
    Seats are integers; clockwise = ascending, wrapping from max back to 1.
    """
    if anchor not in seats:
        raise ValueError(f"Anchor seat {anchor} not in seats {seats}")
    s = sorted(seats)
    idx = s.index(anchor)
    return s[idx:] + s[:idx]


def is_in_position(pos: Position) -> bool:
    """Returns True if the position acts last (or near-last) postflop."""
    return pos in IP_POSITIONS


def is_out_of_position(pos: Position) -> bool:
    return pos in BLIND_POSITIONS


def position_from_offset(offset: int, table_size: int) -> Position:
    """
    Convenience: get position from a raw offset without the full seat list.
    Used when seat metadata is already resolved to offset externally.
    """
    table = _POSITION_MAP.get(table_size, {})
    return table.get(offset, Position.UNKNOWN)
