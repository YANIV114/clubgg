import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.dependencies import DBSession
from app.features.leak_examples import build_leak_examples
from app.features.leaks import LeakDetector, analysis_note
from app.features.player_stats import compute_player_stats
from app.features.tournament_plan import build_tournament_plan
from app.schemas.common import PaginatedResponse
from app.schemas.leaks import LeakExampleOut, LeakOut, PlayerLeaksOut
from app.schemas.player import ClubOut, PlayerDetailOut, PlayerOut, PlayerSampleOut
from app.schemas.stats import PlayerStatsOut
from app.schemas.tournament_plan import StudyPriorityOut, TournamentPlanOut, TournamentPlanRequest
from app.services.hand_service import hand_records_for_player
from app.services.player_service import (
    get_club,
    get_player,
    get_player_sample,
    list_clubs,
    list_players,
)

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[PlayerOut])
async def list_players_route(
    db: DBSession,
    club_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    sort_by: str = Query("username", pattern="^(username|hand_count)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> PaginatedResponse[PlayerOut]:
    return await list_players(
        db,
        club_id=club_id,
        agent_id=agent_id,
        is_active=is_active,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )


@router.get("/clubs", response_model=list[ClubOut])
async def list_clubs_route(db: DBSession) -> list[ClubOut]:
    return await list_clubs(db)


# ── Sample endpoint ──────────────────────────────────────────────────────────


@router.get("/{player_id}/sample", response_model=PlayerSampleOut)
async def get_player_sample_route(
    player_id: uuid.UUID,
    db: DBSession,
) -> PlayerSampleOut:
    player = await get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return await get_player_sample(db, player_id)


# ── Stats endpoint ────────────────────────────────────────────────────────────
# Placed before /{player_id} so FastAPI doesn't try to parse "stats" as a UUID.


@router.get("/{player_id}/stats", response_model=PlayerStatsOut)
async def get_player_stats(
    player_id: uuid.UUID,
    db: DBSession,
    limit: int = Query(1000, ge=1, le=10000, description="Max hands to load"),
    from_date: datetime | None = Query(None, description="Filter hands from this UTC datetime"),
    to_date: datetime | None = Query(None, description="Filter hands up to this UTC datetime"),
) -> PlayerStatsOut:
    """
    Compute aggregate poker statistics for a player.

    Loads up to ``limit`` hands (most recent first), converts each to a
    HandRecord, and runs compute_player_stats().

    All rate fields in the response carry an epistemic label (``inferred``).
    Check ``n >= 20`` for reliability.  Rates with zero eligible denominator
    return ``value: null``.
    """
    player = await get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    records, _ = await hand_records_for_player(
        db, player_id, limit=limit, from_date=from_date, to_date=to_date
    )
    stats = compute_player_stats(player_id=player_id, hands=records)
    out = PlayerStatsOut.model_validate(stats, from_attributes=True)
    return out.model_copy(update={"player_name": player.username})


# ── Leaks endpoint ───────────────────────────────────────────────────────────


@router.get("/{player_id}/leaks", response_model=PlayerLeaksOut)
async def get_player_leaks(
    player_id: uuid.UUID,
    db: DBSession,
    limit: int = Query(1000, ge=1, le=10000, description="Max hands to load"),
    from_date: datetime | None = Query(None, description="Filter hands from this UTC datetime"),
    to_date: datetime | None = Query(None, description="Filter hands up to this UTC datetime"),
) -> PlayerLeaksOut:
    """
    Detect exploitable leaks in a player's strategy.

    Loads up to ``limit`` hands, computes PlayerStats, runs all leak rules.
    Results sorted by priority (highest first).  Each leak includes up to 3
    real hand examples ranked by teaching value.
    """
    player = await get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    records, contexts = await hand_records_for_player(
        db, player_id, limit=limit, from_date=from_date, to_date=to_date
    )
    stats = compute_player_stats(player_id=player_id, hands=records)
    detector = LeakDetector()
    leaks = detector.detect(stats)

    leak_outs: list[LeakOut] = []
    for leak in leaks:
        examples = build_leak_examples(leak.leak_id, records, contexts)
        leak_outs.append(
            LeakOut(
                leak_id=leak.leak_id,
                category=leak.category,
                title=leak.title,
                explanation=leak.explanation,
                evidence=leak.evidence,
                confidence=leak.confidence,
                severity=leak.severity,
                frequency=leak.frequency,
                priority=leak.priority,
                sample_size=leak.sample_size,
                limitations=leak.limitations,
                suggested_fix=leak.suggested_fix,
                examples=[
                    LeakExampleOut(
                        hand_external_id=ex.hand_external_id,
                        position=ex.position,
                        stack_bb=ex.stack_bb,
                        effective_stack_bb=ex.effective_stack_bb,
                        board_cards=ex.board_cards,
                        situation=ex.situation,
                        why_weak=ex.why_weak,
                        stronger_line=ex.stronger_line,
                    )
                    for ex in examples
                ],
            )
        )

    return PlayerLeaksOut(
        player_id=player_id,
        hand_count=stats.hand_count,
        leaks=leak_outs,
        analysis_note=analysis_note(stats.hand_count, len(leaks)),
    )


# ── Tournament plan ───────────────────────────────────────────────────────────


@router.post("/{player_id}/tournament-plan", response_model=TournamentPlanOut)
async def get_tournament_plan(
    player_id: uuid.UUID,
    db: DBSession,
    body: TournamentPlanRequest,
    from_date: datetime | None = Query(None, description="Filter hands from this UTC datetime"),
    to_date: datetime | None = Query(None, description="Filter hands up to this UTC datetime"),
) -> TournamentPlanOut:
    """
    Generate a tournament prep plan for a player.
    """
    player = await get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    records, _ = await hand_records_for_player(
        db, player_id, limit=body.limit, from_date=from_date, to_date=to_date
    )
    stats = compute_player_stats(player_id=player_id, hands=records)
    detector = LeakDetector()
    leaks = detector.detect(stats)

    plan = build_tournament_plan(
        player_id=player_id,
        stats=stats,
        leaks=leaks,
        tournament_format=body.tournament_format,
        stage=body.stage,
        stack_bb=body.stack_bb,
        players_remaining=body.players_remaining,
    )

    return TournamentPlanOut(
        player_id=plan.player_id,
        hand_count=plan.hand_count,
        tournament_format=plan.tournament_format,
        stage=plan.stage,
        stack_bb=plan.stack_bb,
        players_remaining=plan.players_remaining,
        reliability_note=plan.reliability_note,
        stage_guidance=plan.stage_guidance,
        format_note=plan.format_note,
        top_leaks=[LeakOut.model_validate(lk, from_attributes=True) for lk in plan.top_leaks],
        study_priorities=[
            StudyPriorityOut.model_validate(sp, from_attributes=True)
            for sp in plan.study_priorities
        ],
    )


# ── Export endpoint ───────────────────────────────────────────────────────────


def _pct(value: str | None) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (ValueError, TypeError):
        return "—"


def _stat_row(label: str, metric: dict) -> str:
    val = _pct(metric.get("value"))
    n = metric.get("n", 0)
    note = " ⚠ low n" if n and n < 20 else ""
    return f"<tr><td>{label}</td><td>{val}</td><td>{n}{note}</td></tr>"


def _severity_color(severity: str) -> str:
    return {"high": "#e05c5c", "medium": "#d4922a", "low": "#6b8fbd"}.get(severity, "#888")


def _build_report_html(player_id: uuid.UUID, username: str, stats: object, leaks: list) -> str:
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    hand_count = getattr(stats, "hand_count", 0)
    reliability = "High" if hand_count >= 200 else "Medium" if hand_count >= 50 else "Low"
    rel_cls = "" if reliability == "High" else "medium" if reliability == "Medium" else "low"

    # ── Key stats table ──
    stat_rows = "".join(
        [
            _stat_row("VPIP", stats.vpip.__dict__),
            _stat_row("PFR", stats.pfr.__dict__),
            _stat_row("3-Bet %", stats.three_bet_pct.__dict__),
            _stat_row("Fold to 3-Bet", stats.fold_to_3bet.__dict__),
            _stat_row("WTSD", stats.wtsd.__dict__),
            _stat_row("WSD", stats.wsd.__dict__),
            _stat_row("Steal %", stats.steal_pct.__dict__),
            _stat_row("BTN Steal %", stats.btn_steal_pct.__dict__),
            _stat_row("CO Steal %", stats.co_steal_pct.__dict__),
        ]
    )

    # ── Positional breakdown ──
    positional = getattr(stats, "positional", {}) or {}
    pos_order = ["BTN", "CO", "HJ", "MP", "UTG", "SB", "BB"]
    pos_rows = ""
    for pos in pos_order:
        pd = positional.get(pos)
        if pd is None:
            continue
        n = pd.get("n_hands", 0)
        if not n:
            continue

        def _pv(m: dict | None) -> str:
            if not m or m.get("value") is None:
                return "—"
            try:
                return f"{float(m['value']) * 100:.1f}%"
            except (ValueError, TypeError):
                return "—"

        pos_rows += (
            f"<tr><td><strong>{pos}</strong></td><td>{n}</td>"
            f"<td>{_pv(pd.get('vpip'))}</td>"
            f"<td>{_pv(pd.get('pfr'))}</td>"
            f"<td>{_pv(pd.get('three_bet_pct'))}</td>"
            f"<td>{_pv(pd.get('fold_to_3bet'))}</td></tr>"
        )
    positional_section = ""
    if pos_rows:
        positional_section = f"""
<h2>Positional Breakdown</h2>
<table>
  <thead><tr><th>Position</th><th>Hands</th><th>VPIP</th><th>PFR</th><th>3-Bet%</th><th>F-3bet</th></tr></thead>
  <tbody>{pos_rows}</tbody>
</table>"""

    # ── Leaks ──
    sorted_leaks = sorted(leaks, key=lambda l: -(l.priority or 0))
    leak_items = ""
    for lk in sorted_leaks:
        color = _severity_color(lk.severity)
        leak_items += f"""
        <div class="leak">
          <div class="leak-header">
            <span class="badge" style="background:{color}">{lk.severity.upper()}</span>
            <strong>{lk.title}</strong>
            <span class="leak-meta">n={lk.sample_size} &middot; priority {lk.priority}/10</span>
          </div>
          <p class="leak-body">{lk.explanation}</p>
          <p class="leak-evidence"><em>Evidence:</em> {lk.evidence}</p>
          <p class="leak-fix"><strong>Fix:</strong> {lk.suggested_fix}</p>
          <p class="leak-limits"><em>Limitations:</em> {lk.limitations}</p>
        </div>"""

    if not leak_items:
        leak_items = "<p>No significant leaks detected at current sample size.</p>"

    # ── Study priorities (top 5 leaks ranked by priority, grouped by severity) ──
    high = [l for l in sorted_leaks if l.severity == "high"][:3]
    medium = [l for l in sorted_leaks if l.severity == "medium"][:3]
    low = [l for l in sorted_leaks if l.severity == "low"][:2]
    priority_items = ""
    rank = 1
    for lk in high + medium + low:
        color = _severity_color(lk.severity)
        priority_items += (
            f'<div class="priority-row">'
            f'<span class="priority-num">{rank}</span>'
            f'<span class="badge" style="background:{color}">{lk.severity.upper()}</span>'
            f'<span class="priority-title">{lk.title}</span>'
            f'<span class="priority-fix">{lk.suggested_fix[:120]}{"…" if len(lk.suggested_fix) > 120 else ""}</span>'
            f"</div>"
        )
        rank += 1
    if not priority_items:
        priority_items = "<p>No actionable priorities at current sample size.</p>"

    # ── Next training focus ──
    next_focus = ""
    if high:
        top = high[0]
        next_focus = f"""
<h2>Next Training Focus</h2>
<div class="focus-box">
  <div class="focus-label">Top priority to drill</div>
  <div class="focus-title">{top.title}</div>
  <p class="focus-fix">{top.suggested_fix}</p>
  <p class="focus-evidence">{top.evidence}</p>
</div>"""
    elif medium:
        top = medium[0]
        next_focus = f"""
<h2>Next Training Focus</h2>
<div class="focus-box">
  <div class="focus-label">Priority leak to drill</div>
  <div class="focus-title">{top.title}</div>
  <p class="focus-fix">{top.suggested_fix}</p>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClubGG Player Report &mdash; {username}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 860px; margin: 40px auto; padding: 0 24px;
         color: #1a1a2e; background: #fff; line-height: 1.5; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  h2 {{ font-size: 1.05rem; border-bottom: 2px solid #e0e0f0; padding-bottom: 6px;
        margin-top: 40px; margin-bottom: 14px; color: #222; }}
  .meta {{ color: #666; font-size: 0.85rem; margin-bottom: 32px; }}
  .reliability {{ display: inline-block; padding: 2px 10px; border-radius: 12px;
                  font-size: 0.75rem; font-weight: 600; background: #e8f4e8;
                  color: #2d7a2d; margin-left: 8px; vertical-align: middle; }}
  .reliability.medium {{ background: #fef3e2; color: #b06010; }}
  .reliability.low {{ background: #fde8e8; color: #c03030; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 4px; font-size: 0.88rem; }}
  th {{ text-align: left; font-size: 0.75rem; color: #888; padding: 5px 12px 5px 0;
        font-weight: 500; border-bottom: 1px solid #e8e8f4; }}
  td {{ padding: 7px 12px 7px 0; border-bottom: 1px solid #f0f0f8; }}
  td:nth-child(2) {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
  td:nth-child(3) {{ color: #888; font-size: 0.8rem; }}
  .badge {{ color: #fff; font-size: 0.68rem; font-weight: 700; padding: 2px 7px;
            border-radius: 10px; letter-spacing: 0.04em; white-space: nowrap; }}
  /* Study priorities */
  .priority-row {{ display: flex; align-items: flex-start; gap: 10px; padding: 10px 0;
                   border-bottom: 1px solid #f0f0f8; }}
  .priority-row:last-child {{ border-bottom: none; }}
  .priority-num {{ font-size: 0.75rem; font-weight: 700; color: #aaa; min-width: 18px;
                   padding-top: 2px; }}
  .priority-title {{ font-weight: 600; font-size: 0.9rem; flex-shrink: 0; min-width: 200px; }}
  .priority-fix {{ font-size: 0.82rem; color: #555; flex: 1; }}
  /* Next focus box */
  .focus-box {{ border-left: 4px solid #e05c5c; background: #fff8f8; border-radius: 0 8px 8px 0;
                padding: 14px 18px; }}
  .focus-label {{ font-size: 0.75rem; font-weight: 600; color: #e05c5c; text-transform: uppercase;
                  letter-spacing: 0.06em; margin-bottom: 4px; }}
  .focus-title {{ font-size: 1.05rem; font-weight: 700; color: #1a1a2e; margin-bottom: 8px; }}
  .focus-fix {{ font-size: 0.88rem; margin: 0 0 6px; }}
  .focus-evidence {{ font-size: 0.8rem; color: #888; margin: 0; }}
  /* Leaks */
  .leak {{ border: 1px solid #e8e8f4; border-radius: 8px; padding: 16px; margin-bottom: 12px; }}
  .leak-header {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }}
  .leak-meta {{ margin-left: auto; color: #999; font-size: 0.75rem; }}
  .leak-body {{ margin: 0 0 6px; font-size: 0.87rem; }}
  .leak-evidence, .leak-fix, .leak-limits {{ margin: 4px 0; font-size: 0.82rem; color: #444; }}
  .leak-limits {{ color: #aaa; font-size: 0.78rem; }}
  footer {{ margin-top: 52px; font-size: 0.72rem; color: #bbb; border-top: 1px solid #f0f0f8;
            padding-top: 12px; }}
  @media print {{
    body {{ margin: 12px; font-size: 0.85rem; }}
    .leak {{ break-inside: avoid; }}
    .priority-row {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
<h1>Player Report &mdash; {username}
  <span class="reliability {rel_cls}">{reliability} reliability</span>
</h1>
<p class="meta">Player ID: {player_id} &middot; {hand_count} hands analysed &middot; Generated {generated}</p>

<h2>Key Stats</h2>
<table>
  <thead><tr><th>Stat</th><th>Value</th><th>Sample (n)</th></tr></thead>
  <tbody>{stat_rows}</tbody>
</table>

{positional_section}

{next_focus}

<h2>Study Priorities</h2>
<div class="priority-list">{priority_items}</div>

<h2>All Detected Leaks ({len(leaks)})</h2>
{leak_items}

<footer>ClubGG Analytics &mdash; All rates are INFERRED from observed hand history.
n &lt; 20 = low confidence. Positional stats are DERIVED from the same sample.
This report does not constitute solver output or guaranteed EV calculations.</footer>
</body>
</html>"""


@router.get("/{player_id}/export")
async def export_player_report(
    player_id: uuid.UUID,
    db: DBSession,
    limit: int = Query(1000, ge=1, le=10000),
) -> HTMLResponse:
    """Return a self-contained HTML report (stats + leaks) for sharing or printing."""
    player = await get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")

    records, _ = await hand_records_for_player(db, player_id, limit=limit)
    stats = compute_player_stats(player_id=player_id, hands=records)
    leaks = LeakDetector().detect(stats)

    html = _build_report_html(player_id, player.username, stats, leaks)
    filename = f"clubgg-report-{player.username}.html"
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Single-player detail ──────────────────────────────────────────────────────


@router.get("/{player_id}", response_model=PlayerDetailOut)
async def get_player_route(player_id: uuid.UUID, db: DBSession) -> PlayerDetailOut:
    player = await get_player(db, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player


@router.get("/clubs/{club_id}", response_model=ClubOut)
async def get_club_route(club_id: uuid.UUID, db: DBSession) -> ClubOut:
    club = await get_club(db, club_id)
    if club is None:
        raise HTTPException(status_code=404, detail="Club not found")
    return club
