"""
Rule-based hand coaching engine.

Analyzes a single hand for the hero player and returns a coaching verdict.
All analysis is INFERRED — no solver data is used. Never raises.

Coverage:
- Short-stack preflop spots (<=15bb): push/fold theory
- Steal spots (BTN/CO/SB): raise vs limp vs fold
- 3-bet spots: facing a raise in steal position
- BB defend: facing steal from BB
- Other: neutral fallback
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut
from app.schemas.tournament import HandCoachingOut

_STEAL_POSITIONS = {"BTN", "CO", "SB"}
_SKIP_POSTING = {"POST_SB", "POST_BB", "POST_ANTE"}
_D0 = Decimal("0")
_D1 = Decimal("1")
_D10 = Decimal("10")
_D12 = Decimal("12")
_D15 = Decimal("15")
_D20 = Decimal("20")


def _bb_amount(amount: Decimal | None, bb: Decimal) -> str:
    if not amount or not bb or bb == _D0:
        return "0bb"
    val = (amount / bb).quantize(Decimal("0.1"))
    return f"{val}bb"


def _describe_action(action_type: str, amount: Decimal | None, bb: Decimal) -> str:
    t = action_type.upper()
    if t in _SKIP_POSTING:
        return f"posted {t.lower().replace('post_', '')}"
    if t == "FOLD":
        return "folded"
    if t == "CHECK":
        return "checked"
    if t == "CALL":
        return f"called {_bb_amount(amount, bb)}" if amount else "called"
    if t in ("BET", "RAISE"):
        return f"{t.lower()} to {_bb_amount(amount, bb)}" if amount else t.lower()
    if t in ("ALL_IN", "ALLIN"):
        return f"shoved {_bb_amount(amount, bb)}" if amount else "shoved all-in"
    return t.lower()


def _preflop_voluntary(hero_hp: HandPlayerOut) -> list[PlayerActionOut]:
    return [
        a for a in hero_hp.actions if a.street == "PREFLOP" and a.action_type not in _SKIP_POSTING
    ]


def _raises_before_hero(hand: HandDetailOut, hero_hp: HandPlayerOut) -> int:
    hero_acts = [a for a in hero_hp.actions if a.street == "PREFLOP"]
    if not hero_acts:
        return 0
    first_order = min(a.action_order for a in hero_acts)
    count = 0
    for hp in hand.hand_players:
        if hp.player_id == hero_hp.player_id:
            continue
        for a in hp.actions:
            if a.street != "PREFLOP" or a.action_order >= first_order:
                continue
            if a.action_type in ("RAISE", "BET", "ALL_IN", "ALLIN"):
                count += 1
    return count


def _last_voluntary(actions: list[PlayerActionOut]) -> PlayerActionOut | None:
    vol = [a for a in actions if a.action_type not in _SKIP_POSTING]
    return max(vol, key=lambda a: a.action_order) if vol else None


def _neutral(spot: str, hero_desc: str) -> HandCoachingOut:
    return HandCoachingOut(
        spot_type=spot,
        hero_action=hero_desc,
        recommended_action="context-dependent",
        explanation="No clear rule-based analysis for this spot. Solver data not available.",
        severity="neutral",
        ev_label="neutral",
    )


def _coach_short_stack(
    preflop_actions: list[PlayerActionOut],
    stack_bb: Decimal,
    position: str,
    bb: Decimal,
) -> HandCoachingOut:
    last = _last_voluntary(preflop_actions)
    if last is None:
        return _neutral("other", "no action")
    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = last.is_all_in or t in ("ALL_IN", "ALLIN")
    stack_str = f"{int(stack_bb)}bb"

    if is_all_in:
        return HandCoachingOut(
            spot_type="shove",
            hero_action=hero_desc,
            recommended_action="shove",
            explanation=f"Shoving with {stack_str} is correct push/fold strategy.",
            severity="good",
            ev_label="+EV",
        )
    if t == "CALL" and not is_all_in:
        sev = "big_mistake" if stack_bb <= _D10 else "small_mistake"
        return HandCoachingOut(
            spot_type="call",
            hero_action=hero_desc,
            recommended_action="shove or fold",
            explanation=f"With {stack_str}, a flat call wastes fold equity. Shove all-in or fold.",
            severity=sev,
            ev_label="losing_chips",
        )
    if t in ("RAISE", "BET") and not is_all_in and stack_bb <= _D10:
        return HandCoachingOut(
            spot_type="open",
            hero_action=hero_desc,
            recommended_action="shove all-in",
            explanation=f"Raising less than all-in with {stack_str} is awkward. Shove for maximum fold equity.",
            severity="small_mistake",
            ev_label="neutral",
        )
    if t == "FOLD" and stack_bb <= _D10 and position in _STEAL_POSITIONS:
        return HandCoachingOut(
            spot_type="shove",
            hero_action=hero_desc,
            recommended_action="consider shoving",
            explanation=f"At {stack_str} from {position}, fold equity is valuable — verify shove profitability here.",
            severity="small_mistake",
            ev_label="neutral",
        )
    return HandCoachingOut(
        spot_type="shove",
        hero_action=hero_desc,
        recommended_action="push/fold chart",
        explanation=f"Short-stack spot ({stack_str}). Consult push/fold ranges for your exact stack and position.",
        severity="neutral",
        ev_label="neutral",
    )


def _coach_steal(
    preflop_actions: list[PlayerActionOut],
    stack_bb: Decimal | None,
    position: str,
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
) -> HandCoachingOut:
    bb = hand.stakes_bb
    raises_before = _raises_before_hero(hand, hero_hp)
    last = _last_voluntary(preflop_actions)
    if last is None:
        return _neutral("open", "no action")
    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = last.is_all_in or t in ("ALL_IN", "ALLIN")

    if raises_before > 0:
        if t in ("RAISE", "BET") or is_all_in:
            return HandCoachingOut(
                spot_type="3bet",
                hero_action=hero_desc,
                recommended_action="3-bet / shove",
                explanation=f"3-betting from {position} facing a raise applies pressure and denies equity.",
                severity="good",
                ev_label="+EV",
            )
        if t == "CALL" and not is_all_in:
            note = f" ({int(stack_bb)}bb)" if stack_bb else ""
            return HandCoachingOut(
                spot_type="call",
                hero_action=hero_desc,
                recommended_action="3-bet or fold",
                explanation=f"Calling raises from {position}{note} sacrifices fold equity. 3-bet to take initiative or fold.",
                severity="small_mistake",
                ev_label="neutral",
            )
        return _neutral("3bet", hero_desc)

    if t == "CALL" and not is_all_in:
        return HandCoachingOut(
            spot_type="open",
            hero_action=hero_desc,
            recommended_action="raise or fold",
            explanation=f"Limping from {position} gives opponents a cheap flop. Open-raise to take initiative or fold.",
            severity="small_mistake",
            ev_label="neutral",
        )
    if t in ("RAISE", "BET") or is_all_in:
        return HandCoachingOut(
            spot_type="open",
            hero_action=hero_desc,
            recommended_action="open raise",
            explanation=f"Raising from {position} is standard. Maintaining steal frequency from late position.",
            severity="good",
            ev_label="+EV",
        )
    if t == "FOLD":
        return HandCoachingOut(
            spot_type="open",
            hero_action=hero_desc,
            recommended_action="consider raising",
            explanation=f"Folding {position} unopened — verify this is not surrendering profitable steal equity.",
            severity="neutral",
            ev_label="neutral",
        )
    return _neutral("open", hero_desc)


def _coach_bb_defend(
    preflop_actions: list[PlayerActionOut],
    stack_bb: Decimal | None,
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
) -> HandCoachingOut:
    bb = hand.stakes_bb
    raises_before = _raises_before_hero(hand, hero_hp)
    last = _last_voluntary(preflop_actions)
    if last is None:
        return _neutral("defend", "no action")
    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = last.is_all_in or t in ("ALL_IN", "ALLIN")

    if raises_before == 0:
        return _neutral("defend", hero_desc)

    if t == "CALL" and not is_all_in and stack_bb and stack_bb <= _D12:
        return HandCoachingOut(
            spot_type="defend",
            hero_action=hero_desc,
            recommended_action="shove or fold",
            explanation=f"Calling from BB with {int(stack_bb)}bb plays OOP with a capped range. Shove all-in or fold.",
            severity="small_mistake",
            ev_label="neutral",
        )
    return HandCoachingOut(
        spot_type="defend",
        hero_action=hero_desc,
        recommended_action="context-dependent",
        explanation="BB defense spot. Pot odds and hand strength determine whether to defend, 3-bet, or fold.",
        severity="neutral",
        ev_label="neutral",
    )


def _detect_spot(hero_hp: HandPlayerOut) -> str:
    pf = _preflop_voluntary(hero_hp)
    postflop = [a for a in hero_hp.actions if a.street in ("FLOP", "TURN", "RIVER")]
    if any(a.is_all_in or a.action_type in ("ALL_IN", "ALLIN") for a in hero_hp.actions):
        return "short_stack" if (hero_hp.stack_bb and hero_hp.stack_bb <= _D20) else "shove"
    pos = hero_hp.position or ""
    if hero_hp.stack_bb and hero_hp.stack_bb <= _D15 and pf:
        return "short_stack"
    if pos in _STEAL_POSITIONS and pf:
        return "steal"
    if pos == "BB" and pf:
        return "bb"
    if postflop:
        return "postflop"
    return "other"


def coach_hand(hand: HandDetailOut, hero_player_id: uuid.UUID) -> HandCoachingOut:
    """Rule-based coaching for a single hand. Never raises."""
    hero_hp = next((hp for hp in hand.hand_players if hp.player_id == hero_player_id), None)
    if hero_hp is None:
        return HandCoachingOut(
            spot_type="other",
            hero_action="not in hand",
            recommended_action="n/a",
            explanation="Hero was not a participant in this hand.",
            severity="neutral",
            ev_label="neutral",
        )

    bb = hand.stakes_bb
    spot = _detect_spot(hero_hp)
    pf = _preflop_voluntary(hero_hp)

    try:
        if spot == "short_stack" and pf and hero_hp.stack_bb:
            return _coach_short_stack(pf, hero_hp.stack_bb, hero_hp.position or "UNKNOWN", bb)
        if spot == "steal" and pf:
            return _coach_steal(pf, hero_hp.stack_bb, hero_hp.position or "UNKNOWN", hand, hero_hp)
        if spot == "bb" and pf:
            return _coach_bb_defend(pf, hero_hp.stack_bb, hand, hero_hp)

        last = _last_voluntary([a for a in hero_hp.actions if a.action_type not in _SKIP_POSTING])
        hero_desc = _describe_action(last.action_type, last.amount, bb) if last else "no action"
        return _neutral(spot, hero_desc)
    except Exception:
        return HandCoachingOut(
            spot_type="other",
            hero_action="analysis error",
            recommended_action="n/a",
            explanation="Could not analyze this hand.",
            severity="neutral",
            ev_label="neutral",
        )
