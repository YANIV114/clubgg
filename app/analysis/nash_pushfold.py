"""
Nash equilibrium push/fold tables for 6-max tournament poker.

Stores Nash equilibrium shove and call ranges keyed by position and stack depth.
These are Nash equilibrium solutions for chip-EV push/fold (no ICM adjustment),
so they are more precisely defined than the approximate ranges in range_library.py
but are still labeled "Nash table estimate" — not solver output.

Design constraints
------------------
- Pure module: no DB, no IO, never raises.
- All ranges are frozensets of canonical hand strings (same format as range_library.py).
- Confidence = INFERRED for standard spots; SPECULATIVE when ICM context applies.
- Backing string: NASH_BACKING = "Nash table estimate"
- Do NOT call these "solver output" anywhere.
- Do NOT claim exact EV.
"""

from __future__ import annotations

__all__ = [
    "NASH_BACKING",
    "NASH_SHOVE_RANGES",
    "NASH_CALL_RANGES",
    "get_nash_shove_range",
    "get_nash_call_range",
    "classify_hand_nash",
]

from app.analysis.range_library import classify_hand_vs_range, expand_range_notation

NASH_BACKING = "Nash table estimate"

# ---------------------------------------------------------------------------
# Nash equilibrium shove range specs
#
# First-in shove ranges for 6-max, no limpers.
# Stored as list-of-spec notation, expanded to frozensets at import time.
# Approximate Nash equilibrium chip-EV solutions.
# ---------------------------------------------------------------------------

