"""Add stop_price column to backtest_trades.

Revision ID: 022
Revises: 021
Create Date: 2026-04-06 00:00:00 UTC

Persists the trigger price for stop-loss and take-profit orders so it
survives backtest completion and is visible in the trade log API.
"""

import sqlalchemy as sa

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "backtest_trades",
        sa.Column("stop_price", sa.Numeric(20, 8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("backtest_trades", "stop_price")
