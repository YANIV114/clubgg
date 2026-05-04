"""normalization context

Adds:
  - tournament_format, payout_spots, starting_stack_chips, reentry_open → game_sessions
  - button_seat, blind_level_index, players_remaining → hands
  - position, stack_bb, effective_stack_bb → hand_players

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── game_sessions ─────────────────────────────────────────────────────
    op.add_column(
        "game_sessions",
        sa.Column(
            "tournament_format",
            sa.String(20),
            nullable=False,
            server_default="CASH",
        ),
    )
    op.add_column(
        "game_sessions",
        sa.Column("payout_spots", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "game_sessions",
        sa.Column("starting_stack_chips", sa.Integer(), nullable=True),
    )
    op.add_column(
        "game_sessions",
        sa.Column("reentry_open", sa.Boolean(), nullable=True),
    )
    op.create_index(
        "ix_game_sessions_tournament_format", "game_sessions", ["tournament_format"]
    )

    # ── hands ─────────────────────────────────────────────────────────────
    op.add_column(
        "hands",
        sa.Column("button_seat", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "hands",
        sa.Column("blind_level_index", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "hands",
        sa.Column("players_remaining", sa.SmallInteger(), nullable=True),
    )

    # ── hand_players ──────────────────────────────────────────────────────
    op.add_column(
        "hand_players",
        sa.Column("position", sa.String(10), nullable=True),
    )
    op.add_column(
        "hand_players",
        sa.Column("stack_bb", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "hand_players",
        sa.Column("effective_stack_bb", sa.Numeric(10, 2), nullable=True),
    )
    op.create_index("ix_hand_players_position", "hand_players", ["position"])


def downgrade() -> None:
    op.drop_index("ix_hand_players_position", "hand_players")
    op.drop_column("hand_players", "effective_stack_bb")
    op.drop_column("hand_players", "stack_bb")
    op.drop_column("hand_players", "position")

    op.drop_column("hands", "players_remaining")
    op.drop_column("hands", "blind_level_index")
    op.drop_column("hands", "button_seat")

    op.drop_index("ix_game_sessions_tournament_format", "game_sessions")
    op.drop_column("game_sessions", "reentry_open")
    op.drop_column("game_sessions", "starting_stack_chips")
    op.drop_column("game_sessions", "payout_spots")
    op.drop_column("game_sessions", "tournament_format")
