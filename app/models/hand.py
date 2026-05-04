import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GameType(StrEnum):
    NLH = "NLH"
    PLO = "PLO"
    PLO5 = "PLO5"
    OFC = "OFC"
    SHORT_DECK = "SHORT_DECK"


class ActionType(StrEnum):
    FOLD = "FOLD"
    CHECK = "CHECK"
    CALL = "CALL"
    BET = "BET"
    RAISE = "RAISE"
    ALL_IN = "ALL_IN"
    POST_SB = "POST_SB"
    POST_BB = "POST_BB"
    POST_ANTE = "POST_ANTE"
    MUCK = "MUCK"
    SHOW = "SHOW"


class Street(StrEnum):
    PREFLOP = "PREFLOP"
    FLOP = "FLOP"
    TURN = "TURN"
    RIVER = "RIVER"
    SHOWDOWN = "SHOWDOWN"


class Hand(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hands"

    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    game_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.id"), nullable=True, index=True
    )
    game_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    stakes_sb: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    stakes_bb: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    stakes_ante: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hand_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    hand_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_pot: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    total_rake: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0")
    )
    # Space-separated card strings e.g. "Ah Kd 2c Ts 9h"
    board_cards: Mapped[str | None] = mapped_column(String(20), nullable=True)
    player_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingestion_source: Mapped[str] = mapped_column(String(20), nullable=False)  # "api" | "file"

    # ── Normalization context ──────────────────────────────────────────────
    # Which seat held the dealer button this hand.
    # Required for position computation. NULL when unavailable (older API data).
    button_seat: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Blind level index within the tournament structure (null = cash / unknown).
    blind_level_index: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Players remaining in tournament at start of this hand (null = cash / unknown).
    # SPECULATIVE if inferred; OBSERVED if provided by API.
    players_remaining: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    hand_players: Mapped[list["HandPlayer"]] = relationship(
        "HandPlayer", back_populates="hand", cascade="all, delete-orphan"
    )
    winners: Mapped[list["HandWinner"]] = relationship(
        "HandWinner", back_populates="hand", cascade="all, delete-orphan"
    )


class HandPlayer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "hand_players"
    __table_args__ = (
        UniqueConstraint("hand_id", "seat_number"),
        UniqueConstraint("hand_id", "player_id"),
    )

    hand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hands.id"), nullable=False, index=True
    )
    player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("players.id"), nullable=False, index=True
    )
    seat_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    starting_stack: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    ending_stack: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)

    # ── Normalized fields (DERIVED) ────────────────────────────────────────
    # Position label: BTN/CO/HJ/MP/UTG/BB/SB/UNKNOWN
    # Computed from seat_number + button_seat at normalization time.
    position: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    # Starting stack in big blinds (chips / bb_size). DERIVED.
    stack_bb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Effective stack in big blinds: min(hero_bb, deepest_opponent_bb). DERIVED.
    effective_stack_bb: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    # e.g. "As Kh"
    hole_cards: Mapped[str | None] = mapped_column(String(20), nullable=True)
    did_show: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    net_won: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)

    hand: Mapped["Hand"] = relationship("Hand", back_populates="hand_players")
    player: Mapped["Player"] = relationship("Player", foreign_keys=[player_id], lazy="noload")
    actions: Mapped[list["PlayerAction"]] = relationship(
        "PlayerAction", back_populates="hand_player", cascade="all, delete-orphan"
    )

    @property
    def username(self) -> str | None:
        try:
            return self.player.username if self.player is not None else None
        except Exception:
            return None


class PlayerAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "player_actions"
    __table_args__ = (UniqueConstraint("hand_id", "action_order"),)

    hand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hands.id"), nullable=False, index=True
    )
    hand_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hand_players.id"), nullable=False, index=True
    )
    street: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    is_all_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    hand_player: Mapped["HandPlayer"] = relationship("HandPlayer", back_populates="actions")


class HandWinner(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "hand_winners"
    __table_args__ = (UniqueConstraint("hand_player_id", "pot_type"),)

    hand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hands.id"), nullable=False, index=True
    )
    hand_player_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hand_players.id"), nullable=False
    )
    pot_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "main" | "side_1" etc.
    amount_won: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    winning_hand_description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    hand: Mapped["Hand"] = relationship("Hand", back_populates="winners")
