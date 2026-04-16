"""Add email_verified column to accounts.

Revision ID: 024
Revises: 023
Create Date: 2026-04-16 00:00:00 UTC

Additive-only migration.  Adds a nullable-then-defaulted ``email_verified``
boolean column to the ``accounts`` table.  All existing rows get
``email_verified = FALSE`` via the server default, which is safe for
zero-downtime deployment — no backfill script is required because the
semantically correct default (unverified) is the same as the new column
default.

Columns added:
  email_verified  BOOLEAN NOT NULL DEFAULT FALSE
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add email_verified column to accounts table."""
    op.add_column(
        "accounts",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    """Remove email_verified column from accounts table."""
    op.drop_column("accounts", "email_verified")
