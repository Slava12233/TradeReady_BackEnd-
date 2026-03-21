"""Add agent logging tables (api calls and strategy signals) and trace_id to decisions.

Revision ID: 018
Revises: 017
Create Date: 2026-03-21 00:00:00 UTC

Additive-only migration.  Three changes:

1. New table ``agent_api_calls`` -- records every outbound API / SDK / MCP / DB
   call made by an agent for observability.  ``trace_id`` groups all calls
   belonging to a single decision cycle.

2. New table ``agent_strategy_signals`` -- records per-strategy signals before
   ensemble combination, keyed by the same ``trace_id``.

3. New nullable column ``trace_id VARCHAR(32)`` on ``agent_decisions`` so that
   decisions can be linked to the call and signal records that produced them.
   Nullable because existing rows have no trace identifier.

Both new tables are regular PostgreSQL tables (NOT TimescaleDB hypertables).
All foreign keys to ``agents.id`` use ``ondelete="CASCADE"``.
Safe for zero-downtime production deployment.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create agent_api_calls, agent_strategy_signals; add trace_id to agent_decisions."""

    # ── agent_api_calls ───────────────────────────────────────────────────────
    op.create_table(
        "agent_api_calls",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("trace_id", sa.VARCHAR(32), nullable=False),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.VARCHAR(10), nullable=False),
        sa.Column("endpoint", sa.VARCHAR(200), nullable=False),
        sa.Column("method", sa.VARCHAR(10), nullable=True),
        sa.Column("status_code", sa.SmallInteger(), nullable=True),
        sa.Column("latency_ms", sa.Numeric(10, 2), nullable=True),
        sa.Column("request_size", sa.Integer(), nullable=True),
        sa.Column("response_size", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "channel IN ('sdk', 'mcp', 'rest', 'db')",
            name="ck_agent_api_calls_channel",
        ),
    )
    # Composite index for the common query pattern: fetch all calls for an
    # agent grouped by trace, ordered by created_at within each trace.
    op.create_index(
        "ix_agent_api_calls_agent_trace",
        "agent_api_calls",
        ["agent_id", "trace_id"],
    )
    # Stand-alone created_at index for time-range purge / observability queries.
    op.create_index(
        "ix_agent_api_calls_created_at",
        "agent_api_calls",
        ["created_at"],
    )

    # ── agent_strategy_signals ────────────────────────────────────────────────
    op.create_table(
        "agent_strategy_signals",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("trace_id", sa.VARCHAR(32), nullable=False),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("strategy_name", sa.VARCHAR(50), nullable=False),
        sa.Column("symbol", sa.VARCHAR(20), nullable=False),
        sa.Column("action", sa.VARCHAR(10), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("weight", sa.Numeric(5, 4), nullable=True),
        sa.Column("signal_data", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "action IN ('buy', 'sell', 'hold')",
            name="ck_agent_strategy_signals_action",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_agent_strategy_signals_confidence",
        ),
        sa.CheckConstraint(
            "weight IS NULL OR (weight >= 0 AND weight <= 1)",
            name="ck_agent_strategy_signals_weight",
        ),
    )
    # trace_id lookup: retrieve all strategy signals for one decision cycle.
    op.create_index(
        "ix_agent_strategy_signals_trace_id",
        "agent_strategy_signals",
        ["trace_id"],
    )
    # Composite index for agent-scoped time-range queries.
    op.create_index(
        "ix_agent_signals_agent_created",
        "agent_strategy_signals",
        ["agent_id", "created_at"],
    )

    # ── agent_decisions.trace_id ──────────────────────────────────────────────
    # Nullable: existing rows have no trace_id; new decisions will populate it.
    op.add_column(
        "agent_decisions",
        sa.Column("trace_id", sa.VARCHAR(32), nullable=True),
    )
    op.create_index(
        "ix_agent_decisions_trace_id",
        "agent_decisions",
        ["trace_id"],
    )


def downgrade() -> None:
    """Remove trace_id from agent_decisions; drop agent_strategy_signals and agent_api_calls."""

    # Reverse order: column added last is removed first.
    op.drop_index("ix_agent_decisions_trace_id", table_name="agent_decisions")
    op.drop_column("agent_decisions", "trace_id")

    # agent_strategy_signals: indexes first, then table.
    op.drop_index("ix_agent_signals_agent_created", table_name="agent_strategy_signals")
    op.drop_index("ix_agent_strategy_signals_trace_id", table_name="agent_strategy_signals")
    op.drop_table("agent_strategy_signals")

    # agent_api_calls: indexes first, then table.
    op.drop_index("ix_agent_api_calls_created_at", table_name="agent_api_calls")
    op.drop_index("ix_agent_api_calls_agent_trace", table_name="agent_api_calls")
    op.drop_table("agent_api_calls")
