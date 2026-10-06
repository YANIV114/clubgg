"""
Range library for hand analysis engine.

All ranges are approximate GTO/Nash equilibrium estimates for 6-max
tournament poker. Labeled "range-based estimate" — not solver output.

Hand string format throughout: canonical two-char strings
  "AA"  — pocket pair
  "AKs" — suited (same suit)
  "AKo" — offsuit (different suits)
"""

from __future__ import annotations

__all__ = [
    "parse_hole_cards",
    "hand_in_range",
    "classify_hand_vs_range",
    "get_push_range",
    "get_call_range",
    "get_steal_range",
    "get_threbet_range",
    "get_bb_defend_range",
    "RANGE_BACKING",
]

RANGE_BACKING = "range-based estimate"

# ---------------------------------------------------------------------------
# Rank / suit constants
# ---------------------------------------------------------------------------

_RANKS = "AKQJT98765432"
_RANK_IDX: dict[str, int] = {r: i for i, r in enumerate(_RANKS)}  # A=0 … 2=12

# ---------------------------------------------------------------------------
# Canonical hand strength order (all 169 unique preflop hands)
# Lower index = stronger hand.  Based on approximate equity vs random hand.
# ---------------------------------------------------------------------------

_STRENGTH_ORDER: list[str] = [
    # --- Tier 1: Premium ---
    "AA",
    "KK",
    "QQ",
    "JJ",
    "AKs",
    # --- Tier 2: Strong ---
    "TT",
    "AQs",
    "AKo",
    "AJs",
    "KQs",
    "99",
    # --- Tier 3: Good ---
    "ATs",
    "AQo",
    "KJs",
    "88",
    "QJs",
    "KTs",
    "AJo",
    "ATo",
    "A9s",
    "KQo",
    "77",
    "JTs",
    "A8s",
    "KJo",
    "QTs",
    "66",
    # --- Tier 4: Marginal ---
    "A7s",
    "T9s",
    "A6s",
    "KTo",
    "QJo",
    "A5s",
    "55",
    "J9s",
    "A4s",
    "K9s",
    "JTo",
    "A3s",
    "Q9s",
    "T8s",
    "44",
    "A2s",
    "98s",
    "K8s",
    "QTo",
    "33",
    "22",
    "J8s",
    "K7s",
    "87s",
    # --- Tier 5: Speculative ---
    "T7s",
    "Q8s",
    "K6s",
    "97s",
    "76s",
    "J7s",
    "K5s",
    "65s",
    "86s",
    "Q7s",
    "K4s",
    "54s",
    "96s",
    "T6s",
    "75s",
    "K3s",
    "85s",
    "Q6s",
    # --- Tier 6: Weak ---
    "K2s",
    "J6s",
    "Q5s",
    "64s",
    "95s",
    "T9o",
    "43s",
    "84s",
    "Q4s",
    "J5s",
    "53s",
    "74s",
    "Q3s",
    "J4s",
    "63s",
    "A9o",
    "Q2s",
    "T5s",
    "J3s",
    "52s",
    "42s",
    "J2s",
    "T4s",
    "K9o",
    "A8o",
    "T3s",
    "32s",
    "T2s",
    "93s",
    "94s",
    "83s",
    "73s",
    "72s",
    "62s",
    "92s",
    "82s",
    # --- Tier 7: Trash offsuit ---
    "A7o",
    "98o",
    "K8o",
    "A6o",
    "Q9o",
    "J9o",
    "87o",
    "A5o",
    "J8o",
    "K7o",
    "T8o",
    "A4o",
    "J7o",
    "97o",
    "Q8o",
    "K6o",
    "A3o",
    "76o",
    "T7o",
    "86o",
    "K5o",
    "A2o",
    "J6o",
    "Q7o",
    "96o",
    "65o",
    "K4o",
    "75o",
    "T6o",
    "Q6o",
    "K3o",
    "85o",
    "J5o",
    "64o",
    "95o",
    "T5o",
    "Q5o",
    "54o",
    "K2o",
    "J4o",
    "74o",
    "84o",
    "Q4o",
    "J3o",
    "63o",
    "T4o",
    "Q3o",
    "53o",
    "J2o",
    "T3o",
    "Q2o",
    "43o",
    "T2o",
    "52o",
    "42o",
    "32o",
    "94o",
    "93o",
    "92o",
    "83o",
    "82o",
    "73o",
    "72o",
    "62o",
]

