import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ClubOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: int
    name: str
    currency: str
    is_active: bool


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: int
    club_id: uuid.UUID
    parent_agent_id: uuid.UUID | None
    username: str
    display_name: str | None
    commission_rate: Decimal | None
    is_active: bool


class PlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: int
    club_id: uuid.UUID
    agent_id: uuid.UUID | None
    username: str
    display_name: str | None
    country_code: str | None
    is_active: bool
    is_stub: bool
    hand_count: int = 0


class PlayerDetailOut(PlayerOut):
    agent: AgentOut | None
    club: ClubOut


class PlayerSampleOut(BaseModel):
    hand_count: int
    tournament_count: int
    first_hand_at: datetime | None
    last_hand_at: datetime | None
    last_updated_at: datetime | None
