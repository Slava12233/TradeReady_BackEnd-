"""Create strategy and training tables.

Revision ID: 016
Revises: 015
Create Date: 2026-03-18 00:00:00 UTC

Adds six new tables for the strategy registry and training observation system:

- ``strategies``              — strategy metadata and lifecycle
- ``strategy_versions``       — immutable versioned strategy definitions
- ``strategy_test_runs``      — multi-episode test run orchestration
- ``strategy_test_episodes``  — individual test episode results
- ``training_runs``           — RL training run tracking
- ``training_episodes``       — individual training episode results

All changes are additive — safe for production with no data loss.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | None = None
depends_on: str | None = None

def _accounts_fk() -> sa.ForeignKey:
    return sa.ForeignKey("accounts.id", ondelete="CASCADE")

def _strategies_fk() -> sa.ForeignKey:
    return sa.ForeignKey("strategies.id", ondelete="CASCADE")

def _strategies_fk_null() -> sa.ForeignKey:
    return sa.ForeignKey("strategies.id", ondelete="SET NULL")


def upgrade() -> None:
    """Create strategy and training tables with indexes."""
    # -- strategies
    op.create_table(
        "strategies",
        sa.Column(
            "id", PG_UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", PG_UUID(as_uuid=True), _accounts_fk(), nullable=False),
        sa.Column("name", sa.VARCHAR(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("current_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="draft"),
        sa.Column("deployed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'validated', 'deployed', 'archived')",
            name="ck_strategies_status",
        ),
    )
    op.create_index("idx_strategies_account", "strategies", ["account_id"])
    op.create_index("idx_strategies_status", "strategies", ["status"])

    # -- strategy_versions
    op.create_table(
        "strategy_versions",
        sa.Column(
            "id", PG_UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", PG_UUID(as_uuid=True), _strategies_fk(), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column("change_notes", sa.Text, nullable=True),
        sa.Column("parent_version", sa.Integer, nullable=True),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="draft"),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("strategy_id", "version", name="uq_sv_strategy_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'validated', 'deployed')",
            name="ck_sv_status",
        ),
    )
    op.create_index("idx_sv_strategy", "strategy_versions", ["strategy_id"])

    # -- strategy_test_runs
    op.create_table(
        "strategy_test_runs",
        sa.Column(
            "id", PG_UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", PG_UUID(as_uuid=True), _strategies_fk(), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("episodes_total", sa.Integer, nullable=False),
        sa.Column("episodes_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="queued"),
        sa.Column("results", JSONB, nullable=True),
        sa.Column("recommendations", JSONB, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_str_status",
        ),
    )
    op.create_index("idx_str_strategy", "strategy_test_runs", ["strategy_id"])

    # -- strategy_test_episodes
    _str_run_fk = sa.ForeignKey("strategy_test_runs.id", ondelete="CASCADE")
    op.create_table(
        "strategy_test_episodes",
        sa.Column(
            "id", PG_UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("test_run_id", PG_UUID(as_uuid=True), _str_run_fk, nullable=False),
        sa.Column("episode_number", sa.Integer, nullable=False),
        sa.Column(
            "backtest_session_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("backtest_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_ste_test_run", "strategy_test_episodes", ["test_run_id"])

    # -- training_runs
    _tr_acct_fk = sa.ForeignKey("accounts.id", ondelete="CASCADE")
    op.create_table(
        "training_runs",
        sa.Column(
            "id", PG_UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("account_id", PG_UUID(as_uuid=True), _tr_acct_fk, nullable=False),
        sa.Column(
            "strategy_id", PG_UUID(as_uuid=True),
            _strategies_fk_null(), nullable=True,
        ),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("episodes_total", sa.Integer, nullable=True),
        sa.Column("episodes_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.VARCHAR(20), nullable=False, server_default="running"),
        sa.Column("aggregate_stats", JSONB, nullable=True),
        sa.Column("learning_curve", JSONB, nullable=True),
        sa.Column(
            "started_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_tr_status",
        ),
    )
    op.create_index("idx_tr_account", "training_runs", ["account_id"])

    # -- training_episodes
    _te_run_fk = sa.ForeignKey("training_runs.id", ondelete="CASCADE")
    op.create_table(
        "training_episodes",
        sa.Column(
            "id", PG_UUID(as_uuid=True), nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "training_run_id", PG_UUID(as_uuid=True), _te_run_fk, nullable=False,
        ),
        sa.Column("episode_number", sa.Integer, nullable=False),
        sa.Column(
            "backtest_session_id", PG_UUID(as_uuid=True),
            sa.ForeignKey("backtest_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_te_training_run", "training_episodes", ["training_run_id"])


def downgrade() -> None:
    """Drop strategy and training tables in reverse dependency order."""
    op.drop_index("idx_te_training_run", table_name="training_episodes")
    op.drop_table("training_episodes")

    op.drop_index("idx_tr_account", table_name="training_runs")
    op.drop_table("training_runs")

    op.drop_index("idx_ste_test_run", table_name="strategy_test_episodes")
    op.drop_table("strategy_test_episodes")

    op.drop_index("idx_str_strategy", table_name="strategy_test_runs")
    op.drop_table("strategy_test_runs")

    op.drop_index("idx_sv_strategy", table_name="strategy_versions")
    op.drop_table("strategy_versions")

    op.drop_index("idx_strategies_status", table_name="strategies")
    op.drop_index("idx_strategies_account", table_name="strategies")
    op.drop_table("strategies")
