"""Fix missing ON DELETE CASCADE on agent_id FK constraints for trading tables.

Revision ID: 021
Revises: 020
Create Date: 2026-04-01 00:00:00 UTC

Root cause of BUG-004 (DELETE /agents/{agent_id} returns DATABASE_ERROR):

Migration 008 added ``agent_id`` to the six core trading tables with
``ondelete="SET NULL"``.  Migration 009 then enforced NOT NULL on those same
columns.  The result is an impossible constraint: PostgreSQL cannot set a
NOT NULL column to NULL on cascade, so it refuses to delete the parent
``agents`` row entirely -- raising a FK violation instead.

Tables affected (SET NULL, must become CASCADE):
  - balances               (balances_agent_id_fkey)
  - orders                 (orders_agent_id_fkey)
  - trades                 (trades_agent_id_fkey)
  - positions              (positions_agent_id_fkey)
  - trading_sessions       (trading_sessions_agent_id_fkey)
  - portfolio_snapshots    (portfolio_snapshots_agent_id_fkey)  ← TimescaleDB hypertable

Tables that already have CASCADE (verified in DB, no change needed):
  - agent_sessions, agent_messages, agent_decisions, agent_journal,
    agent_learnings, agent_feedback, agent_permissions, agent_budgets,
    agent_performance, agent_observations, agent_api_calls,
    agent_strategy_signals, backtest_sessions, battle_participants,
    battle_snapshots

Safety notes:
  - Constraint-only change: no data is modified, no columns added/removed.
  - ALTER TABLE … DROP CONSTRAINT … CASCADE is used for ``portfolio_snapshots``
    so that the constraint is dropped from both the parent hypertable AND all
    existing TimescaleDB chunk tables in one atomic DDL statement.  TimescaleDB
    propagates the new FK to future chunks automatically.
  - For regular (non-hypertable) tables a standard drop + create is used.
  - Both upgrade() and downgrade() are fully reversible.
  - Brief ACCESS EXCLUSIVE lock per table during each ALTER — unavoidable for
    FK changes.  Expected duration: sub-second on non-loaded tables.
"""

from __future__ import annotations

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | None = None
depends_on: str | None = None

# Regular (non-hypertable) tables whose agent_id FK must be changed to CASCADE.
# Tuple layout: (table_name, existing_constraint_name)
_REGULAR_TABLES: list[tuple[str, str]] = [
    ("balances", "balances_agent_id_fkey"),
    ("orders", "orders_agent_id_fkey"),
    ("trades", "trades_agent_id_fkey"),
    ("positions", "positions_agent_id_fkey"),
    ("trading_sessions", "trading_sessions_agent_id_fkey"),
]

# portfolio_snapshots is a TimescaleDB hypertable.  Chunk FK constraints share
# the same name pattern but are stored per-chunk.  Using ALTER TABLE … CASCADE
# on the parent drops the constraint from all chunks in one statement.
_HYPERTABLE = "portfolio_snapshots"
_HYPERTABLE_CONSTRAINT = "portfolio_snapshots_agent_id_fkey"


def upgrade() -> None:
    """Replace SET NULL FK constraints with CASCADE on all trading tables."""

    # ── Regular tables ────────────────────────────────────────────────────────
    for table, constraint in _REGULAR_TABLES:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # ── portfolio_snapshots (hypertable) ──────────────────────────────────────
    # DROP CONSTRAINT … CASCADE removes the FK from the parent table AND from
    # every existing TimescaleDB chunk table atomically.
    op.execute(
        f"ALTER TABLE {_HYPERTABLE} "
        f"DROP CONSTRAINT IF EXISTS {_HYPERTABLE_CONSTRAINT} CASCADE"
    )
    op.create_foreign_key(
        _HYPERTABLE_CONSTRAINT,
        _HYPERTABLE,
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Revert CASCADE back to SET NULL on all trading tables.

    Note: after downgrade the schema returns to the original (broken) state
    where agent_id is NOT NULL but the FK action is SET NULL.  This was the
    original defect; do not deploy the downgrade to production unless you have
    a specific reason.
    """

    # ── portfolio_snapshots (hypertable) ──────────────────────────────────────
    op.execute(
        f"ALTER TABLE {_HYPERTABLE} "
        f"DROP CONSTRAINT IF EXISTS {_HYPERTABLE_CONSTRAINT} CASCADE"
    )
    op.create_foreign_key(
        _HYPERTABLE_CONSTRAINT,
        _HYPERTABLE,
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── Regular tables ────────────────────────────────────────────────────────
    for table, constraint in reversed(_REGULAR_TABLES):
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
