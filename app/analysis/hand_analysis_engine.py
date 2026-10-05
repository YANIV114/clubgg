"""
Hand analysis engine.

Classifies the hero's key decision in a single hand and returns a
HandAnalysisResult with an epistemic label, EV label, and actionable
recommendation.

Design constraints
------------------
- Pure module: no DB, no IO, never raises.
- All chip arithmetic uses Decimal.
- Every confidence output is a MetricLabel from app/features/labels.py.
- analyze_hand() is wrapped in a broad except so callers always get a result.
- Do not import from coaching.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from decimal import Decimal

from app.analysis.nash_pushfold import (
    NASH_BACKING,
    classify_hand_nash,
    get_nash_call_range,
    get_nash_shove_range,
)
from app.analysis.opponent_profile import (  # noqa: E402
    OpponentProfile,
    PlayerStats,
    classify_opponent,
    get_exploit_adjustment,
)
from app.analysis.range_library import (
    RANGE_BACKING,
    classify_hand_vs_range,
    get_bb_defend_range,
    get_call_range,
    get_push_range,
    get_steal_range,
    get_threbet_range,
    parse_hole_cards,
)
from app.features.labels import MetricLabel
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STEAL_POSITIONS = frozenset({"BTN", "CO", "SB"})
_EP_MP_POSITIONS = frozenset({"UTG", "UTG+1", "LJ", "HJ"})
_SKIP_POSTING = frozenset({"POST_SB", "POST_BB", "POST_ANTE"})
_RAISE_TYPES = frozenset({"RAISE", "BET", "ALL_IN", "ALLIN"})

_D0 = Decimal("0")
_D1 = Decimal("1")
_D10 = Decimal("10")
_D12 = Decimal("12")
_D15 = Decimal("15")
_D20 = Decimal("20")
_D40 = Decimal("40")
_D100 = Decimal("100")
_D2 = Decimal("2")

# Minimum hands in a session to consider ICM spots plausible
_ICM_MIN_HANDS = 20


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandAnalysisResult:
    spot_type: str  # one of the spot type strings
    hero_action: str  # human description: "raised to 2.5bb", "called 3bb", "folded"
    recommended_action: str  # "shove all-in", "open raise", "fold", "3-bet or fold", etc.
    mistake_severity: str  # "good" | "none" | "minor" | "major" | "critical"
    explanation: str  # 1–2 sentence plain-language explanation
    key_factors: list[str]  # e.g. ["10bb stack", "BTN position", "first-in"]
    confidence: MetricLabel  # OBSERVED/DERIVED/INFERRED/SPECULATIVE
    ev_label: str  # "+EV" | "neutral" | "-EV" | "unknown"
    backing: str  # "heuristic" | "range-based estimate" | "solver-backed"
    range_context: str = ""  # e.g. "BTN push range at 12bb (44 combos)"
    hero_range_position: str = "unknown"  # "top" | "mid" | "bottom" | "outside" | "unknown"
    exploit_adjustment: str = ""  # e.g. "Villain folds wide — steal range can widen slightly"
    adjustment_reason: str = ""  # e.g. "Villain profile: loose-passive"
    villain_profile: str = ""  # e.g. "loose-passive" | "balanced" | "unknown" | ""
    villain_profile_confidence: str = ""  # "low" | "medium" | "high" | ""


# ---------------------------------------------------------------------------
# Safe fallback
# ---------------------------------------------------------------------------


def _fallback(reason: str = "analysis error") -> HandAnalysisResult:
    return HandAnalysisResult(
        spot_type="other",
        hero_action=reason,
        recommended_action="n/a",
        mistake_severity="none",
        explanation="Could not classify this hand spot.",
        key_factors=[],
        confidence=MetricLabel.SPECULATIVE,
        ev_label="unknown",
        backing="heuristic",
    )


# ---------------------------------------------------------------------------
# Helper functions (public as per interface spec)
# ---------------------------------------------------------------------------


def _preflop_voluntary(hero_hp: HandPlayerOut) -> list[PlayerActionOut]:
    """Non-posting preflop actions."""
    return [
        a for a in hero_hp.actions if a.street == "PREFLOP" and a.action_type not in _SKIP_POSTING
    ]


def _raises_before(hand: HandDetailOut, hero_hp: HandPlayerOut, street: str) -> int:
    """Count RAISE/BET/ALL_IN actions by opponents before hero's first voluntary action on street."""
    hero_vol_on_street = [
        a for a in hero_hp.actions if a.street == street and a.action_type not in _SKIP_POSTING
    ]
    if not hero_vol_on_street:
        return 0
    first_hero_order = min(a.action_order for a in hero_vol_on_street)
    count = 0
    for hp in hand.hand_players:
        if hp.player_id == hero_hp.player_id:
            continue
        for a in hp.actions:
            if a.street != street:
                continue
            if a.action_order >= first_hero_order:
                continue
            if a.action_type in _RAISE_TYPES:
                count += 1
    return count


def _is_first_in(hand: HandDetailOut, hero_hp: HandPlayerOut) -> bool:
    """True if no opponent has raised/bet before hero's first preflop action."""
    return _raises_before(hand, hero_hp, "PREFLOP") == 0


def _hero_was_pfa(hand: HandDetailOut, hero_hp: HandPlayerOut) -> bool:
    """True if hero made the last raise preflop (preflop aggressor)."""
    pf_raises: list[tuple[int, uuid.UUID]] = []
    for hp in hand.hand_players:
        for a in hp.actions:
            if a.street == "PREFLOP" and a.action_type in _RAISE_TYPES:
                pf_raises.append((a.action_order, hp.player_id))
    if not pf_raises:
        return False
    _, last_raiser_id = max(pf_raises, key=lambda x: x[0])
    return last_raiser_id == hero_hp.player_id


