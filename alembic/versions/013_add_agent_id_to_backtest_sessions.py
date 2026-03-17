"""Add nullable agent_id column to backtest_sessions.

Revision ID: 013
Revises: 012
Create Date: 2026-03-17 00:00:00 UTC

Adds a nullable ``agent_id`` (UUID, FK → agents.id) column to backtest_sessions
so that backtests can be scoped to a specific agent rather than just an account.

This is step 1 of the two-step migration pattern:
  013 — add nullable column + indexes
  014 — enforce NOT NULL (run after backfill script has been verified)
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add nullable agent_id FK column and indexes to backtest_sessions."""
    op.add_column(
        "backtest_sessions",
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("idx_bt_sessions_agent", "backtest_sessions", ["agent_id"])
    op.create_index("idx_bt_sessions_agent_status", "backtest_sessions", ["agent_id", "status"])


def downgrade() -> None:
    """Remove agent_id column from backtest_sessions."""
    op.drop_index("idx_bt_sessions_agent_status", table_name="backtest_sessions")
    op.drop_index("idx_bt_sessions_agent", table_name="backtest_sessions")
    op.drop_column("backtest_sessions", "agent_id")
