import uuid
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Club(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "clubs"

    external_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="club")
    players: Mapped[list["Player"]] = relationship("Player", back_populates="club")


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    external_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    parent_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commission_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    club: Mapped["Club"] = relationship("Club", back_populates="agents")
    parent: Mapped["Agent | None"] = relationship(
        "Agent", remote_side="Agent.id", back_populates="children"
    )
    children: Mapped[list["Agent"]] = relationship("Agent", back_populates="parent")
    players: Mapped[list["Player"]] = relationship("Player", back_populates="agent")


class Player(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "players"

    external_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set True when player was auto-created during hand ingestion before a full player sync
    is_stub: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    club: Mapped["Club"] = relationship("Club", back_populates="players")
    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="players")