_STRENGTH_RANK: dict[str, int] = {h: i for i, h in enumerate(_STRENGTH_ORDER)}


# ---------------------------------------------------------------------------
# Parse hole cards
# ---------------------------------------------------------------------------


def parse_hole_cards(hole_cards_str: str | None) -> str | None:
    """
    Parse a hole card string like 'Ah Kd' into canonical form 'AKo'.

    Returns None if string is absent, malformed, or unrecognisable.
    """
    if not hole_cards_str:
        return None
    parts = hole_cards_str.strip().split()
    if len(parts) != 2:
        return None
    try:
        c1, c2 = parts[0], parts[1]
        r1 = c1[0].upper()
        s1 = c1[1].lower()
        r2 = c2[0].upper()
        s2 = c2[1].lower()
        if r1 not in _RANK_IDX or r2 not in _RANK_IDX:
            return None
    except IndexError:
        return None

    # Order high card first
    if _RANK_IDX[r1] > _RANK_IDX[r2]:
        r1, r2 = r2, r1
        s1, s2 = s2, s1

    if r1 == r2:
        return f"{r1}{r2}"  # pocket pair

    suit_tag = "s" if s1 == s2 else "o"
    return f"{r1}{r2}{suit_tag}"


# ---------------------------------------------------------------------------
# Range expansion helpers
# ---------------------------------------------------------------------------


def _expand_pair_range(spec: str) -> list[str]:
    """'JJ+' → ['JJ','QQ','KK','AA'];  'JJ-77' → ['JJ','TT','99','88','77']."""
    if "+" in spec:
        base = spec.rstrip("+")
        r = base[0]
        if r not in _RANK_IDX:
            return []
        return [f"{x}{x}" for x in _RANKS[: _RANK_IDX[r] + 1]]
    if "-" in spec:
        hi, lo = spec.split("-", 1)
        r_hi, r_lo = hi[0], lo[0]
        if r_hi not in _RANK_IDX or r_lo not in _RANK_IDX:
            return []
        start = _RANK_IDX[r_hi]
        stop = _RANK_IDX[r_lo]
        if start > stop:
            start, stop = stop, start
        return [f"{_RANKS[i]}{_RANKS[i]}" for i in range(start, stop + 1)]
    # exact pair
    r = spec[0]
    return [f"{r}{r}"] if len(spec) == 2 and spec[0] == spec[1] else []


def _expand_suited_range(spec: str) -> list[str]:
    """'ATs+' → ['ATs','AJs','AQs','AKs'];  'ATs-A5s' → descending kicker."""
    if "+" in spec:
        base = spec.rstrip("+")
        r1, r2 = base[0], base[1]
        if r1 not in _RANK_IDX or r2 not in _RANK_IDX:
            return []
        # All suited combos with same high card r1, kicker from r2 up to r1-1.
        # _RANK_IDX: A=0, K=1, … 2=12; so "higher rank" = lower index.
        # "ATs+" wants ATs,AJs,AQs,AKs → kicker indices 4,3,2,1 (descending).
        hi_idx = _RANK_IDX[r1]
        lo_idx = _RANK_IDX[r2]
        out = []
        for ki in range(lo_idx, hi_idx, -1):  # descend from r2 toward r1 (exclusive)
            out.append(f"{r1}{_RANKS[ki]}s")
        return out
    if "-" in spec:
        hi_spec, lo_spec = spec.split("-", 1)
        r1 = hi_spec[0]
        k_hi = hi_spec[1]
        k_lo = lo_spec[1]
        if r1 not in _RANK_IDX or k_hi not in _RANK_IDX or k_lo not in _RANK_IDX:
            return []
        start = _RANK_IDX[k_hi]
        stop = _RANK_IDX[k_lo]
        if start > stop:
            start, stop = stop, start
        return [f"{r1}{_RANKS[ki]}s" for ki in range(start, stop + 1)]
    # exact suited
    if len(spec) == 3 and spec[2] == "s":
        return [spec]
    return []


