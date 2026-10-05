"""
Per-tournament summaries and a phase breakdown by blind level.

Pure functions — no DB, no IO.  Input: HandRecord with tournament_id /
blind_level / net_bb / busted set, in chronological order.

What is NOT here, on purpose: bubble / ITM / final-table stages.  ClubGG
exports carry neither players remaining nor the payout structure, so those
stages can't be detected from hand histories.  Phases are blind-level bands,
a rough proxy for "how deep into the tournament": level numbering differs
between structures (turbo vs. regular), so treat them as approximate.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.features.labels import LabeledMetric
from app.features.player_stats import HandRecord, compute_player_stats
from app.features.results import ResultRate, bb_per_100_rate

PHASES: list[tuple[str, int, int | None]] = [
    ("Early (levels 1–6)", 1, 6),
    ("Middle (levels 7–12)", 7, 12),
    ("Late (level 13+)", 13, None),
]

# Whole-word tokens in tournament names → format hint.
_FORMAT_TOKENS: list[tuple[str, re.Pattern[str]]] = [
    ("bounty", re.compile(r"\b(?:PKO|KO|BOUNTY|KNOCKOUT)\b", re.IGNORECASE)),
    ("satellite", re.compile(r"\b(?:SAT|SATELLITE|STEP)\b", re.IGNORECASE)),
    ("re-entry", re.compile(r"\b(?:RE|RE-ENTRY|REENTRY)\b", re.IGNORECASE)),
]


@dataclass(frozen=True)
class TournamentSummary:
    tournament_id: str
    name: str | None
    format_hint: str | None  # inferred from the name only; None = no clue
    hands: int
    first_level: int | None
    last_level: int | None
    entries: int  # 1 + busts followed by more hands (re-entries)
    busts: int
    ended_busted: bool  # last recorded hand was a bust
    total_bb: Decimal


@dataclass(frozen=True)
class PhaseRow:
    label: str
    hands: int
    total_bb: Decimal
    bb_per_100: ResultRate
    vpip: LabeledMetric[Decimal | None]
    pfr: LabeledMetric[Decimal | None]
    three_bet_pct: LabeledMetric[Decimal | None]


@dataclass(frozen=True)
class TournamentBreakdown:
    tournaments: list[TournamentSummary]  # newest first
    phases: list[PhaseRow]
    hands_without_tournament: int


def format_hint(name: str | None) -> str | None:
    """Guess the format from whole-word tokens in the name (INFERRED, may be wrong)."""
    if not name:
        return None
    for hint, pattern in _FORMAT_TOKENS:
        if pattern.search(name):
            return hint
    return None


def _summary(tid: str, hands: list[HandRecord]) -> TournamentSummary:
    levels = [h.blind_level for h in hands if h.blind_level is not None]
    busts = sum(1 for h in hands if h.busted)
    ended_busted = hands[-1].busted
    name = next((h.tournament_name for h in hands if h.tournament_name), None)
    return TournamentSummary(
        tournament_id=tid,
        name=name,
        format_hint=format_hint(name),
        hands=len(hands),
        first_level=levels[0] if levels else None,
        last_level=levels[-1] if levels else None,
        entries=1 + busts - (1 if ended_busted else 0),
        busts=busts,
        ended_busted=ended_busted,
        total_bb=sum((h.net_bb for h in hands if h.net_bb is not None), Decimal("0")).quantize(
            Decimal("0.1")
        ),
    )


def _phase(player_id: uuid.UUID, label: str, hands: list[HandRecord]) -> PhaseRow:
    nets = [h.net_bb for h in hands if h.net_bb is not None]
    stats = compute_player_stats(player_id=player_id, hands=hands)
    return PhaseRow(
        label=label,
        hands=len(hands),
        total_bb=sum(nets, Decimal("0")).quantize(Decimal("0.1")),
        bb_per_100=bb_per_100_rate(nets),
        vpip=stats.vpip,
        pfr=stats.pfr,
        three_bet_pct=stats.three_bet_pct,
    )


def compute_tournaments(
    player_id: uuid.UUID, records: Sequence[HandRecord]
) -> TournamentBreakdown:
    by_tid: dict[str, list[HandRecord]] = {}
    for r in records:
        if r.tournament_id:
            by_tid.setdefault(r.tournament_id, []).append(r)

    # dict preserves first-seen order = chronological; newest tournament first.
    tournaments = [_summary(tid, hands) for tid, hands in by_tid.items()][::-1]

    phases = []
    for label, lo, hi in PHASES:
        band = [
            r
            for r in records
            if r.blind_level is not None and r.blind_level >= lo and (hi is None or r.blind_level <= hi)
        ]
        if band:
            phases.append(_phase(player_id, label, band))

    return TournamentBreakdown(
        tournaments=tournaments,
        phases=phases,
        hands_without_tournament=sum(1 for r in records if not r.tournament_id),
    )
