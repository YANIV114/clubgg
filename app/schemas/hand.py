import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.hand import ActionType, GameType, Street


class PlayerActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    street: Street
    action_type: ActionType
    amount: Decimal | None
    is_all_in: bool
    action_order: int


class HandPlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_id: uuid.UUID
    seat_number: int
    starting_stack: Decimal
    ending_stack: Decimal | None
    hole_cards: str | None
    did_show: bool
    net_won: Decimal | None
    position: str | None = None
    stack_bb: Decimal | None = None
    effective_stack_bb: Decimal | None = None
    username: str | None = None
    actions: list[PlayerActionOut] = []


class HandWinnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hand_player_id: uuid.UUID
    pot_type: str
    amount_won: Decimal
    winning_hand_description: str | None


class HandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    club_id: uuid.UUID
    game_session_id: uuid.UUID | None
    game_type: GameType
    stakes_sb: Decimal
    stakes_bb: Decimal
    stakes_ante: Decimal | None
    table_name: str | None
    hand_started_at: datetime
    hand_ended_at: datetime | None
    total_pot: Decimal
    total_rake: Decimal
    board_cards: str | None
    player_count: int
    ingestion_source: str


class HandDetailOut(HandOut):
    button_seat: int | None = None
    hand_players: list[HandPlayerOut]
    winners: list[HandWinnerOut]