def _expand_offsuit_range(spec: str) -> list[str]:
    """'ATo+' → ['ATo','AJo','AQo','AKo'];  'ATo-A7o' → descending kicker."""
    if "+" in spec:
        base = spec.rstrip("+")
        r1, r2 = base[0], base[1]
        if r1 not in _RANK_IDX or r2 not in _RANK_IDX:
            return []
        hi_idx = _RANK_IDX[r1]
        lo_idx = _RANK_IDX[r2]
        out = []
        for ki in range(lo_idx, hi_idx, -1):  # descend from r2 toward r1 (exclusive)
            out.append(f"{r1}{_RANKS[ki]}o")
        return out
    if "-" in spec:
        hi_spec, lo_spec = spec.split("-", 1)
        r1 = hi_spec[0]
        k_hi = hi_spec[1]
        k_lo = lo_spec[1]
        if r1 not in _RANK_IDX or k_hi not in _RANK_IDX or k_lo not in _RANK_IDX:
            return []
        start = _RANK_IDX[k_hi]
        stop = _RANK_IDX[k_lo]
        if start > stop:
            start, stop = stop, start
        return [f"{r1}{_RANKS[ki]}o" for ki in range(start, stop + 1)]
    # exact offsuit
    if len(spec) == 3 and spec[2] == "o":
        return [spec]
    return []


def expand_range_notation(specs: list[str]) -> frozenset[str]:
    """Expand a list of range specs into a frozenset of canonical hand strings."""
    out: list[str] = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        # Pocket pair shorthand
        if len(spec) >= 2 and spec[0] == spec[1] or (len(spec) == 4 and spec[2] == "-"):
            # Could be "JJ+" or "JJ-77"
            out.extend(_expand_pair_range(spec))
        elif spec.endswith("s") or (len(spec) > 2 and spec[2] == "s"):
            out.extend(_expand_suited_range(spec))
        elif spec.endswith("o") or (len(spec) > 2 and spec[2] == "o"):
            out.extend(_expand_offsuit_range(spec))
        elif len(spec) == 2 and spec[0] == spec[1]:
            out.append(spec)  # exact pair like "AA"
        elif spec.endswith("+"):
            # Could be pair+ or suited+
            base = spec[:-1]
            if len(base) == 2 and base[0] == base[1]:
                out.extend(_expand_pair_range(spec))
            elif len(base) == 3 and base[2] == "s":
                out.extend(_expand_suited_range(spec))
            elif len(base) == 3 and base[2] == "o":
                out.extend(_expand_offsuit_range(spec))
        else:
            # Try to parse as exact hand
            out.append(spec)
    # Filter to only valid hands
    return frozenset(h for h in out if h in _STRENGTH_RANK)


# ---------------------------------------------------------------------------
# Range lookup utilities
# ---------------------------------------------------------------------------


def hand_in_range(canonical_hand: str, range_set: frozenset[str]) -> bool:
    """Return True if the canonical hand is in the range."""
    return canonical_hand in range_set


