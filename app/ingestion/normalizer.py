"""
Normalizers convert raw dicts (from ClubGG API responses or the hand parser)
into the typed Pydantic ingestion payload models consumed by the service layer.
"""
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas.ingestion import (
    IngestAgentPayload,
    IngestHandActionPayload,
    IngestHandPayload,
    IngestHandPlayerPayload,
    IngestHandWinnerPayload,
    IngestPlayerPayload,
    IngestTablePayload,
    IngestTransactionPayload,
)
from app.models.hand import ActionType, GameType, Street
from app.models.session import SessionStatus
from app.models.transaction import TransactionType


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _dec(value: str | int | float | Decimal | None, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


# ── API normalizers ───────────────────────────────────────────────────────────


def normalize_api_hand(raw: dict, club_id: str) -> IngestHandPayload:
    """Convert a raw ClubGG API hand dict to IngestHandPayload."""
    players = [
        IngestHandPlayerPayload(
            player_username=p["username"],
            seat_number=int(p["seat"]),
            starting_stack=_dec(p.get("stack")),
            ending_stack=_dec(p["ending_stack"]) if p.get("ending_stack") else None,
            hole_cards=p.get("hole_cards"),
            did_show=bool(p.get("showed")),
        )
        for p in raw.get("players", [])
    ]
    actions = [
        IngestHandActionPayload(
            player_username=a["username"],
            street=Street(a["street"].upper()),
            action_type=ActionType(a["action"].upper()),
            amount=_dec(a["amount"]) if a.get("amount") else None,
            is_all_in=bool(a.get("all_in")),
            action_order=int(a["order"]),
        )
        for a in raw.get("actions", [])
    ]
    winners = [
        IngestHandWinnerPayload(
            player_username=w["username"],
            pot_type=w.get("pot", "main"),
            amount_won=_dec(w["amount"]),
            winning_hand_description=w.get("hand_description"),
        )
        for w in raw.get("winners", [])
    ]
    return IngestHandPayload(
        external_id=str(raw["id"]),
        club_external_id=int(raw.get("club_id", club_id)),
        game_type=GameType(raw.get("game_type", "NLH").upper()),
        stakes_sb=_dec(raw.get("sb")),
        stakes_bb=_dec(raw.get("bb")),
        stakes_ante=_dec(raw["ante"]) if raw.get("ante") else None,
        table_name=raw.get("table_name"),
        hand_started_at=_dt(raw["started_at"]),  # type: ignore[arg-type]
        hand_ended_at=_dt(raw.get("ended_at")),
        total_pot=_dec(raw.get("total_pot")),
        total_rake=_dec(raw.get("rake"), "0"),
        board_cards=raw.get("board"),
        ingestion_source="api",
        players=players,
        actions=actions,
        winners=winners,
    )


def normalize_api_player(raw: dict, club_id: str) -> IngestPlayerPayload:
    return IngestPlayerPayload(
        external_id=int(raw["id"]),
        club_external_id=int(raw.get("club_id", club_id)),
        agent_external_id=int(raw["agent_id"]) if raw.get("agent_id") else None,
        username=raw["username"],
        display_name=raw.get("display_name") or raw.get("nickname"),
        country_code=raw.get("country"),
        is_active=bool(raw.get("active", True)),
    )


def normalize_api_agent(raw: dict, club_id: str) -> IngestAgentPayload:
    return IngestAgentPayload(
        external_id=int(raw["id"]),
        club_external_id=int(raw.get("club_id", club_id)),
        parent_agent_external_id=int(raw["parent_id"]) if raw.get("parent_id") else None,
        username=raw["username"],
        display_name=raw.get("display_name"),
        commission_rate=_dec(raw["commission"]) if raw.get("commission") else None,
        is_active=bool(raw.get("active", True)),
    )


def normalize_api_transaction(raw: dict, club_id: str) -> IngestTransactionPayload:
    return IngestTransactionPayload(
        external_id=str(raw["id"]),
        club_external_id=int(raw.get("club_id", club_id)),
        player_external_id=int(raw["player_id"]) if raw.get("player_id") else None,
        agent_external_id=int(raw["agent_id"]) if raw.get("agent_id") else None,
        counterparty_player_external_id=int(raw["cp_player_id"]) if raw.get("cp_player_id") else None,
        counterparty_agent_external_id=int(raw["cp_agent_id"]) if raw.get("cp_agent_id") else None,
        transaction_type=TransactionType(raw["type"].upper()),
        amount=_dec(raw["amount"]),
        balance_before=_dec(raw["balance_before"]) if raw.get("balance_before") is not None else None,
        balance_after=_dec(raw["balance_after"]) if raw.get("balance_after") is not None else None,
        hand_external_id=str(raw["hand_id"]) if raw.get("hand_id") else None,
        transacted_at=_dt(raw["created_at"]),  # type: ignore[arg-type]
        notes=raw.get("notes"),
    )


def normalize_api_table(raw: dict, club_id: str) -> IngestTablePayload:
    return IngestTablePayload(
        external_id=str(raw["id"]),
        club_external_id=int(raw.get("club_id", club_id)),
        table_name=raw["table_name"],
        game_type=GameType(raw.get("game_type", "NLH").upper()),
        stakes_sb=_dec(raw.get("sb")),
        stakes_bb=_dec(raw.get("bb")),
        stakes_ante=_dec(raw["ante"]) if raw.get("ante") else None,
        max_players=int(raw.get("max_players", 9)),
        status=SessionStatus(raw.get("status", "RUNNING").upper()),
        started_at=_dt(raw["started_at"]),  # type: ignore[arg-type]
        ended_at=_dt(raw.get("ended_at")),
        hand_count=int(raw.get("hand_count", 0)),
    )


# ── File normalizers ──────────────────────────────────────────────────────────


def normalize_file_hand(raw: dict, club_id: str) -> IngestHandPayload:
    """Convert a HandHistoryParser output dict to IngestHandPayload."""
    players = [
        IngestHandPlayerPayload(
            player_username=p["player_username"],
            seat_number=int(p["seat_number"]),
            starting_stack=_dec(p["starting_stack"]),
            ending_stack=_dec(p["ending_stack"]) if p.get("ending_stack") else None,
            hole_cards=p.get("hole_cards"),
            did_show=bool(p.get("did_show", False)),
            position=p.get("position"),
            stack_bb=_dec(p["stack_bb"]) if p.get("stack_bb") is not None else None,
            effective_stack_bb=_dec(p["effective_stack_bb"]) if p.get("effective_stack_bb") is not None else None,
        )
        for p in raw.get("players", [])
    ]
    actions = [
        IngestHandActionPayload(
            player_username=a["player_username"],
            street=Street(a["street"]),
            action_type=ActionType(a["action_type"]),
            amount=_dec(a["amount"]) if a.get("amount") else None,
            is_all_in=bool(a.get("is_all_in", False)),
            action_order=int(a["action_order"]),
        )
        for a in raw.get("actions", [])
    ]
    winners = [
        IngestHandWinnerPayload(
            player_username=w["player_username"],
            pot_type=w.get("pot_type", "main"),
            amount_won=_dec(w["amount_won"]),
            winning_hand_description=w.get("winning_hand_description"),
        )
        for w in raw.get("winners", [])
    ]
    club_ext_id = raw.get("club_external_id") or (int(club_id) if str(club_id).isdigit() else 0)
    return IngestHandPayload(
        external_id=raw["external_id"],
        club_external_id=int(club_ext_id),
        game_type=GameType(raw["game_type"]),
        stakes_sb=_dec(raw["stakes_sb"]),
        stakes_bb=_dec(raw["stakes_bb"]),
        stakes_ante=_dec(raw["stakes_ante"]) if raw.get("stakes_ante") else None,
        table_name=raw.get("table_name"),
        button_seat=raw.get("button_seat"),
        hand_started_at=_dt(raw["hand_started_at"]),  # type: ignore[arg-type]
        hand_ended_at=_dt(raw.get("hand_ended_at")),
        total_pot=_dec(raw["total_pot"]),
        total_rake=_dec(raw.get("total_rake"), "0"),
        board_cards=raw.get("board_cards"),
        raw_text=raw.get("raw_text"),
        ingestion_source="file",
        players=players,
        actions=actions,
        winners=winners,
    )
