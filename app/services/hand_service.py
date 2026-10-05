"""
Service layer for Hand ingestion and queries.
"""

import dataclasses
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hand import Hand, HandPlayer, HandWinner, PlayerAction
from app.models.player import Club
from app.schemas.common import PaginatedResponse
from app.schemas.hand import HandDetailOut, HandOut
from app.schemas.ingestion import IngestHandPayload
from app.services.player_service import get_or_create_stub_player


async def upsert_hand(session: AsyncSession, payload: IngestHandPayload) -> None:
    # Resolve club
    club_row = await session.execute(
        select(Club.id).where(Club.external_id == payload.club_external_id)
    )
    club_id: uuid.UUID | None = club_row.scalar_one_or_none()
    if club_id is None:
        raise ValueError(f"Club external_id={payload.club_external_id} not found")

    # Upsert the hand row
    hand_values: dict[str, Any] = {
        "external_id": payload.external_id,
        "club_id": club_id,
        "game_type": payload.game_type.value,
        "stakes_sb": payload.stakes_sb,
        "stakes_bb": payload.stakes_bb,
        "stakes_ante": payload.stakes_ante,
        "table_name": payload.table_name,
        "hand_started_at": payload.hand_started_at,
        "hand_ended_at": payload.hand_ended_at,
        "total_pot": payload.total_pot,
        "total_rake": payload.total_rake,
        "board_cards": payload.board_cards,
        "player_count": len(payload.players),
        "raw_text": payload.raw_text,
        "ingestion_source": payload.ingestion_source,
        "button_seat": payload.button_seat,
        "blind_level_index": payload.blind_level_index,
        "players_remaining": payload.players_remaining,
    }
    hand_stmt = (
        insert(Hand)
        .values(**hand_values)
        .on_conflict_do_update(
            index_elements=["external_id"],
            set_={k: v for k, v in hand_values.items() if k != "external_id"},
        )
        .returning(Hand.id)
    )
    result = await session.execute(hand_stmt)
    hand_id: uuid.UUID = result.scalar_one()

    # Upsert hand_players and build username→hand_player_id map
    username_to_hp_id: dict[str, uuid.UUID] = {}
    for p in payload.players:
        player_id = await get_or_create_stub_player(session, club_id, p.player_username)
        net_won = (p.ending_stack - p.starting_stack) if p.ending_stack is not None else None
        hp_values: dict[str, Any] = {
            "hand_id": hand_id,
            "player_id": player_id,
            "seat_number": p.seat_number,
            "starting_stack": p.starting_stack,
            "ending_stack": p.ending_stack,
            "net_won": net_won,
            "hole_cards": p.hole_cards,
            "did_show": p.did_show,
            "position": p.position,
            "stack_bb": p.stack_bb,
            "effective_stack_bb": p.effective_stack_bb,
        }
        hp_stmt = (
            insert(HandPlayer)
            .values(**hp_values)
            .on_conflict_do_update(
                constraint="uq_hand_players_hand_id_player_id",
                set_={k: v for k, v in hp_values.items() if k not in ("hand_id", "player_id")},
            )
            .returning(HandPlayer.id)
        )
        hp_result = await session.execute(hp_stmt)
        hp_id: uuid.UUID = hp_result.scalar_one()
        username_to_hp_id[p.player_username] = hp_id

    # Insert player_actions (delete + re-insert on conflict to keep order stable)
    for action in payload.actions:
        action_hp_id = username_to_hp_id.get(action.player_username)
        if action_hp_id is None:
            continue
        hp_id = action_hp_id
        action_values: dict[str, Any] = {
            "hand_id": hand_id,
            "hand_player_id": hp_id,
            "street": action.street.value,
            "action_type": action.action_type.value,
            "amount": action.amount,
            "is_all_in": action.is_all_in,
            "action_order": action.action_order,
        }
        await session.execute(
            insert(PlayerAction)
            .values(**action_values)
            .on_conflict_do_nothing(index_elements=["hand_id", "action_order"])
        )

    # Upsert hand_winners
    for winner in payload.winners:
        winner_hp_id = username_to_hp_id.get(winner.player_username)
        if winner_hp_id is None:
            continue
        hp_id = winner_hp_id
        winner_values: dict[str, Any] = {
            "hand_id": hand_id,
            "hand_player_id": hp_id,
            "pot_type": winner.pot_type,
            "amount_won": winner.amount_won,
            "winning_hand_description": winner.winning_hand_description,
        }
        await session.execute(
            insert(HandWinner)
            .values(**winner_values)
            .on_conflict_do_nothing(index_elements=["hand_player_id", "pot_type"])
        )