def classify_hand_vs_range(
    canonical_hand: str,
    range_set: frozenset[str],
) -> str:
    """
    Return 'top' | 'mid' | 'bottom' | 'outside'.

    Position is computed by where the hand's strength rank falls relative
    to the strength ranks of all hands in the range.
    """
    if canonical_hand not in range_set:
        return "outside"
    if canonical_hand not in _STRENGTH_RANK:
        return "outside"

    # Collect ranks of all range hands
    range_ranks = sorted(_STRENGTH_RANK[h] for h in range_set if h in _STRENGTH_RANK)
    if not range_ranks:
        return "outside"

    hero_rank = _STRENGTH_RANK[canonical_hand]
    n = len(range_ranks)
    # Find position within sorted range_ranks (lower rank = stronger)
    pos = sum(1 for r in range_ranks if r <= hero_rank)
    frac = pos / n  # 0.0 = strongest, 1.0 = weakest
    if frac <= 0.33:
        return "top"
    if frac <= 0.67:
        return "mid"
    return "bottom"


# ---------------------------------------------------------------------------
# Range definitions
#
# All ranges are approximate Nash equilibrium estimates for 6-max tournaments.
# Stack depths are in big blinds (bb).
# Source: standard push/fold theory; labeled "range-based estimate".
# ---------------------------------------------------------------------------

# ── Push / fold ranges ──────────────────────────────────────────────────────
# Nash approximate all-in ranges by position and effective stack depth.
# Based on widely published ICM-adjusted push/fold charts.

