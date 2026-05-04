import uuid
from decimal import Decimal
from enum import StrEnum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SessionStatus(StrEnum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class TournamentFormat(StrEnum):
    CASH = "CASH"
    FREEZEOUT = "FREEZEOUT"
    REENTRY = "REENTRY"
    PKO = "PKO"           # Progressive Knockout
    SATELLITE = "SATELLITE"
    SPIN = "SPIN"         # Spin & Go / lottery SNG


class GameSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "game_sessions"

    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    game_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stakes_sb: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    stakes_bb: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    stakes_ante: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    max_players: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hand_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Tournament context ─────────────────────────────────────────────────
    # Defaults to CASH; must be set explicitly for tournament sessions.
    tournament_format: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TournamentFormat.CASH, index=True
    )
    # Number of prize-paying spots (null = unknown / cash game)
    payout_spots: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Total starting chips per player in tournament (null = cash)
    starting_stack_chips: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Whether re-entries are still open at session start
    reentry_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    seat_assignments: Mapped[list["SeatAssignment"]] = relationship(
        "SeatAssignment", back_populates="game_session", cascade="all, delete-orphan"
    )


class SeatAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "seat_assignments"
    __table_args__ = (
        # Same seat can be reoccupied; uniqueness scoped by sat_in_at
        UniqueConstraint("game_session_id", "seat_number", "sat_in_at"),
    )

    game_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.id"), nullable=False, index=True
    )
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id"), nullable=False, index=True
    )
    seat_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sat_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sat_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    buy_in_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    cash_out_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )

    game_session: Mapped["GameSession"] = relationship(
        "GameSession", back_populates="seat_assignments"
    )
