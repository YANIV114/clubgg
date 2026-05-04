from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionFactory, get_db
from app.dependencies import require_tester
from app.features.leak_examples import build_leak_examples
from app.features.leaks import LeakDetector, analysis_note
from app.features.player_stats import compute_player_stats
from app.ingestion.hand_parser import _HAND_BLOCK_RE, HandHistoryFileIngestor, HandHistoryParser
from app.models.hand import Hand, HandPlayer
from app.models.player import Club, Player
from app.models.user import User
from app.schemas.leaks import LeakExampleOut, LeakOut, PlayerLeaksOut
from app.schemas.me import (
    HandPlayerSummaryOut,
    LinkedPlayerOut,
    LinkPlayerRequest,
    MeAnalysisOut,
    MeHandOut,
    MeHandsOut,
    MeImportSummary,
    MeSummaryOut,
)
from app.schemas.stats import PlayerStatsOut
from app.services.billing_service import require_feature
from app.services.hand_service import hand_records_for_player
from app.services.user_player_service import (
    get_linked_players,
    get_primary_player,
    link_player,
)

router = APIRouter()
_require_leak_tracker = require_feature("leak_tracker")


async def _get_primary_or_404(session: AsyncSession, user_id: uuid.UUID) -> Player:
    player = await get_primary_player(session, user_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No player linked to your account",
        )
    return player


