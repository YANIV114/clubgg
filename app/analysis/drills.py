"""
Real-spot drills: Hero facing a single preflop raise.

Pure module — no DB, no IO.  Input is a parsed hand dict (HandHistoryParser
output) whose players were enriched by normalize_hand_players().

Scope (deliberately narrow, to stay where the ranges below are meaningful):
  - exactly one raise before Hero's first decision, no other caller
  - Hero not in the BB (BB defence is a different, wider problem)
  - effective stack ≥ 30bb (shallower, 3-bet-shove strategy takes over)
  - Hero's hole cards known

Recommendations are approximate tournament ranges ("range-based estimate"),
not solver output.  Hands where two answers are standard accept both.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from app.analysis.range_library import (
    expand_range_notation,
    get_threbet_range,
    parse_hole_cards,
)

Action = Literal["3bet", "call", "fold"]

MIN_EFFECTIVE_BB = Decimal("30")
RECOMMENDATION_BACKING = "range-based estimate"

# Seat-name aliases from 8/9-max tables onto the 6-max names the ranges use.
_SEAT_ALIAS = {"UTG1": "UTG", "UTG2": "UTG", "MP": "HJ", "LJ": "HJ"}

# Used when the range library has no entry for the seat pair: value only.
_DEFAULT_3BET = expand_range_notation(["AA-QQ", "AKs", "AKo"])

# Flat-call ranges vs a single open.  The BTN closes the action in position
# and calls widest; CO/HJ call tighter (players behind); the SB, out of
# position with the BB behind, flats only hands that play well multiway.
_FLAT_SPECS: dict[str, list[str]] = {
    "BTN": [
        "JJ-22", "AQs-ATs", "KQs-KTs", "QJs-QTs", "JTs-J9s", "T9s", "98s", "87s",
        "76s", "65s", "AQo-AJo", "KQo",
    ],
    "CO": ["JJ-22", "AQs-ATs", "KQs-KJs", "QJs", "JTs", "AQo"],
    "HJ": ["JJ-66", "AQs-AJs", "KQs", "AQo"],
    "UTG": ["JJ-77", "AQs", "AQo"],
    "SB": ["99-22", "KQs", "QJs", "JTs"],
}
_FLAT_RANGES = {k: expand_range_notation(v) for k, v in _FLAT_SPECS.items()}

_RAISES = ("RAISE", "BET", "ALL_IN")


@dataclass(frozen=True)
class Recommendation:
    best: Action
    acceptable: tuple[Action, ...]
    reason: str
    backing: str = RECOMMENDATION_BACKING


@dataclass(frozen=True)
class SpotVsRaise:
    hand_external_id: str
    position: str
    opener_position: str
    raise_to_bb: Decimal
    eff_bb: Decimal
    hole_cards: str
    canonical: str
    hero_action: Action


def _seat(pos: str | None) -> str | None:
    return _SEAT_ALIAS.get(pos, pos) if pos else None


def recommend_vs_raise(position: str, opener_position: str, canonical: str) -> Recommendation:
    """Recommend 3-bet / call / fold for ``canonical`` facing one open."""
    pos = _seat(position) or position
    vs = _seat(opener_position) or opener_position
    three_bet, _ = get_threbet_range(pos, vs)
    if not three_bet:
        three_bet = _DEFAULT_3BET
    in_3bet = canonical in three_bet
    in_flat = canonical in _FLAT_RANGES.get(pos, frozenset())

    if in_3bet and in_flat:
        return Recommendation(
            best="3bet",
            acceptable=("3bet", "call"),
            reason=(
                f"{canonical} in the {pos} vs a {vs} open is strong enough to 3-bet for value, "
                "and flatting is also standard here. Both are fine."
            ),
        )
    if in_3bet:
        return Recommendation(
            best="3bet",
            acceptable=("3bet",),
            reason=(
                f"{canonical} is a value 3-bet from the {pos} vs a {vs} open. Flatting lets "
                "worse hands in cheaply and gives up initiative."
            ),
        )
    if in_flat:
        if pos == "SB":
            return Recommendation(
                best="call",
                acceptable=("call", "3bet", "fold"),
                reason=(
                    f"{canonical} is one of the few hands that can flat from the SB vs a {vs} "
                    "open: it plays well multiway when the BB comes along. 3-betting or folding is "
                    "also fine."
                ),
            )
        # 3-betting a hand from the calling range is a frequency choice, not an
        # error: only calls/folds outside both ranges count as mistakes.
        return Recommendation(
            best="call",
            acceptable=("call", "3bet"),
            reason=(
                f"{canonical} is a standard call from the {pos} vs a {vs} open; mixing in "
                "some 3-bets is fine. Folding gives up a profitable hand."
            ),
        )
    if pos == "SB":
        why = (
            "From the SB you are out of position with the BB still to act: play 3-bet or "
            "fold, and this hand is a fold."
        )
    elif pos == "BTN":
        why = (
            "Even with position, this hand is dominated by a typical opening range too "
            "often to call profitably."
        )
    else:
        why = (
            "With players still to act behind, calling invites squeezes and multiway pots "
            "where this hand does poorly."
        )
    return Recommendation(
        best="fold",
        acceptable=("fold",),
        reason=f"{canonical} is outside a continuing range from the {pos} vs a {vs} open. {why}",
    )


def find_spot_vs_raise(hand: dict[str, Any], hero: str) -> SpotVsRaise | None:
    """Return Hero's facing-one-raise spot in ``hand``, or None if out of scope."""
    players = {p["player_username"]: p for p in hand["players"]}
    me = players.get(hero)
    if not me or not me.get("position") or me["position"] == "BB":
        return None
    canonical = parse_hole_cards(me.get("hole_cards"))
    if canonical is None:
        return None
    eff = me.get("effective_stack_bb")
    if eff is None or Decimal(str(eff)) < MIN_EFFECTIVE_BB:
        return None

    pre = [
        a
        for a in hand["actions"]
        if a["street"] == "PREFLOP" and not a["action_type"].startswith("POST")
    ]
    mine = [a for a in pre if a["player_username"] == hero]
    if not mine:
        return None
    first = mine[0]
    before = [a for a in pre if a["action_order"] < first["action_order"]]
    raises = [a for a in before if a["action_type"] in _RAISES]
    if len(raises) != 1 or any(a["action_type"] == "CALL" for a in before):
        return None
    opener = players.get(raises[0]["player_username"])
    if not opener or not opener.get("position") or raises[0]["amount"] is None:
        return None

    t = first["action_type"]
    hero_action: Action = "3bet" if t in _RAISES else "call" if t == "CALL" else "fold"
    bb = Decimal(str(hand["stakes_bb"]))
    return SpotVsRaise(
        hand_external_id=hand["external_id"],
        position=me["position"],
        opener_position=opener["position"],
        raise_to_bb=(Decimal(raises[0]["amount"]) / bb).quantize(Decimal("0.1")),
        eff_bb=Decimal(str(eff)).quantize(Decimal("1")),
        hole_cards=me["hole_cards"],
        canonical=canonical,
        hero_action=hero_action,
    )
