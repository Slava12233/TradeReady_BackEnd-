"""Create battle tables.

Revision ID: 010
Revises: 009
Create Date: 2026-03-15 00:00:00 UTC

Creates ``battles``, ``battle_participants``, and ``battle_snapshots`` tables
with all indexes and constraints.  ``battle_snapshots`` is converted to a
TimescaleDB hypertable for efficient time-series queries.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create battle tables with indexes and hypertable."""
    # ── battles ───────────────────────────────────────────────────────────────
    op.create_table(
        "battles",
        sa.Column("id", PG_UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", PG_UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="'draft'"),
        sa.Column("config", JSONB, nullable=False, server_default="'{}'"),
        sa.Column("preset", sa.VARCHAR(50), nullable=True),
        sa.Column("ranking_metric", sa.VARCHAR(30), nullable=False, server_default="'roi_pct'"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        "ALTER TABLE battles ADD CONSTRAINT ck_battles_status "
        "CHECK (status IN ('draft', 'pending', 'active', 'paused', 'completed', 'cancelled'))"
    )
    op.execute(
        "ALTER TABLE battles ADD CONSTRAINT ck_battles_ranking_metric "
        "CHECK (ranking_metric IN ('roi_pct', 'total_pnl', 'sharpe_ratio', 'win_rate', 'profit_factor'))"
    )
    op.create_index("idx_battles_account", "battles", ["account_id"])
    op.create_index("idx_battles_status", "battles", ["account_id", "status"])

    # ── battle_participants ───────────────────────────────────────────────────
    op.create_table(
        "battle_participants",
        sa.Column("id", PG_UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("battle_id", PG_UUID(as_uuid=True), sa.ForeignKey("battles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", PG_UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_balance", sa.Numeric(20, 8), nullable=True),
        sa.Column("final_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("final_rank", sa.Integer, nullable=True),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="'active'"),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        "ALTER TABLE battle_participants ADD CONSTRAINT ck_bp_status "
        "CHECK (status IN ('active', 'paused', 'stopped', 'blown_up'))"
    )
    op.create_index("idx_bp_battle", "battle_participants", ["battle_id"])
    op.create_index("idx_bp_agent", "battle_participants", ["agent_id"])
    op.create_index("uq_bp_battle_agent", "battle_participants", ["battle_id", "agent_id"], unique=True)

    # ── battle_snapshots ──────────────────────────────────────────────────────
    op.create_table(
        "battle_snapshots",
        sa.Column("id", sa.BigInteger, autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("battle_id", PG_UUID(as_uuid=True), sa.ForeignKey("battles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", PG_UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("trade_count", sa.Integer, nullable=True),
        sa.Column("open_positions", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )

    # Convert to TimescaleDB hypertable
    op.execute("SELECT create_hypertable('battle_snapshots', 'timestamp')")

    op.create_index("idx_battle_snap", "battle_snapshots", ["battle_id", "agent_id", "timestamp"])


def downgrade() -> None:
    """Drop battle tables."""
    op.drop_index("idx_battle_snap", table_name="battle_snapshots")
    op.drop_table("battle_snapshots")

    op.drop_index("uq_bp_battle_agent", table_name="battle_participants")
    op.drop_index("idx_bp_agent", table_name="battle_participants")
    op.drop_index("idx_bp_battle", table_name="battle_participants")
    op.drop_table("battle_participants")

    op.drop_index("idx_battles_status", table_name="battles")
    op.drop_index("idx_battles_account", table_name="battles")
    op.drop_table("battles")