def _describe_action(action_type: str, amount: Decimal | None, bb: Decimal) -> str:
    """Human-readable action description using Decimal arithmetic."""
    t = action_type.upper()
    if t in _SKIP_POSTING:
        return f"posted {t.lower().replace('post_', '')}"
    if t == "FOLD":
        return "folded"
    if t == "CHECK":
        return "checked"
    if t == "CALL":
        if amount and bb and bb > _D0:
            val = (amount / bb).quantize(Decimal("0.1"))
            return f"called {val}bb"
        return "called"
    if t in ("BET", "RAISE"):
        if amount and bb and bb > _D0:
            val = (amount / bb).quantize(Decimal("0.1"))
            return f"{t.lower()} to {val}bb"
        return t.lower()
    if t in ("ALL_IN", "ALLIN"):
        if amount and bb and bb > _D0:
            val = (amount / bb).quantize(Decimal("0.1"))
            return f"shoved {val}bb"
        return "shoved all-in"
    return t.lower()


def _pot_at_decision(hand: HandDetailOut, hero_hp: HandPlayerOut, street: str) -> Decimal:
    """Approximate pot in BB at hero's first action on the given street."""
    bb = hand.stakes_bb
    if not bb or bb <= _D0:
        return _D0

    hero_acts = [a for a in hero_hp.actions if a.street == street]
    if not hero_acts:
        return _D0
    first_hero_order = min(a.action_order for a in hero_acts)

    total: Decimal = _D0
    for hp in hand.hand_players:
        for a in hp.actions:
            if a.action_order >= first_hero_order:
                continue
            if a.amount and a.action_type not in ("CHECK", "FOLD", "MUCK", "SHOW"):
                total += a.amount

    return (total / bb).quantize(Decimal("0.01")) if bb > _D0 else _D0


def _build_key_factors(
    hero_hp: HandPlayerOut,
    hand: HandDetailOut,
    extras: list[str],
) -> list[str]:
    """Build the key_factors list: position, stack, player_count, + extras."""
    factors: list[str] = []
    if hero_hp.position:
        factors.append(f"{hero_hp.position} position")
    if hero_hp.stack_bb is not None:
        factors.append(f"{hero_hp.stack_bb}bb stack")
    factors.append(f"{hand.player_count}-handed")
    factors.extend(extras)
    return factors


def _last_voluntary(actions: list[PlayerActionOut]) -> PlayerActionOut | None:
    vol = [a for a in actions if a.action_type not in _SKIP_POSTING]
    return max(vol, key=lambda a: a.action_order) if vol else None


def _is_all_in_action(action: PlayerActionOut) -> bool:
    return action.is_all_in or action.action_type in ("ALL_IN", "ALLIN")


# ---------------------------------------------------------------------------
# Spot classifiers
# ---------------------------------------------------------------------------


def _classify_spot(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
) -> str:
    """Return the spot type string. First match wins."""
    pf_vol = _preflop_voluntary(hero_hp)
    pos = hero_hp.position or ""
    stack_bb = hero_hp.stack_bb

    # Priority 1: hero calls an all-in preflop (opponent is_all_in=True before hero's
    # first voluntary action).  Checked before push_fold so that BB calling a short-
    # stack shove is classified as call_all_in, not push_fold.
    # Use first VOLUNTARY action order so posting (POST_BB/POST_SB) does not
    # obscure opponents' all-in actions that come between the post and the
    # hero's actual decision.
    hero_pf_vol_acts = [
        a for a in hero_hp.actions if a.street == "PREFLOP" and a.action_type not in _SKIP_POSTING
    ]
    if hero_pf_vol_acts:
        first_hero_vol_order = min(a.action_order for a in hero_pf_vol_acts)
        opp_all_in_before = any(
            a.is_all_in or a.action_type in ("ALL_IN", "ALLIN")
            for hp in hand.hand_players
            if hp.player_id != hero_hp.player_id
            for a in hp.actions
            if a.street == "PREFLOP" and a.action_order < first_hero_vol_order
        )
        if opp_all_in_before:
            last_hero = _last_voluntary(pf_vol)
            if last_hero and last_hero.action_type == "CALL":
                return "call_all_in"

    # Priority 2: short stack with preflop voluntary action
    if pf_vol and stack_bb is not None and stack_bb <= _D15:
        # ICM variants require knowing session hand count (≥20 hands deep in the tournament).
        # HandDetailOut does not carry session hand count.  We use player_count as an
        # intentionally conservative proxy: a table of ≤3 players strongly suggests a
        # late-stage tournament (final table / bubble); 4–5 players is a plausible bubble.
        # This keeps standard 6-max cash/early-tournament hands in push_fold.
        # Both ICM spot types are always SPECULATIVE per spec (payout unknown).
        if stack_bb <= _D10 and hand.player_count <= 4:
            return "final_table_icm"
        if stack_bb <= _D15 and hand.player_count <= 5:
            return "bubble_icm"
        return "push_fold"

    # Priority 3: hero faces 2+ preflop raises — spot is four_bet_jam regardless of
    # whether hero jams or calls (the situation is a 4-bet-or-call decision).
    raises_count = _raises_before(hand, hero_hp, "PREFLOP")
    if raises_count >= 2 and pf_vol:
        return "four_bet_jam"

    # Priority 4: hero faces 1 raise preflop and re-raises.
    # BB re-raising a single steal is classified as defend_bb (BB defence context).
    if raises_count == 1 and pf_vol:
        last = _last_voluntary(pf_vol)
        if last and last.action_type in ("RAISE", "BET") or (last and _is_all_in_action(last)):
            if pos == "BB":
                return "defend_bb"
            return "three_bet"

    # Postflop check (priorities 8–9) comes before BB-defend / steal / open-fold
    # because when a hand reaches postflop the hero's key decision is there, not
    # preflop.  Priorities 1–4 (short-stack / all-in / 3-bet / 4-bet) are more
    # critical and have already returned above.
    hero_postflop = [a for a in hero_hp.actions if a.street in ("FLOP", "TURN", "RIVER")]
    if hero_postflop:
        # River first (most specific)
        river_acts = [a for a in hero_postflop if a.street == "RIVER"]
        if river_acts:
            opp_river_bets = [
                a
                for hp in hand.hand_players
                if hp.player_id != hero_hp.player_id
                for a in hp.actions
                if a.street == "RIVER" and a.action_type in _RAISE_TYPES
            ]
            if opp_river_bets:
                return "river_call_fold"

        # Turn
        turn_acts = [a for a in hero_postflop if a.street == "TURN"]
        if turn_acts:
            return "turn_barrel"

        # Flop — hero was PFA → c-bet spot
        flop_acts = [a for a in hero_postflop if a.street == "FLOP"]
        if flop_acts and _hero_was_pfa(hand, hero_hp):
            return "flop_cbet"

        # Flop — hero was not PFA; check for river bet anyway
        if flop_acts:
            opp_river_bets_2 = [
                a
                for hp in hand.hand_players
                if hp.player_id != hero_hp.player_id
                for a in hp.actions
                if a.street == "RIVER" and a.action_type in _RAISE_TYPES
            ]
            if opp_river_bets_2:
                return "river_call_fold"

    # Priority 5: hero is BB, ≥1 raise before hero (hand ended preflop)
    if pos == "BB" and raises_count >= 1 and pf_vol:
        return "defend_bb"

    # Priority 6: first-in from BTN/CO/SB (hand ended preflop)
    if pos in _STEAL_POSITIONS and pf_vol and _is_first_in(hand, hero_hp):
        return "steal"

    # Priority 7: first-in from other position (hand ended preflop)
    if pf_vol and _is_first_in(hand, hero_hp):
        return "open_fold"

    # Priority 10: facing river bet with river hero action (fallback)
    opp_river = any(
        a.street == "RIVER" and a.action_type in _RAISE_TYPES
        for hp in hand.hand_players
        if hp.player_id != hero_hp.player_id
        for a in hp.actions
    )
    if opp_river:
        hero_river = [a for a in hero_hp.actions if a.street == "RIVER"]
        if hero_river:
            return "river_call_fold"

    return "other"


