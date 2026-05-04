"""add unique constraint to player_actions (hand_id, action_order)

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-19

action_order is a global monotonically-increasing counter per hand, so
(hand_id, action_order) is naturally unique. Without this constraint the
ON CONFLICT DO NOTHING in upsert_hand() had no effect and re-ingesting the
same file duplicated every action row.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Remove duplicate rows before adding the constraint.
    op.execute("""
        DELETE FROM player_actions pa
        WHERE pa.id NOT IN (
            SELECT DISTINCT ON (hand_id, action_order) id
            FROM player_actions
            ORDER BY hand_id, action_order, id
        )
    """)
    op.create_unique_constraint(
        "uq_player_actions_hand_id_action_order",
        "player_actions",
        ["hand_id", "action_order"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_player_actions_hand_id_action_order",
        "player_actions",
        type_="unique",
    )
