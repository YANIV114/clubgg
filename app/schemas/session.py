import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.session import SessionStatus
from app.models.hand import GameType


class SeatAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    player_id: uuid.UUID
    seat_number: int
    sat_in_at: datetime
    sat_out_at: datetime | None
    buy_in_amount: Decimal
    cash_out_amount: Decimal | None


class GameSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    club_id: uuid.UUID
    table_name: str
    game_type: GameType
    stakes_sb: Decimal
    stakes_bb: Decimal
    stakes_ante: Decimal | None
    max_players: int
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None
    hand_count: int


class GameSessionDetailOut(GameSessionOut):
    seat_assignments: list[SeatAssignmentOut]