def _build_leak_outs(leaks: list, records: list, contexts: dict) -> list[LeakOut]:
    out = []
    for leak in leaks:
        examples = build_leak_examples(leak.leak_id, records, contexts)
        out.append(
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
    return out


def _detect_hero(file_texts: list[str]) -> tuple[str | None, int | None]:
    """
    Parse all hand blocks and find the most likely hero player.

    Prefers players with hole_cards set and did_show=False (dealt pre-showdown,
    i.e., the exporting client's player). Falls back to the player with the most
    hands with hole_cards set (showdown reveals). Returns (username, club_ext_id).
    """
    parser = HandHistoryParser()
    counts_pre: Counter[str] = Counter()
    counts_all: Counter[str] = Counter()
    club_ext_id: int | None = None

    for text in file_texts:
        blocks = [b.strip() for b in _HAND_BLOCK_RE.split(text) if b.strip()]
        for block in blocks:
            try:
                raw = parser.parse(block)
            except ValueError:
                continue
            if club_ext_id is None and raw.get("club_external_id"):
                club_ext_id = int(raw["club_external_id"])
            for p in raw.get("players", []):
                if p.get("hole_cards"):
                    uname = p["player_username"]
                    if not p.get("did_show", False):
                        counts_pre[uname] += 1
                    counts_all[uname] += 1

    if counts_pre:
        return counts_pre.most_common(1)[0][0], club_ext_id
    if counts_all:
        return counts_all.most_common(1)[0][0], club_ext_id
    return None, club_ext_id


# ── Player linking ────────────────────────────────────────────────────────────


@router.post("/me/players/link", response_model=LinkedPlayerOut, status_code=status.HTTP_200_OK)
async def link_my_player(
    body: LinkPlayerRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> LinkedPlayerOut:
    player = await session.get(Player, body.player_id)
    if player is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")

    link = await link_player(session, current_user.id, body.player_id, body.is_primary)
    return LinkedPlayerOut(
        player_id=player.id,
        player_username=player.username,
        is_primary=link.is_primary,
        is_stub=player.is_stub,
        linked_at=link.created_at,
    )


@router.get("/me/players", response_model=list[LinkedPlayerOut])
async def get_my_players(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> list[LinkedPlayerOut]:
    rows = await get_linked_players(session, current_user.id)
    return [
        LinkedPlayerOut(
            player_id=player.id,
            player_username=player.username,
            is_primary=link.is_primary,
            is_stub=player.is_stub,
            linked_at=link.created_at,
        )
        for link, player in rows
    ]


# ── Analysis ──────────────────────────────────────────────────────────────────


@router.get("/me/analysis", response_model=MeAnalysisOut)
async def get_my_analysis(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
    limit: int = Query(1000, ge=1, le=10000),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
) -> MeAnalysisOut:
    player = await _get_primary_or_404(session, current_user.id)

    records, contexts = await hand_records_for_player(
        session, player.id, limit=limit, from_date=from_date, to_date=to_date
    )
    stats = compute_player_stats(player_id=player.id, hands=records)
    detector = LeakDetector()
    leaks = detector.detect(stats)
    leak_outs = _build_leak_outs(leaks[:5], records, contexts)

    biggest = leaks[0].title if leaks else None
    note = analysis_note(stats.hand_count, len(leaks))

    return MeAnalysisOut(
        player_id=player.id,
        player_username=player.username,
        summary=MeSummaryOut(
            hands_analyzed=stats.hand_count,
            biggest_leak=biggest,
            leaks_count=len(leaks),
            analysis_note=note,
        ),
        stats=PlayerStatsOut.model_validate(stats, from_attributes=True),
        leaks=PlayerLeaksOut(
            player_id=player.id,
            hand_count=stats.hand_count,
            leaks=leak_outs,
            analysis_note=note,
        ),
    )


@router.get("/me/stats", response_model=PlayerStatsOut)
async def get_my_stats(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
    limit: int = Query(1000, ge=1, le=10000),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
) -> PlayerStatsOut:
    player = await _get_primary_or_404(session, current_user.id)
    records, _ = await hand_records_for_player(
        session, player.id, limit=limit, from_date=from_date, to_date=to_date
    )
    stats = compute_player_stats(player_id=player.id, hands=records)
    out = PlayerStatsOut.model_validate(stats, from_attributes=True)
    return out.model_copy(update={"player_name": player.username})


@router.get("/me/leaks", response_model=PlayerLeaksOut)
async def get_my_leaks(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
    _gate: None = Depends(_require_leak_tracker),
    limit: int = Query(1000, ge=1, le=10000),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
) -> PlayerLeaksOut:
    player = await _get_primary_or_404(session, current_user.id)
    records, contexts = await hand_records_for_player(
        session, player.id, limit=limit, from_date=from_date, to_date=to_date
    )
    stats = compute_player_stats(player_id=player.id, hands=records)
    detector = LeakDetector()
    leaks = detector.detect(stats)
    leak_outs = _build_leak_outs(leaks, records, contexts)
    note = analysis_note(stats.hand_count, len(leaks))
    return PlayerLeaksOut(
        player_id=player.id,
        hand_count=stats.hand_count,
        leaks=leak_outs,
        analysis_note=note,
    )


# ── Recent hands ──────────────────────────────────────────────────────────────


@router.get("/me/hands", response_model=MeHandsOut)
async def get_my_hands(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
    limit: int = Query(50, ge=1, le=500),
) -> MeHandsOut:
    player = await _get_primary_or_404(session, current_user.id)

    # Load all hands where the hero played, with every seat's player loaded so
    # we can surface real usernames instead of raw player_ids.
    hero_hand_ids = select(HandPlayer.hand_id).where(HandPlayer.player_id == player.id)
    result = await session.execute(
        select(Hand)
        .options(selectinload(Hand.hand_players).options(selectinload(HandPlayer.player)))
        .where(Hand.id.in_(hero_hand_ids))
        .order_by(Hand.hand_started_at.desc())
        .limit(limit)
    )
    hands = result.scalars().all()

    hand_outs: list[MeHandOut] = []
    for hand in hands:
        hero_hp = next((hp for hp in hand.hand_players if hp.player_id == player.id), None)
        all_players = [
            HandPlayerSummaryOut(
                player_id=hp.player_id,
                username=hp.username,
                position=hp.position,
                stack_bb=str(hp.stack_bb) if hp.stack_bb is not None else None,
            )
            for hp in sorted(hand.hand_players, key=lambda hp: hp.seat_number or 0)
        ]
        hand_outs.append(
            MeHandOut(
                hand_external_id=hand.external_id,
                table_name=hand.table_name,
                position=hero_hp.position if hero_hp else None,
                stack_bb=(
                    str(hero_hp.stack_bb) if hero_hp and hero_hp.stack_bb is not None else None
                ),
                net_won=(str(hero_hp.net_won) if hero_hp and hero_hp.net_won is not None else None),
                board_cards=hand.board_cards,
                hand_started_at=hand.hand_started_at,
                player_count=hand.player_count,
                hero_player_id=player.id,
                hero_username=hero_hp.username if hero_hp else None,
                all_players=all_players,
            )
        )

    return MeHandsOut(player_id=player.id, hands=hand_outs, total=len(hand_outs))


# ── Authenticated import ──────────────────────────────────────────────────────


@router.post("/me/import", response_model=MeImportSummary)
async def me_import_hands(
    files: list[UploadFile] = File(...),
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> MeImportSummary:
    """
    Import hand history files and automatically link the detected hero player.

    Hero detection: the player whose hole cards appear most often pre-showdown
    (via "Dealt to" lines) is treated as the importing user's player. Falls back
    to the player with the most showdown card reveals across all uploaded files.

    Linking rules:
    - If user has no primary player, the detected player becomes primary.
    - If user already has a primary player, the detected player is linked but
      does NOT replace the existing primary.
    """
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    texts: list[str] = []
    for f in files:
        if not f.filename or not f.filename.endswith(".txt"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{f.filename!r}: only .txt hand history files accepted",
            )
        content = await f.read()
        try:
            texts.append(content.decode("utf-8"))
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{f.filename!r}: file must be UTF-8 encoded",
            )

    # Detect hero before import (pure parse, no DB)
    hero_username, club_ext_id = _detect_hero(texts)

    # Run ingestion — uses its own session and commits independently
    ingestor = HandHistoryFileIngestor("", AsyncSessionFactory)
    result = await ingestor.run_from_uploads(texts)

    # After import, look up the detected hero player and link to user
    detected_player_id: str | None = None
    player_linked = False
    player_is_primary = False
    link_message = ""

    if hero_username and club_ext_id is not None:
        club = await session.scalar(select(Club).where(Club.external_id == club_ext_id))
        if club:
            hero_player = await session.scalar(
                select(Player).where(
                    Player.club_id == club.id,
                    Player.username == hero_username,
                )
            )
            if hero_player:
                detected_player_id = str(hero_player.id)
                existing_primary = await get_primary_player(session, current_user.id)
                # Only set as primary if user has no primary yet
                make_primary = existing_primary is None
                await link_player(session, current_user.id, hero_player.id, is_primary=make_primary)
                player_linked = True
                player_is_primary = make_primary
                if make_primary:
                    link_message = (
                        f"Player '{hero_username}' detected and linked as your primary player."
                    )
                else:
                    link_message = (
                        f"Player '{hero_username}' detected and linked. "
                        f"Your primary player was not changed."
                    )
            else:
                link_message = (
                    f"Player '{hero_username}' detected but not found in database after import."
                )
    elif not hero_username:
        link_message = (
            "No player detected from hole cards. Use 'Connect Your Player' to link manually."
        )

    return MeImportSummary(
        files_processed=result.files_processed,
        hands_parsed=result.hands_parsed,
        hands_imported=result.hands_imported,
        duplicates_skipped=result.duplicates_skipped,
        parse_failures=result.parse_failures,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
        detected_player_username=hero_username,
        detected_player_id=detected_player_id,
        player_linked=player_linked,
        player_is_primary=player_is_primary,
        link_message=link_message,
    )
