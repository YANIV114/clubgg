import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.transaction import TransactionType


class ChipTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    club_id: uuid.UUID
    player_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    counterparty_player_id: uuid.UUID | None
    counterparty_agent_id: uuid.UUID | None
    transaction_type: TransactionType
    amount: Decimal
    balance_before: Decimal | None
    balance_after: Decimal | None
    hand_id: uuid.UUID | None
    transacted_at: datetime
    notes: str | None