_NASH_SHOVE_SPECS: dict[str, list[str]] = {
    # ── BTN (button — most liberal position) ─────────────────────────────────
    # ~100% at 5bb, narrowing to ~35% at 15bb
    "BTN_5bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K2s",
        "QJs-Q2s",
        "JTs-J2s",
        "T9s-T2s",
        "98s-92s",
        "87s-82s",
        "76s-72s",
        "65s-62s",
        "54s-52s",
        "43s-42s",
        "32s",
        "AKo-A2o",
        "KQo-K2o",
        "QJo-Q2o",
        "JTo-J2o",
        "T9o-T2o",
        "98o-92o",
        "87o-82o",
        "76o-72o",
        "65o-62o",
        "54o-52o",
        "43o-42o",
        "32o",
    ],
    "BTN_8bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K2s",
        "QJs-Q3s",
        "JTs-J4s",
        "T9s-T6s",
        "98s-96s",
        "87s-85s",
        "76s-75s",
        "65s-64s",
        "54s",
        "AKo-A2o",
        "KQo-K5o",
        "QJo-Q8o",
        "JTo-J9o",
        "T9o",
        "98o",
        "87o",
        "76o",
    ],
    "BTN_10bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K4s",
        "QJs-Q6s",
        "JTs-J7s",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s",
        "65s",
        "AKo-A2o",
        "KQo-K7o",
        "QJo-Q9o",
        "JTo",
        "T9o",
    ],
    "BTN_12bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K5s",
        "QJs-Q8s",
        "JTs-J8s",
        "T9s-T8s",
        "98s-97s",
        "87s",
        "76s",
        "65s",
        "AKo-A4o",
        "KQo-K8o",
        "QJo-QTo",
        "JTo",
    ],
    "BTN_15bb": [
        "AA-22",
        "AKs-A4s",
        "KQs-K7s",
        "QJs-Q9s",
        "JTs-J9s",
        "T9s",
        "98s",
        "AKo-A7o",
        "KQo-K9o",
        "QJo",
    ],
    # ── CO (cutoff) ───────────────────────────────────────────────────────────
    # ~95% at 5bb, narrowing to ~28% at 15bb
    "CO_5bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K2s",
        "QJs-Q2s",
        "JTs-J3s",
        "T9s-T4s",
        "98s-95s",
        "87s-84s",
        "76s-74s",
        "65s-63s",
        "54s-53s",
        "43s",
        "AKo-A2o",
        "KQo-K3o",
        "QJo-Q7o",
        "JTo-J8o",
        "T9o-T8o",
        "98o",
        "87o",
        "76o",
    ],
    "CO_8bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K4s",
        "QJs-Q7s",
        "JTs-J7s",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s",
        "65s",
        "AKo-A3o",
        "KQo-K8o",
        "QJo-Q9o",
        "JTo",
        "T9o",
    ],
    "CO_10bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K6s",
        "QJs-Q8s",
        "JTs-J8s",
        "T9s-T8s",
        "98s-97s",
        "87s",
        "76s",
        "AKo-A5o",
        "KQo-K9o",
        "QJo-QTo",
    ],
    "CO_12bb": [
        "AA-22",
        "AKs-A4s",
        "KQs-K7s",
        "QJs-Q9s",
        "JTs-J9s",
        "T9s",
        "98s",
        "AKo-A7o",
        "KQo-KTo",
        "QJo",
    ],
    "CO_15bb": [
        "AA-33",
        "AKs-A6s",
        "KQs-K8s",
        "QJs-QTs",
        "JTs",
        "T9s",
        "AKo-A9o",
        "KQo-KJo",
    ],
    # ── HJ (hijack) ───────────────────────────────────────────────────────────
    # ~90% at 5bb, narrowing to ~24% at 15bb
    "HJ_5bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K2s",
        "QJs-Q3s",
        "JTs-J4s",
        "T9s-T5s",
        "98s-95s",
        "87s-84s",
        "76s-73s",
        "65s-63s",
        "54s",
        "AKo-A2o",
        "KQo-K4o",
        "QJo-Q8o",
        "JTo-J8o",
        "T9o",
        "98o",
        "87o",
    ],
    "HJ_8bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K5s",
        "QJs-Q8s",
        "JTs-J8s",
        "T9s-T7s",
        "98s-96s",
        "87s",
        "76s",
        "AKo-A4o",
        "KQo-K9o",
        "QJo-QTo",
        "JTo",
    ],
    "HJ_10bb": [
        "AA-22",
        "AKs-A4s",
        "KQs-K7s",
        "QJs-Q9s",
        "JTs-J8s",
        "T9s",
        "98s",
        "AKo-A7o",
        "KQo-KTo",
        "QJo",
    ],
    "HJ_12bb": [
        "AA-33",
        "AKs-A6s",
        "KQs-K8s",
        "QJs-QTs",
        "JTs",
        "T9s",
        "AKo-A9o",
        "KQo-KJo",
    ],
    "HJ_15bb": [
        "AA-44",
        "AKs-A8s",
        "KQs-K9s",
        "QJs-QTs",
        "AKo-ATo",
        "KQo",
    ],
    # ── UTG (under the gun — tightest position) ───────────────────────────────
    # ~80% at 5bb, narrowing to ~18% at 15bb
    "UTG_5bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K3s",
        "QJs-Q5s",
        "JTs-J7s",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s",
        "65s",
        "AKo-A2o",
        "KQo-K6o",
        "QJo-Q9o",
        "JTo",
        "T9o",
    ],
    "UTG_8bb": [
        "AA-22",
        "AKs-A4s",
        "KQs-K7s",
        "QJs-Q9s",
        "JTs-J8s",
        "T9s",
        "98s",
        "AKo-A7o",
        "KQo-KTo",
        "QJo",
    ],
    "UTG_10bb": [
        "AA-33",
        "AKs-A6s",
        "KQs-K8s",
        "QJs-QTs",
        "JTs",
        "T9s",
        "AKo-A9o",
        "KQo-KJo",
    ],
    "UTG_12bb": [
        "AA-44",
        "AKs-A8s",
        "KQs-K9s",
        "QTs",
        "AKo-ATo",
        "KQo",
    ],
    "UTG_15bb": [
        "AA-55",
        "AKs-A9s",
        "KQs-KTs",
        "AKo-AJo",
        "KQo",
    ],
    # ── SB (small blind, heads-up vs BB) ─────────────────────────────────────
    # ~100% at 5bb, narrowing to ~40% at 15bb
    "SB_5bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K2s",
        "QJs-Q2s",
        "JTs-J2s",
        "T9s-T2s",
        "98s-92s",
        "87s-82s",
        "76s-72s",
        "65s-62s",
        "54s-52s",
        "43s-42s",
        "32s",
        "AKo-A2o",
        "KQo-K2o",
        "QJo-Q2o",
        "JTo-J2o",
        "T9o-T2o",
        "98o-92o",
        "87o-82o",
        "76o-72o",
        "65o-62o",
        "54o-52o",
        "43o-42o",
        "32o",
    ],
    "SB_8bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K2s",
        "QJs-Q4s",
        "JTs-J5s",
        "T9s-T6s",
        "98s-95s",
        "87s-84s",
        "76s-74s",
        "65s-63s",
        "54s-52s",
        "43s",
        "AKo-A2o",
        "KQo-K4o",
        "QJo-Q8o",
        "JTo-J9o",
        "T9o",
        "98o",
        "87o",
        "76o",
    ],
    "SB_10bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K3s",
        "QJs-Q6s",
        "JTs-J7s",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s-74s",
        "65s",
        "AKo-A2o",
        "KQo-K6o",
        "QJo-Q9o",
        "JTo",
        "T9o",
    ],
    "SB_12bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K5s",
        "QJs-Q7s",
        "JTs-J8s",
        "T9s-T8s",
        "98s-96s",
        "87s-85s",
        "76s",
        "65s",
        "AKo-A3o",
        "KQo-K7o",
        "QJo-QTo",
        "JTo",
    ],
    "SB_15bb": [
        "AA-22",
        "AKs-A3s",
        "KQs-K6s",
        "QJs-Q8s",
        "JTs-J8s",
        "T9s-T7s",
        "98s-96s",
        "87s",
        "76s",
        "AKo-A5o",
        "KQo-K9o",
        "QJo",
    ],
}

