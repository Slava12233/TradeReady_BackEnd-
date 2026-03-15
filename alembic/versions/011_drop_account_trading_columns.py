"""Drop legacy account trading columns and account_id from trading tables.

Revision ID: 011
Revises: 010
Create Date: 2026-03-15 00:00:00 UTC

Now that all code uses agent_id exclusively, this migration:
1. Drops api_key, api_key_hash, api_secret_hash, starting_balance,
   risk_profile from the accounts table.
2. Drops account_id FK columns from trading tables (balances, orders,
   trades, positions, trading_sessions, portfolio_snapshots).

IMPORTANT: Only apply this migration AFTER verifying all code paths
use agent_id instead of account_id for trading operations.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | None = None
depends_on: str | None = None

_TRADING_TABLES = [
    "balances",
    "orders",
    "trades",
    "positions",
    "trading_sessions",
    "portfolio_snapshots",
]


def upgrade() -> None:
    """Drop legacy columns from accounts and account_id from trading tables."""
    # 1. Drop account trading columns
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("api_key")
        batch_op.drop_column("api_key_hash")
        batch_op.drop_column("api_secret_hash")
        batch_op.drop_column("starting_balance")
        batch_op.drop_column("risk_profile")

    # 2. Drop account_id from trading tables
    for table in _TRADING_TABLES:
        with op.batch_alter_table(table) as batch_op:
            # Drop FK constraint first (name follows SQLAlchemy convention)
            try:
                batch_op.drop_constraint(f"fk_{table}_account_id_accounts", type_="foreignkey")
            except Exception:  # noqa: BLE001, S110
                pass  # Constraint may not exist or have a different name
            batch_op.drop_column("account_id")


def downgrade() -> None:
    """Restore legacy columns to accounts and account_id to trading tables."""
    # 1. Restore account_id to trading tables (nullable for rollback safety)
    for table in reversed(_TRADING_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("account_id", sa.UUID(), nullable=True)
            )
            batch_op.create_foreign_key(
                f"fk_{table}_account_id_accounts",
                "accounts",
                ["account_id"],
                ["id"],
            )

    # 2. Restore account columns (nullable for rollback safety)
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column("api_key", sa.VARCHAR(128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("api_key_hash", sa.VARCHAR(128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("api_secret_hash", sa.VARCHAR(128), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "starting_balance",
                sa.Numeric(20, 8),
                nullable=True,
                server_default="10000",
            )
        )
        batch_op.add_column(
            sa.Column(
                "risk_profile",
                JSONB,
                nullable=True,
                server_default="{}",
            )
        )
