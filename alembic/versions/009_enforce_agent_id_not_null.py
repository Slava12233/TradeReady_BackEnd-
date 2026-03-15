"""Enforce agent_id NOT NULL on trading tables.

Revision ID: 009
Revises: 008
Create Date: 2026-03-12 00:00:00 UTC

After the data backfill script has populated agent_id on all existing rows,
this migration sets the column to NOT NULL. The account_id columns are
kept for backward compatibility during the transition period (dropped in
Phase 6.6).

IMPORTANT: Run scripts/backfill_agent_ids.py BEFORE applying this migration.
"""

from __future__ import annotations

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | None = None
depends_on: str | None = None

_TABLES = ["balances", "orders", "trades", "positions", "trading_sessions", "portfolio_snapshots"]


def upgrade() -> None:
    """Set agent_id to NOT NULL on all trading tables."""
    for table in _TABLES:
        op.alter_column(table, "agent_id", nullable=False)


def downgrade() -> None:
    """Revert agent_id to nullable on all trading tables."""
    for table in reversed(_TABLES):
        op.alter_column(table, "agent_id", nullable=True)
