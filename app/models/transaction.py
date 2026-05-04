import uuid
from decimal import Decimal
from enum import StrEnum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TransactionType(StrEnum):
    BUYIN = "BUYIN"
    CASHOUT = "CASHOUT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    AGENT_CREDIT = "AGENT_CREDIT"
    AGENT_DEBIT = "AGENT_DEBIT"
    RAKE_BACK = "RAKE_BACK"
    BONUS = "BONUS"
    ADJUSTMENT = "ADJUSTMENT"


class ChipTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chip_transactions"

    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id"), nullable=True, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    counterparty_player_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id"), nullable=True
    )
    counterparty_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    balance_before: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    hand_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hands.id"), nullable=True
    )
    transacted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    player: Mapped["Player | None"] = relationship(  # type: ignore[name-defined]
        "Player",
        foreign_keys=[player_id],
    )
    agent: Mapped["Agent | None"] = relationship(  # type: ignore[name-defined]
        "Agent",
        foreign_keys=[agent_id],
    )