_PUSH_SPECS: dict[str, list[str]] = {
    # BTN push (heads-up vs BB, or 2-3 left at final stages)
    "BTN_5bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A2o",
        "KQs-K2s",
        "KQo-K2o",
        "QJs-Q2s",
        "QJo-Q2o",
        "JTs-J2s",
        "JTo-J4o",
        "T9s-T2s",
        "T9o-T5o",
        "98s-92s",
        "98o-96o",
        "87s-84s",
        "87o-86o",
        "76s-74s",
        "65s-63s",
        "54s-53s",
        "43s",
    ],
    "BTN_8bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A7o",
        "KQs-K5s",
        "KQo-K9o",
        "QJs-Q7s",
        "QJo-Q9o",
        "JTs-J8s",
        "JTo",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s-74s",
        "65s-64s",
        "54s",
    ],
    "BTN_10bb": [
        "AA-22",
        "AKs-A3s",
        "AKo-A9o",
        "KQs-K6s",
        "KQo-KTo",
        "QJs-Q8s",
        "QJo",
        "JTs-J8s",
        "JTo",
        "T9s-T8s",
        "98s-97s",
        "87s-86s",
        "76s-75s",
        "65s",
    ],
    "BTN_12bb": [
        "AA-33",
        "AKs-A4s",
        "AKo-ATo",
        "KQs-K8s",
        "KJo-KTo",
        "QJs-Q9s",
        "QJo",
        "JTs-J9s",
        "JTo",
        "T9s-T8s",
        "98s",
        "87s",
        "76s",
    ],
    "BTN_15bb": [
        "AA-44",
        "AKs-A5s",
        "AKo-AJo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-Q9s",
        "QJo",
        "JTs-J9s",
        "T9s",
        "98s",
        "87s",
        "76s",
        "65s",
    ],
    # CO push
    "CO_5bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A2o",
        "KQs-K3s",
        "KQo-K7o",
        "QJs-Q4s",
        "QJo-Q9o",
        "JTs-J5s",
        "JTo",
        "T9s-T5s",
        "T9o",
        "98s-95s",
        "87s-84s",
        "76s-73s",
        "65s-63s",
        "54s",
        "43s",
    ],
    "CO_8bb": [
        "AA-22",
        "AKs-A4s",
        "AKo-A9o",
        "KQs-K7s",
        "KQo-KTo",
        "QJs-Q8s",
        "QJo",
        "JTs-J8s",
        "JTo",
        "T9s-T8s",
        "98s",
        "87s",
        "76s",
    ],
    "CO_10bb": [
        "AA-33",
        "AKs-A5s",
        "AKo-AJo",
        "KQs-K8s",
        "KQo-KJo",
        "QJs-Q9s",
        "QJo",
        "JTs-J9s",
        "T9s",
        "98s",
        "87s",
    ],
    "CO_12bb": [
        "AA-44",
        "AKs-A6s",
        "AKo-AJo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-Q9s",
        "JTs-J9s",
        "T9s",
        "98s",
    ],
    "CO_15bb": [
        "AA-55",
        "AKs-A7s",
        "AKo-AQo",
        "KQs-KTs",
        "KQo",
        "QJs-QTs",
        "JTs",
        "T9s",
    ],
    # SB push (always out of position postflop — wider push range)
    "SB_5bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A2o",
        "KQs-K2s",
        "KQo-K5o",
        "QJs-Q3s",
        "QJo-Q8o",
        "JTs-J3s",
        "JTo-J9o",
        "T9s-T3s",
        "T9o",
        "98s-92s",
        "98o",
        "87s-83s",
        "76s-73s",
        "65s-63s",
        "54s-53s",
    ],
    "SB_8bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A8o",
        "KQs-K5s",
        "KQo-K9o",
        "QJs-Q7s",
        "QJo-QTo",
        "JTs-J7s",
        "JTo",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s-74s",
        "65s-64s",
        "54s",
    ],
    "SB_10bb": [
        "AA-22",
        "AKs-A3s",
        "AKo-A9o",
        "KQs-K7s",
        "KQo-KTo",
        "QJs-Q8s",
        "QJo",
        "JTs-J8s",
        "JTo",
        "T9s-T8s",
        "98s-97s",
        "87s",
        "76s",
        "65s",
    ],
    "SB_12bb": [
        "AA-33",
        "AKs-A4s",
        "AKo-ATo",
        "KQs-K8s",
        "KQo-KJo",
        "QJs-Q9s",
        "QJo",
        "JTs-J9s",
        "T9s",
        "98s",
        "87s",
        "76s",
    ],
    "SB_15bb": [
        "AA-44",
        "AKs-A5s",
        "AKo-AJo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-QTs",
        "JTs",
        "T9s",
        "98s",
        "87s",
    ],
    # UTG push
    "UTG_5bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A5o",
        "KQs-K7s",
        "KQo-KJo",
        "QJs-Q8s",
        "QJo",
        "JTs-J8s",
        "T9s-T8s",
        "98s",
        "87s",
    ],
    "UTG_8bb": [
        "AA-44",
        "AKs-A8s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs-QTs",
        "JTs",
    ],
    "UTG_10bb": [
        "AA-55",
        "AKs-A9s",
        "AKo-AQo",
        "KQs-KJs",
        "KQo",
        "QJs",
    ],
    "UTG_12bb": [
        "AA-66",
        "AKs-ATs",
        "AKo-AQo",
        "KQs-KJs",
        "KQo",
    ],
    "UTG_15bb": [
        "AA-77",
        "AKs-AJs",
        "AKo",
        "KQs",
    ],
    # HJ push
    "HJ_5bb": [
        "AA-22",
        "AKs-A2s",
        "AKo-A7o",
        "KQs-K6s",
        "KQo-KTo",
        "QJs-Q8s",
        "QJo",
        "JTs-J8s",
        "JTo",
        "T9s-T8s",
        "98s",
        "87s",
        "76s",
    ],
    "HJ_8bb": [
        "AA-33",
        "AKs-A6s",
        "AKo-ATo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-Q9s",
        "JTs-J9s",
        "T9s",
        "98s",
    ],
    "HJ_10bb": [
        "AA-44",
        "AKs-A7s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs-QTs",
        "JTs",
    ],
    "HJ_12bb": [
        "AA-55",
        "AKs-A8s",
        "AKo-AQo",
        "KQs-KJs",
        "KQo",
        "QJs",
    ],
    "HJ_15bb": [
        "AA-66",
        "AKs-A9s",
        "AKo-AQo",
        "KQs-KJs",
    ],
}

# ── BB call vs shove ranges ─────────────────────────────────────────────────
# How wide BB should call vs an all-in push from various positions.
# Based on pot-odds + equity requirements.

