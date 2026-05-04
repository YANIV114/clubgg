"""
Tournament prep plan builder.

Pure function — no DB, no IO.  Takes PlayerStats, a pre-ranked list of
detected Leaks, and optional tournament context, and returns a structured
TournamentPlan.

Design contract
---------------
- All output is derived from observed statistics. No poker theory is injected
  unless it connects directly to a detected leak.
- Stage / format guidance is static framing; the concrete study priorities are
  always driven by the player's own data.
- When hand count is too low to support any reliable leaks, the plan says so
  explicitly rather than inventing advice.
- Returns a dataclass (no Pydantic) so the function stays pure and testable
  without FastAPI.

Supported stages  : early | middle | bubble | itm | final_table
Supported formats : CASH | FREEZEOUT | REENTRY | PKO | SATELLITE | SPIN
Unknown values    : silently treated as None (no crash, no fake context).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.features.leaks import Leak
    from app.features.player_stats import PlayerStats

# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

_URGENCY_IMMEDIATE = "immediate"
_URGENCY_THIS_WEEK = "this_week"
_URGENCY_LONG_TERM = "long_term"

_SOURCE_LEAK = "detected_leak"
_SOURCE_STAGE = "stage_specific"
_SOURCE_FORMAT = "format_specific"


@dataclass(frozen=True)
class StudyPriority:
    rank: int
    focus_area: str  # short label e.g. "Flop c-bet frequency"
    action: str  # concrete drill or adjustment, derived from leak or stage
    source: str  # _SOURCE_* constant
    urgency: str  # _URGENCY_* constant
    leak_id: str | None = None


@dataclass(frozen=True)
class TournamentPlan:
    player_id: uuid.UUID
    hand_count: int
    tournament_format: str | None
    stage: str | None
    stack_bb: Decimal | None
    players_remaining: int | None
    reliability_note: str
    stage_guidance: str
    format_note: str  # empty string when format not supplied or CASH
    top_leaks: list[Leak]  # top 3 by priority; may be empty
    study_priorities: list[StudyPriority]


# ---------------------------------------------------------------------------
# Static guidance strings
# ---------------------------------------------------------------------------

_STAGE_GUIDANCE: dict[str | None, str] = {
    "early": (
        "Early levels are deep-stacked — standard chip-EV poker applies and ICM "
        "is not yet a factor.  Build your stack through disciplined preflop "
        "selection and postflop aggression.  Avoid marginal commit-or-fold spots; "
        "favour situations where your skill edge can compound over many streets."
    ),
    "middle": (
        "Middle levels combine increasing antes with a shrinking stack-to-blind "
        "ratio.  Blind stealing and resteal efficiency become the primary profit "
        "drivers.  Avoid calling off large fractions of your stack without a "
        "clear equity edge.  Identify and exploit the tightest players at your "
        "table before the field tightens further."
    ),
    "bubble": (
        "The bubble is where ICM pressure is sharpest.  Short stacks will push "
        "wide to survive; widen your calling range only when you have a large "
        "chip lead and the equity math is clear.  Expand your steal range against "
        "medium stacks who are protecting their tournament life.  Fold equity is "
        "your primary weapon — use aggression to collect blinds, not to build pots."
    ),
    "itm": (
        "You are in the money — min-cash pressure is gone.  Shift to chip "
        "accumulation mode: increase steal frequency, pressure the short stacks, "
        "and avoid being blinded down by playing too conservatively.  Focus on "
        "pay-jump awareness near significant prize increases."
    ),
    "final_table": (
        "Final table play demands ICM awareness at every decision point near pay "
        "jumps.  Short-stacked players (< 15bb) should be playing near-GTO "
        "push/fold.  With a big stack, apply pressure to medium stacks who cannot "
        "afford to call.  Identify the tightest players at the table — they are "
        "your highest-EV steal targets."
    ),
    None: (
        "Tournament stage not provided — the following priorities apply across "
        "all stages and should be addressed regardless of where in the tournament "
        "you are."
    ),
}

_FORMAT_NOTES: dict[str, str] = {
    "PKO": (
        "PKO format: bounty equity makes wide calls profitable against short "
        "stacks you cover.  Adjust preflop call ranges to include the bounty "
        "overlay — do not fold away significant bounty equity to preserve chips "
        "against players you have well-covered.  ICM considerations are partially "
        "offset by bounty value throughout the tournament."
    ),
    "SATELLITE": (
        "Satellite format: only the top N seats matter; chip accumulation above "
        "the average stack has diminishing value.  Near the bubble, dramatically "
        "reduce your risk exposure — a min-cash and a seat-cash are equally "
        "valuable.  Fold aggressively to preserve your seat; let shorter stacks "
        "bust each other."
    ),
    "SPIN": (
        "Spin & Go hyper-turbo: the structure compresses to push/fold within "
        "a few orbits.  Postflop play is minimal; preflop fundamentals and "
        "push/fold accuracy are the dominant skill edges.  Study push/fold "
        "ranges for 3–15bb effective stacks."
    ),
    "FREEZEOUT": "",
    "REENTRY": (
        "Re-entry format: early level play is closer to cash-game chip-EV because "
        "the option to re-enter reduces early ICM pressure.  Do not over-fold in "
        "the early levels — re-entry value supports a more aggressive strategy "
        "before the re-entry period closes."
    ),
    "CASH": "",
}

# Map leak category → short focus-area label
_CATEGORY_LABELS: dict[str, str] = {
    "preflop": "Preflop strategy",
    "postflop": "Postflop play",
    "tournament": "Tournament adjustments",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_tournament_plan(
    player_id: uuid.UUID,
    stats: PlayerStats,
    leaks: list[Leak],
    *,
    tournament_format: str | None = None,
    stage: str | None = None,
    stack_bb: Decimal | None = None,
    players_remaining: int | None = None,
) -> TournamentPlan:
    """
    Build a tournament prep plan from existing stats and detected leaks.

    Parameters
    ----------
    player_id:
        Player UUID — echoed in the plan for traceability.
    stats:
        Aggregate player statistics from ``compute_player_stats()``.
    leaks:
        Pre-ranked list of Leak instances from ``LeakDetector.detect()``.
        Must be sorted priority-descending (highest first) — the caller is
        responsible for ordering.
    tournament_format:
        Optional format string.  Unrecognised values are treated as None.
    stage:
        Optional stage string.  Unrecognised values are treated as None.
    stack_bb:
        Hero's current stack in big blinds.  Used only for context echo;
        not used in guidance generation (stack-depth advice requires
        opponent stack data we do not have).
    players_remaining:
        Players remaining in the tournament.  Echoed for context.

    Returns
    -------
    TournamentPlan dataclass ready for serialisation.
    """
    # Normalise inputs — unknown values map to None
    norm_stage = stage.lower() if stage and stage.lower() in _STAGE_GUIDANCE else None
    norm_format = tournament_format.upper() if tournament_format else None
    if norm_format not in _FORMAT_NOTES:
        norm_format = None

    reliability_note = _reliability_note(stats.hand_count, leaks)
    stage_guidance = _stage_guidance_for(norm_stage, stats, leaks)
    format_note = _FORMAT_NOTES.get(norm_format or "", "")
    top_leaks = leaks[:3]
    study_priorities = _build_study_priorities(stats, leaks, norm_stage, norm_format)

    return TournamentPlan(
        player_id=player_id,
        hand_count=stats.hand_count,
        tournament_format=norm_format,
        stage=norm_stage,
        stack_bb=stack_bb,
        players_remaining=players_remaining,
        reliability_note=reliability_note,
        stage_guidance=stage_guidance,
        format_note=format_note,
        top_leaks=top_leaks,
        study_priorities=study_priorities,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _reliability_note(hand_count: int, leaks: list[Leak]) -> str:
    if hand_count == 0:
        return "No hands on record — plan cannot be personalised."
    if hand_count < 50:
        return (
            f"Only {hand_count} hands analysed.  All findings are speculative; "
            "play at least 200 hands before treating this plan as reliable."
        )
    if hand_count < 200:
        return (
            f"{hand_count} hands analysed.  Low-confidence leaks are directional "
            "only — confirm with a larger sample before making major adjustments."
        )
    note = f"{hand_count} hands analysed."
    if not leaks:
        note += "  No statistically supported leaks detected."
    return note


def _stage_guidance_for(
    stage: str | None,
    stats: PlayerStats,
    leaks: list[Leak],
) -> str:
    """Return stage guidance, appending one data-driven sentence if applicable."""
    base = _STAGE_GUIDANCE[stage]
    addon = _stage_leak_addon(stage, stats, leaks)
    return f"{base}  {addon}" if addon else base


def _stage_leak_addon(
    stage: str | None,
    stats: PlayerStats,
    leaks: list[Leak],
) -> str:
    """
    Return one sentence connecting the player's top leak to the current stage.

    Returns empty string when there are no leaks or the connection is not clear.
    """
    if not leaks:
        return ""

    top = leaks[0]
    lid = top.leak_id

    if stage == "bubble":
        if lid == "fold_to_3bet_too_high":
            return (
                "Your high fold-to-3bet rate is especially costly at the bubble, "
                "where opponents will apply relentless 3bet pressure knowing you fold."
            )
        if lid in ("cbet_too_low", "too_passive_postflop"):
            return (
                "Passive postflop play at the bubble surrenders chip equity that "
                "is magnified by ICM — you need to win more of the pots you contest."
            )
        if lid in ("vpip_too_loose", "pfr_too_passive"):
            return (
                "Loose preflop play is particularly damaging at the bubble, "
                "where committing chips with marginal hands amplifies ICM risk."
            )

    if stage == "final_table":
        if lid in ("fold_to_3bet_too_high", "fold_to_flop_bet_too_high"):
            return (
                "Folding tendencies are magnified at the final table, where "
                "opponents with ICM awareness will apply maximum pressure knowing you yield."
            )
        if lid in ("btn_steal_too_low", "co_steal_too_low", "sb_steal_too_low"):
            return (
                "Final tables frequently stall while players wait for others to bust; "
                "under-stealing leaves significant chip equity on the table."
            )

    if stage == "early":
        if lid in ("too_passive_postflop", "cbet_too_low", "wtsd_too_high"):
            return (
                "Deep-stacked early play heavily rewards postflop aggression — "
                "your passive tendencies cost more per hand at high stack-to-blind ratios."
            )

    if stage == "middle":
        if lid in ("btn_steal_too_low", "co_steal_too_low", "sb_steal_too_low"):
            return (
                "Middle levels are where steal efficiency determines stack trajectory — "
                "correcting your under-stealing now has compounding value."
            )

    if stage == "itm":
        if lid in ("vpip_too_tight", "vpip_too_loose"):
            return (
                "ITM play rewards active chip accumulation; "
                "range imbalances that were tolerable earlier now directly affect "
                "your ability to reach meaningful pay jumps."
            )

    return ""


def _urgency(priority: int) -> str:
    if priority >= 7:
        return _URGENCY_IMMEDIATE
    if priority >= 4:
        return _URGENCY_THIS_WEEK
    return _URGENCY_LONG_TERM


def _build_study_priorities(
    stats: PlayerStats,
    leaks: list[Leak],
    stage: str | None,
    fmt: str | None,
) -> list[StudyPriority]:
    """
    Produce a ranked list of study priorities.

    Ordering:
    1. Top 3 detected leaks → direct study actions (source=detected_leak).
    2. One format-specific priority when the format has material implications.
    3. One stage-specific priority not already covered by the top leaks.
    """
    priorities: list[StudyPriority] = []

    # ── Leak-driven priorities ────────────────────────────────────────────────
    for rank, leak in enumerate(leaks[:3], start=1):
        priorities.append(
            StudyPriority(
                rank=rank,
                focus_area=_focus_area(leak),
                action=leak.suggested_fix,
                source=_SOURCE_LEAK,
                urgency=_urgency(leak.priority),
                leak_id=leak.leak_id,
            )
        )

    base_rank = len(priorities) + 1

    # ── Format-specific priority ──────────────────────────────────────────────
    fmt_priority = _format_study_priority(fmt, base_rank)
    if fmt_priority is not None:
        priorities.append(fmt_priority)
        base_rank += 1

    # ── Stage-specific priority ───────────────────────────────────────────────
    existing_leak_ids = {p.leak_id for p in priorities if p.leak_id}
    stage_priority = _stage_study_priority(stage, stats, existing_leak_ids, base_rank)
    if stage_priority is not None:
        priorities.append(stage_priority)

    return priorities


def _focus_area(leak: Leak) -> str:
    label = _CATEGORY_LABELS.get(str(leak.category), "Strategy")
    return f"{label} — {leak.title}"


def _format_study_priority(fmt: str | None, rank: int) -> StudyPriority | None:
    if fmt == "PKO":
        return StudyPriority(
            rank=rank,
            focus_area="PKO-specific: bounty-adjusted calling ranges",
            action=(
                "Study bounty-adjusted call-off thresholds vs. short stacks you "
                "cover.  When the bounty represents > 20% of the pot, widen "
                "your calling range by roughly one tier of hand strength."
            ),
            source=_SOURCE_FORMAT,
            urgency=_URGENCY_THIS_WEEK,
        )
    if fmt == "SATELLITE":
        return StudyPriority(
            rank=rank,
            focus_area="Satellite-specific: stack preservation near the bubble",
            action=(
                "Identify the exact number of players remaining until the seats "
                "are awarded and compute whether you are 'safe'.  Once safe, "
                "fold almost any hand — do not gamble to accumulate chips you "
                "cannot use."
            ),
            source=_SOURCE_FORMAT,
            urgency=_URGENCY_IMMEDIATE,
        )
    if fmt == "SPIN":
        return StudyPriority(
            rank=rank,
            focus_area="Spin & Go: push/fold accuracy at 3–15bb",
            action=(
                "Drill push/fold charts for heads-up and 3-handed play at "
                "3bb, 5bb, 8bb, 10bb, and 15bb effective.  Use a solver "
                "or ICM trainer; the ranges change significantly by stack depth."
            ),
            source=_SOURCE_FORMAT,
            urgency=_URGENCY_IMMEDIATE,
        )
    if fmt == "REENTRY":
        return StudyPriority(
            rank=rank,
            focus_area="Re-entry: exploiting early chip-EV play",
            action=(
                "During the re-entry period, play closer to chip-EV and attack "
                "players who are ICM-folding in spots where a re-entry buy-in "
                "is trivial.  Adjust back to ICM play once re-entry closes."
            ),
            source=_SOURCE_FORMAT,
            urgency=_URGENCY_THIS_WEEK,
        )
    return None


def _stage_study_priority(
    stage: str | None,
    stats: PlayerStats,
    existing_leak_ids: set[str],
    rank: int,
) -> StudyPriority | None:
    """
    Return one stage-specific study priority not already covered by a detected leak.

    Only emits when the player's stats give a concrete hook for the advice.
    Returns None when no data-supported stage priority can be generated.
    """
    if stage == "bubble":
        if "fold_to_3bet_too_high" not in existing_leak_ids:
            f3b = stats.fold_to_3bet
            if f3b.value is not None and f3b.value > Decimal("0.58"):
                return StudyPriority(
                    rank=rank,
                    focus_area="Bubble: 3bet defend range",
                    action=(
                        f"Your fold-to-3bet is {float(f3b.value):.0%} (n={f3b.n}).  "
                        "At the bubble, opponents will 3bet you frequently.  "
                        "Build a documented 4bet-bluff and flat-call range for "
                        "each position so you are not purely exploitable."
                    ),
                    source=_SOURCE_STAGE,
                    urgency=_URGENCY_IMMEDIATE,
                )
        return StudyPriority(
            rank=rank,
            focus_area="Bubble: ICM-aware stack management",
            action=(
                "Review at least 5 recent bubble hands where you committed a "
                "large fraction of your stack.  Verify each against ICM "
                "thresholds: was the pot odds advantage sufficient to justify "
                "the elimination risk?"
            ),
            source=_SOURCE_STAGE,
            urgency=_URGENCY_THIS_WEEK,
        )

    if stage == "final_table":
        steal = stats.steal_pct
        if steal.value is not None and steal.value < Decimal("0.40") and steal.n and steal.n >= 10:
            return StudyPriority(
                rank=rank,
                focus_area="Final table: steal frequency from late position",
                action=(
                    f"Your overall steal rate is {float(steal.value):.0%} (n={steal.n}).  "
                    "At the final table, blinds are large and steal equity is high.  "
                    "Open BTN and CO with any two cards when the pot is unopened "
                    "and you have fold equity."
                ),
                source=_SOURCE_STAGE,
                urgency=_URGENCY_IMMEDIATE,
            )
        return StudyPriority(
            rank=rank,
            focus_area="Final table: ICM pay-jump awareness",
            action=(
                "Map the remaining pay jumps before your next final table.  "
                "Quantify the dollar difference between each place and let that "
                "inform how much risk you accept near each jump boundary."
            ),
            source=_SOURCE_STAGE,
            urgency=_URGENCY_THIS_WEEK,
        )

    if stage == "early":
        cbet = stats.cbet_pct
        if (
            cbet.value is not None
            and cbet.n
            and cbet.n >= 10
            and "cbet_too_low" not in existing_leak_ids
            and cbet.value < Decimal("0.50")
        ):
            return StudyPriority(
                rank=rank,
                focus_area="Early levels: postflop continuation",
                action=(
                    f"Your c-bet rate is {float(cbet.value):.0%} (n={cbet.n}).  "
                    "Deep-stacked early play rewards maintaining preflop initiative.  "
                    "Identify one board texture where you routinely check back "
                    "as the PF raiser and drill the correct c-bet range for it."
                ),
                source=_SOURCE_STAGE,
                urgency=_URGENCY_THIS_WEEK,
            )

    if stage == "middle":
        btn_steal = stats.btn_steal_pct
        if (
            btn_steal.value is not None
            and btn_steal.n
            and btn_steal.n >= 8
            and "btn_steal_too_low" not in existing_leak_ids
            and btn_steal.value < Decimal("0.55")
        ):
            return StudyPriority(
                rank=rank,
                focus_area="Middle levels: BTN steal frequency",
                action=(
                    f"Your BTN steal rate is {float(btn_steal.value):.0%} "
                    f"(n={btn_steal.n}).  Raising liberally from BTN in middle "
                    "levels with antes is high-EV.  Aim for ≥ 60% when the "
                    "pot is unopened."
                ),
                source=_SOURCE_STAGE,
                urgency=_URGENCY_THIS_WEEK,
            )

    if stage == "itm":
        # Encourage active accumulation — look for evidence of tightness
        vpip = stats.vpip
        if (
            vpip.value is not None
            and vpip.n
            and vpip.n >= 20
            and vpip.value < Decimal("0.22")
            and "vpip_too_tight" not in existing_leak_ids
        ):
            return StudyPriority(
                rank=rank,
                focus_area="ITM: chip accumulation mode",
                action=(
                    f"Your VPIP is {float(vpip.value):.0%} (n={vpip.n}).  "
                    "In the money, passive chip preservation costs you equity at "
                    "future pay jumps.  Loosen your opening range from late "
                    "position and increase steal attempts."
                ),
                source=_SOURCE_STAGE,
                urgency=_URGENCY_THIS_WEEK,
            )

    return None
