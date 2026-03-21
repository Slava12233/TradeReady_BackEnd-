"""Create agent ecosystem tables.

Revision ID: 017
Revises: 016
Create Date: 2026-03-20 00:00:00 UTC

Adds ten new tables that power the agent cognitive/memory layer:

- ``agent_sessions``      -- conversation sessions per agent
- ``agent_messages``      -- chat history per session
- ``agent_decisions``     -- trade decisions with full reasoning context
- ``agent_journal``       -- trading journal entries (reflections, insights)
- ``agent_learnings``     -- extracted knowledge / memory records
- ``agent_feedback``      -- platform improvement ideas raised by agents
- ``agent_permissions``   -- per-agent capability map (unique per agent)
- ``agent_budgets``       -- daily/weekly trade limits (unique per agent)
- ``agent_performance``   -- rolling strategy stats by period
- ``agent_observations``  -- market snapshots at decision points (hypertable)

``agent_observations`` is converted to a TimescaleDB hypertable partitioned
by ``time`` with 1-day chunks.  The composite PK ``(time, agent_id)`` satisfies
the TimescaleDB requirement that the partition column is part of the primary key.

All changes are purely additive -- no existing tables are modified.
Safe for zero-downtime production deployment.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | None = None
depends_on: str | None = None


# ── FK helpers ─────────────────────────────────────────────────────────────────


def _agents_fk() -> sa.ForeignKey:
    return sa.ForeignKey("agents.id", ondelete="CASCADE")


def _accounts_fk() -> sa.ForeignKey:
    return sa.ForeignKey("accounts.id", ondelete="CASCADE")


def upgrade() -> None:
    """Create all 10 agent ecosystem tables and convert agent_observations to hypertable."""

    # ── agent_sessions ────────────────────────────────────────────────────────
    op.create_table(
        "agent_sessions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column("title", sa.VARCHAR(255), nullable=True),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "message_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agent_sessions_agent_created", "agent_sessions", ["agent_id", "created_at"])
    op.create_index("idx_agent_sessions_active", "agent_sessions", ["agent_id", "is_active"])

    # ── agent_messages ────────────────────────────────────────────────────────
    op.create_table(
        "agent_messages",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.VARCHAR(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tool_calls", JSONB, nullable=True),
        sa.Column("tool_results", JSONB, nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="ck_agent_messages_role",
        ),
    )
    op.create_index(
        "idx_agent_messages_session_created", "agent_messages", ["session_id", "created_at"]
    )

    # ── agent_decisions ───────────────────────────────────────────────────────
    op.create_table(
        "agent_decisions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column(
            "session_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision_type", sa.VARCHAR(20), nullable=False),
        sa.Column("symbol", sa.VARCHAR(20), nullable=True),
        sa.Column("direction", sa.VARCHAR(10), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column("market_snapshot", JSONB, nullable=True),
        sa.Column("signals", JSONB, nullable=True),
        sa.Column("risk_assessment", JSONB, nullable=True),
        sa.Column(
            "order_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome_pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("outcome_recorded_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "decision_type IN ('trade', 'hold', 'exit', 'rebalance')",
            name="ck_agent_decisions_type",
        ),
        sa.CheckConstraint(
            "direction IN ('buy', 'sell', 'hold')",
            name="ck_agent_decisions_direction",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_agent_decisions_confidence",
        ),
    )
    op.create_index(
        "idx_agent_decisions_agent_created", "agent_decisions", ["agent_id", "created_at"]
    )
    op.create_index("idx_agent_decisions_session", "agent_decisions", ["session_id"])
    op.create_index("idx_agent_decisions_order", "agent_decisions", ["order_id"])

    # ── agent_journal ─────────────────────────────────────────────────────────
    op.create_table(
        "agent_journal",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column("entry_type", sa.VARCHAR(30), nullable=False),
        sa.Column("title", sa.VARCHAR(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("market_context", JSONB, nullable=True),
        sa.Column("related_decisions", JSONB, nullable=True),
        sa.Column("tags", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "entry_type IN ('reflection', 'insight', 'mistake', 'improvement', "
            "'daily_review', 'weekly_review')",
            name="ck_agent_journal_type",
        ),
    )
    op.create_index(
        "idx_agent_journal_agent_created", "agent_journal", ["agent_id", "created_at"]
    )
    op.create_index("idx_agent_journal_type", "agent_journal", ["agent_id", "entry_type"])

    # ── agent_learnings ───────────────────────────────────────────────────────
    op.create_table(
        "agent_learnings",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column("memory_type", sa.VARCHAR(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("times_reinforced", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_accessed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Nullable JSONB placeholder for future vector embedding integration.
        sa.Column("embedding", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "memory_type IN ('episodic', 'semantic', 'procedural')",
            name="ck_agent_learnings_memory_type",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_agent_learnings_confidence",
        ),
    )
    op.create_index(
        "idx_agent_learnings_agent_created", "agent_learnings", ["agent_id", "created_at"]
    )
    op.create_index("idx_agent_learnings_type", "agent_learnings", ["agent_id", "memory_type"])
    op.create_index("idx_agent_learnings_expires", "agent_learnings", ["agent_id", "expires_at"])
    # GIN index on embedding JSONB for future similarity queries.
    op.create_index(
        "idx_agent_learnings_embedding_gin",
        "agent_learnings",
        ["embedding"],
        postgresql_using="gin",
    )

    # ── agent_feedback ────────────────────────────────────────────────────────
    op.create_table(
        "agent_feedback",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column("category", sa.VARCHAR(30), nullable=False),
        sa.Column("title", sa.VARCHAR(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column(
            "priority",
            sa.VARCHAR(10),
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ('missing_data', 'missing_tool', 'performance_issue', "
            "'bug', 'feature_request')",
            name="ck_agent_feedback_category",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_agent_feedback_priority",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'acknowledged', 'in_progress', 'resolved', 'wont_fix')",
            name="ck_agent_feedback_status",
        ),
    )
    op.create_index(
        "idx_agent_feedback_agent_created", "agent_feedback", ["agent_id", "created_at"]
    )
    op.create_index("idx_agent_feedback_status", "agent_feedback", ["status"])

    # ── agent_permissions ─────────────────────────────────────────────────────
    op.create_table(
        "agent_permissions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column(
            "role",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'paper_trader'"),
        ),
        sa.Column(
            "capabilities",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("granted_by", PG_UUID(as_uuid=True), _accounts_fk(), nullable=False),
        sa.Column(
            "granted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_permissions_agent"),
        sa.CheckConstraint(
            "role IN ('viewer', 'paper_trader', 'live_trader', 'admin')",
            name="ck_agent_permissions_role",
        ),
    )
    # The unique index doubles as the lookup index for the one-row-per-agent constraint.
    op.create_index(
        "idx_agent_permissions_agent", "agent_permissions", ["agent_id"], unique=True
    )
    op.create_index("idx_agent_permissions_granted_by", "agent_permissions", ["granted_by"])

    # ── agent_budgets ─────────────────────────────────────────────────────────
    op.create_table(
        "agent_budgets",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column("max_trades_per_day", sa.Integer, nullable=True),
        sa.Column("max_exposure_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_daily_loss_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_position_size_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("trades_today", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "exposure_today",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "loss_today",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_reset_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_budgets_agent"),
    )
    op.create_index("idx_agent_budgets_agent", "agent_budgets", ["agent_id"], unique=True)

    # ── agent_performance ─────────────────────────────────────────────────────
    op.create_table(
        "agent_performance",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column("strategy_name", sa.VARCHAR(100), nullable=False),
        sa.Column("period", sa.VARCHAR(10), nullable=False),
        sa.Column("period_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("period_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("total_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column("winning_trades", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "total_pnl",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0",
        ),
        sa.Column("sharpe_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("win_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("avg_trade_duration", sa.Interval, nullable=True),
        sa.Column(
            "extra_metrics",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "period IN ('daily', 'weekly', 'monthly')",
            name="ck_agent_performance_period",
        ),
        sa.CheckConstraint(
            "win_rate IS NULL OR (win_rate >= 0 AND win_rate <= 1)",
            name="ck_agent_performance_win_rate",
        ),
    )
    op.create_index(
        "idx_agent_performance_agent_created", "agent_performance", ["agent_id", "created_at"]
    )
    op.create_index(
        "idx_agent_performance_agent_period",
        "agent_performance",
        ["agent_id", "period", "period_start"],
    )
    op.create_index(
        "idx_agent_performance_strategy", "agent_performance", ["agent_id", "strategy_name"]
    )

    # ── agent_observations (TimescaleDB hypertable) ───────────────────────────
    # Composite PK (time, agent_id) is required: TimescaleDB mandates the
    # partition column (time) is part of the primary key.
    op.create_table(
        "agent_observations",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("agent_id", PG_UUID(as_uuid=True), _agents_fk(), nullable=False),
        sa.Column(
            "decision_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prices", JSONB, nullable=True),
        sa.Column("indicators", JSONB, nullable=True),
        sa.Column("regime", sa.VARCHAR(50), nullable=True),
        sa.Column("portfolio_state", JSONB, nullable=True),
        sa.Column("signals", JSONB, nullable=True),
        sa.PrimaryKeyConstraint("time", "agent_id"),
    )
    # Convert to TimescaleDB hypertable partitioned by time (1-day chunks).
    op.execute(
        "SELECT create_hypertable('agent_observations', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    op.create_index("idx_agent_obs_agent_time", "agent_observations", ["agent_id", "time"])
    op.create_index("idx_agent_obs_decision", "agent_observations", ["decision_id"])


def downgrade() -> None:
    """Drop all agent ecosystem tables in reverse dependency order."""

    # agent_observations has no dependents; drop first (hypertable — indexes first).
    op.drop_index("idx_agent_obs_decision", table_name="agent_observations")
    op.drop_index("idx_agent_obs_agent_time", table_name="agent_observations")
    op.drop_table("agent_observations")

    # agent_performance
    op.drop_index("idx_agent_performance_strategy", table_name="agent_performance")
    op.drop_index("idx_agent_performance_agent_period", table_name="agent_performance")
    op.drop_index("idx_agent_performance_agent_created", table_name="agent_performance")
    op.drop_table("agent_performance")

    # agent_budgets
    op.drop_index("idx_agent_budgets_agent", table_name="agent_budgets")
    op.drop_table("agent_budgets")

    # agent_permissions
    op.drop_index("idx_agent_permissions_granted_by", table_name="agent_permissions")
    op.drop_index("idx_agent_permissions_agent", table_name="agent_permissions")
    op.drop_table("agent_permissions")

    # agent_feedback
    op.drop_index("idx_agent_feedback_status", table_name="agent_feedback")
    op.drop_index("idx_agent_feedback_agent_created", table_name="agent_feedback")
    op.drop_table("agent_feedback")

    # agent_learnings
    op.drop_index("idx_agent_learnings_embedding_gin", table_name="agent_learnings")
    op.drop_index("idx_agent_learnings_expires", table_name="agent_learnings")
    op.drop_index("idx_agent_learnings_type", table_name="agent_learnings")
    op.drop_index("idx_agent_learnings_agent_created", table_name="agent_learnings")
    op.drop_table("agent_learnings")

    # agent_journal
    op.drop_index("idx_agent_journal_type", table_name="agent_journal")
    op.drop_index("idx_agent_journal_agent_created", table_name="agent_journal")
    op.drop_table("agent_journal")

    # agent_decisions references agent_sessions (SET NULL FK) and orders (SET NULL FK);
    # drop before sessions so the FK on agent_observations -> agent_decisions is gone first.
    op.drop_index("idx_agent_decisions_order", table_name="agent_decisions")
    op.drop_index("idx_agent_decisions_session", table_name="agent_decisions")
    op.drop_index("idx_agent_decisions_agent_created", table_name="agent_decisions")
    op.drop_table("agent_decisions")

    # agent_messages depends on agent_sessions; drop before sessions.
    op.drop_index("idx_agent_messages_session_created", table_name="agent_messages")
    op.drop_table("agent_messages")

    # agent_sessions: no remaining dependents.
    op.drop_index("idx_agent_sessions_active", table_name="agent_sessions")
    op.drop_index("idx_agent_sessions_agent_created", table_name="agent_sessions")
    op.drop_table("agent_sessions")
