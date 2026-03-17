"""Enforce agent_id NOT NULL on backtest_sessions.

Revision ID: 014
Revises: 013
Create Date: 2026-03-17 00:00:00 UTC

Step 2 of the agent-scoped backtesting migration.
Only run AFTER the backfill script (scripts/backfill_backtest_agent_ids.py)
has been executed and verified — all rows must have a non-null agent_id.
"""

from __future__ import annotations

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Make agent_id NOT NULL on backtest_sessions."""
    op.alter_column(
        "backtest_sessions",
        "agent_id",
        nullable=False,
    )


def downgrade() -> None:
    """Revert agent_id to nullable on backtest_sessions."""
    op.alter_column(
        "backtest_sessions",
        "agent_id",
        nullable=True,
    )
