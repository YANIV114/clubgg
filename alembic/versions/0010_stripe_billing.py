"""add stripe columns to subscriptions

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("stripe_customer_id", sa.String(255), nullable=True))
    op.add_column(
        "subscriptions", sa.Column("stripe_subscription_id", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "stripe_subscription_id")
    op.drop_column("subscriptions", "stripe_customer_id")
