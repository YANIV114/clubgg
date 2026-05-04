"""
Hand normalization pipeline.

Takes a raw IngestHandPayload (as produced by the parser or API normalizer)
and enriches the hand_players entries with:
  - position (OBSERVED)
  - stack_bb (DERIVED)
  - effective_stack_bb (DERIVED)

Also sets hand-level fields:
  - button_seat (OBSERVED — extracted from hand history or API data)
  - total_pot in BB (useful for downstream features, not persisted separately)

This module is pure computation — no DB access, no IO.
Input/output types are dicts matching the service layer's upsert contracts.

Why a separate module (not inline in the service)?
  The spec requires separating parsing, analytics, and storage concerns.
  Normalization is an analytics step that should be testable without a DB.

Limitations:
  - If button_seat is absent, position cannot be computed → stored as None.
  - If bb_size is zero or missing, stack_bb cannot be computed → stored as None.
    This should not occur for valid ClubGG data but is handled defensively.
  - effective_stack_bb requires at least 2 players; stored as None for heads-up
    before all stacks are known (partial data).
"""

from __future__ import annotations

from decimal import Decimal

from app.features.position import Position, compute_position
from app.features.stack import effective_stack_bb as calc_eff_stack
from app.features.stack import stack_bb as calc_stack_bb


def normalize_hand_players(
    players: list[dict],
    bb_size: Decimal,
    button_seat: int | None,
) -> list[dict]:
    """
    Enrich each player dict with position, stack_bb, and effective_stack_bb.

    Parameters
    ----------
    players:
        List of player dicts from IngestHandPayload.players.
        Each dict must have: player_username, seat_number, starting_stack.
        Dicts are mutated in place AND returned.
    bb_size:
        Big blind size in chips (from Hand.stakes_bb).
    button_seat:
        Seat number holding the button, or None if unknown.

    Returns
    -------
    The same list, with each dict enriched:
        position: str | None
        stack_bb: str | None   (Decimal as string for serialisation)
        effective_stack_bb: str | None
    """
    if not players:
        return players

    active_seats = [int(p["seat_number"]) for p in players]

    # Compute stack_bb for each player first (needed for effective_stack_bb)
    stack_bbs: dict[int, Decimal | None] = {}
    for p in players:
        seat = int(p["seat_number"])
        chips = Decimal(str(p["starting_stack"]))
        if bb_size > Decimal("0"):
            sbb = calc_stack_bb(chips, bb_size)
            stack_bbs[seat] = sbb.value
        else:
            stack_bbs[seat] = None

    for p in players:
        seat = int(p["seat_number"])

        # Position — skip if button_seat is not an occupied seat (e.g. GGPoker seat #0)
        effective_btn = button_seat if button_seat in active_seats else None
        if effective_btn is not None:
            pos_metric = compute_position(seat, effective_btn, active_seats)
            p["position"] = pos_metric.value if pos_metric.value != Position.UNKNOWN else None
        else:
            p["position"] = None

        # stack_bb
        sbb = stack_bbs.get(seat)
        p["stack_bb"] = str(sbb) if sbb is not None else None

        # effective_stack_bb
        my_sbb = stack_bbs.get(seat)
        if my_sbb is not None:
            others = [v for k, v in stack_bbs.items() if k != seat and v is not None]
            if others:
                eff = calc_eff_stack(my_sbb, others)
                p["effective_stack_bb"] = str(eff.value)
            else:
                # Heads-up with no other stacks known
                p["effective_stack_bb"] = str(my_sbb)
        else:
            p["effective_stack_bb"] = None

    return players


def extract_button_seat(raw_text: str | None) -> int | None:
    """
    Extract the button seat number from a raw ClubGG hand history text block.

    ClubGG format: "Table 'Name' N-max Seat #K is the button"

    Returns None if not found or text is absent.
    This is OBSERVED data — the line is either present or not.
    """
    if not raw_text:
        return None
    import re

    m = re.search(r"Seat #(\d+) is the button", raw_text)
    if m:
        return int(m.group(1))
    return None
