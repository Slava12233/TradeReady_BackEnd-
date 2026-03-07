"""Add password_hash column to accounts and unique index on email.

Revision ID: 003
Revises: 002
Create Date: 2026-03-07 00:00:00 UTC

Changes:
1. Add nullable ``password_hash`` VARCHAR(128) column to ``accounts``.
   Existing rows are unaffected (column defaults to NULL).
2. Create a partial unique index on ``accounts.email`` so that email
   becomes the login identifier for human users while still allowing
   rows where email is NULL (agent-only accounts).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply password_hash column and unique email index."""

    op.add_column(
        "accounts",
        sa.Column("password_hash", sa.VARCHAR(128), nullable=True),
    )

    # Partial unique index: only enforce uniqueness where email IS NOT NULL,
    # preserving rows that have no email (API-key-only agent accounts).
    op.create_index(
        "uq_accounts_email",
        "accounts",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    """Reverse the password_hash column and unique email index."""

    op.drop_index("uq_accounts_email", table_name="accounts")
    op.drop_column("accounts", "password_hash")
