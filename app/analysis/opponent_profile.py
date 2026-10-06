"""
Opponent modeling — pure module.

Classifies a villain by their observed statistics and produces exploit
adjustments that can be layered on top of Nash/range-based analysis.

Design constraints
------------------
- Pure module: no DB, no IO, no imports from hand_analysis_engine or services.
- All thresholds are documented inline; no magic numbers.
- Adjustments are intentionally conservative: small/moderate nudges only.
  They never contradict Nash blindly and never claim exact EV.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Opponent profile
# ---------------------------------------------------------------------------


class OpponentProfile(str, Enum):
    TIGHT_PASSIVE = "tight-passive"
    TIGHT_AGGRESSIVE = "tight-aggressive"
    LOOSE_PASSIVE = "loose-passive"
    LOOSE_AGGRESSIVE = "loose-aggressive"
    BALANCED = "balanced"
    UNKNOWN = "unknown"


@dataclass
class PlayerStats:
    vpip: float | None = None  # fraction 0.0–1.0
    pfr: float | None = None  # fraction 0.0–1.0
    aggression_freq: float | None = None  # (bets+raises)/(bets+raises+calls) 0.0–1.0
    fold_to_steal: float | None = None  # fraction 0.0–1.0
    hands_observed: int = 0
    three_bet_pct: float | None = None  # re-raise frequency when facing one preflop raise
    reliable: bool = False  # True when hands_observed >= _MIN_HANDS


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_MIN_HANDS = 20  # fewer than this → UNKNOWN always

_VPIP_TIGHT_CUTOFF = 0.18  # VPIP < 0.18 → tight
_VPIP_LOOSE_CUTOFF = 0.28  # VPIP > 0.28 → loose
# 0.18 ≤ VPIP ≤ 0.28 → BALANCED

_PFR_TIGHT_AGG = 0.12  # tight: pfr >= 0.12 → aggressive
_PFR_LOOSE_PASSIVE_MAX = 0.10  # loose: pfr < 0.10 → passive
_PFR_LOOSE_AGG_MIN = 0.18  # loose: pfr >= 0.18 → aggressive
# loose: 0.10 ≤ pfr < 0.18 → BALANCED

# Aggression-freq fallback (when pfr is unavailable)
_AGG_FREQ_HIGH = 0.55
_AGG_FREQ_LOW = 0.35


def classify_opponent(stats: PlayerStats) -> OpponentProfile:
    if stats.hands_observed < _MIN_HANDS:
        return OpponentProfile.UNKNOWN
    if stats.vpip is None:
        return OpponentProfile.UNKNOWN

    vpip = stats.vpip

    # 1. Determine VPIP bucket
    if vpip < _VPIP_TIGHT_CUTOFF:
        bucket = "tight"
    elif vpip > _VPIP_LOOSE_CUTOFF:
        bucket = "loose"
    else:
        return OpponentProfile.BALANCED  # middle VPIP range

    # 2. Determine aggressiveness within bucket
    if stats.pfr is not None:
        pfr = stats.pfr
        if bucket == "tight":
            return (
                OpponentProfile.TIGHT_AGGRESSIVE
                if pfr >= _PFR_TIGHT_AGG
                else OpponentProfile.TIGHT_PASSIVE
            )
        else:  # bucket == "loose"
            if pfr < _PFR_LOOSE_PASSIVE_MAX:
                return OpponentProfile.LOOSE_PASSIVE
            if pfr >= _PFR_LOOSE_AGG_MIN:
                return OpponentProfile.LOOSE_AGGRESSIVE
            return OpponentProfile.BALANCED  # loose but mid-PFR range

    elif stats.aggression_freq is not None:
        # Fallback when pfr is not available
        af = stats.aggression_freq
        if af > _AGG_FREQ_HIGH:
            is_aggressive = True
        elif af < _AGG_FREQ_LOW:
            is_aggressive = False
        else:
            return OpponentProfile.UNKNOWN  # ambiguous aggression

        if bucket == "tight":
            return (
                OpponentProfile.TIGHT_AGGRESSIVE if is_aggressive else OpponentProfile.TIGHT_PASSIVE
            )
        else:
            return (
                OpponentProfile.LOOSE_AGGRESSIVE if is_aggressive else OpponentProfile.LOOSE_PASSIVE
            )

    else:
        return OpponentProfile.UNKNOWN  # no aggressiveness signal


# ---------------------------------------------------------------------------
# Exploit adjustments
# ---------------------------------------------------------------------------

# Map: (spot_group, profile) → (trait, consequence, action, reason)
# trait:       Short behavioral observation ("Calls too wide").
# consequence: What that means for us ("Bluffing loses value").
# action:      Concrete adjustment ("Prefer value-heavy shoves").
# reason:      Short label shown in UI ("tight-passive").
# Empty strings signal "no adjustment available".

_EXPLOIT_TABLE: dict[str, dict[OpponentProfile, tuple[str, str, str, str]]] = {
    # ── push / shove spots ──────────────────────────────────────────────────
    "push_fold": {
        OpponentProfile.TIGHT_PASSIVE: (
            "Folds wide to shoves more than expected",
            "Shoving is slightly better than Nash here",
            "A slightly wider shove range tends to be more profitable",
            "tight-passive",
        ),
        OpponentProfile.TIGHT_AGGRESSIVE: (
            "Calls shoves with a strong, disciplined range",
            "Nash holds reliably vs this player type",
            "Stick close to Nash — deviations are marginally worse",
            "tight-aggressive",
        ),
        OpponentProfile.LOOSE_PASSIVE: (
            "Tends to call shoves too wide",
            "Thin bluff-shoves are marginally worse in practice",
            "Lean toward value-heavy shoves; reduce marginal bluffs",
            "loose-passive",
        ),
        OpponentProfile.LOOSE_AGGRESSIVE: (
            "Calls wide and re-raises lightly",
            "Marginal shoves are slightly worse vs their range",
            "Stay close to Nash; avoid the thinner shove candidates",
            "loose-aggressive",
        ),
        OpponentProfile.BALANCED: ("", "", "", ""),
        OpponentProfile.UNKNOWN: ("", "", "", ""),
    },
    # ── calling an all-in ───────────────────────────────────────────────────
    "call_all_in": {
        OpponentProfile.TIGHT_PASSIVE: (
            "Rarely bluffs all-in",
            "Marginal calls are slightly worse vs their range",
            "A slightly tighter call range tends to be more profitable",
            "tight-passive",
        ),
        OpponentProfile.TIGHT_AGGRESSIVE: (
            "Value-shoves strong hands only",
            "Calling borderline hands is marginally worse here",
            "Lean toward folding the thinner calls in your range",
            "tight-aggressive",
        ),
        OpponentProfile.LOOSE_PASSIVE: (
            "Tends to shove wide with thin value",
            "Calling is slightly better than Nash suggests",
            "Widen your call range slightly — more profitable in practice",
            "loose-passive",
        ),
        OpponentProfile.LOOSE_AGGRESSIVE: (
            "Over-shoves including bluffs",
            "Calling tends to be slightly better in practice",
            "Widen call range moderately — their range is weaker than it looks",
            "loose-aggressive",
        ),
        OpponentProfile.BALANCED: ("", "", "", ""),
        OpponentProfile.UNKNOWN: ("", "", "", ""),
    },
    # ── steal (BTN/CO/SB open vs defenders) ────────────────────────────────
    "steal": {
        OpponentProfile.TIGHT_PASSIVE: (
            "Folds blinds frequently",
            "Stealing is slightly more profitable in practice",
            "A slightly wider steal range tends to work here",
            "tight-passive",
        ),
        OpponentProfile.TIGHT_AGGRESSIVE: (
            "3-bets steal attempts often",
            "Thin steals are marginally worse vs this player",
            "Tighten slightly, or be ready to 4-bet jam",
            "tight-aggressive",
        ),
        OpponentProfile.LOOSE_PASSIVE: (
            "Calls wide but plays passively postflop",
            "Thin steals are slightly worse — expect a call",
            "Favor top of range; be ready to play postflop",
            "loose-passive",
        ),
        OpponentProfile.LOOSE_AGGRESSIVE: (
            "3-bets or calls steal attempts wide",
            "Thin steals are marginally worse in practice",
            "Tighten steal range; fold to re-raises when they push back",
            "loose-aggressive",
        ),
        OpponentProfile.BALANCED: ("", "", "", ""),
        OpponentProfile.UNKNOWN: ("", "", "", ""),
    },
    # ── defending big blind ─────────────────────────────────────────────────
    "defend_bb": {
        OpponentProfile.TIGHT_PASSIVE: (
            "Opens tight range only",
            "Their hand strength is real — bluffing is marginally worse",
            "Defending borderline hands tends to be slightly worse",
            "tight-passive",
        ),
        OpponentProfile.TIGHT_AGGRESSIVE: (
            "Opens tight and 3-bets for value",
            "Wide defense tends to be marginally worse here",
            "Defend your strongest hands; fold the middle of your range",
            "tight-aggressive",
        ),
        OpponentProfile.LOOSE_PASSIVE: (
            "Opens wide, plays passively",
            "Their range is weaker than it looks",
            "Widen defense slightly — slightly more profitable in practice",
            "loose-passive",
        ),
        OpponentProfile.LOOSE_AGGRESSIVE: (
            "Opens wide and barrels aggressively",
            "Fighting back tends to be slightly more profitable in practice",
            "Widen defense slightly and be prepared to push back",
            "loose-aggressive",
        ),
        OpponentProfile.BALANCED: ("", "", "", ""),
        OpponentProfile.UNKNOWN: ("", "", "", ""),
    },
    # ── 3-betting ───────────────────────────────────────────────────────────
    "three_bet": {
        OpponentProfile.TIGHT_PASSIVE: (
            "Calls 3-bets with strong hands",
            "Bluff 3-bets are marginally worse here",
            "3-bet for value; reduce bluff 3-bets slightly",
            "tight-passive",
        ),
        OpponentProfile.TIGHT_AGGRESSIVE: (
            "4-bets strong after facing a 3-bet",
            "Bluff 3-bets are marginally worse in practice",
            "3-bet only for value; bluff frequency should drop",
            "tight-aggressive",
        ),
        OpponentProfile.LOOSE_PASSIVE: (
            "Calls 3-bets wide, folds to pressure",
            "Value 3-bets are slightly more profitable in practice",
            "3-bet a slightly wider value range; they tend to pay off",
            "loose-passive",
        ),
        OpponentProfile.LOOSE_AGGRESSIVE: (
            "4-bets or calls 3-bets light",
            "Bluff 3-bets are marginally worse vs this player",
            "3-bet strong hands only; bluffing tends to be slightly worse",
            "loose-aggressive",
        ),
        OpponentProfile.BALANCED: ("", "", "", ""),
        OpponentProfile.UNKNOWN: ("", "", "", ""),
    },
}

# bubble_icm and final_table_icm use the same text as push_fold
_EXPLOIT_TABLE["bubble_icm"] = _EXPLOIT_TABLE["push_fold"]
_EXPLOIT_TABLE["final_table_icm"] = _EXPLOIT_TABLE["push_fold"]


def get_exploit_adjustment(
    profile: OpponentProfile,
    spot_type: str,
    hero_range_pos: str,
    stats: PlayerStats | None = None,
) -> tuple[str, str]:
    """
    Return (exploit_adjustment, adjustment_reason).

    The exploit_adjustment string is structured for card rendering:
        Line 0: Stats subtitle when available — "VPIP 34 / PFR 8 · 42 hands"
                (present only when stats.vpip is not None)
        Line 1 (or 0 without stats): Behavioral trait  ("Calls too wide")
        Line 2 (or 1): Consequence       ("Bluffing loses value")
        Line 3 (or 2): Action            ("Prefer value-heavy shoves")

    The frontend detects the stats line by the "VPIP" prefix on line 0.

    Adjustments are conservative nudges vs Nash/range baseline. They never
    claim exact EV and never reference solver outputs.

    Parameters
    ----------
    profile:
        Classified OpponentProfile for the key villain in this hand.
    spot_type:
        The spot_type string from HandAnalysisResult (e.g. "push_fold", "steal").
    hero_range_pos:
        The hero_range_position from HandAnalysisResult ("top", "mid", "bottom",
        "outside", "unknown"). Reserved for future calibration.
    stats:
        Optional PlayerStats for the villain. When provided, VPIP/PFR/hands
        are embedded as the first line of the adjustment text.

    Returns
    -------
    (adjustment, reason) — both empty strings if spot_type is not covered
    or profile is UNKNOWN.
    """
    spot_table = _EXPLOIT_TABLE.get(spot_type)
    if spot_table is None:
        return ("", "")

    entry = spot_table.get(profile, ("", "", "", ""))
    trait, consequence, action, reason = entry

    if not trait:
        return ("", "")

    if stats is not None and stats.vpip is not None:
        vpip_pct = round(stats.vpip * 100)
        n = stats.hands_observed
        if stats.pfr is not None:
            pfr_pct = round(stats.pfr * 100)
            stats_line = f"VPIP {vpip_pct} / PFR {pfr_pct} · {n} hands"
        else:
            stats_line = f"VPIP {vpip_pct} · {n} hands"
        adjustment = f"{stats_line}\n{trait}\n{consequence}\n{action}"
    else:
        adjustment = f"{trait}\n{consequence}\n{action}"

    return (adjustment, reason)