_CALL_SPECS: dict[str, list[str]] = {
    # BB call vs BTN shove
    "BB_vs_BTN_5bb": [  # pot odds ~25%, very wide call
        "AA-22",
        "AKs-A2s",
        "AKo-A2o",
        "KQs-K5s",
        "KQo-K9o",
        "QJs-Q7s",
        "QJo-QTo",
        "JTs-J7s",
        "JTo",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s-74s",
        "65s",
    ],
    "BB_vs_BTN_8bb": [  # pot odds ~33%
        "AA-22",
        "AKs-A4s",
        "AKo-A9o",
        "KQs-K8s",
        "KQo-KTo",
        "QJs-Q9s",
        "QJo",
        "JTs-J9s",
        "T9s",
        "98s",
    ],
    "BB_vs_BTN_10bb": [  # pot odds ~37%
        "AA-22",
        "AKs-A5s",
        "AKo-ATo",
        "KQs-K9s",
        "KJo-KQo",
        "QJs-QTs",
        "JTs",
        "T9s",
    ],
    "BB_vs_BTN_12bb": [  # pot odds ~40%
        "AA-33",
        "AKs-A6s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs",
    ],
    "BB_vs_BTN_15bb": [  # pot odds ~43%
        "AA-44",
        "AKs-A8s",
        "AKo-AQo",
        "KQs-KJs",
        "KQo",
    ],
    # BB call vs CO shove (tighter — wider CO range means tighter call is fine)
    "BB_vs_CO_8bb": [
        "AA-22",
        "AKs-A5s",
        "AKo-ATo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-QTs",
        "JTs",
        "T9s",
    ],
    "BB_vs_CO_10bb": [
        "AA-33",
        "AKs-A7s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs",
    ],
    "BB_vs_CO_12bb": [
        "AA-44",
        "AKs-A8s",
        "AKo-AQo",
        "KQs-KJs",
    ],
    # BB call vs SB shove
    "BB_vs_SB_8bb": [
        "AA-22",
        "AKs-A5s",
        "AKo-ATo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-QTs",
        "JTs",
        "T9s",
    ],
    "BB_vs_SB_10bb": [
        "AA-33",
        "AKs-A6s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs",
    ],
    # SB call vs BTN shove
    "SB_vs_BTN_8bb": [
        "AA-33",
        "AKs-A7s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs-QTs",
    ],
}

# ── Steal open ranges (> 15bb, first-in) ───────────────────────────────────
# Standard 6-max opening ranges for raise-first-in from late position.
# These apply when effective stack > 20bb (deeper = wider).

_STEAL_SPECS: dict[str, list[str]] = {
    "BTN_open": [  # ~55% of hands
        "AA-22",
        "AKs-A2s",
        "AKo-A2o",
        "KQs-K2s",
        "KQo-K5o",
        "QJs-Q2s",
        "QJo-Q8o",
        "JTs-J3s",
        "JTo-J9o",
        "T9s-T5s",
        "T9o",
        "98s-96s",
        "98o",
        "87s-85s",
        "87o",
        "76s-74s",
        "76o",
        "65s-64s",
        "54s",
    ],
    "CO_open": [  # ~40%
        "AA-22",
        "AKs-A2s",
        "AKo-A5o",
        "KQs-K5s",
        "KQo-K9o",
        "QJs-Q7s",
        "QJo-QTo",
        "JTs-J7s",
        "JTo",
        "T9s-T7s",
        "T9o",
        "98s-96s",
        "87s-86s",
        "76s",
        "65s",
    ],
    "HJ_open": [  # ~28%
        "AA-22",
        "AKs-A5s",
        "AKo-A9o",
        "KQs-K8s",
        "KQo-KJo",
        "QJs-Q9s",
        "QJo",
        "JTs-J9s",
        "T9s",
        "98s",
    ],
    "SB_open": [  # ~40% (raising vs BB only)
        "AA-22",
        "AKs-A3s",
        "AKo-A5o",
        "KQs-K6s",
        "KQo-K9o",
        "QJs-Q7s",
        "QJo-QTo",
        "JTs-J7s",
        "JTo",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s-74s",
        "65s",
    ],
    "UTG_open": [  # ~18%
        "AA-55",
        "AKs-A9s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs-QTs",
        "JTs",
    ],
    "MP_open": [  # ~22%
        "AA-44",
        "AKs-A8s",
        "AKo-ATo",
        "KQs-K9s",
        "KQo-KJo",
        "QJs-QTs",
        "JTs",
    ],
}

