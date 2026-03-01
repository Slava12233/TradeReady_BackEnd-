"""Initial schema: ticks hypertable, continuous aggregates, trading_pairs.

Revision ID: 001
Revises: (none)
Create Date: 2026-02-23 00:00:00 UTC

This migration creates all Phase 1 database objects:

1. Enable the TimescaleDB extension.
2. Create the ``ticks`` table and convert it to a hypertable (1-hour chunks).
3. Add indexes, compression settings, and retention/compression policies.
4. Create four continuous aggregates: ``candles_1m``, ``candles_5m``,
   ``candles_1h``, ``candles_1d`` with refresh policies.
5. Create the ``trading_pairs`` reference table.

All TimescaleDB-specific DDL is executed via ``op.execute()`` because there
is no SQLAlchemy / Alembic native equivalent for hypertables or continuous
aggregates.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Apply the initial Phase 1 schema."""

    # ── 1. Enable TimescaleDB extension ──────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

    # ── 2. Create ticks table ────────────────────────────────────────────────
    op.create_table(
        "ticks",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "is_buyer_maker",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("trade_id", sa.BigInteger(), nullable=False),
    )

    # ── 3. Convert ticks to a TimescaleDB hypertable (1-hour chunks) ─────────
    op.execute(
        "SELECT create_hypertable('ticks', 'time', "
        "chunk_time_interval => INTERVAL '1 hour');"
    )

    # ── 4. Indexes ────────────────────────────────────────────────────────────
    # Primary lookup: symbol + descending time range scans
    op.execute(
        "CREATE INDEX idx_ticks_symbol_time ON ticks (symbol, time DESC);"
    )
    # Deduplication when re-ingesting after a reconnect
    op.execute(
        "CREATE INDEX idx_ticks_trade_id ON ticks (symbol, trade_id);"
    )

    # ── 5. Compression settings ───────────────────────────────────────────────
    op.execute(
        """
        ALTER TABLE ticks SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'symbol',
            timescaledb.compress_orderby = 'time DESC'
        );
        """
    )

    # Auto-compress chunks older than 7 days
    op.execute(
        "SELECT add_compression_policy('ticks', INTERVAL '7 days');"
    )

    # ── 6. Retention policy: drop raw ticks older than 90 days ───────────────
    op.execute(
        "SELECT add_retention_policy('ticks', INTERVAL '90 days');"
    )

    # ── 7. Continuous aggregate: candles_1m ───────────────────────────────────
    op.execute(
        """
        CREATE MATERIALIZED VIEW candles_1m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 minute', time)  AS bucket,
            symbol,
            FIRST(price, time)             AS open,
            MAX(price)                     AS high,
            MIN(price)                     AS low,
            LAST(price, time)              AS close,
            SUM(quantity)                  AS volume,
            COUNT(*)                       AS trade_count
        FROM ticks
        GROUP BY bucket, symbol
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('candles_1m',
            start_offset    => INTERVAL '10 minutes',
            end_offset      => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute'
        );
        """
    )

    # ── 8. Continuous aggregate: candles_5m ───────────────────────────────────
    op.execute(
        """
        CREATE MATERIALIZED VIEW candles_5m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('5 minutes', time) AS bucket,
            symbol,
            FIRST(price, time)             AS open,
            MAX(price)                     AS high,
            MIN(price)                     AS low,
            LAST(price, time)              AS close,
            SUM(quantity)                  AS volume,
            COUNT(*)                       AS trade_count
        FROM ticks
        GROUP BY bucket, symbol
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('candles_5m',
            start_offset    => INTERVAL '30 minutes',
            end_offset      => INTERVAL '5 minutes',
            schedule_interval => INTERVAL '5 minutes'
        );
        """
    )

    # ── 9. Continuous aggregate: candles_1h ───────────────────────────────────
    op.execute(
        """
        CREATE MATERIALIZED VIEW candles_1h
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', time)    AS bucket,
            symbol,
            FIRST(price, time)             AS open,
            MAX(price)                     AS high,
            MIN(price)                     AS low,
            LAST(price, time)              AS close,
            SUM(quantity)                  AS volume,
            COUNT(*)                       AS trade_count
        FROM ticks
        GROUP BY bucket, symbol
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('candles_1h',
            start_offset    => INTERVAL '4 hours',
            end_offset      => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour'
        );
        """
    )

    # ── 10. Continuous aggregate: candles_1d ──────────────────────────────────
    op.execute(
        """
        CREATE MATERIALIZED VIEW candles_1d
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', time)     AS bucket,
            symbol,
            FIRST(price, time)             AS open,
            MAX(price)                     AS high,
            MIN(price)                     AS low,
            LAST(price, time)              AS close,
            SUM(quantity)                  AS volume,
            COUNT(*)                       AS trade_count
        FROM ticks
        GROUP BY bucket, symbol
        WITH NO DATA;
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('candles_1d',
            start_offset    => INTERVAL '3 days',
            end_offset      => INTERVAL '1 day',
            schedule_interval => INTERVAL '1 day'
        );
        """
    )

    # ── 11. Create trading_pairs reference table ──────────────────────────────
    op.create_table(
        "trading_pairs",
        sa.Column("symbol", sa.VARCHAR(20), primary_key=True, nullable=False),
        sa.Column("base_asset", sa.VARCHAR(20), nullable=False),
        sa.Column("quote_asset", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("min_qty", sa.Numeric(20, 8), nullable=True),
        sa.Column("max_qty", sa.Numeric(20, 8), nullable=True),
        sa.Column("step_size", sa.Numeric(20, 8), nullable=True),
        sa.Column("min_notional", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    """Remove all Phase 1 schema objects in reverse dependency order."""

    # Drop continuous aggregates (must precede the ticks hypertable drop)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS candles_1d CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS candles_1h CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS candles_5m CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS candles_1m CASCADE;")

    # Drop tables (hypertable first so TimescaleDB cleans up internal chunks)
    op.drop_table("ticks")
    op.drop_table("trading_pairs")

    # Leave the TimescaleDB extension in place — other schemas may depend on it.
