"""add unique constraint to hand_winners (hand_player_id, pot_type)

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-19

Fixes duplicate HandWinner rows created on re-ingestion: the ON CONFLICT DO
NOTHING in upsert_hand() had no effect because HandWinner had no unique
constraint — every insert got a new auto-generated UUID primary key and
always succeeded.  Adding (hand_player_id, pot_type) as a unique key means
re-uploading the same hand history file skips existing winner records cleanly.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove duplicate rows before adding the constraint: keep the first
    # inserted row (lowest ctid) for each (hand_player_id, pot_type) pair.
    op.execute("""
        DELETE FROM hand_winners hw
        WHERE hw.id NOT IN (
            SELECT DISTINCT ON (hand_player_id, pot_type) id
            FROM hand_winners
            ORDER BY hand_player_id, pot_type, id
        )
    """)
    op.create_unique_constraint(
        "uq_hand_winners_hand_player_id_pot_type",
        "hand_winners",
        ["hand_player_id", "pot_type"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_hand_winners_hand_player_id_pot_type",
        "hand_winners",
        type_="unique",
    )
