"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── clubs ─────────────────────────────────────────────────────────────────
    op.create_table(
        "clubs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_clubs"),
        sa.UniqueConstraint("external_id", name="uq_clubs_external_id"),
    )

    # ── agents ────────────────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("club_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("commission_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_agents_club_id_clubs"),
        sa.ForeignKeyConstraint(["parent_agent_id"], ["agents.id"], name="fk_agents_parent_agent_id_agents"),
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
        sa.UniqueConstraint("external_id", name="uq_agents_external_id"),
    )
    op.create_index("ix_agents_club_id", "agents", ["club_id"])
    op.create_index("ix_agents_parent_agent_id", "agents", ["parent_agent_id"])

    # ── players ───────────────────────────────────────────────────────────────
    op.create_table(
        "players",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("club_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("country_code", sa.CHAR(2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_stub", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_players_club_id_clubs"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name="fk_players_agent_id_agents"),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
        sa.UniqueConstraint("external_id", name="uq_players_external_id"),
    )
    op.create_index("ix_players_club_id", "players", ["club_id"])
    op.create_index("ix_players_agent_id", "players", ["agent_id"])

    # ── game_sessions ─────────────────────────────────────────────────────────
    op.create_table(
        "game_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("club_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("game_type", sa.String(20), nullable=False),
        sa.Column("stakes_sb", sa.Numeric(20, 4), nullable=False),
        sa.Column("stakes_bb", sa.Numeric(20, 4), nullable=False),
        sa.Column("stakes_ante", sa.Numeric(20, 4), nullable=True),
        sa.Column("max_players", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hand_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_game_sessions_club_id_clubs"),
        sa.PrimaryKeyConstraint("id", name="pk_game_sessions"),
        sa.UniqueConstraint("external_id", name="uq_game_sessions_external_id"),
    )
    op.create_index("ix_game_sessions_club_id", "game_sessions", ["club_id"])
    op.create_index("ix_game_sessions_started_at", "game_sessions", ["started_at"])
    op.create_index("ix_game_sessions_status", "game_sessions", ["status"])

    # ── hands ─────────────────────────────────────────────────────────────────
    op.create_table(
        "hands",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("club_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("game_type", sa.String(20), nullable=False),
        sa.Column("stakes_sb", sa.Numeric(20, 4), nullable=False),
        sa.Column("stakes_bb", sa.Numeric(20, 4), nullable=False),
        sa.Column("stakes_ante", sa.Numeric(20, 4), nullable=True),
        sa.Column("table_name", sa.String(255), nullable=True),
        sa.Column("hand_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hand_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_pot", sa.Numeric(20, 4), nullable=False),
        sa.Column("total_rake", sa.Numeric(20, 4), nullable=False, server_default="0"),
        sa.Column("board_cards", sa.String(20), nullable=True),
        sa.Column("player_count", sa.SmallInteger(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("ingestion_source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_hands_club_id_clubs"),
        sa.ForeignKeyConstraint(["game_session_id"], ["game_sessions.id"], name="fk_hands_game_session_id_game_sessions"),
        sa.PrimaryKeyConstraint("id", name="pk_hands"),
        sa.UniqueConstraint("external_id", name="uq_hands_external_id"),
    )
    op.create_index("ix_hands_club_id", "hands", ["club_id"])
    op.create_index("ix_hands_game_session_id", "hands", ["game_session_id"])
    op.create_index("ix_hands_hand_started_at", "hands", ["hand_started_at"])
    op.create_index("ix_hands_game_type", "hands", ["game_type"])

    # ── hand_players ──────────────────────────────────────────────────────────
    op.create_table(
        "hand_players",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seat_number", sa.SmallInteger(), nullable=False),
        sa.Column("starting_stack", sa.Numeric(20, 4), nullable=False),
        sa.Column("ending_stack", sa.Numeric(20, 4), nullable=True),
        sa.Column("hole_cards", sa.String(20), nullable=True),
        sa.Column("did_show", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("net_won", sa.Numeric(20, 4), nullable=True),
        sa.ForeignKeyConstraint(["hand_id"], ["hands.id"], name="fk_hand_players_hand_id_hands"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], name="fk_hand_players_player_id_players"),
        sa.PrimaryKeyConstraint("id", name="pk_hand_players"),
        sa.UniqueConstraint("hand_id", "seat_number", name="uq_hand_players_hand_id_seat_number"),
        sa.UniqueConstraint("hand_id", "player_id", name="uq_hand_players_hand_id_player_id"),
    )
    op.create_index("ix_hand_players_hand_id", "hand_players", ["hand_id"])
    op.create_index("ix_hand_players_player_id", "hand_players", ["player_id"])

    # ── player_actions ────────────────────────────────────────────────────────
    op.create_table(
        "player_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hand_player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("street", sa.String(20), nullable=False),
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("is_all_in", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("action_order", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["hand_id"], ["hands.id"], name="fk_player_actions_hand_id_hands"),
        sa.ForeignKeyConstraint(["hand_player_id"], ["hand_players.id"], name="fk_player_actions_hand_player_id_hand_players"),
        sa.PrimaryKeyConstraint("id", name="pk_player_actions"),
    )
    op.create_index("ix_player_actions_hand_id", "player_actions", ["hand_id"])
    op.create_index("ix_player_actions_hand_player_id", "player_actions", ["hand_player_id"])

    # ── hand_winners ──────────────────────────────────────────────────────────
    op.create_table(
        "hand_winners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hand_player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pot_type", sa.String(20), nullable=False),
        sa.Column("amount_won", sa.Numeric(20, 4), nullable=False),
        sa.Column("winning_hand_description", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["hand_id"], ["hands.id"], name="fk_hand_winners_hand_id_hands"),
        sa.ForeignKeyConstraint(["hand_player_id"], ["hand_players.id"], name="fk_hand_winners_hand_player_id_hand_players"),
        sa.PrimaryKeyConstraint("id", name="pk_hand_winners"),
    )
    op.create_index("ix_hand_winners_hand_id", "hand_winners", ["hand_id"])

    # ── chip_transactions ─────────────────────────────────────────────────────
    op.create_table(
        "chip_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("club_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("counterparty_player_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("counterparty_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("balance_before", sa.Numeric(20, 4), nullable=True),
        sa.Column("balance_after", sa.Numeric(20, 4), nullable=True),
        sa.Column("hand_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("transacted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_chip_transactions_club_id_clubs"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], name="fk_chip_transactions_player_id_players"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], name="fk_chip_transactions_agent_id_agents"),
        sa.ForeignKeyConstraint(["counterparty_player_id"], ["players.id"], name="fk_chip_transactions_counterparty_player_id_players"),
        sa.ForeignKeyConstraint(["counterparty_agent_id"], ["agents.id"], name="fk_chip_transactions_counterparty_agent_id_agents"),
        sa.ForeignKeyConstraint(["hand_id"], ["hands.id"], name="fk_chip_transactions_hand_id_hands"),
        sa.PrimaryKeyConstraint("id", name="pk_chip_transactions"),
        sa.UniqueConstraint("external_id", name="uq_chip_transactions_external_id"),
    )
    op.create_index("ix_chip_transactions_club_id", "chip_transactions", ["club_id"])
    op.create_index("ix_chip_transactions_player_id", "chip_transactions", ["player_id"])
    op.create_index("ix_chip_transactions_agent_id", "chip_transactions", ["agent_id"])
    op.create_index("ix_chip_transactions_transacted_at", "chip_transactions", ["transacted_at"])
    op.create_index("ix_chip_transactions_transaction_type", "chip_transactions", ["transaction_type"])

    # ── seat_assignments ──────────────────────────────────────────────────────
    op.create_table(
        "seat_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("game_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seat_number", sa.SmallInteger(), nullable=False),
        sa.Column("sat_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sat_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("buy_in_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("cash_out_amount", sa.Numeric(20, 4), nullable=True),
        sa.ForeignKeyConstraint(["game_session_id"], ["game_sessions.id"], name="fk_seat_assignments_game_session_id_game_sessions"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], name="fk_seat_assignments_player_id_players"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_assignments"),
        sa.UniqueConstraint("game_session_id", "seat_number", "sat_in_at", name="uq_seat_assignments_game_session_id_seat_number_sat_in_at"),
    )
    op.create_index("ix_seat_assignments_game_session_id", "seat_assignments", ["game_session_id"])
    op.create_index("ix_seat_assignments_player_id", "seat_assignments", ["player_id"])

    # ── ingest_checkpoints ────────────────────────────────────────────────────
    op.create_table(
        "ingest_checkpoints",
        sa.Column("club_id", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(20), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("club_id", "domain", name="pk_ingest_checkpoints"),
    )


def downgrade() -> None:
    op.drop_table("ingest_checkpoints")
    op.drop_table("seat_assignments")
    op.drop_table("chip_transactions")
    op.drop_table("hand_winners")
    op.drop_table("player_actions")
    op.drop_table("hand_players")
    op.drop_table("hands")
    op.drop_table("game_sessions")
    op.drop_table("players")
    op.drop_table("agents")
    op.drop_table("clubs")
