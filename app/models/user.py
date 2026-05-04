from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="player")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    onboarding_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    onboarding_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_tester: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
