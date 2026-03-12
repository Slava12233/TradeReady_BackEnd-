"""Replays historical market data from TimescaleDB for backtesting.

The ``DataReplayer`` queries continuous aggregates (candles) and raw ticks
to provide price data scoped to a virtual clock position.  **Every query
enforces** ``WHERE bucket <= virtual_clock`` to prevent look-ahead bias.

When continuous aggregate data is unavailable (e.g. for historical periods
before live ingestion began), queries UNION with the ``candles_backfill``
table which stores Binance historical klines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

logger = structlog.get_logger(__name__)


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Candle:
    """A single OHLCV candle."""

    bucket: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int


@dataclass(frozen=True, slots=True)
class TickerData:
    """24-hour rolling statistics for a symbol at a point in time."""

    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    price_change: Decimal
    price_change_pct: Decimal


@dataclass(frozen=True, slots=True)
class DataRange:
    """Available data range in TimescaleDB."""

    earliest: datetime
    latest: datetime
    total_pairs: int


# ── Interval mappings ────────────────────────────────────────────────────────

_INTERVAL_TO_VIEW: dict[int, str] = {
    60: "candles_1m",
    300: "candles_5m",
    3600: "candles_1h",
    86400: "candles_1d",
}

_INTERVAL_TO_BACKFILL: dict[int, str] = {
    60: "1m",
    300: "5m",
    3600: "1h",
    86400: "1d",
}


class DataReplayer:
    """Replays historical prices from TimescaleDB continuous aggregates.

    All queries are scoped to ``<= virtual_clock`` to prevent look-ahead bias.
    Queries UNION with ``candles_backfill`` to include historical data that
    predates live ingestion.

    Supports **bulk preloading** via :meth:`preload_range` to load all candle
    data for a time range into memory in a single query, eliminating per-step
    DB round-trips during backtesting.

    Args:
        session: An open async SQLAlchemy session.
        pairs: Optional list of trading pairs to include.  ``None`` means all.
        step_interval: Candle interval in seconds, used to pick the right
            backfill interval string for price lookups.
    """

    def __init__(
        self,
        session: AsyncSession,
        pairs: list[str] | None = None,
        step_interval: int = 60,
    ) -> None:
        self._session = session
        self._pairs = pairs
        self._step_interval = step_interval
        # Preloaded price cache: bucket → {symbol → close}
        self._price_cache: dict[datetime, dict[str, Decimal]] = {}
        self._cache_loaded = False

    async def preload_range(self, start_time: datetime, end_time: datetime) -> int:
        """Bulk-load all candle close prices for a time range into memory.

        After this call, :meth:`load_prices` serves from the in-memory cache
        with zero DB queries.

        Args:
            start_time: Start of backtest period.
            end_time:   End of backtest period.

        Returns:
            Number of data points loaded.
        """
        pair_filter = ""
        params: dict[str, Any] = {"start": start_time, "end": end_time}
        if self._pairs:
            pair_filter = "AND symbol = ANY(:pairs)"
            params["pairs"] = self._pairs

        # Load from all available backfill intervals.  When multiple intervals
        # provide data for the same (bucket, symbol), the cache naturally
        # overwrites with the last writer — since we ORDER BY bucket this is
        # fine; we just need *some* price at each timestamp.
        query = text(f"""
            SELECT bucket, symbol, close
            FROM (
                SELECT bucket, symbol, close FROM candles_1m
                WHERE bucket >= :start AND bucket <= :end {pair_filter}
                UNION ALL
                SELECT bucket, symbol, close FROM candles_backfill
                WHERE bucket >= :start AND bucket <= :end {pair_filter}
            ) combined
            ORDER BY bucket, symbol
        """)  # noqa: S608

        result = await self._session.execute(query, params)
        rows = result.fetchall()

        self._price_cache.clear()
        count = 0
        for row in rows:
            bucket = row.bucket
            if bucket not in self._price_cache:
                self._price_cache[bucket] = {}
            self._price_cache[bucket][row.symbol] = Decimal(str(row.close))
            count += 1

        # Build sorted index for fast bisect lookups
        self._sorted_buckets: list[datetime] = sorted(self._price_cache.keys())
        self._cache_loaded = True
        logger.info(
            "data_replayer.preloaded",
            start=start_time.isoformat(),
            end=end_time.isoformat(),
            data_points=count,
            buckets=len(self._price_cache),
        )
        return count

    async def load_prices(self, timestamp: datetime) -> dict[str, Decimal]:
        """Load close prices for all (or configured) pairs at *timestamp*.

        If :meth:`preload_range` was called, serves from the in-memory cache.
        Otherwise falls back to a per-step DB query.

        Args:
            timestamp: Virtual clock position (UTC).

        Returns:
            Dict of symbol → close price.
        """
        if self._cache_loaded:
            return self._load_prices_from_cache(timestamp)

        pair_filter = ""
        params: dict[str, Any] = {"ts": timestamp}
        if self._pairs:
            pair_filter = "AND symbol = ANY(:pairs)"
            params["pairs"] = self._pairs

        query = text(f"""
            SELECT DISTINCT ON (symbol)
                symbol, close
            FROM (
                SELECT symbol, close, bucket FROM candles_1m
                WHERE bucket <= :ts {pair_filter}
                UNION ALL
                SELECT symbol, close, bucket FROM candles_backfill
                WHERE bucket <= :ts {pair_filter}
            ) combined
            ORDER BY symbol, bucket DESC
        """)  # noqa: S608

        result = await self._session.execute(query, params)
        rows = result.fetchall()
        return {row.symbol: Decimal(str(row.close)) for row in rows}

    def _load_prices_from_cache(self, timestamp: datetime) -> dict[str, Decimal]:
        """Resolve prices from preloaded cache at or before *timestamp*.

        Uses bisect for O(log n) lookup of the nearest bucket.
        """
        import bisect

        if not self._sorted_buckets:
            return {}

        # Exact match (most common case with aligned candle intervals)
        if timestamp in self._price_cache:
            return dict(self._price_cache[timestamp])

        # Binary search: find rightmost bucket <= timestamp
        idx = bisect.bisect_right(self._sorted_buckets, timestamp) - 1
        if idx < 0:
            return {}
        return dict(self._price_cache[self._sorted_buckets[idx]])

    async def load_candles(
        self,
        symbol: str,
        end_time: datetime,
        interval: int = 60,
        limit: int = 100,
    ) -> list[Candle]:
        """Load candles for *symbol* at or before *end_time*.

        Queries both the continuous aggregate view and ``candles_backfill``,
        deduplicating by bucket timestamp.

        Args:
            symbol:   Trading pair, e.g. ``"BTCUSDT"``.
            end_time: Virtual clock position — only candles with
                      ``bucket <= end_time`` are returned.
            interval: Candle interval in seconds (60, 300, 3600, 86400).
            limit:    Maximum number of candles to return.

        Returns:
            List of :class:`Candle` ordered oldest-first.
        """
        view = _INTERVAL_TO_VIEW.get(interval, "candles_1m")
        bf_interval = _INTERVAL_TO_BACKFILL.get(interval, "1m")

        query = text(f"""
            SELECT DISTINCT ON (bucket)
                bucket, symbol, open, high, low, close, volume, trade_count
            FROM (
                SELECT bucket, symbol, open, high, low, close, volume, trade_count
                FROM {view}
                WHERE symbol = :symbol AND bucket <= :end_time
                UNION ALL
                SELECT bucket, symbol, open, high, low, close, volume, trade_count
                FROM candles_backfill
                WHERE symbol = :symbol AND interval = :bf_interval AND bucket <= :end_time
            ) combined
            ORDER BY bucket DESC, symbol
            LIMIT :limit
        """)  # noqa: S608

        result = await self._session.execute(
            query, {"symbol": symbol, "end_time": end_time, "bf_interval": bf_interval, "limit": limit}
        )
        rows = result.fetchall()

        candles = [
            Candle(
                bucket=row.bucket,
                symbol=row.symbol,
                open=Decimal(str(row.open)),
                high=Decimal(str(row.high)),
                low=Decimal(str(row.low)),
                close=Decimal(str(row.close)),
                volume=Decimal(str(row.volume)),
                trade_count=int(row.trade_count),
            )
            for row in rows
        ]
        # Return oldest-first
        candles.reverse()
        return candles

    async def load_ticker_24h(self, symbol: str, timestamp: datetime) -> TickerData | None:
        """Compute 24-hour rolling stats ending at *timestamp*.

        UNIONs ``candles_1m`` with ``candles_backfill`` (using 1h as fallback
        for historical periods without 1m data).

        Args:
            symbol:    Trading pair.
            timestamp: Virtual clock position.

        Returns:
            :class:`TickerData` or ``None`` if no data in the window.
        """
        start_24h = timestamp - timedelta(hours=24)

        query = text("""
            SELECT
                FIRST(open, bucket)              AS open,
                MAX(high)                        AS high,
                MIN(low)                         AS low,
                (ARRAY_AGG(close ORDER BY bucket DESC))[1] AS close,
                COALESCE(SUM(volume), 0)         AS volume,
                COALESCE(SUM(trade_count), 0)    AS trade_count
            FROM (
                SELECT bucket, open, high, low, close, volume, trade_count
                FROM candles_1m
                WHERE symbol = :symbol
                  AND bucket > :start_24h
                  AND bucket <= :timestamp
                UNION ALL
                SELECT bucket, open, high, low, close, volume, trade_count
                FROM candles_backfill
                WHERE symbol = :symbol AND interval = '1h'
                  AND bucket > :start_24h
                  AND bucket <= :timestamp
            ) combined
        """)

        result = await self._session.execute(query, {"symbol": symbol, "start_24h": start_24h, "timestamp": timestamp})
        row = result.fetchone()

        if row is None or row.open is None:
            return None

        open_price = Decimal(str(row.open))
        close_price = Decimal(str(row.close))
        change = close_price - open_price
        change_pct = (change / open_price * Decimal("100")) if open_price != 0 else Decimal("0")

        return TickerData(
            symbol=symbol,
            open=open_price,
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=close_price,
            volume=Decimal(str(row.volume)),
            trade_count=int(row.trade_count),
            price_change=change,
            price_change_pct=change_pct.quantize(Decimal("0.01")),
        )

    async def get_data_range(self) -> DataRange | None:
        """Return the earliest and latest timestamps with candle data.

        Considers both continuous aggregates and backfill data.

        Returns:
            :class:`DataRange` or ``None`` if no data exists.
        """
        query = text("""
            SELECT
                MIN(bucket)              AS earliest,
                MAX(bucket)              AS latest,
                COUNT(DISTINCT symbol)   AS total_pairs
            FROM (
                SELECT bucket, symbol FROM candles_1m
                UNION ALL
                SELECT bucket, symbol FROM candles_backfill
            ) combined
        """)

        result = await self._session.execute(query)
        row = result.fetchone()

        if row is None or row.earliest is None:
            return None

        return DataRange(
            earliest=row.earliest,
            latest=row.latest,
            total_pairs=int(row.total_pairs),
        )

    async def get_available_pairs(self, timestamp: datetime) -> list[str]:
        """Return symbols that have candle data at or before *timestamp*.

        Considers both continuous aggregates and backfill data.

        Args:
            timestamp: Virtual clock position.

        Returns:
            Sorted list of symbol strings.
        """
        pair_filter = ""
        params: dict[str, Any] = {"ts": timestamp}
        if self._pairs:
            pair_filter = "AND symbol = ANY(:pairs)"
            params["pairs"] = self._pairs

        query = text(f"""
            SELECT DISTINCT symbol
            FROM (
                SELECT symbol, bucket FROM candles_1m
                WHERE bucket <= :ts {pair_filter}
                UNION ALL
                SELECT symbol, bucket FROM candles_backfill
                WHERE bucket <= :ts {pair_filter}
            ) combined
            ORDER BY symbol
        """)  # noqa: S608

        result = await self._session.execute(query, params)
        return [row.symbol for row in result.fetchall()]