# ── 3-bet ranges ────────────────────────────────────────────────────────────
# Value + bluff 3-bet ranges for common positions vs steal/open.
# These are tight-ish — tournament appropriate.

_THREBET_SPECS: dict[str, list[str]] = {
    "BTN_vs_CO": [  # ~12%
        "AA-TT",
        "AKs-AQs",
        "AKo-AQo",
        "KQs-KJs",
        "A5s-A4s",
        "JTs-J9s",
        "T9s",
    ],
    "BTN_vs_HJ": [  # ~9%
        "AA-JJ",
        "AKs-AJs",
        "AKo-AQo",
        "KQs",
        "A5s",
    ],
    "BTN_vs_UTG": [  # ~6%
        "AA-QQ",
        "AKs",
        "AKo",
    ],
    "CO_vs_HJ": [  # ~10%
        "AA-JJ",
        "AKs-AQs",
        "AKo",
        "KQs",
        "A5s",
        "T9s",
    ],
    "CO_vs_UTG": [  # ~6%
        "AA-QQ",
        "AKs",
        "AKo",
    ],
    "SB_vs_BTN": [  # ~12%
        "AA-TT",
        "AKs-AQs",
        "AKo",
        "KQs",
        "A5s-A4s",
        "JTs",
        "T9s",
    ],
    "SB_vs_CO": [
        "AA-JJ",
        "AKs-AQs",
        "AKo",
        "KQs",
        "A5s",
    ],
    "BB_vs_BTN": [  # ~10%
        "AA-TT",
        "AKs-AQs",
        "AKo-AJo",
        "KQs",
        "A5s-A4s",
        "JTs",
        "T9s",
        "98s",
    ],
    "BB_vs_CO": [  # ~8%
        "AA-JJ",
        "AKs-AQs",
        "AKo",
        "KQs",
        "A5s",
    ],
    "BB_vs_SB": [  # ~15%
        "AA-99",
        "AKs-ATs",
        "AKo-AJo",
        "KQs-KJs",
        "QJs",
        "A5s-A3s",
        "JTs",
        "T9s",
    ],
}

# ── BB defend (call) ranges ─────────────────────────────────────────────────
# How wide BB calls vs steal opens (not shoves) when effective stack > 15bb.

_BB_DEFEND_SPECS: dict[str, list[str]] = {
    "BB_vs_BTN": [  # ~50% (tight) — defending vs 2.5bb raise, deep stacked
        "AA-22",
        "AKs-A2s",
        "AKo-A5o",
        "KQs-K5s",
        "KQo-K9o",
        "QJs-Q6s",
        "QJo-Q9o",
        "JTs-J6s",
        "JTo",
        "T9s-T6s",
        "T9o",
        "98s-95s",
        "87s-84s",
        "76s-73s",
        "65s-63s",
        "54s",
    ],
    "BB_vs_CO": [  # ~40%
        "AA-22",
        "AKs-A3s",
        "AKo-A7o",
        "KQs-K7s",
        "KQo-KTo",
        "QJs-Q8s",
        "QJo",
        "JTs-J8s",
        "JTo",
        "T9s-T7s",
        "98s-96s",
        "87s-85s",
        "76s",
    ],
    "BB_vs_SB": [  # ~55% (SB completes or small-raises — wide call)
        "AA-22",
        "AKs-A2s",
        "AKo-A4o",
        "KQs-K4s",
        "KQo-K8o",
        "QJs-Q5s",
        "QJo-Q9o",
        "JTs-J5s",
        "JTo",
        "T9s-T5s",
        "T9o",
        "98s-95s",
        "87s-84s",
        "76s-73s",
        "65s-62s",
        "54s",
        "43s",
    ],
    "BB_vs_UTG": [  # ~30% (UTG opens tight — BB calls tight)
        "AA-44",
        "AKs-A8s",
        "AKo-AJo",
        "KQs-KTs",
        "KQo",
        "QJs-QTs",
        "QJo",
        "JTs",
    ],
}

