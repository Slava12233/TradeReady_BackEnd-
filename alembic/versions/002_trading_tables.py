"""Phase 2 trading tables: accounts, balances, trading_sessions, orders,
trades, positions, portfolio_snapshots (hypertable), audit_log.

Revision ID: 002
Revises: 001
Create Date: 2026-02-24 00:00:00 UTC

This migration creates all Phase 2 database objects:

1. Enable ``uuid-ossp`` and ``pgcrypto`` extensions (for ``gen_random_uuid()``).
2. Create ``accounts`` table with API-key fields and JSONB risk profile.
3. Create ``balances`` table with non-negative CHECK constraints.
4. Create ``trading_sessions`` table.
5. Create ``orders`` table with full lifecycle CHECK constraints and partial
   index on pending orders.
6. Create ``trades`` table with composite time-range indexes.
7. Create ``positions`` table with unique (account_id, symbol) constraint.
8. Create ``portfolio_snapshots`` table and convert it to a TimescaleDB
   hypertable (1-day chunks).
9. Create ``audit_log`` table with BIGSERIAL PK and INET ip_address column.

All foreign-key relationships enforce ``ON DELETE CASCADE`` where the child
row has no independent meaning without its parent account.

The ``downgrade()`` function drops all tables in reverse dependency order,
ensuring referential integrity is preserved during rollback.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply the Phase 2 trading schema."""

    # ── 1. Extensions ─────────────────────────────────────────────────────────
    # uuid-ossp provides gen_random_uuid() on older PG versions; pgcrypto is
    # used by bcrypt helpers.  Both are idempotent (IF NOT EXISTS).
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    # ── 2. accounts ───────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("api_key", sa.VARCHAR(128), unique=True, nullable=False),
        sa.Column("api_key_hash", sa.VARCHAR(128), nullable=False),
        sa.Column("api_secret_hash", sa.VARCHAR(128), nullable=False),
        sa.Column("display_name", sa.VARCHAR(100), nullable=False),
        sa.Column("email", sa.VARCHAR(255), nullable=True),
        sa.Column(
            "starting_balance",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("10000.00"),
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "risk_profile",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_accounts_status",
        ),
    )

    # ── 3. balances ───────────────────────────────────────────────────────────
    op.create_table(
        "balances",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "available",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "locked",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("available >= 0", name="ck_balances_available_non_negative"),
        sa.CheckConstraint("locked >= 0", name="ck_balances_locked_non_negative"),
        sa.UniqueConstraint("account_id", "asset", name="uq_balances_account_asset"),
    )
    op.create_index("idx_balances_account", "balances", ["account_id"])

    # ── 4. trading_sessions ───────────────────────────────────────────────────
    op.create_table(
        "trading_sessions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("starting_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ending_equity", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_sessions_status",
        ),
    )
    op.create_index("idx_sessions_account", "trading_sessions", ["account_id"])

    # ── 5. orders ─────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("trading_sessions.id"),
            nullable=True,
        ),
        sa.Column("symbol", sa.VARCHAR(20), nullable=False),
        sa.Column("side", sa.VARCHAR(4), nullable=False),
        sa.Column("type", sa.VARCHAR(20), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=True),
        sa.Column("executed_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("executed_qty", sa.Numeric(20, 8), nullable=True),
        sa.Column("slippage_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("fee", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("rejection_reason", sa.VARCHAR(100), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("filled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="ck_orders_side"),
        sa.CheckConstraint(
            "type IN ('market', 'limit', 'stop_loss', 'take_profit')",
            name="ck_orders_type",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'filled', 'partially_filled', 'cancelled', 'rejected', 'expired')",
            name="ck_orders_status",
        ),
    )
    op.create_index("idx_orders_account", "orders", ["account_id"])
    op.create_index("idx_orders_account_status", "orders", ["account_id", "status"])
    # Partial index — only rows with status = 'pending' are included so the
    # limit-order matcher can scan open orders cheaply without a full table scan.
    op.execute(
        "CREATE INDEX idx_orders_symbol_status "
        "ON orders (symbol, status) "
        "WHERE status = 'pending';"
    )

    # ── 6. trades ─────────────────────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("trading_sessions.id"),
            nullable=True,
        ),
        sa.Column("symbol", sa.VARCHAR(20), nullable=False),
        sa.Column("side", sa.VARCHAR(4), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quote_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("fee", sa.Numeric(20, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_trades_account", "trades", ["account_id"])
    # Descending on created_at matches the typical query pattern
    # (most-recent trades first per account / per symbol).
    op.execute(
        "CREATE INDEX idx_trades_account_time "
        "ON trades (account_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX idx_trades_symbol "
        "ON trades (symbol, created_at DESC);"
    )

    # ── 7. positions ──────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "side",
            sa.VARCHAR(4),
            nullable=False,
            server_default=sa.text("'long'"),
        ),
        sa.Column(
            "quantity",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("avg_entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "realized_pnl",
            sa.Numeric(20, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "opened_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("account_id", "symbol", name="uq_positions_account_symbol"),
    )
    op.create_index("idx_positions_account", "positions", ["account_id"])

    # ── 8. portfolio_snapshots ────────────────────────────────────────────────
    # TimescaleDB requires the partition column (created_at) to be part of any
    # primary key. We use a composite PK (id, created_at) to satisfy this.
    op.create_table(
        "portfolio_snapshots",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_type", sa.VARCHAR(10), nullable=False),
        sa.Column("total_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("available_cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("position_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("positions", JSONB, nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id", "created_at", name="pk_portfolio_snapshots"),
        sa.CheckConstraint(
            "snapshot_type IN ('minute', 'hourly', 'daily')",
            name="ck_snapshots_type",
        ),
    )
    # Composite index covers the common query: fetch snapshots for an account
    # filtered by type, ordered by time descending.
    op.create_index(
        "idx_snapshots_account_type",
        "portfolio_snapshots",
        ["account_id", "snapshot_type", "created_at"],
    )

    # Convert to TimescaleDB hypertable — 1-day chunks on created_at.
    # migrate_data=FALSE is safe because the table is brand-new.
    op.execute(
        "SELECT create_hypertable('portfolio_snapshots', 'created_at', "
        "chunk_time_interval => INTERVAL '1 day', "
        "migrate_data => FALSE);"
    )

    # ── 9. audit_log ──────────────────────────────────────────────────────────
    # Uses BIGSERIAL (auto-increment) rather than UUID so insertion order is
    # preserved for forensic analysis without relying on timestamp resolution.
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=True,
        ),
        sa.Column("action", sa.VARCHAR(50), nullable=False),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("ip_address", INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_audit_account",
        "audit_log",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    """Remove all Phase 2 schema objects in reverse dependency order."""

    # Drop in reverse dependency order so FK constraints are not violated.
    # audit_log has a nullable FK to accounts — drop it first.
    op.drop_index("idx_audit_account", table_name="audit_log")
    op.drop_table("audit_log")

    # portfolio_snapshots is a hypertable; DROP TABLE cascades to chunks.
    op.drop_index("idx_snapshots_account_type", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")

    op.drop_index("idx_positions_account", table_name="positions")
    op.drop_table("positions")

    op.execute("DROP INDEX IF EXISTS idx_trades_symbol;")
    op.execute("DROP INDEX IF EXISTS idx_trades_account_time;")
    op.drop_index("idx_trades_account", table_name="trades")
    op.drop_table("trades")

    op.execute("DROP INDEX IF EXISTS idx_orders_symbol_status;")
    op.drop_index("idx_orders_account_status", table_name="orders")
    op.drop_index("idx_orders_account", table_name="orders")
    op.drop_table("orders")

    op.drop_index("idx_sessions_account", table_name="trading_sessions")
    op.drop_table("trading_sessions")

    op.drop_index("idx_balances_account", table_name="balances")
    op.drop_table("balances")

    op.drop_table("accounts")
