"""Create candles_backfill hypertable for historical Binance kline data.

Revision ID: 006
Revises: 005
Create Date: 2026-03-11 00:00:00 UTC

Stores backfilled OHLCV candles (1m, 5m, 1h, 1d) from Binance public API
so that backtests can cover years of historical data rather than only the
~2 weeks available from live ingestion.
"""

from __future__ import annotations

from alembic import op

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create candles_backfill hypertable with compression."""
    op.execute("""
        CREATE TABLE candles_backfill (
            bucket      TIMESTAMPTZ NOT NULL,
            symbol      TEXT NOT NULL,
            interval    TEXT NOT NULL,
            open        NUMERIC(20,8) NOT NULL,
            high        NUMERIC(20,8) NOT NULL,
            low         NUMERIC(20,8) NOT NULL,
            close       NUMERIC(20,8) NOT NULL,
            volume      NUMERIC(30,8) NOT NULL,
            trade_count INTEGER NOT NULL DEFAULT 0
        );
    """)

    op.execute(
        "SELECT create_hypertable('candles_backfill', 'bucket', "
        "chunk_time_interval => INTERVAL '1 month');"
    )

    op.execute(
        "ALTER TABLE candles_backfill "
        "ADD CONSTRAINT uq_backfill_sym_int_bucket UNIQUE (symbol, interval, bucket);"
    )

    op.execute(
        "CREATE INDEX ix_backfill_sym_int_bucket "
        "ON candles_backfill (symbol, interval, bucket DESC);"
    )

    # Enable TimescaleDB compression after 90 days
    op.execute(
        "ALTER TABLE candles_backfill SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'symbol,interval', "
        "timescaledb.compress_orderby = 'bucket DESC');"
    )
    op.execute(
        "SELECT add_compression_policy('candles_backfill', INTERVAL '90 days');"
    )


def downgrade() -> None:
    """Drop candles_backfill table."""
    op.execute("DROP TABLE IF EXISTS candles_backfill CASCADE;")