# ---------------------------------------------------------------------------
# Per-spot analysis functions
# ---------------------------------------------------------------------------


def _analyze_push_fold(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
    icm_note: str = "",
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    stack_bb = hero_hp.stack_bb or _D0
    pos = hero_hp.position or "UNKNOWN"
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action found")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = _is_all_in_action(last)
    stack_str = f"{stack_bb}bb"

    extras: list[str] = []
    if icm_note:
        extras.append(icm_note)
        extras.append("payout structure unknown — ICM equity cannot be computed")

    if is_all_in:
        return HandAnalysisResult(
            spot_type="push_fold"
            if not icm_note
            else ("final_table_icm" if stack_bb <= _D10 else "bubble_icm"),
            hero_action=hero_desc,
            recommended_action="shove all-in",
            mistake_severity="good",
            explanation=(
                f"Shoving with {stack_str} is correct push/fold strategy. "
                "At this depth, shoving is always at least as good as any other action."
                + (f" {icm_note}" if icm_note else "")
            ),
            key_factors=_build_key_factors(hero_hp, hand, ["first-in"] + extras),
            confidence=MetricLabel.INFERRED,
            ev_label="+EV",
            backing="range-based estimate",
        )

    if t == "CALL" and not is_all_in:
        severity = "critical" if stack_bb <= _D10 else "major"
        return HandAnalysisResult(
            spot_type="push_fold"
            if not icm_note
            else ("final_table_icm" if stack_bb <= _D10 else "bubble_icm"),
            hero_action=hero_desc,
            recommended_action="shove all-in or fold",
            mistake_severity=severity,
            explanation=(
                f"Flat-calling with {stack_str} sacrifices fold equity. "
                "With a short stack, the shove-or-fold framework maximises EV."
                + (f" {icm_note}" if icm_note else "")
            ),
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="-EV",
            backing="range-based estimate",
        )

    if t in ("RAISE", "BET") and not is_all_in and stack_bb <= _D10:
        return HandAnalysisResult(
            spot_type="push_fold" if not icm_note else "final_table_icm",
            hero_action=hero_desc,
            recommended_action="shove all-in",
            mistake_severity="minor",
            explanation=(
                f"Min-raising with {stack_str} is awkward — you commit chips without maximising fold equity. "
                "Jam all-in for full fold equity." + (f" {icm_note}" if icm_note else "")
            ),
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="-EV",
            backing="range-based estimate",
        )

    if t == "FOLD":
        if pos in _STEAL_POSITIONS and stack_bb <= _D10:
            return HandAnalysisResult(
                spot_type="push_fold"
                if not icm_note
                else ("final_table_icm" if stack_bb <= _D10 else "bubble_icm"),
                hero_action=hero_desc,
                recommended_action="consider shoving",
                mistake_severity="minor",
                explanation=(
                    f"Folding from {pos} with {stack_str} surrenders steal equity. "
                    "Verify whether this hand is a profitable shove from this position."
                    + (f" {icm_note}" if icm_note else "")
                ),
                key_factors=_build_key_factors(hero_hp, hand, extras),
                confidence=MetricLabel.INFERRED,
                ev_label="neutral",
                backing="range-based estimate",
            )
        # Fold from blind
        return HandAnalysisResult(
            spot_type="push_fold"
            if not icm_note
            else ("final_table_icm" if stack_bb <= _D10 else "bubble_icm"),
            hero_action=hero_desc,
            recommended_action="push/fold chart",
            mistake_severity="none",
            explanation=(
                f"Folding from {pos} with {stack_str}. "
                "Folding from the blinds at short stacks can be correct with weak holdings."
                + (f" {icm_note}" if icm_note else "")
            ),
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="range-based estimate",
        )

    # Generic push/fold — neutral
    return HandAnalysisResult(
        spot_type="push_fold"
        if not icm_note
        else ("final_table_icm" if stack_bb <= _D10 else "bubble_icm"),
        hero_action=hero_desc,
        recommended_action="push/fold chart",
        mistake_severity="none",
        explanation=f"Short-stack spot ({stack_str}). Consult push/fold ranges for your exact stack and position.",
        key_factors=_build_key_factors(hero_hp, hand, extras),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="range-based estimate",
    )


def _analyze_steal(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    pos = hero_hp.position or "UNKNOWN"
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = _is_all_in_action(last)

    if t in ("RAISE", "BET") or is_all_in:
        return HandAnalysisResult(
            spot_type="steal",
            hero_action=hero_desc,
            recommended_action="open raise",
            mistake_severity="good",
            explanation=f"Raising first-in from {pos} is standard steal play. Maintains profitable late-position frequency.",
            key_factors=_build_key_factors(hero_hp, hand, ["first-in"]),
            confidence=MetricLabel.INFERRED,
            ev_label="+EV",
            backing="heuristic",
        )

    if t == "CALL" and not is_all_in:
        return HandAnalysisResult(
            spot_type="steal",
            hero_action=hero_desc,
            recommended_action="raise or fold",
            mistake_severity="minor",
            explanation=f"Limping from {pos} gives opponents a cheap flop. Open-raise to take initiative or fold.",
            key_factors=_build_key_factors(
                hero_hp, hand, ["first-in", "limp surrenders initiative"]
            ),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    if t == "FOLD":
        return HandAnalysisResult(
            spot_type="steal",
            hero_action=hero_desc,
            recommended_action="consider raising",
            mistake_severity="none",
            explanation=f"Folding {pos} first-in. Hand-strength dependent — some folds are correct from steal positions.",
            key_factors=_build_key_factors(hero_hp, hand, ["first-in"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="steal",
        hero_action=hero_desc,
        recommended_action="raise or fold",
        mistake_severity="none",
        explanation="Steal position with first-in opportunity. Raise or fold — limping leaks EV.",
        key_factors=_build_key_factors(hero_hp, hand, ["first-in"]),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_open_fold(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    pos = hero_hp.position or "UNKNOWN"
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = _is_all_in_action(last)

    if t in ("RAISE", "BET") or is_all_in:
        return HandAnalysisResult(
            spot_type="open_fold",
            hero_action=hero_desc,
            recommended_action="open raise",
            mistake_severity="none",
            explanation=f"Opening from {pos}. Cannot evaluate without knowing the hand — range-dependent.",
            key_factors=_build_key_factors(hero_hp, hand, ["early/mid position open"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    if t == "FOLD":
        return HandAnalysisResult(
            spot_type="open_fold",
            hero_action=hero_desc,
            recommended_action="fold or open raise",
            mistake_severity="none",
            explanation=f"Folding from {pos}. Early position folds are often correct — range-dependent.",
            key_factors=_build_key_factors(hero_hp, hand, ["early/mid position"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    if t == "CALL" and not is_all_in:
        return HandAnalysisResult(
            spot_type="open_fold",
            hero_action=hero_desc,
            recommended_action="raise or fold",
            mistake_severity="minor",
            explanation=f"Limping from {pos} allows opponents to see a cheap flop. Open-raise or fold.",
            key_factors=_build_key_factors(hero_hp, hand, ["limp from early/mid position"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="open_fold",
        hero_action=hero_desc,
        recommended_action="raise or fold",
        mistake_severity="none",
        explanation=f"Early/mid position spot from {pos}. Raise or fold — limping leaks EV.",
        key_factors=_build_key_factors(hero_hp, hand, []),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_defend_bb(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    stack_bb = hero_hp.stack_bb
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = _is_all_in_action(last)

    if t in ("RAISE", "BET") or is_all_in:
        return HandAnalysisResult(
            spot_type="defend_bb",
            hero_action=hero_desc,
            recommended_action="3-bet",
            mistake_severity="good",
            explanation="3-betting from BB applies pressure on the steal and takes the initiative.",
            key_factors=_build_key_factors(hero_hp, hand, ["BB vs steal"]),
            confidence=MetricLabel.INFERRED,
            ev_label="+EV",
            backing="range-based estimate",
        )

    if t == "CALL" and not is_all_in:
        if stack_bb is not None and stack_bb <= _D12:
            return HandAnalysisResult(
                spot_type="defend_bb",
                hero_action=hero_desc,
                recommended_action="shove or fold",
                mistake_severity="minor",
                explanation=(
                    f"Calling from BB with {stack_bb}bb plays OOP with a capped range. "
                    "With a short stack, shove all-in or fold to preserve fold equity."
                ),
                key_factors=_build_key_factors(hero_hp, hand, ["BB vs steal", "short stack OOP"]),
                confidence=MetricLabel.INFERRED,
                ev_label="neutral",
                backing="heuristic",
            )
        return HandAnalysisResult(
            spot_type="defend_bb",
            hero_action=hero_desc,
            recommended_action="context-dependent",
            mistake_severity="none",
            explanation="Calling from BB facing a steal. Pot odds and hand strength determine the correct play.",
            key_factors=_build_key_factors(hero_hp, hand, ["BB defense", "pot odds apply"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    if t == "FOLD":
        return HandAnalysisResult(
            spot_type="defend_bb",
            hero_action=hero_desc,
            recommended_action="context-dependent",
            mistake_severity="none",
            explanation="Folding from BB. Hand-strength and pot odds determine whether a fold is correct.",
            key_factors=_build_key_factors(hero_hp, hand, ["BB vs steal"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="defend_bb",
        hero_action=hero_desc,
        recommended_action="3-bet or fold",
        mistake_severity="none",
        explanation="BB defense spot. Pot odds and hand strength determine whether to defend, 3-bet, or fold.",
        key_factors=_build_key_factors(hero_hp, hand, []),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_three_bet(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    pos = hero_hp.position or "UNKNOWN"
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)

    if pos in _STEAL_POSITIONS:
        return HandAnalysisResult(
            spot_type="three_bet",
            hero_action=hero_desc,
            recommended_action="3-bet",
            mistake_severity="good",
            explanation=f"3-betting from {pos} facing a raise applies maximum pressure from steal position.",
            key_factors=_build_key_factors(hero_hp, hand, ["3-bet from steal position"]),
            confidence=MetricLabel.INFERRED,
            ev_label="+EV",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="three_bet",
        hero_action=hero_desc,
        recommended_action="3-bet",
        mistake_severity="none",
        explanation=f"3-betting from {pos}. Range and opponent tendencies determine whether this is optimal.",
        key_factors=_build_key_factors(hero_hp, hand, ["3-bet from non-steal position"]),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_four_bet_jam(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    is_all_in = _is_all_in_action(last)

    if is_all_in:
        return HandAnalysisResult(
            spot_type="four_bet_jam",
            hero_action=hero_desc,
            recommended_action="jam all-in",
            mistake_severity="none",
            explanation="Jamming over a 3-bet is standard play. Hand-dependent — polarised 4-bet range applies.",
            key_factors=_build_key_factors(hero_hp, hand, ["4-bet jam", "facing 3-bet"]),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    # Call without jamming
    return HandAnalysisResult(
        spot_type="four_bet_jam",
        hero_action=hero_desc,
        recommended_action="jam or fold",
        mistake_severity="minor",
        explanation="Calling a 3-bet without jamming gives information without applying pressure. Jam or fold is more +EV.",
        key_factors=_build_key_factors(hero_hp, hand, ["4-bet facing", "non-jam call"]),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_call_all_in(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    pf_vol: list[PlayerActionOut],
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    last = _last_voluntary(pf_vol)

    if last is None:
        return _fallback("no preflop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)

    # Compute pot odds
    call_amount = last.amount or _D0
    # Pot before call: sum all actions before hero's call
    hero_first_order = min(a.action_order for a in hero_hp.actions if a.street == "PREFLOP")
    pot_before: Decimal = _D0
    for hp in hand.hand_players:
        for a in hp.actions:
            if a.street == "PREFLOP" and a.action_order < hero_first_order:
                if a.amount and a.action_type not in ("CHECK", "FOLD", "MUCK", "SHOW"):
                    pot_before += a.amount

    pot_odds_pct: Decimal = _D0
    if call_amount > _D0 and bb > _D0:
        total_pot = pot_before + call_amount
        if total_pot > _D0:
            pot_odds_pct = (call_amount / total_pot * _D100).quantize(Decimal("0.1"))

    extras: list[str] = [
        f"pot odds: {pot_odds_pct}% ({call_amount / bb if bb > _D0 else 0:.1f}bb to call)"
    ]
    if pot_odds_pct > _D40:
        extras.append("calling requires ~40%+ equity")

    return HandAnalysisResult(
        spot_type="call_all_in",
        hero_action=hero_desc,
        recommended_action="call if equity ≥ pot odds",
        mistake_severity="none",
        explanation=(
            "Cannot compute equity without hole cards. "
            f"Pot odds are {pot_odds_pct}% — call is correct if hero holds equivalent or better equity."
        ),
        key_factors=_build_key_factors(hero_hp, hand, extras),
        confidence=MetricLabel.SPECULATIVE,
        ev_label="unknown",
        backing="heuristic",
    )


def _analyze_flop_cbet(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    flop_acts = [a for a in hero_hp.actions if a.street == "FLOP"]
    last = _last_voluntary(flop_acts) if flop_acts else None

    if last is None:
        return _fallback("no flop action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    pot = _pot_at_decision(hand, hero_hp, "FLOP")

    extras = [f"pot: {pot}bb"]
    if hand.board_cards:
        extras.append(f"board: {hand.board_cards}")

    t = last.action_type.upper()
    if t in ("BET", "RAISE") or _is_all_in_action(last):
        return HandAnalysisResult(
            spot_type="flop_cbet",
            hero_action=hero_desc,
            recommended_action="c-bet",
            mistake_severity="none",
            explanation="C-betting as preflop aggressor. Board texture and hand strength determine optimal frequency.",
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="flop_cbet",
        hero_action=hero_desc,
        recommended_action="context-dependent",
        mistake_severity="none",
        explanation="Check-back as preflop aggressor. Consider SPR and board texture to decide c-bet vs check-back frequency.",
        key_factors=_build_key_factors(hero_hp, hand, extras),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_turn_barrel(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    turn_acts = [a for a in hero_hp.actions if a.street == "TURN"]
    last = _last_voluntary(turn_acts) if turn_acts else None

    if last is None:
        return _fallback("no turn action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    pot = _pot_at_decision(hand, hero_hp, "TURN")

    extras = [f"pot: {pot}bb"]
    if hand.board_cards:
        extras.append(f"board: {hand.board_cards}")

    t = last.action_type.upper()
    if t in ("BET", "RAISE") or _is_all_in_action(last):
        return HandAnalysisResult(
            spot_type="turn_barrel",
            hero_action=hero_desc,
            recommended_action="barrel",
            mistake_severity="none",
            explanation="Turn bet. Consider board run-out and equity when deciding to barrel vs check.",
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="turn_barrel",
        hero_action=hero_desc,
        recommended_action="context-dependent",
        mistake_severity="none",
        explanation="Turn check. Pot control or giving up — hand and equity determine the correct frequency.",
        key_factors=_build_key_factors(hero_hp, hand, extras),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


def _analyze_river_call_fold(
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
) -> HandAnalysisResult:
    bb = hand.stakes_bb
    river_acts = [a for a in hero_hp.actions if a.street == "RIVER"]
    last = _last_voluntary(river_acts) if river_acts else None

    if last is None:
        return _fallback("no river action")

    hero_desc = _describe_action(last.action_type, last.amount, bb)
    t = last.action_type.upper()
    pot = _pot_at_decision(hand, hero_hp, "RIVER")

    # Compute pot odds for call
    call_amount = last.amount or _D0
    pot_odds_pct: Decimal = _D0
    if t == "CALL" and call_amount > _D0 and pot > _D0:
        total = pot + (call_amount / bb if bb > _D0 else _D0)
        call_bb = call_amount / bb if bb > _D0 else _D0
        if total > _D0:
            pot_odds_pct = (call_bb / total * _D100).quantize(Decimal("0.1"))

    extras = [f"pot: {pot}bb"]

    if t == "CALL":
        extras.append(f"pot odds: {pot_odds_pct}%")
        return HandAnalysisResult(
            spot_type="river_call_fold",
            hero_action=hero_desc,
            recommended_action="call if equity ≥ pot odds",
            mistake_severity="none",
            explanation=f"River call facing a bet. Pot odds are {pot_odds_pct}% — call if bluff-catch equity exceeds that.",
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    if t == "FOLD":
        extras.append("surrendered pot equity")
        return HandAnalysisResult(
            spot_type="river_call_fold",
            hero_action=hero_desc,
            recommended_action="context-dependent",
            mistake_severity="none",
            explanation="River fold facing a bet. Correct when opponent's value range exceeds the bluff-catch threshold.",
            key_factors=_build_key_factors(hero_hp, hand, extras),
            confidence=MetricLabel.INFERRED,
            ev_label="neutral",
            backing="heuristic",
        )

    return HandAnalysisResult(
        spot_type="river_call_fold",
        hero_action=hero_desc,
        recommended_action="context-dependent",
        mistake_severity="none",
        explanation="River decision facing a bet. Correct play depends on pot odds and opponent range.",
        key_factors=_build_key_factors(hero_hp, hand, extras),
        confidence=MetricLabel.INFERRED,
        ev_label="neutral",
        backing="heuristic",
    )


# ---------------------------------------------------------------------------
# Range augmentation helper
# ---------------------------------------------------------------------------


def _augment_with_range(
    result: HandAnalysisResult,
    hero_hp: HandPlayerOut,
    hand: HandDetailOut,
) -> HandAnalysisResult:
    """
    Attach range_context and hero_range_position to an existing result.

    Prefers Nash equilibrium tables for push/fold and call_all_in spots when
    available, falling back to the approximate range_library ranges.  Nash
    ranges are chip-EV solutions — ICM spots (bubble_icm, final_table_icm)
    remain SPECULATIVE regardless of which range source is used.

    When hole cards are available, also appends a range-position key factor
    and, for push/fold and steal spots, rewrites the explanation to mention
    range context.  Returns a new (frozen) HandAnalysisResult.
    """
    pos = (hero_hp.position or "").upper()
    stack = float(hero_hp.stack_bb) if hero_hp.stack_bb is not None else 20.0
    spot = result.spot_type
    canonical = parse_hole_cards(hero_hp.hole_cards)

    range_set: frozenset[str] = frozenset()
    range_key: str = ""
    range_label: str = ""  # human-readable label for context string
    backing_override: str = ""  # non-empty overrides RANGE_BACKING

    # ── Select the relevant range ──────────────────────────────────────────
    if spot in ("push_fold", "bubble_icm", "final_table_icm"):
        # Try Nash table first — more precise than range_library approximations.
        # Nash ranges are chip-EV; ICM spots stay SPECULATIVE regardless.
        nash_set, nash_key = get_nash_shove_range(pos, stack)
        if nash_key:
            range_set = nash_set
            range_key = nash_key
            depth = int(nash_key.split("_")[-1].rstrip("bb"))
            range_label = f"{pos} Nash shove range at {depth}bb ({len(range_set)} combos)"
            backing_override = NASH_BACKING
        else:
            # Fallback to range_library approximation
            range_set, range_key = get_push_range(pos, stack)
            if range_key:
                depth = int(range_key.split("_")[-1].rstrip("bb"))
                range_label = f"{pos} push range at {depth}bb ({len(range_set)} combos)"

    elif spot == "steal":
        range_set, range_key = get_steal_range(pos)
        if range_key:
            range_label = f"{pos} first-in open range ({len(range_set)} combos)"

    elif spot == "defend_bb":
        # Determine villain's position (first raiser who is not hero)
        raisers = [
            hp
            for hp in hand.hand_players
            if hp.player_id != hero_hp.player_id
            and any(a.street == "PREFLOP" and a.action_type in ("RAISE", "BET") for a in hp.actions)
        ]
        vs_pos = (raisers[0].position or "BTN").upper() if raisers else "BTN"
        range_set, range_key = get_bb_defend_range(vs_pos)
        if range_key:
            range_label = f"BB defend vs {vs_pos} ({len(range_set)} combos)"

    elif spot == "three_bet":
        # Find villain's position
        raisers = [
            hp
            for hp in hand.hand_players
            if hp.player_id != hero_hp.player_id
            and any(a.street == "PREFLOP" and a.action_type in ("RAISE", "BET") for a in hp.actions)
        ]
        vs_pos = (raisers[0].position or "CO").upper() if raisers else "CO"
        range_set, range_key = get_threbet_range(pos, vs_pos)
        if range_key:
            range_label = f"{pos} 3-bet range vs {vs_pos} ({len(range_set)} combos)"

    elif spot == "call_all_in":
        # Find the all-in raiser
        shover_hp = next(
            (
                hp
                for hp in hand.hand_players
                if hp.player_id != hero_hp.player_id
                and any(_is_all_in_action(a) for a in hp.actions if a.street == "PREFLOP")
            ),
            None,
        )
        vs_pos = (shover_hp.position or "UTG").upper() if shover_hp else "UTG"
        # Try Nash call range first
        nash_set, nash_key = get_nash_call_range("BB", vs_pos, stack)
        if nash_key:
            range_set = nash_set
            range_key = nash_key
            range_label = (
                f"Nash call range vs {vs_pos} shove at {int(stack)}bb ({len(range_set)} combos)"
            )
            backing_override = NASH_BACKING
        else:
            # Fallback to range_library
            range_set, range_key = get_call_range("BB", vs_pos, stack)
            if range_key:
                range_label = (
                    f"call range vs {vs_pos} shove at {int(stack)}bb ({len(range_set)} combos)"
                )

    # ── Compute range position ──────────────────────────────────────────────
    if not range_set:
        # No range found for this spot — return result unchanged
        return result

    range_context = range_label or range_key

    if canonical is None:
        # Hole cards absent — we know the range but not the hero's hand
        hero_range_pos = "unknown"
        extra_factors: list[str] = []
        new_explanation = result.explanation
    else:
        in_range = canonical in range_set
        # Use classify_hand_nash for Nash ranges, classify_hand_vs_range for others.
        # Both functions share the same logic; the distinction is explicit for clarity.
        if backing_override == NASH_BACKING:
            hero_range_pos = classify_hand_nash(canonical, range_set) if in_range else "outside"
        else:
            hero_range_pos = classify_hand_vs_range(canonical, range_set) if in_range else "outside"

        pos_label = {
            "top": f"Top of range ({canonical})",
            "mid": f"Mid range ({canonical})",
            "bottom": f"Bottom of range ({canonical})",
            "outside": f"Outside range ({canonical})",
        }.get(hero_range_pos, canonical)

        extra_factors = [pos_label]

        # Rewrite explanation for clear spots where range context is meaningful
        if spot in ("push_fold", "bubble_icm", "final_table_icm"):
            if backing_override == NASH_BACKING:
                # Nash-sourced explanation
                if hero_range_pos in ("top", "mid"):
                    new_explanation = (
                        f"{canonical} is in the {hero_range_pos} of the Nash shove range "
                        f"for {pos} at {int(stack)}bb. {result.explanation}"
                    )
                elif hero_range_pos == "bottom":
                    new_explanation = (
                        f"{canonical} is at the bottom of the Nash shove range "
                        f"for {pos} at {int(stack)}bb — marginal shove, proceed with care. "
                        f"{result.explanation}"
                    )
                else:
                    new_explanation = (
                        f"{canonical} is outside the Nash shove range for {pos} at {int(stack)}bb"
                        f" — this shove is wider than the Nash equilibrium suggests. "
                        f"{result.explanation}"
                    )
            else:
                # range_library fallback explanation
                if hero_range_pos in ("top", "mid"):
                    new_explanation = (
                        f"{canonical} is in the {hero_range_pos} of the {pos} push range "
                        f"at {int(stack)}bb — shoving is correct. {result.explanation}"
                    )
                elif hero_range_pos == "bottom":
                    new_explanation = (
                        f"{canonical} is at the bottom of the {pos} push range "
                        f"at {int(stack)}bb — marginal shove, proceed with care. {result.explanation}"
                    )
                else:
                    new_explanation = (
                        f"{canonical} is outside the standard {pos} push range "
                        f"at {int(stack)}bb — this shove/call is wider than equilibrium suggests. "
                        f"{result.explanation}"
                    )
        elif spot == "steal":
            if hero_range_pos == "outside":
                new_explanation = (
                    f"{canonical} falls outside the standard {pos} open range. {result.explanation}"
                )
            else:
                new_explanation = (
                    f"{canonical} is in the {hero_range_pos} of the {pos} open range — "
                    f"raising is standard. {result.explanation}"
                )
        else:
            new_explanation = result.explanation

    # ── Rebuild result with range fields ────────────────────────────────────
    new_factors = list(result.key_factors) + extra_factors

    # Add Nash table key factor when Nash data is used
    if backing_override == NASH_BACKING and range_key:
        new_factors = new_factors + [f"Nash table: {range_key}"]

    backing = (
        backing_override if backing_override else (RANGE_BACKING if range_set else result.backing)
    )

    return HandAnalysisResult(
        spot_type=result.spot_type,
        hero_action=result.hero_action,
        recommended_action=result.recommended_action,
        mistake_severity=result.mistake_severity,
        explanation=new_explanation,
        key_factors=new_factors,
        confidence=result.confidence,
        ev_label=result.ev_label,
        backing=backing,
        range_context=range_context,
        hero_range_position=hero_range_pos,
    )


# ---------------------------------------------------------------------------
# Exploit application helper
# ---------------------------------------------------------------------------


def _find_bb_player(hand: HandDetailOut, hero_hp: HandPlayerOut) -> HandPlayerOut | None:
    """Return the player in the BB position, excluding hero."""
    for hp in hand.hand_players:
        if hp.player_id != hero_hp.player_id and hp.position == "BB":
            return hp
    return None


def _find_last_preflop_raiser(hand: HandDetailOut, hero_hp: HandPlayerOut) -> HandPlayerOut | None:
    """Return the player who made the last preflop raise before hero's action, excluding hero."""
    hero_pf_vol = [
        a for a in hero_hp.actions if a.street == "PREFLOP" and a.action_type not in _SKIP_POSTING
    ]
    if not hero_pf_vol:
        return None
    first_hero_order = min(a.action_order for a in hero_pf_vol)

    best: tuple[int, HandPlayerOut] | None = None
    for hp in hand.hand_players:
        if hp.player_id == hero_hp.player_id:
            continue
        for a in hp.actions:
            if a.street != "PREFLOP":
                continue
            if a.action_type not in _RAISE_TYPES:
                continue
            if a.action_order >= first_hero_order:
                continue
            if best is None or a.action_order > best[0]:
                best = (a.action_order, hp)
    return best[1] if best else None


def _find_all_in_shover(hand: HandDetailOut, hero_hp: HandPlayerOut) -> HandPlayerOut | None:
    """
    For call_all_in spots: return the player whose action was all-in preflop
    before hero's first voluntary action.
    """
    hero_pf_vol = [
        a for a in hero_hp.actions if a.street == "PREFLOP" and a.action_type not in _SKIP_POSTING
    ]
    if not hero_pf_vol:
        return None
    first_hero_order = min(a.action_order for a in hero_pf_vol)

    best: tuple[int, HandPlayerOut] | None = None
    for hp in hand.hand_players:
        if hp.player_id == hero_hp.player_id:
            continue
        for a in hp.actions:
            if a.street != "PREFLOP":
                continue
            if not (a.is_all_in or a.action_type in ("ALL_IN", "ALLIN")):
                continue
            if a.action_order >= first_hero_order:
                continue
            if best is None or a.action_order > best[0]:
                best = (a.action_order, hp)
    return best[1] if best else None


def _confidence_level(hands_observed: int) -> str:
    """Maps sample size to confidence tier for villain profile display."""
    if hands_observed < 50:
        return "low"
    if hands_observed < 100:
        return "medium"
    return "high"


def _apply_exploit(
    result: HandAnalysisResult,
    hand: HandDetailOut,
    hero_hp: HandPlayerOut,
    opponent_stats: dict[uuid.UUID, PlayerStats] | None,
) -> HandAnalysisResult:
    """
    Detect key villain, classify, attach exploit adjustment.

    villain_profile is set to:
    - ""        when this spot type has no villain detection rule
    - ""        when opponent_stats is None (caller did not gather stats)
    - "unknown" when villain was found but too few hands to classify
    - profile   when classification succeeds
    """
    spot = result.spot_type

    # Determine villain for this spot type
    villain: HandPlayerOut | None = None
    if spot in ("push_fold", "bubble_icm", "final_table_icm"):
        villain = _find_bb_player(hand, hero_hp)
        if villain is None:
            others = [hp for hp in hand.hand_players if hp.player_id != hero_hp.player_id]
            villain = others[0] if others else None
    elif spot == "steal":
        villain = _find_bb_player(hand, hero_hp)
    elif spot == "call_all_in":
        villain = _find_all_in_shover(hand, hero_hp)
    elif spot in ("three_bet", "defend_bb", "four_bet_jam"):
        villain = _find_last_preflop_raiser(hand, hero_hp)
    else:
        return result  # spot has no villain detection → villain_profile stays ""

    if opponent_stats is None or villain is None:
        return result  # no stats provided or villain not found → villain_profile stays ""

    stats = opponent_stats.get(villain.player_id)
    if stats is None:
        # Villain is in the hand but we have no stats for them
        return replace(result, villain_profile="unknown", villain_profile_confidence="")

    profile = classify_opponent(stats)
    if profile == OpponentProfile.UNKNOWN:
        return replace(result, villain_profile="unknown", villain_profile_confidence="")

    confidence = _confidence_level(stats.hands_observed)
    adjustment, reason = get_exploit_adjustment(
        profile, spot, result.hero_range_position, stats=stats
    )

    return replace(
        result,
        villain_profile=profile.value,
        villain_profile_confidence=confidence,
        exploit_adjustment=adjustment,
        adjustment_reason=reason,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_hand(
    hand: HandDetailOut,
    hero_player_id: uuid.UUID,
    opponent_stats: dict[uuid.UUID, PlayerStats] | None = None,
) -> HandAnalysisResult:
    """
    Classify the hero's key decision and return a HandAnalysisResult.

    Never raises. If classification fails, returns spot_type='other' with
    confidence=SPECULATIVE.

    Parameters
    ----------
    hand:
        Fully populated HandDetailOut for this hand.
    hero_player_id:
        UUID of the player being analyzed.
    opponent_stats:
        Optional map of villain player_id → PlayerStats. When provided,
        _apply_exploit() injects a conservative exploit adjustment into the
        result. Pass None (default) to skip — the result is still complete,
        just without an opponent-specific nudge.
    """
    try:
        hero_hp = next(
            (hp for hp in hand.hand_players if hp.player_id == hero_player_id),
            None,
        )
        if hero_hp is None:
            return HandAnalysisResult(
                spot_type="other",
                hero_action="not in hand",
                recommended_action="n/a",
                mistake_severity="none",
                explanation="Hero was not a participant in this hand.",
                key_factors=[],
                confidence=MetricLabel.SPECULATIVE,
                ev_label="unknown",
                backing="heuristic",
            )

        pf_vol = _preflop_voluntary(hero_hp)
        bb = hand.stakes_bb
        stack_bb = hero_hp.stack_bb

        spot = _classify_spot(hand, hero_hp)

        if spot == "push_fold":
            raw = _analyze_push_fold(hand, hero_hp, pf_vol)
            result = _augment_with_range(raw, hero_hp, hand)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot in ("bubble_icm", "final_table_icm"):
            icm_note = (
                "ICM pressure applies — short stack near final table."
                if spot == "final_table_icm"
                else "ICM pressure applies — possible bubble spot."
            )
            result = _analyze_push_fold(hand, hero_hp, pf_vol, icm_note=icm_note)
            # Force SPECULATIVE, correct spot_type, and drop EV direction claim.
            # Chip-EV direction from push_fold analysis is not ICM-adjusted, so
            # claiming +EV/-EV without payout structure would be overclaiming.
            raw = HandAnalysisResult(
                spot_type=spot,
                hero_action=result.hero_action,
                recommended_action=result.recommended_action,
                mistake_severity=result.mistake_severity,
                explanation=result.explanation,
                key_factors=result.key_factors,
                confidence=MetricLabel.SPECULATIVE,
                ev_label="unknown",
                backing=result.backing,
            )
            result = _augment_with_range(raw, hero_hp, hand)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "call_all_in":
            raw = _analyze_call_all_in(hand, hero_hp, pf_vol)
            result = _augment_with_range(raw, hero_hp, hand)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "four_bet_jam":
            result = _analyze_four_bet_jam(hand, hero_hp, pf_vol)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "three_bet":
            raw = _analyze_three_bet(hand, hero_hp, pf_vol)
            result = _augment_with_range(raw, hero_hp, hand)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "defend_bb":
            raw = _analyze_defend_bb(hand, hero_hp, pf_vol)
            result = _augment_with_range(raw, hero_hp, hand)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "steal":
            raw = _analyze_steal(hand, hero_hp, pf_vol)
            result = _augment_with_range(raw, hero_hp, hand)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "open_fold":
            result = _analyze_open_fold(hand, hero_hp, pf_vol)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "flop_cbet":
            result = _analyze_flop_cbet(hand, hero_hp)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "turn_barrel":
            result = _analyze_turn_barrel(hand, hero_hp)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        if spot == "river_call_fold":
            result = _analyze_river_call_fold(hand, hero_hp)
            return _apply_exploit(result, hand, hero_hp, opponent_stats)

        # Fallback for "other"
        all_acts = [a for a in hero_hp.actions if a.action_type not in _SKIP_POSTING]
        last = _last_voluntary(all_acts)
        hero_desc = _describe_action(last.action_type, last.amount, bb) if last else "no action"
        result = HandAnalysisResult(
            spot_type="other",
            hero_action=hero_desc,
            recommended_action="context-dependent",
            mistake_severity="none",
            explanation="No clear classification for this hand spot.",
            key_factors=_build_key_factors(hero_hp, hand, []),
            confidence=MetricLabel.SPECULATIVE,
            ev_label="unknown",
            backing="heuristic",
        )
        return _apply_exploit(result, hand, hero_hp, opponent_stats)

    except Exception:
        return _fallback()