async def get_existing_external_ids(session: AsyncSession, external_ids: list[str]) -> set[str]:
    """Return the subset of external_ids that already exist in the hands table."""
    if not external_ids:
        return set()
    result = await session.execute(
        select(Hand.external_id).where(Hand.external_id.in_(external_ids))
    )
    return set(result.scalars())


async def list_hands(
    session: AsyncSession,
    club_id: uuid.UUID | None = None,
    game_type: str | None = None,
    player_id: uuid.UUID | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[HandOut]:
    q = select(Hand)
    if club_id:
        q = q.where(Hand.club_id == club_id)
    if game_type:
        q = q.where(Hand.game_type == game_type)
    if from_date:
        q = q.where(Hand.hand_started_at >= from_date)
    if to_date:
        q = q.where(Hand.hand_started_at <= to_date)
    if player_id:
        q = q.join(Hand.hand_players).where(HandPlayer.player_id == player_id)

    count_q = select(func.count()).select_from(Hand)
    if club_id:
        count_q = count_q.where(Hand.club_id == club_id)
    if game_type:
        count_q = count_q.where(Hand.game_type == game_type)
    if from_date:
        count_q = count_q.where(Hand.hand_started_at >= from_date)
    if to_date:
        count_q = count_q.where(Hand.hand_started_at <= to_date)
    if player_id:
        count_q = count_q.join(Hand.hand_players).where(HandPlayer.player_id == player_id)
    total: int = await session.scalar(count_q) or 0

    q = q.order_by(Hand.hand_started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(q)
    hands = result.scalars().all()

    return PaginatedResponse(
        items=[HandOut.model_validate(h) for h in hands],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size) < total,
    )


async def get_hand_by_external_id(session: AsyncSession, external_id: str) -> HandDetailOut | None:
    result = await session.execute(
        select(Hand)
        .options(
            selectinload(Hand.hand_players).options(
                selectinload(HandPlayer.actions),
                selectinload(HandPlayer.player),
            ),
            selectinload(Hand.winners),
        )
        .where(Hand.external_id == external_id)
    )
    hand = result.scalar_one_or_none()
    return HandDetailOut.model_validate(hand) if hand else None


async def get_hand(session: AsyncSession, hand_id: uuid.UUID) -> HandDetailOut | None:
    result = await session.execute(
        select(Hand)
        .options(
            selectinload(Hand.hand_players).options(
                selectinload(HandPlayer.actions),
                selectinload(HandPlayer.player),
            ),
            selectinload(Hand.winners),
        )
        .where(Hand.id == hand_id)
    )
    hand = result.scalar_one_or_none()
    return HandDetailOut.model_validate(hand) if hand else None


def _derive_saw_flop(board_cards: str | None, hero_actions: list[Any]) -> bool:
    """
    Return True iff the flop was dealt AND the player did not fold preflop.

    ``board_cards`` is the space-separated community card string stored on the
    Hand row.  3+ cards means the flop was dealt (including all-in run-outs
    where no actions are recorded on the FLOP street).

    ``hero_actions`` is the iterable of PlayerAction ORM objects (or any object
    with ``.street`` and ``.action_type`` attributes) belonging to the hero.
    """
    had_flop = board_cards is not None and len(board_cards.split()) >= 3
    if not had_flop:
        return False
    hero_folded_preflop = any(
        a.street == "PREFLOP" and a.action_type == "FOLD" for a in hero_actions
    )
    return not hero_folded_preflop


def _derive_reached_showdown(did_show: bool, hero_actions: list[Any]) -> bool:
    """
    Return True iff the player participated in a showdown.

    Two paths:
    - ``did_show=True`` on the HandPlayer row (set for explicit shows).
    - A SHOWDOWN-street SHOW or MUCK action exists (parser stores both;
      API may only store did_show).
    """
    if did_show:
        return True
    return any(a.street == "SHOWDOWN" and a.action_type in ("SHOW", "MUCK") for a in hero_actions)


def _derive_won_at_showdown(
    reached_showdown: bool, hero_hp_id: Any, winner_hp_ids: set[Any]
) -> bool:
    """
    Return True iff the player reached showdown AND appears in hand_winners.

    Uncontested pot wins (everyone else folded) are NOT won at showdown —
    ``reached_showdown`` will be False so this returns False correctly.

    Side-pot winners are covered: if the player appears in any winner record
    (main or side), won_at_showdown is True.
    """
    return reached_showdown and hero_hp_id in winner_hp_ids


async def hand_records_for_player(
    session: AsyncSession,
    player_id: uuid.UUID,
    limit: int = 1000,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Load a player's hands from the DB and convert each to a HandRecord.

    Returns ``(records, contexts)`` where:
    - ``records`` is a list of HandRecord instances for compute_player_stats().
    - ``contexts`` maps hand_external_id → HandContext (board_cards, stakes_bb)
      for use by the leak example builder.  Callers that don't need examples
      can discard the second element with ``records, _ = await ...``.

    Design notes
    ------------
    - ``saw_flop`` uses ``_derive_saw_flop``: board_cards-based, handles
      all-in run-outs where no post-flop actions are recorded.
    - ``reached_showdown`` uses ``_derive_reached_showdown``: did_show OR
      explicit SHOW/MUCK action.  No extra DB column needed.
    - ``won_at_showdown`` uses ``_derive_won_at_showdown``: requires both
      reaching showdown AND appearing in hand_winners (any pot).
    - All preflop actions across every player at the table are gathered so
      ``hand_record_from_actions`` can compute 3bet / faced_3bet correctly.
    """
    from app.features.leak_examples import HandContext
    from app.features.player_stats import HandRecord, hand_record_from_actions

    q = (
        select(HandPlayer)
        .where(HandPlayer.player_id == player_id)
        .options(
            selectinload(HandPlayer.hand).options(
                # Load all hand_players + their actions so we can build the
                # full preflop-action list and derive saw_flop/reached_showdown.
                # SQLAlchemy's identity map ensures hero_hp.actions is populated
                # by this load (hero_hp is the same Python object as the matching
                # HandPlayer inside hand.hand_players).
                selectinload(Hand.hand_players).selectinload(HandPlayer.actions),
                selectinload(Hand.winners),
            ),
        )
        .join(HandPlayer.hand)
        .order_by(Hand.hand_started_at.desc())
        .limit(limit)
    )
    if from_date is not None:
        q = q.where(Hand.hand_started_at >= from_date)
    if to_date is not None:
        q = q.where(Hand.hand_started_at <= to_date)

    result = await session.execute(q)
    hero_hand_players = result.scalars().all()

    records: list[HandRecord] = []
    contexts: dict[str, HandContext] = {}
    for hero_hp in hero_hand_players:
        hand = hero_hp.hand

        saw_flop = _derive_saw_flop(hand.board_cards, hero_hp.actions)
        reached_showdown = _derive_reached_showdown(hero_hp.did_show, hero_hp.actions)
        winner_hp_ids = {w.hand_player_id for w in hand.winners}
        won_at_showdown = _derive_won_at_showdown(reached_showdown, hero_hp.id, winner_hp_ids)

        # Build position lookup for all hand_players in this hand.
        # Used by hand_record_from_actions for steal/defend detection.
        hp_positions: dict[str, str | None] = {str(hp.id): hp.position for hp in hand.hand_players}

        all_preflop_actions: list[dict[str, Any]] = [
            {
                "hand_player_id": str(a.hand_player_id),
                "action_type": a.action_type,
                "action_order": a.action_order,
                "position": hp_positions.get(str(a.hand_player_id)),
            }
            for hp in hand.hand_players
            for a in hp.actions
            if a.street == "PREFLOP"
        ]

        # Postflop actions (FLOP/TURN/RIVER only — SHOWDOWN excluded).
        # Street is passed through so _compute_postflop_flags can group by street.
        all_postflop_actions: list[dict[str, Any]] = [
            {
                "hand_player_id": str(a.hand_player_id),
                "action_type": a.action_type,
                "action_order": a.action_order,
                "street": a.street,
            }
            for hp in hand.hand_players
            for a in hp.actions
            if a.street in ("FLOP", "TURN", "RIVER")
        ]

        record = hand_record_from_actions(
            hand_external_id=hand.external_id,
            player_position=hero_hp.position,
            player_stack_bb=hero_hp.stack_bb,
            player_effective_stack_bb=hero_hp.effective_stack_bb,
            this_hand_player_id=str(hero_hp.id),
            all_preflop_actions=all_preflop_actions,
            all_postflop_actions=all_postflop_actions,
            saw_flop=saw_flop,
            reached_showdown=reached_showdown,
            won_at_showdown=won_at_showdown,
        )
        net_bb = (
            hero_hp.net_won / hand.stakes_bb
            if hero_hp.net_won is not None and hand.stakes_bb
            else None
        )
        record = dataclasses.replace(record, has_ante=bool(hand.stakes_ante), net_bb=net_bb)
        records.append(record)
        contexts[hand.external_id] = HandContext(
            board_cards=hand.board_cards,
            stakes_bb=hand.stakes_bb,
        )

    return records, contexts