# ---------------------------------------------------------------------------
# Expand all specs to frozensets (done once at import time)
# ---------------------------------------------------------------------------

PUSH_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _PUSH_SPECS.items()
}
CALL_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _CALL_SPECS.items()
}
STEAL_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _STEAL_SPECS.items()
}
THREBET_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _THREBET_SPECS.items()
}
BB_DEFEND_RANGES: dict[str, frozenset[str]] = {
    k: expand_range_notation(v) for k, v in _BB_DEFEND_SPECS.items()
}

# ---------------------------------------------------------------------------
# Public accessors with stack-depth bucketing
# ---------------------------------------------------------------------------

_PUSH_DEPTHS = (5, 8, 10, 12, 15)


def _nearest_depth(stack_bb: float, depths: tuple[int, ...] = _PUSH_DEPTHS) -> int:
    """Return the nearest defined stack depth for range lookup."""
    return min(depths, key=lambda d: abs(d - stack_bb))


def get_push_range(position: str, stack_bb: float) -> tuple[frozenset[str], str]:
    """
    Return (range_set, range_key) for push/fold at given position and stack.

    Falls back to UTG range if position not found.
    """
    pos = position.upper()
    depth = _nearest_depth(stack_bb)
    key = f"{pos}_{depth}bb"
    if key in PUSH_RANGES:
        return PUSH_RANGES[key], key
    # Try positional fallback
    for fallback in ("UTG", "HJ", "CO", "BTN"):
        fb_key = f"{fallback}_{depth}bb"
        if fb_key in PUSH_RANGES:
            return PUSH_RANGES[fb_key], fb_key
    return frozenset(), ""


def get_call_range(hero_pos: str, vs_pos: str, stack_bb: float) -> tuple[frozenset[str], str]:
    """Return (range_set, range_key) for calling a shove."""
    hero = hero_pos.upper()
    vs = vs_pos.upper()
    depth = _nearest_depth(stack_bb)
    key = f"{hero}_vs_{vs}_{depth}bb"
    if key in CALL_RANGES:
        return CALL_RANGES[key], key
    # Generic fallback
    fb_key = f"BB_vs_BTN_{depth}bb"
    if fb_key in CALL_RANGES:
        return CALL_RANGES[fb_key], fb_key
    return frozenset(), ""


def get_steal_range(position: str) -> tuple[frozenset[str], str]:
    """Return (range_set, range_key) for first-in open from position."""
    pos = position.upper()
    key = f"{pos}_open"
    if key in STEAL_RANGES:
        return STEAL_RANGES[key], key
    return frozenset(), ""


def get_threbet_range(hero_pos: str, vs_pos: str) -> tuple[frozenset[str], str]:
    """Return (range_set, range_key) for 3-betting."""
    key = f"{hero_pos.upper()}_vs_{vs_pos.upper()}"
    if key in THREBET_RANGES:
        return THREBET_RANGES[key], key
    return frozenset(), ""


def get_bb_defend_range(vs_pos: str) -> tuple[frozenset[str], str]:
    """Return (range_set, range_key) for BB defending vs steal."""
    key = f"BB_vs_{vs_pos.upper()}"
    if key in BB_DEFEND_RANGES:
        return BB_DEFEND_RANGES[key], key
    return frozenset(), ""
