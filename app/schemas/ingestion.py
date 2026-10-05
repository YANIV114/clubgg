"""
Internal Pydantic schemas used by the ingestion layer to carry normalized
data between ingestors, normalizers, and service-layer upsert functions.
These are NOT exposed via the HTTP API.
"""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.models.hand import ActionType, GameType, Street
from app.models.session import SessionStatus
from app.models.transaction import TransactionType


class IngestClubPayload(BaseModel):
    external_id: int
    name: str
    currency: str = "USD"
    is_active: bool = True


class IngestAgentPayload(BaseModel):
    external_id: int
    club_external_id: int
    parent_agent_external_id: int | None = None
    username: str
    display_name: str | None = None
    commission_rate: Decimal | None = None
    is_active: bool = True


class IngestPlayerPayload(BaseModel):
    external_id: int
    club_external_id: int
    agent_external_id: int | None = None
    username: str
    display_name: str | None = None
    country_code: str | None = None
    is_active: bool = True


class IngestHandActionPayload(BaseModel):
    player_username: str
    street: Street
    action_type: ActionType
    amount: Decimal | None = None
    is_all_in: bool = False
    action_order: int


class IngestHandPlayerPayload(BaseModel):
    player_username: str
    seat_number: int
    starting_stack: Decimal
    ending_stack: Decimal | None = None
    hole_cards: str | None = None
    did_show: bool = False
    # Populated by the normalization pipeline
    position: str | None = None          # e.g. "BTN", "CO", None if unknown
    stack_bb: Decimal | None = None      # DERIVED: starting_stack / bb_size
    effective_stack_bb: Decimal | None = None  # DERIVED: min(hero_bb, deepest_opp_bb)


class IngestHandWinnerPayload(BaseModel):
    player_username: str
    pot_type: str
    amount_won: Decimal
    winning_hand_description: str | None = None


class IngestHandPayload(BaseModel):
    external_id: str
    club_external_id: int
    game_type: GameType
    stakes_sb: Decimal
    stakes_bb: Decimal
    stakes_ante: Decimal | None = None
    table_name: str | None = None
    hand_started_at: datetime
    hand_ended_at: datetime | None = None
    total_pot: Decimal
    total_rake: Decimal = Decimal("0")
    board_cards: str | None = None
    raw_text: str | None = None
    ingestion_source: Literal["api", "file"]
    # Normalization context
    button_seat: int | None = None
    blind_level_index: int | None = None
    players_remaining: int | None = None
    tournament_external_id: str | None = None
    tournament_name: str | None = None
    players: list[IngestHandPlayerPayload]
    actions: list[IngestHandActionPayload]
    winners: list[IngestHandWinnerPayload]


class IngestTransactionPayload(BaseModel):
    external_id: str
    club_external_id: int
    player_external_id: int | None = None
    agent_external_id: int | None = None
    counterparty_player_external_id: int | None = None
    counterparty_agent_external_id: int | None = None
    transaction_type: TransactionType
    amount: Decimal
    balance_before: Decimal | None = None
    balance_after: Decimal | None = None
    hand_external_id: str | None = None
    transacted_at: datetime
    notes: str | None = None


class IngestTablePayload(BaseModel):
    external_id: str
    club_external_id: int
    table_name: str
    game_type: GameType
    stakes_sb: Decimal
    stakes_bb: Decimal
    stakes_ante: Decimal | None = None
    max_players: int
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    hand_count: int = 0
