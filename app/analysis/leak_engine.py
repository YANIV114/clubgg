"""
Leak detection engine.

Pure functions — no DB, no IO. Takes PlayerStats (and optionally the raw
HandRecord sequence) and returns a list of Leak instances.

Leak taxonomy (detection priority order)
-----------------------------------------
1. preflop frequency — VPIP/PFR gap, 3bet%, fold-to-3bet
2. postflop tendencies — WTSD, WSD
3. positional — same stats broken out by position

Confidence rules (applied to every detector)
---------------------------------------------
  n = 0            → detector returns None (never emit)
  n = 1–4          → SPECULATIVE; severity capped at "major"
  n = 5–19         → INFERRED with low confidence_note
  n ≥ 20           → INFERRED, is_reliable() = True
  frequency field  → always INFERRED, never DERIVED

Severity thresholds
--------------------
  critical — gap / rate is so large it dominates EV loss at any stake
  major    — clearly exploitable; significant EV loss per session
  minor    — slight leak; context-dependent

Usage
-----
    stats = compute_player_stats(player_id=pid, hands=records)
    leaks = run_leak_detection(stats, hands=records)
    for leak in leaks:
        if leak.confidence != MetricLabel.SPECULATIVE or show_speculative:
            print(leak.name, leak.severity, leak.frequency)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Sequence

from app.features.labels import LabeledMetric, MetricLabel, inferred, speculative
from app.features.player_stats import HandRecord, PlayerStats

# ---------------------------------------------------------------------------
# Thresholds — separated so callers can override in tests
# ---------------------------------------------------------------------------

# VPIP − PFR gap: difference at which passive calling becomes a structural leak
_VPIP_PFR_GAP_MAJOR: Decimal = Decimal("0.15")
_VPIP_PFR_GAP_CRITICAL: Decimal = Decimal("0.25")

# 3bet%: below this is under-aggression in a modern 6-max game
_THREE_BET_LOW_MINOR: Decimal = Decimal("0.07")
_THREE_BET_LOW_MAJOR: Decimal = Decimal("0.04")

# Fold-to-3bet: above this is over-folding (optimal defender folds ~50-60%)
_FOLD_TO_3BET_MAJOR: Decimal = Decimal("0.60")
_FOLD_TO_3BET_CRITICAL: Decimal = Decimal("0.75")

# WTSD: below this is over-folding postflop (typical: 25–32%)
_WTSD_LOW_MINOR: Decimal = Decimal("0.24")
_WTSD_LOW_MAJOR: Decimal = Decimal("0.20")


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Leak:
    """
    A detected strategic leak.

    All fields are required. Callers should check ``confidence`` before
    displaying: SPECULATIVE findings should only surface in verbose reports.

    Fields
    ------
    name:
        Kebab-case identifier. Unique within a single run.
    description:
        What the player is doing wrong and why it costs chips.
    evidence:
        Specific hand IDs and/or stat lines substantiating the finding.
        Never vague summaries — include numbers.
    confidence:
        INFERRED or SPECULATIVE. OBSERVED/DERIVED are not used for leaks
        because leaks are always pattern-based inferences from a sample.
    severity:
        "critical" | "major" | "minor". SPECULATIVE leaks are capped at "major".
    frequency:
        Rate at which the leak manifests. Always INFERRED. n = denominator.
    limitations:
        Why this finding might be wrong or overstated.
    suggested_fix:
        Position + stack depth + specific action. No generic advice.
    """

    name: str
    description: str
    evidence: list[str]
    confidence: MetricLabel
    severity: Literal["critical", "major", "minor"]
    frequency: LabeledMetric[Decimal | None]
    limitations: str
    suggested_fix: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_leak_detection(
    stats: PlayerStats,
    hands: Sequence[HandRecord] | None = None,
) -> list[Leak]:
    """
    Detect strategic leaks from aggregate player statistics.

    Parameters
    ----------
    stats:
        Aggregate player stats from ``compute_player_stats()``.
    hands:
        Optional raw hand records — used to extract specific hand IDs as
        evidence for leaks. When omitted, evidence is stat-based only.

    Returns
    -------
    List of detected Leak instances, ordered by severity (critical first),
    then by confidence (INFERRED before SPECULATIVE).
    Empty list when no thresholds are crossed or all denominators are zero.
    """
    _hands = list(hands) if hands is not None else []
    detectors = [
        _detect_vpip_pfr_gap,
        _detect_low_3bet,
        _detect_overfold_to_3bet,
        _detect_low_wtsd,
        _detect_positional_overfold_to_3bet,
        _detect_positional_low_3bet,
    ]
    results: list[Leak] = []
    for detect in detectors:
        leak = detect(stats, _hands)
        if leak is not None:
            results.append(leak)

    # Sort: critical > major > minor, then INFERRED before SPECULATIVE
    _sev_order = {"critical": 0, "major": 1, "minor": 2}
    _conf_order = {MetricLabel.INFERRED: 0, MetricLabel.SPECULATIVE: 1}
    results.sort(
        key=lambda lk: (
            _sev_order.get(lk.severity, 9),
            _conf_order.get(lk.confidence, 9),
        )
    )
    return results


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def _detect_vpip_pfr_gap(
    stats: PlayerStats, hands: list[HandRecord]
) -> Leak | None:
    """
    Passive preflop: player calls frequently but rarely raises.

    A large VPIP−PFR gap means the player is entering pots with a calling
    range rather than a raising range. Calling ranges are harder to play
    postflop and give up initiative. Gap > 15 pp is exploitable; > 25 pp
    is a critical structural leak.
    """
    vpip = stats.vpip
    pfr = stats.pfr

    # Need at least one reliable stat to compute gap
    if vpip.value is None or pfr.value is None:
        return None
    n = stats.hand_count
    if n == 0:
        return None

    gap = vpip.value - pfr.value
    if gap < _VPIP_PFR_GAP_MAJOR:
        return None

    confidence, conf_note = _confidence_for_n(n)
    raw_sev: Literal["critical", "major", "minor"] = (
        "critical" if gap >= _VPIP_PFR_GAP_CRITICAL else "major"
    )
    severity = _cap_severity(raw_sev, confidence)

    evidence = [
        f"VPIP={vpip.value:.1%} PFR={pfr.value:.1%} gap={gap:.1%} over {n} hands",
        f"vpip_source: {vpip.source}",
        f"pfr_source: {pfr.source}",
    ]
    # Attach hand IDs where player called but did not raise preflop
    call_no_raise = [h.hand_external_id for h in hands if h.vpip and not h.pfr]
    if call_no_raise:
        sample = call_no_raise[:5]
        evidence.append(f"Sample call-not-raise hand IDs: {', '.join(sample)}")

    freq = inferred(
        gap,
        source=f"(VPIP={vpip.value:.1%}) - (PFR={pfr.value:.1%}) over {n} hands",
        n=n,
        confidence_note=conf_note,
    )

    return Leak(
        name="vpip-pfr-gap",
        description=(
            f"Player is calling preflop {gap:.0%} more often than raising. "
            "Passive ranges are hard to play postflop and surrender initiative."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=freq,
        limitations=(
            "VPIP−PFR gap is acceptable in loose passive games where overcalling "
            "is exploitative. Position not accounted for in this overall stat."
        ),
        suggested_fix=(
            "From BTN/CO/HJ with VPIP > 25%: replace flat-calls with 3x raises "
            "or folds. From blinds: defend with a tighter continue range and "
            "increase check-raise frequency on favorable flop textures."
        ),
    )


def _detect_low_3bet(
    stats: PlayerStats, hands: list[HandRecord]
) -> Leak | None:
    """
    Under-3betting: player rarely re-raises when facing an open.

    3bet% below 7% in a modern 6-max game leaves value on the table: opponents
    can open wide with minimal risk of re-raise pressure.
    """
    tbt = stats.three_bet_pct
    if tbt.value is None or tbt.n is None or tbt.n == 0:
        return None

    if tbt.value >= _THREE_BET_LOW_MINOR:
        return None

    confidence, conf_note = _confidence_for_n(tbt.n)
    raw_sev: Literal["critical", "major", "minor"] = (
        "major" if tbt.value < _THREE_BET_LOW_MAJOR else "minor"
    )
    severity = _cap_severity(raw_sev, confidence)

    evidence = [
        f"3bet%={tbt.value:.1%} over {tbt.n} facing-open situations",
        f"source: {tbt.source}",
    ]
    three_bet_hands = [h.hand_external_id for h in hands if h.three_bet]
    if three_bet_hands:
        evidence.append(f"3bet hand IDs (first 5): {', '.join(three_bet_hands[:5])}")

    freq = inferred(
        tbt.value,
        source=tbt.source,
        n=tbt.n,
        confidence_note=conf_note,
    )

    return Leak(
        name="low-3bet-frequency",
        description=(
            f"Player 3bets only {tbt.value:.1%} of eligible spots. "
            "Opponents can open wide without fear of re-raise pressure."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=freq,
        limitations=(
            "Optimal 3bet frequency depends on opponent open frequency and "
            "position. A low overall rate can be correct against very tight openers."
        ),
        suggested_fix=(
            "From BTN facing CO/HJ opens: construct a 3bet range of strong hands "
            "(QQ+/AK for value) and bluffs (A2s-A5s, K5s-K9s suited). "
            "Target 3bet% of 8–12% from BTN, 5–8% from blinds."
        ),
    )


def _detect_overfold_to_3bet(
    stats: PlayerStats, hands: list[HandRecord]
) -> Leak | None:
    """
    Over-folding to 3bets: player folds too often after opening and facing a 3bet.

    Optimal defender should continue ~40–50% vs a balanced 3bet range.
    Folding more than 60% is exploitable; > 75% is critical.
    """
    f3b = stats.fold_to_3bet
    if f3b.value is None or f3b.n is None or f3b.n == 0:
        return None

    if f3b.value < _FOLD_TO_3BET_MAJOR:
        return None

    confidence, conf_note = _confidence_for_n(f3b.n)
    raw_sev: Literal["critical", "major", "minor"] = (
        "critical" if f3b.value >= _FOLD_TO_3BET_CRITICAL else "major"
    )
    severity = _cap_severity(raw_sev, confidence)

    evidence = [
        f"fold-to-3bet={f3b.value:.1%} over {f3b.n} faced-3bet situations",
        f"source: {f3b.source}",
    ]
    fold_hand_ids = [h.hand_external_id for h in hands if h.folded_to_3bet]
    if fold_hand_ids:
        evidence.append(f"Sample fold-to-3bet hand IDs: {', '.join(fold_hand_ids[:5])}")

    freq = inferred(
        f3b.value,
        source=f3b.source,
        n=f3b.n,
        confidence_note=conf_note,
    )

    return Leak(
        name="overfold-to-3bet",
        description=(
            f"Player folds to 3bets {f3b.value:.1%} of the time after opening. "
            "This makes any 3bet immediately profitable for opponents."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=freq,
        limitations=(
            "Fold-to-3bet rate is position-blind. Folding > 60% from EP is "
            "defensible; from BTN/CO it is a clear leak. Positional breakdown "
            "in the positional detector is more precise."
        ),
        suggested_fix=(
            "Defend open-raises from BTN/CO with 4bets or calls; target ~45% "
            "continue rate. Widen 4bet bluff range with hands like A5s, KQo. "
            "From EP vs BTN 3bet, tighten opening range to reduce situations."
        ),
    )


def _detect_low_wtsd(
    stats: PlayerStats, hands: list[HandRecord]
) -> Leak | None:
    """
    Over-folding postflop: player rarely reaches showdown relative to flop-seeing rate.

    WTSD < 24% suggests systematic postflop capitulation — giving up too often
    on made hands or draws under pressure.
    """
    wtsd = stats.wtsd
    if wtsd.value is None or wtsd.n is None or wtsd.n == 0:
        return None

    if wtsd.value >= _WTSD_LOW_MINOR:
        return None

    confidence, conf_note = _confidence_for_n(wtsd.n)
    raw_sev: Literal["critical", "major", "minor"] = (
        "major" if wtsd.value < _WTSD_LOW_MAJOR else "minor"
    )
    severity = _cap_severity(raw_sev, confidence)

    evidence = [
        f"WTSD={wtsd.value:.1%} over {wtsd.n} flop-seeing situations",
        f"source: {wtsd.source}",
    ]

    freq = inferred(
        wtsd.value,
        source=wtsd.source,
        n=wtsd.n,
        confidence_note=conf_note,
    )

    return Leak(
        name="low-wtsd",
        description=(
            f"Player reaches showdown only {wtsd.value:.1%} of flop-seeing hands. "
            "Typical 6-max range is 25–32%. Frequent folding to postflop bets "
            "makes bluffs immediately profitable."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=freq,
        limitations=(
            "Low WTSD can be correct with a tight range or against specific "
            "opponents who never bluff. Check WSD: if WSD > 58%, low WTSD may "
            "just reflect good hand selection, not a leak."
        ),
        suggested_fix=(
            "On wet flop textures with top pair or better: call down two "
            "streets vs moderate sizing. Float in position more with air "
            "to balance against bluffing. Review fold equity assumptions."
        ),
    )


def _detect_positional_overfold_to_3bet(
    stats: PlayerStats, hands: list[HandRecord]
) -> Leak | None:
    """
    Position-specific over-folding to 3bets from BTN or CO.

    From these positions, a fold-to-3bet > 65% is particularly exploitable
    since BTN/CO opens wide and should continue often vs 3bets.
    """
    _THRESHOLD = Decimal("0.65")
    worst_pos: str | None = None
    worst_rate: Decimal = _THRESHOLD
    worst_n: int = 0

    for pos in ("BTN", "CO"):
        pos_stats = stats.positional.get(pos)
        if pos_stats is None:
            continue
        f3b = pos_stats.fold_to_3bet
        if f3b.value is None or f3b.n is None or f3b.n == 0:
            continue
        if f3b.value > worst_rate:
            worst_rate = f3b.value
            worst_pos = pos
            worst_n = f3b.n

    if worst_pos is None:
        return None

    confidence, conf_note = _confidence_for_n(worst_n)
    severity = _cap_severity("major", confidence)

    evidence = [
        f"fold-to-3bet from {worst_pos}={worst_rate:.1%} over {worst_n} situations",
    ]
    fold_hand_ids = [
        h.hand_external_id
        for h in hands
        if h.folded_to_3bet and h.position == worst_pos
    ]
    if fold_hand_ids:
        evidence.append(
            f"Sample {worst_pos} fold-to-3bet hand IDs: {', '.join(fold_hand_ids[:5])}"
        )

    freq = inferred(
        worst_rate,
        source=f"fold-to-3bet from {worst_pos} (n={worst_n})",
        n=worst_n,
        confidence_note=conf_note,
    )

    return Leak(
        name=f"overfold-to-3bet-{worst_pos.lower()}",
        description=(
            f"From {worst_pos}, player folds to 3bets {worst_rate:.1%} of the time. "
            f"{worst_pos} opens wide by design; folding this often abandons all "
            "range advantage and makes the position's opens unprofitable."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=freq,
        limitations=(
            f"Sample size from {worst_pos} may be small. Fold rate depends on "
            "opponent 3bet sizing and range. Large 3bets justify tighter continues."
        ),
        suggested_fix=(
            f"From {worst_pos} with 20+ BB: target ~50% continue rate vs 3bets "
            "by adding 4bet bluffs (A5s, KQo) and expanding call range (AJs+, "
            "KQs, 77+). Against large 3bets (>12 BB), tighten continues to "
            "strong made hands."
        ),
    )


def _detect_positional_low_3bet(
    stats: PlayerStats, hands: list[HandRecord]
) -> Leak | None:
    """
    Low 3bet frequency from BTN/CO, the two most profitable 3bet positions.

    Detects only the single worst position to avoid duplicate reports.
    """
    _THRESHOLD = Decimal("0.06")
    worst_pos: str | None = None
    worst_rate: Decimal = _THRESHOLD
    worst_n: int = 0

    for pos in ("BTN", "CO"):
        pos_stats = stats.positional.get(pos)
        if pos_stats is None:
            continue
        tbt = pos_stats.three_bet_pct
        if tbt.value is None or tbt.n is None or tbt.n == 0:
            continue
        if tbt.value < worst_rate:
            worst_rate = tbt.value
            worst_pos = pos
            worst_n = tbt.n

    if worst_pos is None:
        return None

    confidence, conf_note = _confidence_for_n(worst_n)
    severity = _cap_severity("minor", confidence)

    evidence = [
        f"3bet% from {worst_pos}={worst_rate:.1%} over {worst_n} facing-open situations",
    ]

    freq = inferred(
        worst_rate,
        source=f"3bet% from {worst_pos} (n={worst_n})",
        n=worst_n,
        confidence_note=conf_note,
    )

    return Leak(
        name=f"low-3bet-{worst_pos.lower()}",
        description=(
            f"Player 3bets only {worst_rate:.1%} from {worst_pos}, the strongest "
            "3bet position. Opponents can open into this player's BTN/CO with "
            "impunity, expecting a flat or fold."
        ),
        evidence=evidence,
        confidence=confidence,
        severity=severity,
        frequency=freq,
        limitations=(
            f"Optimal {worst_pos} 3bet% is opponent-dependent. Against a tight "
            "opener (< 15% RFI), a low 3bet% may be correct. Check opponent's "
            "RFI before acting on this leak."
        ),
        suggested_fix=(
            f"From {worst_pos} vs CO/HJ opens: add A2s–A5s, K9s–KJs, and "
            "suited connectors (76s, 87s) as 3bet bluffs. Merge sizing to "
            "3x the open. Target 8–12% 3bet frequency in this position."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _confidence_for_n(n: int) -> tuple[MetricLabel, str]:
    """Map sample size to confidence label and note."""
    if n < 5:
        return MetricLabel.SPECULATIVE, f"very low — only {n} eligible hand(s)"
    if n < 20:
        return MetricLabel.INFERRED, f"low — only {n} eligible hands (< 20)"
    return MetricLabel.INFERRED, ""


def _cap_severity(
    severity: Literal["critical", "major", "minor"],
    confidence: MetricLabel,
) -> Literal["critical", "major", "minor"]:
    """SPECULATIVE findings are capped at major, never critical."""
    if confidence == MetricLabel.SPECULATIVE and severity == "critical":
        return "major"
    return severity
