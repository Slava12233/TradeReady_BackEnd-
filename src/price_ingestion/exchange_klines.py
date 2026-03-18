"""Exchange-agnostic OHLCV klines client powered by CCXT.

Drop-in replacement for :func:`fetch_binance_klines` that works with any
CCXT-supported exchange.  Falls back to the legacy Binance-specific function
if CCXT is not installed.

Usage::

    candles = await fetch_exchange_klines("BTCUSDT", "1h", limit=100)
    candles = await fetch_exchange_klines("BTCUSDT", "1h", exchange_id="okx")
"""

from __future__ import annotations

from datetime import datetime
import logging

logger = logging.getLogger(__name__)


async def fetch_exchange_klines(
    symbol: str,
    interval: str,
    limit: int = 500,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    exchange_id: str = "binance",
) -> list[dict[str, object]]:
    """Fetch OHLCV klines from any exchange via CCXT.

    Returns data in the same shape as :func:`fetch_binance_klines`::

        [{"time": datetime, "open": Decimal, "high": Decimal, "low": Decimal,
          "close": Decimal, "volume": Decimal, "trade_count": int}, ...]

    Args:
        symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.
        interval: Candle interval (``"1m"``, ``"5m"``, ``"1h"``, ``"1d"``).
        limit: Maximum candles to return.
        start_time: Inclusive start (UTC datetime).
        end_time: Inclusive end (UTC datetime).
        exchange_id: CCXT exchange identifier (default ``"binance"``).

    Returns:
        List of candle dicts matching the ``CandleResponse`` shape.
    """
    try:
        from src.exchange.ccxt_adapter import CCXTAdapter  # noqa: PLC0415

        adapter = CCXTAdapter(exchange_id)
        await adapter.initialize()

        try:
            candles = await adapter.fetch_ohlcv(
                symbol,
                timeframe=interval,
                since=start_time,
                limit=limit,
            )

            result: list[dict[str, object]] = []
            for c in candles:
                # Filter by end_time if specified.
                if end_time and c.timestamp > end_time:
                    break
                result.append(
                    {
                        "time": c.timestamp,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                        "trade_count": c.trade_count,
                    }
                )

            logger.debug(
                "exchange_klines.fetched",
                extra={
                    "symbol": symbol,
                    "interval": interval,
                    "exchange": exchange_id,
                    "count": len(result),
                },
            )
            return result

        finally:
            await adapter.close()

    except ImportError:
        logger.info(
            "CCXT not available — falling back to legacy Binance klines",
            extra={"symbol": symbol},
        )
        from src.price_ingestion.binance_klines import fetch_binance_klines  # noqa: PLC0415

        return await fetch_binance_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as exc:
        logger.error(
            "exchange_klines.fetch_failed",
            extra={
                "symbol": symbol,
                "interval": interval,
                "exchange": exchange_id,
                "error": str(exc),
            },
        )
        # Fallback to legacy Binance if exchange was binance.
        if exchange_id == "binance":
            from src.price_ingestion.binance_klines import fetch_binance_klines  # noqa: PLC0415

            return await fetch_binance_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
            )
        return []
