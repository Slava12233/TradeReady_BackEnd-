"""Add webhook_subscriptions table.

Revision ID: 023
Revises: 022
Create Date: 2026-04-07 00:00:00 UTC

Additive-only migration.  Creates a new ``webhook_subscriptions`` table
that stores per-account outbound webhook endpoint registrations.

When a subscribed event fires (e.g. ``order.filled``, ``trade.executed``),
the platform makes a POST request to the registered ``url`` with a JSON
payload signed via ``secret`` using HMAC-SHA256.

Columns:
  id                 UUID PK (gen_random_uuid)
  account_id         UUID NOT NULL FK → accounts.id ON DELETE CASCADE
  url                VARCHAR(2048) NOT NULL
  events             JSONB NOT NULL default '[]'
  secret             VARCHAR(128) NOT NULL
  description        VARCHAR(255) nullable
  active             BOOLEAN NOT NULL default TRUE
  failure_count      INTEGER NOT NULL default 0
  created_at         TIMESTAMP WITH TIME ZONE NOT NULL default now()
  updated_at         TIMESTAMP WITH TIME ZONE NOT NULL default now()
  last_triggered_at  TIMESTAMP WITH TIME ZONE nullable

Indexes:
  idx_webhook_subscriptions_account_id — per-account queries
  idx_webhook_subscriptions_active     — filter enabled subscriptions

Safe for zero-downtime production deployment.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create webhook_subscriptions table with indexes."""

    op.create_table(
        "webhook_subscriptions",
        sa.Column(
            "id",
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "account_id",
            PG_UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("url", sa.VARCHAR(2048), nullable=False),
        sa.Column(
            "events",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("secret", sa.VARCHAR(128), nullable=False),
        sa.Column("description", sa.VARCHAR(255), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_triggered_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "idx_webhook_subscriptions_account_id",
        "webhook_subscriptions",
        ["account_id"],
    )
    op.create_index(
        "idx_webhook_subscriptions_active",
        "webhook_subscriptions",
        ["active"],
    )


def downgrade() -> None:
    """Drop webhook_subscriptions table and all its indexes."""

    op.drop_index("idx_webhook_subscriptions_active", table_name="webhook_subscriptions")
    op.drop_index("idx_webhook_subscriptions_account_id", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")
