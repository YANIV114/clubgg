"""
Leak finder — pattern detection across analyzed hands.

Pure module: no DB, no IO. Takes a list of AnalyzedHandRecord (HandAnalysisResult
paired with hand metadata) and returns a LeakReport with LeakFinding instances.

This module is SEPARATE from leak_engine.py:
- leak_engine.py: aggregate stats (VPIP/PFR/3bet%) → structural leaks from raw hand data
- leak_finder.py: per-hand HandAnalysisResult patterns → behavioral leaks from engine outputs

Confidence tiers
----------------
  sample < 5    → low
  sample 5–14   → medium
  sample ≥ 15   → high

Low-confidence findings are capped at "major" severity (never critical).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from app.analysis.hand_analysis_engine import HandAnalysisResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CRITICAL_MAJOR = frozenset({"major", "critical"})
_PUSH_FOLD_SPOTS = frozenset({"push_fold", "bubble_icm", "final_table_icm"})

# Overfold thresholds
_STEAL_FOLD_THRESHOLD = Decimal("0.65")  # folding > 65% of first-in steal spots
_BB_FOLD_THRESHOLD = Decimal("0.72")  # folding > 72% of BB defense spots
_BUBBLE_FOLD_THRESHOLD = Decimal("0.55")  # folding > 55% of bubble spots with 10–20bb


# ---------------------------------------------------------------------------
# Input type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyzedHandRecord:
    """
    A single hand's analysis result paired with metadata for evidence linking.

    Fields
    ------
    hand_external_id:
        ClubGG external hand ID for linking back to the source hand.
    result:
        HandAnalysisResult from hand_analysis_engine.analyze_hand().
    position:
        Hero's position string ("BTN", "BB", etc.) or None.
    stack_bb:
        Hero's starting stack in big blinds. None if unavailable.
    """

    hand_external_id: str
    result: HandAnalysisResult
    position: str | None = None
    stack_bb: Decimal | None = None


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeakFinding:
    """
    A detected behavioral leak across a sample of analyzed hands.

    Fields
    ------
    leak_id:        Kebab-case identifier, unique within a single report.
    category:       "preflop" | "postflop" | "tournament"
    title:          One-line human-readable title.
    description:    What the player is doing wrong and why it costs chips.
    evidence:       Specific hand IDs with context. At most 5 entries.
    confidence:     "low" | "medium" | "high" (maps to sample size: <5, 5-14, ≥15)
    severity:       "critical" | "major" | "minor". Capped at "major" when confidence="low".
    frequency:      Rate this pattern fires (0.0–1.0), or None if not a rate.
    sample_size:    Denominator for frequency — eligible hands for this detector.
    limitations:    Why this finding might be wrong or overstated.
    suggested_fix:  Concrete, actionable correction with position and stack depth.
    """

    leak_id: str
    category: str
    title: str
    description: str
    evidence: list[str]
    confidence: str
    severity: Literal["critical", "major", "minor"]
    frequency: float | None
    sample_size: int
    limitations: str
    suggested_fix: str


@dataclass(frozen=True)
class LeakReport:
    """
    Aggregated leak findings across a player's analyzed hands.

    Fields
    ------
    player_id:              UUID of the analyzed player.
    leaks:                  Detected LeakFinding instances, sorted by severity then confidence.
    summary:                One-sentence overview of the report.
    total_hands_analyzed:   Count of AnalyzedHandRecord inputs (all hands, including "other").
    sample_size:            Count of hands with a classifiable spot (not "other").
    generated_at:           UTC timestamp of report generation.
    """

    player_id: uuid.UUID
    leaks: list[LeakFinding]
    summary: str
    total_hands_analyzed: int
    sample_size: int
    generated_at: datetime


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_leaks(
    records: list[AnalyzedHandRecord],
    player_id: uuid.UUID,
) -> LeakReport:
    """
    Detect behavioral leaks from per-hand analysis results.

    Parameters
    ----------
    records:
        List of AnalyzedHandRecord — each is a HandAnalysisResult plus metadata.
        Pass all analyzed hands for the player, including "other" spots (they are
        filtered internally).
    player_id:
        UUID of the player being analyzed. Stored in the report for traceability.

    Returns
    -------
    LeakReport with leaks sorted by severity (critical first) then confidence (high first).
    Returns a report with empty leaks list when no thresholds are crossed.
    """
    classifiable = [r for r in records if r.result.spot_type != "other"]

    detectors = [
        _detect_flat_calling_short_stack,
        _detect_missing_pushfold_shove,
        _detect_overfold_steal_position,
        _detect_passive_bb_defense,
        _detect_loose_call_all_in,
        _detect_bubble_overtightness,
        _detect_final_table_passivity,
    ]

    leaks: list[LeakFinding] = []
    for detect in detectors:
        finding = detect(records, classifiable)
        if finding is not None:
            leaks.append(finding)

    _sev_order = {"critical": 0, "major": 1, "minor": 2}
    _conf_order = {"high": 0, "medium": 1, "low": 2}
    leaks.sort(
        key=lambda lk: (
            _sev_order.get(lk.severity, 9),
            _conf_order.get(lk.confidence, 9),
        )
    )

    n_total = len(records)
    n_classifiable = len(classifiable)

    if leaks:
        worst = leaks[0]
        summary = (
            f"Found {len(leaks)} leak{'s' if len(leaks) != 1 else ''} across "
            f"{n_total} analyzed hands. Top issue: {worst.title}."
        )
    else:
        summary = (
            f"No clear leaks detected across {n_total} analyzed hands. Keep building your sample."
        )

    return LeakReport(
        player_id=player_id,
        leaks=leaks,
        summary=summary,
        total_hands_analyzed=n_total,
        sample_size=n_classifiable,
        generated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _detect_flat_calling_short_stack(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Flat-calling at short stack instead of shoving or folding.

    The analysis engine marks calling (non-all-in) in push/fold spots as
    critical (≤10bb) or major (10–15bb). Repeated occurrences are a leak.
    """
    eligible = [r for r in classifiable if r.result.spot_type in _PUSH_FOLD_SPOTS]
    if not eligible:
        return None

    mistakes = [
        r
        for r in eligible
        if r.result.mistake_severity in _CRITICAL_MAJOR and "called" in r.result.hero_action.lower()
    ]
    n = len(eligible)
    n_mistakes = len(mistakes)

    if n_mistakes < 2:
        return None

    rate = n_mistakes / n
    confidence = _confidence_tier(n_mistakes)
    severity = _cap_severity("critical" if n_mistakes >= 5 else "major", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: {r.result.spot_type} — {r.result.hero_action} "
        f"(stack: {r.stack_bb}bb, recommended: {r.result.recommended_action})"
        for r in mistakes[:5]
    ]

    return LeakFinding(
        leak_id="flat-calling-short-stack",
        category="tournament",
        title="Flat-Calling at Short Stack",
        description=(
            f"Called without shoving in {n_mistakes}/{n} short-stack spots. "
            "Flat-calling at ≤15bb sacrifices fold equity — the shove-or-fold "
            "framework dominates in these situations."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(rate, 3),
        sample_size=n,
        limitations=(
            "Calling can be correct when the opponent's all-in was a shove into a caller "
            "rather than an open. Pot odds context (already-committed chips) is not captured here."
        ),
        suggested_fix=(
            "At ≤15bb use a push/fold chart exclusively: shove strong hands, fold the rest. "
            "Flat-calling without intending to commit the stack leaks significant EV."
        ),
    )


def _detect_missing_pushfold_shove(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Min-raising instead of shoving at short stack.

    The engine marks min-raise at ≤10bb as a minor mistake (recommended: shove all-in).
    Detect repeated occurrences.
    """
    eligible = [r for r in classifiable if r.result.spot_type in _PUSH_FOLD_SPOTS]
    if not eligible:
        return None

    mistakes = [
        r
        for r in eligible
        if r.result.mistake_severity == "minor"
        and r.result.recommended_action == "shove all-in"
        and "shoved" not in r.result.hero_action.lower()
        and ("raised" in r.result.hero_action.lower() or "bet" in r.result.hero_action.lower())
    ]
    n = len(eligible)
    n_mistakes = len(mistakes)

    if n_mistakes < 2:
        return None

    rate = n_mistakes / n
    confidence = _confidence_tier(n_mistakes)
    severity = _cap_severity("minor", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: {r.result.spot_type} — {r.result.hero_action} "
        f"({r.stack_bb}bb, should shove all-in)"
        for r in mistakes[:5]
    ]

    return LeakFinding(
        leak_id="missing-pushfold-shove",
        category="tournament",
        title="Min-Raising Instead of Shoving",
        description=(
            f"Min-raised in {n_mistakes}/{n} push/fold spots instead of going all-in. "
            "With ≤10bb, min-raises leak fold equity and expose stack to unfavorable "
            "re-jam/call situations."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(rate, 3),
        sample_size=n,
        limitations=(
            "Min-raises at 8–12bb can occasionally be correct against opponents who "
            "over-fold to any open. Without specific opponent data this is directional only."
        ),
        suggested_fix=(
            "Replace min-raises with all-in shoves at ≤10bb. The shove applies maximum "
            "fold equity and prevents opponents from realizing equity cheaply post-flop."
        ),
    )


def _detect_overfold_steal_position(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Over-folding in steal positions (BTN/CO/SB) when first-in.

    A high fold rate in steal spots indicates the player is leaving unclaimed
    pots and surrendering their positional advantage.
    """
    eligible = [r for r in classifiable if r.result.spot_type == "steal"]

    if len(eligible) < 5:
        return None

    folds = [r for r in eligible if "folded" in r.result.hero_action.lower()]
    n = len(eligible)
    n_folds = len(folds)

    if n_folds == 0:
        return None

    rate = Decimal(n_folds) / Decimal(n)
    if rate < _STEAL_FOLD_THRESHOLD:
        return None

    confidence = _confidence_tier(n)
    severity = _cap_severity("minor", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: {r.result.spot_type} — {r.result.hero_action} "
        f"({r.position or 'unknown'}, {r.stack_bb}bb)"
        for r in folds[:5]
    ]

    pos_note = _position_breakdown(eligible, folds)
    if pos_note:
        evidence.insert(0, f"Position breakdown (folds/total): {pos_note}")

    return LeakFinding(
        leak_id="overfold-steal-position",
        category="preflop",
        title="Over-Folding in Steal Positions",
        description=(
            f"Folded {n_folds}/{n} ({float(rate):.0%}) first-in opportunities from BTN/CO/SB. "
            "A high fold rate here surrenders unclaimed blinds and reduces positional edge."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(float(rate), 3),
        sample_size=n,
        limitations=(
            "Fold rate in steal spots is hand-strength dependent. Without hole cards, "
            "this is directional only. Folding from SB is more often correct due to "
            "out-of-position disadvantage post-flop."
        ),
        suggested_fix=(
            "From BTN first-in: open-raise with the top 50–60% of hands. From CO: 40–45%. "
            "From SB vs empty pot: 35–40% is a reasonable starting baseline. "
            "Suited connectors, small pairs, and suited broadways should nearly always open."
        ),
    )


def _detect_passive_bb_defense(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Over-folding in BB defense spots.

    A very high fold rate in BB defense spots makes any steal attempt
    immediately profitable, leaking chips every orbit.
    """
    eligible = [r for r in classifiable if r.result.spot_type == "defend_bb"]

    if len(eligible) < 5:
        return None

    folds = [r for r in eligible if "folded" in r.result.hero_action.lower()]
    n = len(eligible)
    n_folds = len(folds)

    if n_folds == 0:
        return None

    rate = Decimal(n_folds) / Decimal(n)
    if rate < _BB_FOLD_THRESHOLD:
        return None

    confidence = _confidence_tier(n)
    severity = _cap_severity("major", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: BB defense — {r.result.hero_action} ({r.stack_bb}bb)"
        for r in folds[:5]
    ]

    return LeakFinding(
        leak_id="passive-bb-defense",
        category="preflop",
        title="Passive BB Defense (Over-Folding)",
        description=(
            f"Folded {n_folds}/{n} ({float(rate):.0%}) BB defense opportunities. "
            "This makes any steal from BTN/CO/SB immediately profitable — "
            "opponents can print money by opening wide."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(float(rate), 3),
        sample_size=n,
        limitations=(
            "Optimal BB defense depends on opener position and sizing. "
            "Against large 3x–4x opens from EP, 65%+ fold is defensible. "
            "Pot odds and exact stack depth are not captured here."
        ),
        suggested_fix=(
            "From BB vs BTN open: defend the bottom ~30% of hands at minimum — "
            "suited connectors, small pairs, any ace. "
            "Add 3-bets with A5s–A2s (bluffs) and QQ+/AK (value) to prevent opponents "
            "from exploiting a call-only defending range."
        ),
    )


def _detect_loose_call_all_in(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Calling all-in with hands outside the standard calling range.

    When the engine has range context and the hero's hand is outside the
    Nash/standard call range, this is a chip-EV leak.
    """
    eligible = [r for r in classifiable if r.result.spot_type == "call_all_in"]

    if not eligible:
        return None

    range_evaluated = [r for r in eligible if r.result.hero_range_position not in ("unknown", "")]
    if len(range_evaluated) < 3:
        return None

    outside_range = [
        r
        for r in range_evaluated
        if r.result.hero_range_position == "outside" and "called" in r.result.hero_action.lower()
    ]
    n = len(range_evaluated)
    n_outside = len(outside_range)

    if n_outside < 2:
        return None

    rate = n_outside / n
    confidence = _confidence_tier(n_outside)
    severity = _cap_severity("major", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: call all-in — {r.result.hero_action}, "
        f"hand outside {r.result.range_context}"
        for r in outside_range[:5]
    ]

    return LeakFinding(
        leak_id="loose-call-all-in",
        category="preflop",
        title="Calling All-In with Marginal Hands",
        description=(
            f"Called all-in with hands outside the standard range in {n_outside}/{n} "
            "evaluated spots. Calling too wide vs all-in shoves is a direct chip-EV leak."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(rate, 3),
        sample_size=n,
        limitations=(
            "Range evaluation uses approximate Nash calling ranges, which assume chip-EV. "
            "Some outside-range calls may be ICM-correct or correct against specific "
            "opponent shoving ranges that are wider than Nash equilibrium."
        ),
        suggested_fix=(
            "Use Nash push/fold charts for calling ranges vs short-stack shoves. "
            "At 15bb effective vs BTN shove, the call range is roughly JJ+/AK/AQs. "
            "You can widen slightly vs loose shovers but track results before widening further."
        ),
    )


def _detect_bubble_overtightness(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Over-folding during bubble play with a playable stack (ICM paralysis).

    Folding too often at 10–20bb on the bubble is a common tournament leak.
    ICM pressure is real but should not prevent all aggression at this depth.
    """
    eligible = [r for r in classifiable if r.result.spot_type == "bubble_icm"]

    if len(eligible) < 3:
        return None

    foldable = [
        r
        for r in eligible
        if "folded" in r.result.hero_action.lower()
        and r.stack_bb is not None
        and Decimal("10") < r.stack_bb <= Decimal("20")
    ]
    n = len(eligible)
    n_folds = len(foldable)

    if n_folds < 2:
        return None

    rate = n_folds / n
    if rate < float(_BUBBLE_FOLD_THRESHOLD):
        return None

    confidence = _confidence_tier(n)
    severity = _cap_severity("major", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: bubble — {r.result.hero_action} (stack: {r.stack_bb}bb)"
        for r in foldable[:5]
    ]

    return LeakFinding(
        leak_id="bubble-overtightness",
        category="tournament",
        title="Bubble ICM Paralysis",
        description=(
            f"Folded {n_folds}/{n} ({rate:.0%}) bubble spots with 10–20bb effective stack. "
            "ICM pressure is real, but over-folding at this depth surrenders chip accumulation "
            "and leads to blinding out instead of building a stack."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(rate, 3),
        sample_size=n,
        limitations=(
            "Without knowing the payout structure, ICM pressure cannot be precisely quantified. "
            "Large pay jumps justify tighter play; small pay jumps do not. "
            "Table stack distribution also heavily influences correct bubble strategy."
        ),
        suggested_fix=(
            "On the bubble with 12–20bb, keep shoving from BTN/CO with a wide range. "
            "ICM pressure mainly affects marginal spots, not clear profitable shoves. "
            "A 14bb shove from BTN can still be +EV with 3× ICM chip value applied."
        ),
    )


def _detect_final_table_passivity(
    all_records: list[AnalyzedHandRecord],
    classifiable: list[AnalyzedHandRecord],
) -> LeakFinding | None:
    """
    Repeated critical/major mistakes at the final table.

    Multiple serious errors in final_table_icm spots indicates systematic
    passivity — flat-calling or min-raising when shoving is required.
    """
    eligible = [r for r in classifiable if r.result.spot_type == "final_table_icm"]

    if not eligible:
        return None

    mistakes = [r for r in eligible if r.result.mistake_severity in _CRITICAL_MAJOR]
    n = len(eligible)
    n_mistakes = len(mistakes)

    if n_mistakes < 2:
        return None

    rate = n_mistakes / n
    confidence = _confidence_tier(n_mistakes)
    severity = _cap_severity("major", confidence)

    evidence = [
        f"Hand {r.hand_external_id}: final table — {r.result.hero_action} "
        f"(stack: {r.stack_bb}bb, recommended: {r.result.recommended_action})"
        for r in mistakes[:5]
    ]

    return LeakFinding(
        leak_id="final-table-icm-mistakes",
        category="tournament",
        title="Repeated Final Table Mistakes",
        description=(
            f"Made critical/major mistakes in {n_mistakes}/{n} final table spots. "
            "Systematic errors here — flat-calling or min-raising with a short stack — "
            "cost disproportionate chip equity at the highest-value stage."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=round(rate, 3),
        sample_size=n,
        limitations=(
            "All final table ICM analysis is SPECULATIVE — payout structure is unknown. "
            "Some flagged hands may be ICM-correct plays that deviate from chip-EV optimal. "
            "Stack distributions and pay jump sizes strongly affect correct strategy here."
        ),
        suggested_fix=(
            "Study push/fold charts for 3–6 player final table scenarios specifically. "
            "Practice with ICM-aware solvers (HRC, ICMIZER) using estimated payouts. "
            "When in doubt, prefer shoving over limping or calling at ≤10bb."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _confidence_tier(n: int) -> str:
    if n < 5:
        return "low"
    if n < 15:
        return "medium"
    return "high"


def _cap_severity(
    severity: Literal["critical", "major", "minor"],
    confidence: str,
) -> Literal["critical", "major", "minor"]:
    if confidence == "low" and severity == "critical":
        return "major"
    return severity


def _position_breakdown(
    eligible: list[AnalyzedHandRecord],
    folds: list[AnalyzedHandRecord],
) -> str:
    pos_total: dict[str, int] = {}
    pos_folds: dict[str, int] = {}
    for r in eligible:
        pos = r.position or "?"
        pos_total[pos] = pos_total.get(pos, 0) + 1
    for r in folds:
        pos = r.position or "?"
        pos_folds[pos] = pos_folds.get(pos, 0) + 1

    parts = []
    for pos in ("BTN", "CO", "SB"):
        total = pos_total.get(pos, 0)
        if total > 0:
            fld = pos_folds.get(pos, 0)
            parts.append(f"{pos}: {fld}/{total}")
    return ", ".join(parts) if parts else ""
