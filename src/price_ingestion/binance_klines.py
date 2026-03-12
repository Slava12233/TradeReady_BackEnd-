"""Binance REST API klines (candlestick) client.

Provides an async function to fetch historical OHLCV candles from the Binance
public REST API.  Used as a fallback when TimescaleDB doesn't have enough
local history to satisfy a user's time-range request (e.g. 1Y, 5Y).

The Binance ``/api/v3/klines`` endpoint is **public** — no API key required.

Reference: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import logging

import httpx

logger = logging.getLogger(__name__)

_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

_INTERVAL_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "1h": "1h",
    "1d": "1d",
}

_MAX_BINANCE_LIMIT = 1000


async def fetch_binance_klines(
    symbol: str,
    interval: str,
    limit: int = 500,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict[str, object]]:
    """Fetch klines from Binance public REST API.

    Args:
        symbol:     Uppercase pair, e.g. ``"BTCUSDT"``.
        interval:   One of ``"1m"``, ``"5m"``, ``"1h"``, ``"1d"``.
        limit:      Max candles (capped at 1000 by Binance).
        start_time: Inclusive start (UTC datetime).
        end_time:   Inclusive end (UTC datetime).

    Returns:
        List of dicts with keys: ``time``, ``open``, ``high``, ``low``,
        ``close``, ``volume``, ``trade_count`` — matching the shape expected
        by ``CandleResponse``.
    """
    binance_interval = _INTERVAL_MAP.get(interval)
    if binance_interval is None:
        logger.warning("binance_klines.unsupported_interval", extra={"interval": interval})
        return []

    params: dict[str, str | int] = {
        "symbol": symbol.upper(),
        "interval": binance_interval,
        "limit": min(limit, _MAX_BINANCE_LIMIT),
    }

    if start_time is not None:
        params["startTime"] = int(start_time.timestamp() * 1000)
    if end_time is not None:
        params["endTime"] = int(end_time.timestamp() * 1000)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_BINANCE_KLINES_URL, params=params)
            resp.raise_for_status()
            raw = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error(
            "binance_klines.fetch_failed",
            extra={"symbol": symbol, "interval": interval, "error": str(exc)},
        )
        return []

    candles: list[dict[str, object]] = []
    for kline in raw:
        candles.append(
            {
                "time": datetime.fromtimestamp(kline[0] / 1000, tz=UTC),
                "open": Decimal(str(kline[1])),
                "high": Decimal(str(kline[2])),
                "low": Decimal(str(kline[3])),
                "close": Decimal(str(kline[4])),
                "volume": Decimal(str(kline[5])),
                "trade_count": int(kline[8]),
            }
        )

    logger.debug(
        "binance_klines.fetched",
        extra={"symbol": symbol, "interval": interval, "count": len(candles)},
    )
    return candles
