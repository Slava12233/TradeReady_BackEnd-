"""Add feedback lifecycle columns to agent_feedback.

Revision ID: 019
Revises: 018
Create Date: 2026-03-21 00:00:00 UTC

Additive migration with one constraint update.  Changes to ``agent_feedback``:

1. New column ``resolution TEXT`` (nullable) — short resolution summary set
   by operators when closing a feedback item.  Distinct from the existing
   ``resolution_notes`` column which holds operator triage notes.

2. Updated CHECK constraint ``ck_agent_feedback_status`` — adds ``submitted``
   as an allowed status value alongside the existing values (``new``,
   ``acknowledged``, ``in_progress``, ``resolved``, ``wont_fix``).  Both
   ``submitted`` and ``new`` remain valid so that existing rows are not
   invalidated by the migration.

3. Updated server-default on ``status`` from ``'new'`` to ``'submitted'``
   for newly inserted rows going forward.

The ``resolved_at`` column already exists (added in migration 017); this
migration does not touch it.

Safe for zero-downtime production deployment.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add resolution column; update status check constraint and server default."""

    # 1. Add resolution column (nullable — existing rows have no resolution).
    op.add_column(
        "agent_feedback",
        sa.Column("resolution", sa.Text(), nullable=True),
    )

    # 2. Drop the old check constraint and recreate it with 'submitted' added.
    #    PostgreSQL does not support ALTER CONSTRAINT for CHECK constraints, so
    #    we must drop and recreate.
    op.drop_constraint("ck_agent_feedback_status", "agent_feedback", type_="check")
    op.create_check_constraint(
        "ck_agent_feedback_status",
        "agent_feedback",
        "status IN ('submitted', 'new', 'acknowledged', 'in_progress', 'resolved', 'wont_fix')",
    )

    # 3. Update the column server default from 'new' to 'submitted'.
    #    This only affects new rows; existing rows are untouched.
    op.alter_column(
        "agent_feedback",
        "status",
        server_default=sa.text("'submitted'"),
        existing_type=sa.VARCHAR(20),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Remove resolution column; restore original status check constraint and default."""

    # Reverse order: restore server default first, then constraint, then column.
    op.alter_column(
        "agent_feedback",
        "status",
        server_default=sa.text("'new'"),
        existing_type=sa.VARCHAR(20),
        existing_nullable=False,
    )

    op.drop_constraint("ck_agent_feedback_status", "agent_feedback", type_="check")
    op.create_check_constraint(
        "ck_agent_feedback_status",
        "agent_feedback",
        "status IN ('new', 'acknowledged', 'in_progress', 'resolved', 'wont_fix')",
    )

    op.drop_column("agent_feedback", "resolution")