# ---------------------------------------------------------------------------
# Nash equilibrium call range specs
#
# BB (and SB) calling ranges vs all-in shoves from various positions.
# Based on Nash equilibrium pot-odds + equity solutions.
# ---------------------------------------------------------------------------

_NASH_CALL_SPECS: dict[str, list[str]] = {
    # ── BB calling vs BTN shove ───────────────────────────────────────────────
    "BB_vs_BTN_5bb": [
        "AA-22",
        "AKs-A2s",
        "KQs-K3s",
        "QJs-Q6s",
        "JTs-J7s",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s-74s",
        "65s",
        "AKo-A2o",
        "KQo-K7o",
        "QJo-Q9o",
        "JTo",
        "T9o",
    ],
    "BB_vs_BTN_8bb": [
        "AA-22",
        "AKs-A4s",
        "KQs-K7s",
        "QJs-Q9s",
        "JTs-J9s",
        "T9s",
        "98s",
        "AKo-A7o",
        "KQo-KTo",
        "QJo",
    ],
    "BB_vs_BTN_10bb": [
        "AA-33",
        "AKs-A6s",
        "KQs-K8s",
        "QJs-QTs",
        "JTs",
        "T9s",
        "AKo-A9o",
        "KQo-KJo",
    ],
    "BB_vs_BTN_12bb": [
        "AA-44",
        "AKs-A8s",
        "KQs-K9s",
        "QJs-QTs",
        "AKo-ATo",
        "KQo",
    ],
    "BB_vs_BTN_15bb": [
        "AA-55",
        "AKs-A9s",
        "KQs-KTs",
        "AKo-AJo",
        "KQo",
    ],
    # ── BB calling vs CO shove ────────────────────────────────────────────────
    "BB_vs_CO_8bb": [
        "AA-33",
        "AKs-A5s",
        "KQs-K8s",
        "QJs-Q9s",
        "JTs-J9s",
        "T9s",
        "AKo-A8o",
        "KQo-KJo",
    ],
    "BB_vs_CO_10bb": [
        "AA-44",
        "AKs-A7s",
        "KQs-K9s",
        "QJs-QTs",
        "JTs",
        "AKo-ATo",
        "KQo",
    ],
    "BB_vs_CO_12bb": [
        "AA-55",
        "AKs-A9s",
        "KQs-KTs",
        "QJs",
        "AKo-AJo",
        "KQo",
    ],
    # ── BB calling vs HJ shove ────────────────────────────────────────────────
    "BB_vs_HJ_8bb": [
        "AA-33",
        "AKs-A6s",
        "KQs-K8s",
        "QJs-QTs",
        "JTs",
        "T9s",
        "AKo-A9o",
        "KQo-KJo",
    ],
    "BB_vs_HJ_10bb": [
        "AA-44",
        "AKs-A8s",
        "KQs-K9s",
        "QJs",
        "AKo-AJo",
        "KQo",
    ],
    # ── BB calling vs UTG shove ───────────────────────────────────────────────
    "BB_vs_UTG_8bb": [
        "AA-44",
        "AKs-A8s",
        "KQs-K9s",
        "QJs",
        "AKo-AJo",
        "KQo",
    ],
    "BB_vs_UTG_10bb": [
        "AA-55",
        "AKs-A9s",
        "KQs-KTs",
        "AKo-AQo",
    ],
    "BB_vs_UTG_12bb": [
        "AA-66",
        "AKs-ATs",
        "KQs",
        "AKo",
    ],
    # ── SB calling vs BTN shove ───────────────────────────────────────────────
    "SB_vs_BTN_8bb": [
        "AA-33",
        "AKs-A5s",
        "KQs-K7s",
        "QJs-Q9s",
        "JTs",
        "T9s",
        "AKo-A8o",
        "KQo-KJo",
        "QJo",
    ],
}

