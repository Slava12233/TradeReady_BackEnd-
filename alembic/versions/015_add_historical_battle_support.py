"""Add historical battle support columns.

Revision ID: 015
Revises: 014
Create Date: 2026-03-17 00:00:00 UTC

Adds ``battle_mode`` and ``backtest_config`` to the ``battles`` table, and
``backtest_session_id`` (FK → backtest_sessions.id) to ``battle_participants``.

All changes are additive — safe for production with no data loss.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add battle_mode, backtest_config to battles and backtest_session_id to battle_participants."""
    # -- battles: battle_mode column with CHECK constraint
    op.add_column(
        "battles",
        sa.Column(
            "battle_mode",
            sa.VARCHAR(20),
            nullable=False,
            server_default="live",
        ),
    )
    op.create_check_constraint(
        "ck_battles_mode",
        "battles",
        "battle_mode IN ('live', 'historical')",
    )

    # -- battles: backtest_config JSONB (nullable)
    op.add_column(
        "battles",
        sa.Column(
            "backtest_config",
            JSONB,
            nullable=True,
        ),
    )

    # -- battle_participants: backtest_session_id FK
    op.add_column(
        "battle_participants",
        sa.Column(
            "backtest_session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("backtest_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_bp_backtest_session",
        "battle_participants",
        ["backtest_session_id"],
    )


def downgrade() -> None:
    """Remove historical battle support columns."""
    op.drop_index("idx_bp_backtest_session", table_name="battle_participants")
    op.drop_column("battle_participants", "backtest_session_id")
    op.drop_column("battles", "backtest_config")
    op.drop_constraint("ck_battles_mode", "battles", type_="check")
    op.drop_column("battles", "battle_mode")
