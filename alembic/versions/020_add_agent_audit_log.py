"""Add agent_audit_log table for durable permission check audit trail.

Revision ID: 020
Revises: 019
Create Date: 2026-03-23 00:00:00 UTC

Additive-only migration.  Creates a new ``agent_audit_log`` table that
stores every permission check outcome ("allow" or "deny") made by the
:class:`~agent.permissions.enforcement.PermissionEnforcer`.

Previously only "deny" events were persisted (to the ``agent_feedback``
table as a workaround).  This dedicated table records both outcomes so
that a complete, durable audit trail survives process restarts.

Columns:
  id           UUID PK (gen_random_uuid)
  agent_id     UUID NOT NULL (no FK — records survive agent deletion)
  action       VARCHAR(100) NOT NULL
  outcome      VARCHAR(10) NOT NULL CHECK IN ('allow', 'deny')
  reason       TEXT nullable
  trade_value  NUMERIC(20, 8) nullable — monetary value of the authorised trade
  metadata     JSONB nullable — caller-supplied context at check time
  created_at   TIMESTAMP WITH TIME ZONE NOT NULL default now()

Indexes:
  idx_agent_audit_log_agent_id      — per-agent queries
  idx_agent_audit_log_created_at    — time-range pruning / monitoring
  idx_agent_audit_log_agent_created — composite for per-agent time-range

No FK to ``agents.id`` is intentional: audit records should outlive the
agent they describe.  The table is a regular PostgreSQL table, NOT a
TimescaleDB hypertable, to keep the schema simple.

Safe for zero-downtime production deployment.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create agent_audit_log table with indexes."""

    op.create_table(
        "agent_audit_log",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action", sa.VARCHAR(100), nullable=False),
        sa.Column("outcome", sa.VARCHAR(10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("trade_value", sa.Numeric(20, 8), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('allow', 'deny')",
            name="ck_agent_audit_log_outcome",
        ),
    )

    op.create_index(
        "idx_agent_audit_log_agent_id",
        "agent_audit_log",
        ["agent_id"],
    )
    op.create_index(
        "idx_agent_audit_log_created_at",
        "agent_audit_log",
        ["created_at"],
    )
    op.create_index(
        "idx_agent_audit_log_agent_created",
        "agent_audit_log",
        ["agent_id", "created_at"],
    )


def downgrade() -> None:
    """Drop agent_audit_log table and all its indexes."""

    op.drop_index("idx_agent_audit_log_agent_created", table_name="agent_audit_log")
    op.drop_index("idx_agent_audit_log_created_at", table_name="agent_audit_log")
    op.drop_index("idx_agent_audit_log_agent_id", table_name="agent_audit_log")
    op.drop_table("agent_audit_log")
