"""add onboarding fields to users

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_complete", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users",
        sa.Column("onboarding_data", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_data")
    op.drop_column("users", "onboarding_complete")
