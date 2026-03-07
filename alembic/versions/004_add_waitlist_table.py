"""Create waitlist_entries table for landing-page email collection.

Revision ID: 004
Revises: 003
Create Date: 2026-03-08 00:00:00 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the waitlist_entries table."""
    op.create_table(
        "waitlist_entries",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.VARCHAR(255), unique=True, nullable=False),
        sa.Column(
            "source",
            sa.VARCHAR(50),
            nullable=False,
            server_default="'landing'",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_waitlist_created", "waitlist_entries", ["created_at"])


def downgrade() -> None:
    """Drop the waitlist_entries table."""
    op.drop_index("idx_waitlist_created", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
