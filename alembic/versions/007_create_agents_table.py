"""Create agents table.

Revision ID: 007
Revises: 006
Create Date: 2026-03-12 00:00:00 UTC

Additive-only migration: creates the ``agents`` table and its indexes.
No existing tables are modified.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the agents table with all indexes."""
    op.create_table(
        "agents",
        sa.Column("id", PG_UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("account_id", PG_UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.VARCHAR(100), nullable=False),
        sa.Column("api_key", sa.VARCHAR(128), nullable=False),
        sa.Column("api_key_hash", sa.VARCHAR(128), nullable=False),
        sa.Column("starting_balance", sa.Numeric(20, 8), nullable=False, server_default="10000.00"),
        sa.Column("llm_model", sa.VARCHAR(100), nullable=True),
        sa.Column("framework", sa.VARCHAR(100), nullable=True),
        sa.Column("strategy_tags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("risk_profile", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("color", sa.VARCHAR(7), nullable=True),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # CHECK constraint for status
    op.execute("ALTER TABLE agents ADD CONSTRAINT ck_agents_status CHECK (status IN ('active', 'paused', 'archived'))")

    # Indexes
    op.create_index("idx_agents_account", "agents", ["account_id"])
    op.create_index("idx_agents_api_key", "agents", ["api_key"], unique=True)
    op.create_index("idx_agents_status", "agents", ["status"])


def downgrade() -> None:
    """Drop the agents table."""
    op.drop_index("idx_agents_status", table_name="agents")
    op.drop_index("idx_agents_api_key", table_name="agents")
    op.drop_index("idx_agents_account", table_name="agents")
    op.drop_table("agents")