# ---------------------------------------------------------------------------
# Expand all specs to frozensets (done once at import time)
# ---------------------------------------------------------------------------

NASH_SHOVE_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _NASH_SHOVE_SPECS.items()
}
NASH_CALL_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _NASH_CALL_SPECS.items()
}

# ---------------------------------------------------------------------------
# Stack depth bucketing (same depths as range_library)
# ---------------------------------------------------------------------------

_NASH_DEPTHS = (5, 8, 10, 12, 15)


def _nearest_depth(stack_bb: float, depths: tuple[int, ...] = _NASH_DEPTHS) -> int:
    """Return the nearest defined stack depth for Nash table lookup."""
    return min(depths, key=lambda d: abs(d - stack_bb))


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_nash_shove_range(position: str, stack_bb: float) -> tuple[frozenset[str], str]:
    """
    Return (range_set, key_str) for the Nash equilibrium shove range.

    Parameters
    ----------
    position:
        Hero's position string, e.g. "BTN", "CO", "HJ", "SB", "UTG".
        Case-insensitive. Unknown positions fall back to UTG (tightest).
    stack_bb:
        Effective stack in big blinds. Bucketed to nearest defined depth
        in (5, 8, 10, 12, 15).

    Returns
    -------
    (range_set, key_str) where key_str is like "BTN_10bb".
    Returns (frozenset(), "") only if all fallbacks fail (should not happen).

    Confidence: INFERRED. For ICM spots (bubble/final table), callers should
    override to SPECULATIVE — these ranges are chip-EV solutions, not ICM-adjusted.
    """
    pos = position.upper()
    depth = _nearest_depth(stack_bb)
    key = f"{pos}_{depth}bb"
    if key in NASH_SHOVE_RANGES:
        return NASH_SHOVE_RANGES[key], key
    # Positional fallback: unknown positions fall back to UTG (tightest)
    for fallback in ("UTG", "HJ", "CO", "BTN"):
        fb_key = f"{fallback}_{depth}bb"
        if fb_key in NASH_SHOVE_RANGES:
            return NASH_SHOVE_RANGES[fb_key], fb_key
    return frozenset(), ""


def get_nash_call_range(
    position: str, villain_position: str, stack_bb: float
) -> tuple[frozenset[str], str]:
    """
    Return (range_set, key_str) for the Nash equilibrium call range.

    Parameters
    ----------
    position:
        Caller's position, e.g. "BB" or "SB". Case-insensitive.
    villain_position:
        Shover's position, e.g. "BTN", "CO", "HJ", "UTG". Case-insensitive.
        Unknown positions fall back to BTN (widest expected shove — most demanding call).
    stack_bb:
        Effective stack in big blinds. Bucketed to nearest defined depth.

    Returns
    -------
    (range_set, key_str) where key_str is like "BB_vs_BTN_10bb".
    Falls back to BB_vs_BTN if specific combo not found.

    Confidence: INFERRED. For ICM spots (bubble/final table), callers should
    override to SPECULATIVE.
    """
    hero = position.upper()
    vs = villain_position.upper()
    depth = _nearest_depth(stack_bb)
    key = f"{hero}_vs_{vs}_{depth}bb"
    if key in NASH_CALL_RANGES:
        return NASH_CALL_RANGES[key], key
    # Try with nearest depths for the specific position combo
    for d in sorted(_NASH_DEPTHS, key=lambda x: abs(x - stack_bb)):
        candidate = f"{hero}_vs_{vs}_{d}bb"
        if candidate in NASH_CALL_RANGES:
            return NASH_CALL_RANGES[candidate], candidate
    # Unknown villain position: fall back to BTN (demanding call, covers most cases)
    fb_key = f"BB_vs_BTN_{depth}bb"
    if fb_key in NASH_CALL_RANGES:
        return NASH_CALL_RANGES[fb_key], fb_key
    # Last resort: any available BB_vs_BTN depth
    for d in sorted(_NASH_DEPTHS, key=lambda x: abs(x - stack_bb)):
        candidate = f"BB_vs_BTN_{d}bb"
        if candidate in NASH_CALL_RANGES:
            return NASH_CALL_RANGES[candidate], candidate
    return frozenset(), ""


def classify_hand_nash(hand: str, range_set: frozenset[str]) -> str:
    """
    Classify a hand's position within a Nash range.

    Returns 'top' | 'mid' | 'bottom' | 'outside'.

    Delegates to classify_hand_vs_range from range_library — same logic,
    same strength-order ranking. Nash ranges use identical hand string format.
    """
    return classify_hand_vs_range(hand, range_set)
