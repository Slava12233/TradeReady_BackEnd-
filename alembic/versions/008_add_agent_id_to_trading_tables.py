"""Add nullable agent_id column to trading tables.

Revision ID: 008
Revises: 007
Create Date: 2026-03-12 00:00:00 UTC

Adds a nullable ``agent_id`` (UUID, FK → agents.id) column to:
balances, orders, trades, positions, trading_sessions, portfolio_snapshots.

Does NOT drop account_id — both columns coexist during the transition period.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | None = None
depends_on: str | None = None

_TABLES = ["balances", "orders", "trades", "positions", "trading_sessions", "portfolio_snapshots"]


def upgrade() -> None:
    """Add nullable agent_id FK column and index to each trading table."""
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "agent_id",
                PG_UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"idx_{table}_agent", table, ["agent_id"])


def downgrade() -> None:
    """Remove agent_id column from each trading table."""
    for table in reversed(_TABLES):
        op.drop_index(f"idx_{table}_agent", table_name=table)
        op.drop_column(table, "agent_id")
