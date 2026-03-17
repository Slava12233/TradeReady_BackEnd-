"""Change unique constraints from account-scoped to agent-scoped.

Revision ID: 012
Revises: 010
Create Date: 2026-03-15 00:00:00 UTC

The old unique constraints (account_id, asset) and (account_id, symbol) allowed
only one balance/position per account, causing data to be shared across agents.
This migration replaces them with agent-scoped constraints so each agent gets
its own balance and position rows.

Skips migration 011 (drop legacy columns) since the codebase still references
account_id on trading tables during the transition period.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "012"
down_revision: str | None = "010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Replace account-scoped unique constraints with agent-scoped ones."""
    conn = op.get_bind()

    # ── Drop old account-scoped constraints ──────────────────────────────
    # positions: uq_positions_account_symbol is a CONSTRAINT (not plain index)
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint WHERE conname = 'uq_positions_account_symbol' "
            "AND conrelid = 'positions'::regclass"
        )
    )
    if result.fetchone():
        op.drop_constraint("uq_positions_account_symbol", "positions", type_="unique")

    # balances: may be an index named uq_balances_account_asset or uq_balances_account_asset_legacy
    for old_name in ("uq_balances_account_asset", "uq_balances_account_asset_legacy"):
        result = conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
            {"name": old_name},
        )
        if result.fetchone():
            op.drop_index(old_name, table_name="balances")

    # ── Create agent-scoped unique indexes ───────────────────────────────
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_balances_agent_asset'")
    )
    if not result.fetchone():
        op.create_index(
            "uq_balances_agent_asset",
            "balances",
            ["agent_id", "asset"],
            unique=True,
        )

    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_positions_agent_symbol'")
    )
    if not result.fetchone():
        op.create_index(
            "uq_positions_agent_symbol",
            "positions",
            ["agent_id", "symbol"],
            unique=True,
        )


def downgrade() -> None:
    """Drop agent-scoped unique indexes."""
    conn = op.get_bind()

    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_positions_agent_symbol'")
    )
    if result.fetchone():
        op.drop_index("uq_positions_agent_symbol", table_name="positions")

    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = 'uq_balances_agent_asset'")
    )
    if result.fetchone():
        op.drop_index("uq_balances_agent_asset", table_name="balances")
