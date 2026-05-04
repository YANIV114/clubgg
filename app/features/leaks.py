"""
Leak detection engine for poker player analysis.

A "leak" is a statistically observable pattern that suggests an exploitable
tendency in a player's strategy.  Leaks are always evidence-based: each one
references a specific measured stat with its sample size, states what baseline
the stat deviates from, and distinguishes what is *observed* from what is
*inferred*.

Design principles
-----------------
1. Sample-size awareness  — small n → lower confidence; never overclaim.
2. Exploitability focus   — priority reflects how easily an opponent can
                            monetise the pattern, not just how "wrong" it is.
3. Honest limitations     — every leak includes a ``limitations`` field that
                            describes what this analysis cannot see.
4. Separate fact/interp   — ``evidence`` is factual; ``explanation`` adds
                            interpretation.

Baseline ranges used
--------------------
All baselines are typical for 6-max cash, deep-stacked.  They are deliberately
wide to avoid false positives on legitimate style variation.

    VPIP:           22–38 %
    PFR:            14–24 %   (PFR/VPIP ratio ≥ 0.60)
    3-bet %:         4–12 %
    Fold to 3-bet:  50–68 %
    WTSD:           28–38 %
    WSD:            46–56 %
    BB VPIP:        35–58 %   (pot odds justify wide defence)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.player_stats import PlayerStats


# ── Enums ─────────────────────────────────────────────────────────────────────


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(StrEnum):
    HIGH = "high"  # n ≥ high_threshold
    MEDIUM = "medium"  # n ≥ medium_threshold
    LOW = "low"  # n ≥ low_threshold but < medium_threshold
    INSUFFICIENT = "insufficient_data"  # n < low_threshold → do not emit leak


class Category(StrEnum):
    PREFLOP = "preflop"
    POSTFLOP = "postflop"
    TOURNAMENT = "tournament"


class Frequency(StrEnum):
    """How often the relevant situation arises in a typical session."""

    PER_HAND = "per_hand"  # every hand
    COMMON = "common"  # several times per session
    SITUATIONAL = "situational"  # position- or opponent-specific
    RARE = "rare"  # infrequent


# ── Leak output ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Leak:
    """
    One exploitable pattern in a player's strategy, with all supporting evidence.

    ``priority`` (1–10) reflects practical urgency: how exploitable this pattern
    is AND how confident we are.  Always sort descending on priority for display.
    """

    leak_id: str
    category: Category
    title: str
    explanation: str
    evidence: str
    confidence: Confidence
    severity: Severity
    frequency: Frequency
    priority: int  # 1–10; higher = more urgent to address
    sample_size: int
    limitations: str
    suggested_fix: str


# ── Sample-size thresholds ─────────────────────────────────────────────────────
# Dict keys: "high" / "medium" / "low" (minimum n for each confidence tier).

_VPIP_N = {"high": 100, "medium": 30, "low": 10}
_PFR_N = {"high": 100, "medium": 30, "low": 10}
_THREE_BET_N = {"high": 100, "medium": 40, "low": 15}
_FOLD_3BET_N = {"high": 50, "medium": 20, "low": 8}
_WTSD_N = {"high": 60, "medium": 25, "low": 10}
_WSD_N = {"high": 30, "medium": 15, "low": 5}
# Steal thresholds: position-specific situations occur ~1/3–1/6 of all hands
_STEAL_N = {"high": 40, "medium": 15, "low": 6}
_DEFEND_N = {"high": 40, "medium": 15, "low": 6}
_RESTEAL_N = {"high": 30, "medium": 12, "low": 5}
# Postflop: c-bet situations arise ~30–50% of hands (pfr saw flop)
_CBET_N = {"high": 50, "medium": 20, "low": 8}
# Fold-to-flop-bet: arise whenever hero sees the flop
_FOLD_FLOP_N = {"high": 50, "medium": 20, "low": 8}
# Turn barrel: subset of c-bet hands that saw the turn
_TURN_BARREL_N = {"high": 40, "medium": 15, "low": 6}
# Fold-to-turn-bet: similar frequency to turn barrel
_FOLD_TURN_N = {"high": 40, "medium": 15, "low": 6}
# Aggression factor: n = total postflop calls across all hands
_AF_N = {"high": 60, "medium": 25, "low": 10}


# ── Internal helpers ──────────────────────────────────────────────────────────


def _confidence(n: int | None, thresholds: dict[str, int]) -> Confidence:
    """Map a sample size to a Confidence level using the given threshold dict."""
    if n is None or n < thresholds["low"]:
        return Confidence.INSUFFICIENT
    if n >= thresholds["high"]:
        return Confidence.HIGH
    if n >= thresholds["medium"]:
        return Confidence.MEDIUM
    return Confidence.LOW


def _pct(d: Decimal | None) -> str:
    """Format a Decimal fraction as a percentage string for evidence text."""
    if d is None:
        return "N/A"
    return f"{float(d) * 100:.1f}%"


def _compute_priority(severity: Severity, confidence: Confidence) -> int:
    """
    Combine severity and confidence into a 1–10 priority score.

    The formula weights confidence heavily: a high-severity pattern with low
    confidence has lower priority than a medium-severity pattern that is
    reliably measured.  ``INSUFFICIENT`` should be filtered out before calling.

    Score table:
        HIGH+HIGH=10  HIGH+MEDIUM=8   HIGH+LOW=5
        MED +HIGH=7   MED +MEDIUM=5   MED +LOW=3
        LOW +HIGH=4   LOW +MEDIUM=3   LOW +LOW=2
    """
    sev = {Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1}[severity]
    con = {
        Confidence.HIGH: 3,
        Confidence.MEDIUM: 2,
        Confidence.LOW: 1,
        Confidence.INSUFFICIENT: 0,
    }.get(confidence, 0)

    raw = sev * con  # 1–9
    # Add 1 point bonus for HIGH severity to break HIGH/MEDIUM ties at top
    bonus = 1 if severity == Severity.HIGH and con >= 2 else 0
    return max(1, min(10, raw + bonus))


# ── LeakDetector ──────────────────────────────────────────────────────────────


class LeakDetector:
    """
    Runs all leak rules against a PlayerStats snapshot.

    Usage::

        detector = LeakDetector()
        leaks = detector.detect(stats)
        # leaks is sorted by priority descending (most urgent first)
    """

    def detect(self, stats: PlayerStats) -> list[Leak]:
        """Return all detected leaks, sorted by priority (highest first)."""
        rules = [
            # Generic preflop
            self._vpip_too_loose,
            self._vpip_too_tight,
            self._pfr_too_passive,
            self._fold_to_3bet_too_high,
            self._three_bet_too_low,
            self._three_bet_too_high,
            # Positional steal / defend
            self._btn_steal_too_low,
            self._co_steal_too_low,
            self._sb_steal_too_low,
            self._bb_overfolding_vs_steals,
            self._bb_overfolding_vs_btn,
            self._sb_overfolding_vs_steals,
            self._bb_defending_too_loose,
            self._resteal_too_low,
            self._late_position_passive,
            # Positional BB VPIP (old rules, now superseded by more granular ones above)
            self._bb_defend_too_tight,
            self._bb_defend_too_loose,
            # Postflop — WTSD / WSD
            self._wtsd_too_high,
            self._wtsd_too_low,
            self._wsd_suspiciously_low,
            # Postflop — c-bet / fold-to-bet / aggression
            self._cbet_too_high,
            self._cbet_too_low,
            self._fold_to_flop_bet_too_high,
            self._fold_to_turn_bet_too_high,
            self._too_passive_postflop,
        ]
        leaks = [rule(stats) for rule in rules]
        result = [leak for leak in leaks if leak is not None]
        return sorted(result, key=lambda l: l.priority, reverse=True)

    # ── Preflop rules ─────────────────────────────────────────────────────────

    def _vpip_too_loose(self, stats: PlayerStats) -> Leak | None:
        vpip = stats.vpip
        n = vpip.n or 0
        value = vpip.value
        conf = _confidence(n, _VPIP_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.38"):
            return None

        severity = Severity.HIGH if value > Decimal("0.50") else Severity.MEDIUM
        return Leak(
            leak_id="vpip_too_loose",
            category=Category.PREFLOP,
            title="VPIP too loose",
            explanation=(
                f"Playing {_pct(value)} of hands voluntarily is above the 22–38% "
                "range typical for winning 6-max cash players.  Excessive loose play "
                "inflates your average cost per hand and leaves you in many "
                "dominated-hand situations — especially from early position."
            ),
            evidence=(f"VPIP={_pct(value)} over {n} hands  (baseline: 22–38%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.PER_HAND,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "Overall VPIP is position-agnostic.  A high total can be partly "
                "explained by disproportionate hands from the BB, where wide "
                "defence is correct.  Check the BB positional breakdown separately."
            ),
            suggested_fix=(
                "Tighten preflop ranges from UTG and UTG+1.  Audit cold-call "
                "frequencies from all positions.  A VPIP of 24–30% is a "
                "reasonable cash-game target in 6-max."
            ),
        )

    def _vpip_too_tight(self, stats: PlayerStats) -> Leak | None:
        vpip = stats.vpip
        n = vpip.n or 0
        value = vpip.value
        conf = _confidence(n, _VPIP_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.18"):
            return None

        severity = Severity.HIGH if value < Decimal("0.12") else Severity.LOW
        return Leak(
            leak_id="vpip_too_tight",
            category=Category.PREFLOP,
            title="VPIP too tight",
            explanation=(
                f"Playing only {_pct(value)} of hands leaves significant value on "
                "the table.  Very tight players miss profitable opens from late "
                "position, have predictable ranges postflop, and allow opponents to "
                "steal liberally from BTN and CO."
            ),
            evidence=(f"VPIP={_pct(value)} over {n} hands  (baseline: 22–38%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.PER_HAND,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "Tight play can be appropriate in very loose passive games where "
                "multi-way pots make bluffing difficult.  Short-handed tables "
                "require wider opening ranges."
            ),
            suggested_fix=(
                "Open more hands from CO, BTN, and SB.  Defend the BB at "
                "a reasonable frequency vs. late-position opens.  Aim for 22–28% "
                "in most 6-max cash lineups."
            ),
        )

    def _pfr_too_passive(self, stats: PlayerStats) -> Leak | None:
        pfr = stats.pfr
        vpip = stats.vpip
        n = pfr.n or 0
        pfr_val = pfr.value
        vpip_val = vpip.value
        conf = _confidence(n, _PFR_N)
        if conf is Confidence.INSUFFICIENT or pfr_val is None:
            return None

        low_abs = pfr_val < Decimal("0.13")
        low_ratio = (
            vpip_val is not None
            and vpip_val > Decimal("0.01")
            and (pfr_val / vpip_val) < Decimal("0.55")
        )
        if not (low_abs or low_ratio):
            return None

        ratio_note = ""
        if vpip_val and vpip_val > Decimal("0"):
            ratio = float(pfr_val / vpip_val)
            ratio_note = f", PFR/VPIP={ratio:.2f} (baseline ≥0.60)"

        severity = Severity.HIGH if (low_abs and low_ratio) else Severity.MEDIUM
        return Leak(
            leak_id="pfr_too_passive",
            category=Category.PREFLOP,
            title="PFR too passive (calling too much preflop)",
            explanation=(
                f"A PFR of {_pct(pfr_val)} indicates frequent calling rather than "
                "raising preflop.  Passive entry forfeits fold equity, fails to "
                "define your range, and allows opponents to play speculative hands "
                "cheaply in position."
            ),
            evidence=(
                f"PFR={_pct(pfr_val)}, VPIP={_pct(vpip_val)}{ratio_note} "
                f"over {n} hands  (PFR baseline: 14–24%)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.PER_HAND,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "PFR measures preflop raise frequency across all positions.  A "
                "low PFR from the BB specifically may reflect correct flat-calling "
                "vs. mid-position opens rather than a systematic limp problem."
            ),
            suggested_fix=(
                "Convert limps to open-raises or folds from all positions.  "
                "Replace cold-calls with 3-bets or folds in late position.  "
                "Target PFR/VPIP ≥ 0.65 and a PFR of 14–22%."
            ),
        )

    def _fold_to_3bet_too_high(self, stats: PlayerStats) -> Leak | None:
        f3b = stats.fold_to_3bet
        n = f3b.n or 0
        value = f3b.value
        conf = _confidence(n, _FOLD_3BET_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.68"):
            return None

        severity = Severity.HIGH if value > Decimal("0.80") else Severity.MEDIUM
        return Leak(
            leak_id="fold_to_3bet_too_high",
            category=Category.PREFLOP,
            title="Fold to 3-bet too high",
            explanation=(
                f"Folding to 3-bets {_pct(value)} of the time is directly "
                "exploitable: opponents can profitably 3-bet you with any two cards "
                "from the right positions, turning your opens into profitable "
                "steal-targets.  This is among the most mechanically exploitable "
                "preflop leaks."
            ),
            evidence=(
                f"Fold to 3-bet={_pct(value)} over {n} facing-3bet situations (baseline: 50–68%)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "This stat does not separate by position or 3-bettor type.  "
                "A high fold rate against a tight 3-bettor may be correct; "
                "the problem is folding this frequency to *all* 3-bets."
            ),
            suggested_fix=(
                "Build a mixed 4-bet range (value + bluffs with blockers) and a "
                "calling range for facing 3-bets.  From BTN/CO opens, you should "
                "continue ~32–50%.  4-bet bluff frequency: ~25–30% of 4-bets."
            ),
        )

    def _three_bet_too_low(self, stats: PlayerStats) -> Leak | None:
        tbt = stats.three_bet_pct
        n = tbt.n or 0
        value = tbt.value
        conf = _confidence(n, _THREE_BET_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.04"):
            return None

        return Leak(
            leak_id="three_bet_too_low",
            category=Category.PREFLOP,
            title="3-bet frequency too low",
            explanation=(
                f"3-betting only {_pct(value)} of the time (vs. 4–12% typical) "
                "means you cede initiative too often, your strong hands become "
                "identifiable (you never 3-bet bluff), and your opening range "
                "plays predictably postflop."
            ),
            evidence=(f"3-bet%={_pct(value)} over {n} 3-bet opportunities (baseline: 4–12%)"),
            confidence=conf,
            severity=Severity.LOW,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.LOW, conf),
            sample_size=n,
            limitations=(
                "Overall 3-bet% is position-agnostic.  A low total may partly "
                "reflect fewer BTN opportunities (where 3-betting is most "
                "profitable).  Check positional breakdown when available."
            ),
            suggested_fix=(
                "Add light 3-bets from the BTN and CO facing late-position "
                "opens.  Use a polarised 3-bet range: strong value + suited "
                "blockers (A2s–A5s).  Target 5–9% overall."
            ),
        )

    def _three_bet_too_high(self, stats: PlayerStats) -> Leak | None:
        tbt = stats.three_bet_pct
        n = tbt.n or 0
        value = tbt.value
        conf = _confidence(n, _THREE_BET_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.14"):
            return None

        return Leak(
            leak_id="three_bet_too_high",
            category=Category.PREFLOP,
            title="3-bet frequency too high",
            explanation=(
                f"3-betting {_pct(value)} of opportunities is unusually aggressive "
                "and likely includes marginal bluffs.  Attentive opponents will "
                "respond with tighter calling ranges and increased 4-bet frequency."
            ),
            evidence=(f"3-bet%={_pct(value)} over {n} opportunities (baseline: 4–12%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "A high 3-bet% may be profitable against passive openers who fold "
                "too much.  Sample may include a period of intentionally exploitative "
                "play against specific opponents."
            ),
            suggested_fix=(
                "Ensure your 3-bet bluffs have strong blockers and good "
                "equity when called (suited Ax, KQs).  Reduce light 3-bets "
                "from out of position.  Review 4-bet call-off frequency."
            ),
        )

    # ── Steal rules ───────────────────────────────────────────────────────────

    def _btn_steal_too_low(self, stats: PlayerStats) -> Leak | None:
        n = stats.btn_steal_pct.n or 0
        value = stats.btn_steal_pct.value
        conf = _confidence(n, _STEAL_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.50"):
            return None

        severity = Severity.HIGH if value < Decimal("0.35") else Severity.MEDIUM
        return Leak(
            leak_id="btn_steal_too_low",
            category=Category.PREFLOP,
            title="BTN steal frequency too low",
            explanation=(
                f"Stealing only {_pct(value)} from the button is well below the "
                "50–75% range expected of a positionally-aware player.  Button is "
                "the most profitable steal spot — limping or folding there surrenders "
                "a structural edge every orbit."
            ),
            evidence=(f"BTN steal%={_pct(value)} over {n} BTN opportunities (baseline: 50–75%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "BTN steal% doesn't adjust for table composition — a very "
                "tight table justifies higher steal rates, a loose-aggressive "
                "table may justify tighter play."
            ),
            suggested_fix=(
                "Open-raise any two cards that have reasonable equity from "
                "BTN when action folds to you.  Any broadway, suited connector, "
                "any pair, and most Ax/Kx hands are profitable opens."
            ),
        )

    def _co_steal_too_low(self, stats: PlayerStats) -> Leak | None:
        n = stats.co_steal_pct.n or 0
        value = stats.co_steal_pct.value
        conf = _confidence(n, _STEAL_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.28"):
            return None

        return Leak(
            leak_id="co_steal_too_low",
            category=Category.PREFLOP,
            title="CO steal frequency too low",
            explanation=(
                f"Stealing only {_pct(value)} from the cutoff (CO) leaves significant "
                "value on the table.  CO is the second-best steal position and should "
                "be opened at 28–45% when folded to."
            ),
            evidence=(f"CO steal%={_pct(value)} over {n} CO opportunities (baseline: 28–45%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "CO steal% treats all lineups the same.  A tight BTN who "
                "always 3-bets justifies a tighter CO range."
            ),
            suggested_fix=(
                "Open suited connectors, suited aces, any pair, and suited "
                "broadways from CO.  Target a 28–40% open rate when folded to."
            ),
        )

    def _sb_steal_too_low(self, stats: PlayerStats) -> Leak | None:
        n = stats.sb_steal_pct.n or 0
        value = stats.sb_steal_pct.value
        conf = _confidence(n, _STEAL_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.35"):
            return None

        return Leak(
            leak_id="sb_steal_too_low",
            category=Category.PREFLOP,
            title="SB steal frequency too low",
            explanation=(
                f"Raising only {_pct(value)} from SB when folded to is below the "
                "35–55% range typical in 6-max.  SB must act first postflop against "
                "only the BB, making many hands marginal opens worth raising."
            ),
            evidence=(f"SB steal%={_pct(value)} over {n} SB opportunities (baseline: 35–55%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.SITUATIONAL,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "SB steal% doesn't distinguish between completing (call) and "
                "folding.  High complete% might partially compensate but is "
                "usually inferior to raising."
            ),
            suggested_fix=(
                "Raise a wide range from SB vs BB heads-up.  Most suited "
                "hands, pairs, and connected cards are profitable opens.  "
                "Complete rarely — prefer raise or fold."
            ),
        )

    # ── Defend rules ──────────────────────────────────────────────────────────

    def _bb_overfolding_vs_steals(self, stats: PlayerStats) -> Leak | None:
        n = stats.bb_fold_to_steal.n or 0
        value = stats.bb_fold_to_steal.value
        conf = _confidence(n, _DEFEND_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.68"):
            return None

        severity = Severity.HIGH if value > Decimal("0.80") else Severity.MEDIUM
        return Leak(
            leak_id="bb_overfolding_vs_steals",
            category=Category.PREFLOP,
            title="BB over-folding to steals (overall)",
            explanation=(
                f"Folding {_pct(value)} of the time in the BB when facing a steal "
                "is directly exploitable.  Opponents who identify this will open "
                "almost any two cards from steal positions, winning the pot "
                "immediately in excess of break-even frequency."
            ),
            evidence=(
                f"BB fold-to-steal={_pct(value)} over {n} BB-vs-steal situations (baseline: 45–65%)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "Aggregated across all steal positions (BTN/CO/SB).  "
                "A high rate vs. tight openers may be correct; see the BTN-specific "
                "stat for more detail."
            ),
            suggested_fix=(
                "Widen BB defend range.  At typical steal frequencies you need "
                "to continue ~35–55% to prevent profitable exploitation.  "
                "Prioritise suited hands, pairs, and suited connectors."
            ),
        )

    def _bb_overfolding_vs_btn(self, stats: PlayerStats) -> Leak | None:
        n = stats.bb_fold_to_btn_open.n or 0
        value = stats.bb_fold_to_btn_open.value
        conf = _confidence(n, _DEFEND_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.72"):
            return None

        severity = Severity.HIGH if value > Decimal("0.82") else Severity.MEDIUM
        return Leak(
            leak_id="bb_overfolding_vs_btn",
            category=Category.PREFLOP,
            title="BB over-folding specifically to BTN opens",
            explanation=(
                f"Folding to BTN opens {_pct(value)} of the time is a precise, "
                "directly exploitable pattern.  BTN knows the action is heads-up "
                "and will open extremely wide once this fold rate is identified.  "
                "This is one of the highest-value exploits in 6-max poker."
            ),
            evidence=(
                f"BB fold-to-BTN={_pct(value)} over {n} BB-vs-BTN situations (baseline: 38–60%)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "Does not adjust for BTN open-sizing or BTN's own tendencies.  "
                "A tight BTN (30% open rate) warrants tighter BB defence."
            ),
            suggested_fix=(
                "Defend most suited hands, all pocket pairs, suited broadways, "
                "and medium off-suit connectors from BB vs BTN.  Mix 3-bets "
                "to prevent BTN from always getting position cheaply."
            ),
        )

    def _sb_overfolding_vs_steals(self, stats: PlayerStats) -> Leak | None:
        n = stats.sb_fold_to_steal.n or 0
        value = stats.sb_fold_to_steal.value
        conf = _confidence(n, _DEFEND_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.72"):
            return None

        return Leak(
            leak_id="sb_overfolding_vs_steals",
            category=Category.PREFLOP,
            title="SB over-folding to steals",
            explanation=(
                f"Folding {_pct(value)} of SB opportunities when facing a steal "
                "is above the 50–72% baseline.  Although SB acts first postflop "
                "(a real disadvantage), the pot odds and positional play vs. only "
                "the opener justify wider defence."
            ),
            evidence=(
                f"SB fold-to-steal={_pct(value)} over {n} SB-vs-steal situations (baseline: 50–72%)"
            ),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.SITUATIONAL,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "SB defence quality is highly stack-depth dependent.  "
                "Short stacks should fold more; deep stacks should defend "
                "or 3-bet a wider range."
            ),
            suggested_fix=(
                "3-bet or call vs. late-position opens with suited connectors, "
                "medium pairs, and suited aces.  Flat-calling is often fine "
                "with hands that flop well despite OOP disadvantage."
            ),
        )

    def _bb_defending_too_loose(self, stats: PlayerStats) -> Leak | None:
        n = stats.bb_fold_to_steal.n or 0
        value = stats.bb_fold_to_steal.value
        conf = _confidence(n, _DEFEND_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.38"):
            return None

        return Leak(
            leak_id="bb_defending_too_loose",
            category=Category.PREFLOP,
            title="BB defending too loosely vs steals",
            explanation=(
                f"Folding only {_pct(value)} to steals means you defend very widely "
                "from the BB.  While wide defence is correct, defending this "
                "frequently includes dominated hands that leak chips postflop."
            ),
            evidence=(
                f"BB fold-to-steal={_pct(value)} over {n} BB-vs-steal situations (baseline: 45–65%)"
            ),
            confidence=conf,
            severity=Severity.LOW,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.LOW, conf),
            sample_size=n,
            limitations=(
                "A very low fold rate may reflect intentional 3-bet bluffing "
                "rather than passive over-calling.  Check PFR from BB for context."
            ),
            suggested_fix=(
                "Remove dominated off-suit holdings (K5o, Q4o, J3o) from "
                "your BB call range.  Shift flat-calls to 3-bets where possible."
            ),
        )

    def _resteal_too_low(self, stats: PlayerStats) -> Leak | None:
        n = stats.resteal_pct.n or 0
        value = stats.resteal_pct.value
        conf = _confidence(n, _RESTEAL_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.08"):
            return None

        return Leak(
            leak_id="resteal_too_low",
            category=Category.PREFLOP,
            title="Re-steal (3-bet vs steals) too low",
            explanation=(
                f"Only 3-betting {_pct(value)} when facing steal attempts means "
                "opponents can steal against you cheaply from all positions.  "
                "A non-trivial re-steal frequency is essential to balance your "
                "blind defence and protect your open range."
            ),
            evidence=(f"Resteal%={_pct(value)} over {n} re-steal opportunities (baseline: 8–18%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "Resteal% aggregates BB and SB re-steal opportunities.  "
                "A low rate from BB may be compensated by flat-calling then "
                "betting the flop aggressively — but this is harder to execute."
            ),
            suggested_fix=(
                "Build a polar BB 3-bet range: strong value (TT+, AQs+) and "
                "re-steal bluffs (A2s–A5s, K4s, suited blockers).  "
                "Target 8–15% resteal frequency to prevent auto-profitability."
            ),
        )

    def _late_position_passive(self, stats: PlayerStats) -> Leak | None:
        """
        Fires when BTN PFR is much lower than CO PFR — indicates the player
        is not adjusting for positional advantage at all.
        """
        btn_stats = stats.positional.get("BTN")
        co_stats = stats.positional.get("CO")
        if btn_stats is None or co_stats is None:
            return None
        btn_pfr = btn_stats.pfr
        co_pfr = co_stats.pfr
        btn_n = btn_pfr.n or 0
        co_n = co_pfr.n or 0
        btn_val = btn_pfr.value
        co_val = co_pfr.value
        conf_btn = _confidence(btn_n, _VPIP_N)
        conf_co = _confidence(co_n, _VPIP_N)
        # Need both to be at least LOW confidence
        if (
            conf_btn is Confidence.INSUFFICIENT
            or conf_co is Confidence.INSUFFICIENT
            or btn_val is None
            or co_val is None
        ):
            return None
        # Leak: BTN PFR <= CO PFR — not taking positional advantage
        if btn_val > co_val + Decimal("0.04"):
            return None

        conf = min(
            [conf_btn, conf_co],
            key=lambda c: (
                [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW].index(c)
                if c in [Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW]
                else 99
            ),
        )
        return Leak(
            leak_id="late_position_passive",
            category=Category.PREFLOP,
            title="Not exploiting positional advantage (BTN PFR ≤ CO PFR)",
            explanation=(
                f"BTN PFR ({_pct(btn_val)}) is not meaningfully higher than CO PFR "
                f"({_pct(co_val)}).  BTN always has position postflop — it should "
                "be your most aggressive open spot.  Equal or lower BTN aggression "
                "vs. CO indicates no positional adjustment."
            ),
            evidence=(f"BTN PFR={_pct(btn_val)} (n={btn_n}), CO PFR={_pct(co_val)} (n={co_n})"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=min(btn_n, co_n),
            limitations=(
                "This compares only BTN vs CO PFR.  A BTN PFR limited by "
                "a very 3-bet-happy SB/BB may be legitimately lower.  "
                "Check the full table dynamic before acting on this."
            ),
            suggested_fix=(
                "Expand BTN opening range to 40–55%.  BTN is the last to act "
                "preflop and always has position postflop — open wider and "
                "use position to outplay out-of-position callers."
            ),
        )

    # ── Positional preflop ────────────────────────────────────────────────────

    def _bb_defend_too_tight(self, stats: PlayerStats) -> Leak | None:
        bb = stats.positional.get("BB")
        if bb is None:
            return None
        vpip = bb.vpip
        n = vpip.n or 0
        value = vpip.value
        conf = _confidence(n, _VPIP_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.36"):
            return None

        return Leak(
            leak_id="bb_defend_too_tight",
            category=Category.PREFLOP,
            title="Big blind defend frequency too low",
            explanation=(
                f"From the BB you continue only {_pct(value)} of the time.  "
                "You already have 1 BB invested and receive better pot odds than "
                "any other position.  Folding this often is directly exploitable: "
                "opponents can open almost any two cards against you."
            ),
            evidence=(f"BB VPIP={_pct(value)} over {n} BB hands (baseline: 35–58%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.SITUATIONAL,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "BB VPIP includes all voluntary actions (calls, 3-bets, limp-raises) "
                "and cannot isolate pure raise-defence frequency.  Uncontested "
                "limped pots inflate BB VPIP slightly."
            ),
            suggested_fix=(
                "Widen BB defence, especially vs. BTN and CO steals.  "
                "Suited connectors (54s–98s), small pairs, and suited aces "
                "play well.  Mix in more BB 3-bets to prevent auto-steal."
            ),
        )

    def _bb_defend_too_loose(self, stats: PlayerStats) -> Leak | None:
        bb = stats.positional.get("BB")
        if bb is None:
            return None
        vpip = bb.vpip
        n = vpip.n or 0
        value = vpip.value
        conf = _confidence(n, _VPIP_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.65"):
            return None

        return Leak(
            leak_id="bb_defend_too_loose",
            category=Category.PREFLOP,
            title="Big blind defend frequency too high",
            explanation=(
                f"Defending {_pct(value)} from the BB suggests calling raises "
                "with too wide a range.  Despite pot odds, playing dominated "
                "hands OOP across multiple streets produces a large leak."
            ),
            evidence=(f"BB VPIP={_pct(value)} over {n} BB hands (baseline: 35–58%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.SITUATIONAL,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "Same as bb_defend_too_tight: cannot isolate pure raise-call "
                "frequency from BB VPIP."
            ),
            suggested_fix=(
                "Remove dominated off-suit hands (K5o, Q4o, J3o) from BB call "
                "range.  Focus on hands with good playability OOP: suited gappers, "
                "pairs, suited broadways.  Shift some flat-calls to 3-bets."
            ),
        )

    # ── Postflop rules ────────────────────────────────────────────────────────

    def _wtsd_too_high(self, stats: PlayerStats) -> Leak | None:
        wtsd = stats.wtsd
        n = wtsd.n or 0
        value = wtsd.value
        conf = _confidence(n, _WTSD_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.40"):
            return None

        severity = Severity.HIGH if value > Decimal("0.50") else Severity.MEDIUM
        return Leak(
            leak_id="wtsd_too_high",
            category=Category.POSTFLOP,
            title="Went-to-showdown rate too high (showdown-bound)",
            explanation=(
                f"Going to showdown {_pct(value)} of flop-seen hands strongly "
                "suggests a showdown-bound style: calling bets on multiple streets "
                "with marginal made hands.  Opponents exploit this by triple-barrelling "
                "with air on scare-card turns and rivers."
            ),
            evidence=(f"WTSD={_pct(value)} over {n} flop-seen hands (baseline: 28–38%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "WTSD is aggregated across all board textures, positions, and "
                "stack depths.  A slightly elevated WTSD can be correct heads-up "
                "or on very dry boards.  The pattern is meaningful in aggregate "
                "but cannot pinpoint the exact street where you over-call."
            ),
            suggested_fix=(
                "Introduce disciplined turn and river fold decisions.  Middle "
                "pair with a weak kicker facing two streets of aggression on "
                "wet boards is usually a fold.  Build a mental model: "
                '"what worse hands bet all three streets here?"'
            ),
        )

    def _wtsd_too_low(self, stats: PlayerStats) -> Leak | None:
        wtsd = stats.wtsd
        n = wtsd.n or 0
        value = wtsd.value
        conf = _confidence(n, _WTSD_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.22"):
            return None

        return Leak(
            leak_id="wtsd_too_low",
            category=Category.POSTFLOP,
            title="Went-to-showdown rate too low (over-folding postflop)",
            explanation=(
                f"Reaching showdown only {_pct(value)} of the time after seeing "
                "the flop suggests folding too often to postflop aggression.  "
                "Exploitative players will frequently barrel and win pots they "
                "should have lost."
            ),
            evidence=(f"WTSD={_pct(value)} over {n} flop-seen hands (baseline: 28–38%)"),
            confidence=conf,
            severity=Severity.MEDIUM,
            frequency=Frequency.COMMON,
            priority=_compute_priority(Severity.MEDIUM, conf),
            sample_size=n,
            limitations=(
                "A low WTSD can be correct when playing against very tight value "
                "ranges or short-stacked opponents.  Combined with high WSD it "
                "may indicate efficient hand selection rather than a leak."
            ),
            suggested_fix=(
                "Identify turn decisions where you fold medium-strength hands "
                "(top pair weak kicker, second pair) to a single bet on blank "
                "turns.  Build a bluff-catching range that reaches the river."
            ),
        )

    def _wsd_suspiciously_low(self, stats: PlayerStats) -> Leak | None:
        wsd = stats.wsd
        wtsd = stats.wtsd
        n = wsd.n or 0
        value = wsd.value
        wtsd_val = wtsd.value
        conf = _confidence(n, _WSD_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.42"):
            return None
        # If WTSD itself is very low, showdown sample is tiny — don't fire
        if wtsd_val is not None and wtsd_val < Decimal("0.12"):
            return None

        severity = Severity.HIGH if value < Decimal("0.30") else Severity.MEDIUM
        return Leak(
            leak_id="wsd_suspiciously_low",
            category=Category.POSTFLOP,
            title="Win-at-showdown rate suspiciously low",
            explanation=(
                f"Winning only {_pct(value)} of showdowns indicates either "
                "calling too wide on later streets with hands that rarely win, "
                "or poor hand-reading leading to bad bluff-catch decisions.  "
                "Both translate into consistent losses at and around showdown."
            ),
            evidence=(f"WSD={_pct(value)} over {n} showdowns (baseline: 46–56%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.SITUATIONAL,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "WSD is strongly influenced by opponent tendencies.  A low WSD "
                "can be correct if you are bluff-catching correctly (opponents "
                "bluff more than average) but your EV is still positive.  "
                "This metric cannot confirm EV without net-chip data."
            ),
            suggested_fix=(
                "Review river call-down decisions: are you calling bets with "
                "hands that lose to nearly every value combo in their range?  "
                "Consider blockers when deciding whether to call — does your "
                "hand block their likely bluffs?"
            ),
        )

    # ── Postflop c-bet / fold-to-bet / aggression rules ──────────────────────

    def _cbet_too_high(self, stats: PlayerStats) -> Leak | None:
        cbet = stats.cbet_pct
        n = cbet.n or 0
        value = cbet.value
        conf = _confidence(n, _CBET_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.75"):
            return None

        severity = Severity.HIGH if value > Decimal("0.88") else Severity.MEDIUM
        return Leak(
            leak_id="cbet_too_high",
            category=Category.POSTFLOP,
            title="C-bet frequency too high (over-barrelling the flop)",
            explanation=(
                f"C-betting {_pct(value)} of flop-seen hands as the preflop aggressor "
                "is exploitably high.  Opponents can counter-exploit by float-calling "
                "the flop and then either floating the turn or raising.  A high c-bet "
                "rate also makes your range transparent: any check is a likely give-up."
            ),
            evidence=(f"Flop c-bet={_pct(value)} over {n} c-bet opportunities (baseline: 45–70%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "C-bet frequency conflates heads-up and multiway pots.  A high "
                "rate is more exploitable multiway; heads-up it can still be "
                "profitable on dry boards.  Board texture and opponent tendencies "
                "are unknown — some opponents never float, making high c-bet fine."
            ),
            suggested_fix=(
                "Build a check-back range on the flop when you are the preflop "
                "raiser: include strong hands (to protect your checking range) and "
                "pure air (to deny opponents easy decisions).  Target 50–65% on "
                "connected boards, up to 70% on dry ace-high boards heads-up."
            ),
        )

    def _cbet_too_low(self, stats: PlayerStats) -> Leak | None:
        cbet = stats.cbet_pct
        n = cbet.n or 0
        value = cbet.value
        conf = _confidence(n, _CBET_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value >= Decimal("0.38"):
            return None

        severity = Severity.HIGH if value < Decimal("0.22") else Severity.MEDIUM
        return Leak(
            leak_id="cbet_too_low",
            category=Category.POSTFLOP,
            title="C-bet frequency too low (giving up the flop too often)",
            explanation=(
                f"C-betting only {_pct(value)} of flop-seen hands as the preflop "
                "aggressor surrenders initiative and lets opponents realise their "
                "equity cheaply.  Opponents who know you rarely c-bet will float "
                "wide preflop and take the pot away on the flop."
            ),
            evidence=(f"Flop c-bet={_pct(value)} over {n} c-bet opportunities (baseline: 45–70%)"),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "A low overall c-bet rate can be appropriate in multiway pots or "
                "against players who raise their draws aggressively.  Without "
                "positional and stack-depth breakdowns, some check-backs may be "
                "strategically correct rather than passive."
            ),
            suggested_fix=(
                "Identify boards that connect well with your preflop raising "
                "range (ace-high, paired, dry) and c-bet them at a higher "
                "frequency.  As a starting point, aim for ≥50% overall and "
                "target 65–75% on ace-high dry boards where your range has "
                "significant equity advantage."
            ),
        )

    def _fold_to_flop_bet_too_high(self, stats: PlayerStats) -> Leak | None:
        ftfb = stats.fold_to_flop_bet
        n = ftfb.n or 0
        value = ftfb.value
        conf = _confidence(n, _FOLD_FLOP_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.60"):
            return None

        severity = Severity.HIGH if value > Decimal("0.75") else Severity.MEDIUM
        return Leak(
            leak_id="fold_to_flop_bet_too_high",
            category=Category.POSTFLOP,
            title="Folding too often to flop bets (over-folding postflop)",
            explanation=(
                f"Folding to flop bets {_pct(value)} of the time is exploitable: "
                "any opponent who identifies this pattern can profitably bet any two "
                "cards on the flop against you.  Standard pot-odds theory suggests "
                "defending the flop significantly more often."
            ),
            evidence=(
                f"Fold-to-flop-bet={_pct(value)} over {n} flop-bet-facing situations "
                "(baseline: 35–55%)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "This metric captures all flop bets regardless of whether the "
                "bettor was the preflop aggressor.  A probe bet, a donk bet, and a "
                "c-bet all count equally.  The metric cannot separate position, "
                "board texture, or stack depth — all of which affect correct fold "
                "frequency materially."
            ),
            suggested_fix=(
                "Build a flop calling range with hands that have equity plus "
                "implied odds: second pair with a draw, gut-shots, backdoor flush "
                "draws.  At 30bb+ effective, most flop bets should be called or "
                "raised rather than folded when you hold any piece of the board."
            ),
        )

    def _fold_to_turn_bet_too_high(self, stats: PlayerStats) -> Leak | None:
        fttb = stats.fold_to_turn_bet
        n = fttb.n or 0
        value = fttb.value
        conf = _confidence(n, _FOLD_TURN_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        if value <= Decimal("0.65"):
            return None

        severity = Severity.HIGH if value > Decimal("0.80") else Severity.MEDIUM
        return Leak(
            leak_id="fold_to_turn_bet_too_high",
            category=Category.POSTFLOP,
            title="Folding too often to turn bets (over-folding on the turn)",
            explanation=(
                f"Folding to turn bets {_pct(value)} of the time gives opponents "
                "a highly profitable double-barrel line.  When opponents know this "
                "pattern, they can fire a second bullet with any two cards and show "
                "an immediate profit — they do not need to have equity."
            ),
            evidence=(
                f"Fold-to-turn-bet={_pct(value)} over {n} turn-bet-facing situations "
                "(baseline: 40–60%)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.SITUATIONAL,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "This metric does not separate hands where folding is clearly "
                "correct (pure air on a paired board) from situations where a call "
                "or raise is mandatory.  Stack depth matters: short-stacked players "
                "correctly fold more on the turn to preserve tournament equity."
            ),
            suggested_fix=(
                "Identify turn decisions where you have a one-pair hand or better "
                "with pot odds better than 2:1 and are folding anyway.  On blank "
                "turns where your hand has not deteriorated, you need to call more.  "
                "Consider raising with two-pair+ to deny equity and simplify the river."
            ),
        )

    def _too_passive_postflop(self, stats: PlayerStats) -> Leak | None:
        af = stats.aggression_factor
        n = af.n or 0
        value = af.value
        conf = _confidence(n, _AF_N)
        if conf is Confidence.INSUFFICIENT or value is None:
            return None
        # Aggression factor < 1.0 means more calls than bets+raises postflop
        if value >= Decimal("1.0"):
            return None

        severity = Severity.HIGH if value < Decimal("0.50") else Severity.MEDIUM
        return Leak(
            leak_id="too_passive_postflop",
            category=Category.POSTFLOP,
            title="Too passive postflop (aggression factor too low)",
            explanation=(
                f"An aggression factor of {value:.2f} (postflop bets+raises / calls) "
                "indicates a calling-dominant postflop style.  Passive play allows "
                "opponents to control pot size, realise their equity cheaply, and "
                "take free cards on scare streets.  It also signals an exploitable "
                "range: if you rarely raise, opponents can value-bet thin indefinitely."
            ),
            evidence=(
                f"Aggression factor={value:.2f} over {n} postflop call situations "
                "(baseline: 1.5–3.5 for winning players)"
            ),
            confidence=conf,
            severity=severity,
            frequency=Frequency.COMMON,
            priority=_compute_priority(severity, conf),
            sample_size=n,
            limitations=(
                "Aggression factor is an aggregate across all board textures, "
                "positions, stack depths, and opponent types.  Calling more than "
                "betting can be correct as a single session adjustment vs. very "
                "aggressive players.  Without position breakdown, a low AF from "
                "the BB (where passive defence is often correct) will drag the "
                "aggregate down without indicating a systematic error."
            ),
            suggested_fix=(
                "Identify spots where you are flat-calling with strong made hands "
                "that should be raising for value (sets, two pair, overpairs on "
                "wet boards).  Replace one call in three with a raise when you "
                "have a hand that wants to build the pot.  On the flop as the "
                "preflop aggressor, prefer betting over checking even with marginal "
                "equity to maintain initiative."
            ),
        )


# ── Analysis note helper ──────────────────────────────────────────────────────


def analysis_note(hand_count: int, leak_count: int) -> str:
    """
    Return a human-readable note about the reliability of the analysis.

    Exposed separately so callers can include it in API responses.
    """
    if hand_count == 0:
        return "No hands available — leak analysis cannot be performed."
    if hand_count < 20:
        return (
            f"Only {hand_count} hands available.  Most stats will have "
            "'insufficient_data' confidence; shown leaks are directional only."
        )
    if hand_count < 100:
        return (
            f"{hand_count} hands available.  Low-confidence leaks may not "
            "generalise — treat them as hypotheses to investigate."
        )
    if leak_count == 0:
        return (
            f"{hand_count} hands analysed.  No statistically supported leaks "
            "detected in the current sample."
        )
    return f"{hand_count} hands analysed.  {leak_count} leak(s) detected."
