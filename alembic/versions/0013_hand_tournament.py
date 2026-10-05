"""Add tournament id and name to hands.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hands", sa.Column("tournament_external_id", sa.String(32), nullable=True))
    op.add_column("hands", sa.Column("tournament_name", sa.String(255), nullable=True))
    op.create_index("ix_hands_tournament_external_id", "hands", ["tournament_external_id"])


def downgrade() -> None:
    op.drop_index("ix_hands_tournament_external_id", table_name="hands")
    op.drop_column("hands", "tournament_name")
    op.drop_column("hands", "tournament_external_id")
