"""Backtesting tables: backtest_sessions, backtest_trades, backtest_snapshots
(hypertable), and new columns on accounts (current_mode, active_strategy_label).

Revision ID: 005
Revises: 004
Create Date: 2026-03-09 00:00:00 UTC

This migration creates all backtesting database objects:

1. Add ``current_mode`` and ``active_strategy_label`` columns to ``accounts``.
2. Create ``backtest_sessions`` table with full lifecycle and results columns.
3. Create ``backtest_trades`` table for simulated trade fills.
4. Create ``backtest_snapshots`` table and convert it to a TimescaleDB
   hypertable (1-day chunks on ``simulated_at``).

All foreign keys use ``ON DELETE CASCADE`` so deleting a session removes its
trades and snapshots, and deleting an account removes all its sessions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply the backtesting schema."""

    # ── 1. Add columns to accounts ──────────────────────────────────────────
    op.add_column(
        "accounts",
        sa.Column(
            "current_mode",
            sa.VARCHAR(10),
            nullable=False,
            server_default="live",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "active_strategy_label",
            sa.VARCHAR(100),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_accounts_mode",
        "accounts",
        "current_mode IN ('live', 'backtest')",
    )

    # ── 2. backtest_sessions ────────────────────────────────────────────────
    op.create_table(
        "backtest_sessions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy_label", sa.VARCHAR(100), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="created",
        ),
        sa.Column("candle_interval", sa.Integer, nullable=False, server_default="60"),
        sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("starting_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("pairs", JSONB, nullable=True),
        sa.Column("virtual_clock", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_step", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_steps", sa.Integer, nullable=False, server_default="0"),
        sa.Column("progress_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("final_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column("total_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("roi_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("total_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_fees", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_real_sec", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('created', 'running', 'paused', 'completed', 'failed', 'cancelled')",
            name="ck_bt_sessions_status",
        ),
    )

    op.create_index("idx_bt_sessions_account", "backtest_sessions", ["account_id"])
    op.create_index("idx_bt_sessions_account_status", "backtest_sessions", ["account_id", "status"])
    op.create_index("idx_bt_sessions_account_strategy", "backtest_sessions", ["account_id", "strategy_label"])
    op.execute(
        "CREATE INDEX idx_bt_sessions_account_roi "
        "ON backtest_sessions (account_id, roi_pct DESC NULLS LAST)"
    )

    # ── 3. backtest_trades ──────────────────────────────────────────────────
    op.create_table(
        "backtest_trades",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("backtest_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.VARCHAR(20), nullable=False),
        sa.Column("side", sa.VARCHAR(4), nullable=False),
        sa.Column("type", sa.VARCHAR(20), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quote_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("fee", sa.Numeric(20, 8), nullable=False),
        sa.Column("slippage_pct", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("simulated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_bt_trades_side"),
        sa.CheckConstraint(
            "type IN ('market', 'limit', 'stop_loss', 'take_profit')",
            name="ck_bt_trades_type",
        ),
    )

    op.create_index("idx_bt_trades_session", "backtest_trades", ["session_id"])
    op.create_index("idx_bt_trades_session_time", "backtest_trades", ["session_id", "simulated_at"])

    # ── 4. backtest_snapshots (TimescaleDB hypertable) ──────────────────────
    op.create_table(
        "backtest_snapshots",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("simulated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("backtest_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("available_cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("position_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("positions", JSONB, nullable=True),
        # Composite PK required by TimescaleDB (partition column must be in PK).
        sa.PrimaryKeyConstraint("id", "simulated_at"),
    )

    # Convert to hypertable with 1-day chunks.
    op.execute(
        "SELECT create_hypertable('backtest_snapshots', 'simulated_at', "
        "chunk_time_interval => INTERVAL '1 day', migrate_data => true);"
    )

    op.create_index(
        "idx_bt_snapshots_session_time",
        "backtest_snapshots",
        ["session_id", "simulated_at"],
    )


def downgrade() -> None:
    """Reverse the backtesting schema."""

    op.drop_table("backtest_snapshots")
    op.drop_table("backtest_trades")
    op.drop_table("backtest_sessions")

    op.drop_constraint("ck_accounts_mode", "accounts", type_="check")
    op.drop_column("accounts", "active_strategy_label")
    op.drop_column("accounts", "current_mode")
