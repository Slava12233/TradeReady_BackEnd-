"""Market data routes for the AI Agent Crypto Trading Platform.

Implements the following read-only endpoints (Section 15.2):

- ``GET /api/v1/market/pairs``              — list all trading pairs
- ``GET /api/v1/market/price/{symbol}``     — current price for one pair
- ``GET /api/v1/market/prices``             — current prices for all / filtered pairs
- ``GET /api/v1/market/ticker/{symbol}``    — 24h rolling ticker stats
- ``GET /api/v1/market/candles/{symbol}``   — OHLCV candles from TimescaleDB aggregates
- ``GET /api/v1/market/trades/{symbol}``    — recent public trades from tick history
- ``GET /api/v1/market/orderbook/{symbol}`` — simulated order book snapshot

All endpoints are **public** (no authentication required).  They rely on the
``PriceCache`` for sub-ms Redis reads and fall back to TimescaleDB for
historical candle and trade data.

Example::

    GET /api/v1/market/price/BTCUSDT
    → {"symbol": "BTCUSDT", "price": "64521.30000000", "timestamp": "..."}

    GET /api/v1/market/candles/BTCUSDT?interval=1h&limit=24
    → {"symbol": "BTCUSDT", "interval": "1h", "candles": [...], "count": 24}
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.market import (
    BatchTickersResponse,
    CandleResponse,
    CandlesListResponse,
    OrderbookResponse,
    PairResponse,
    PairsListResponse,
    PriceResponse,
    PricesMapResponse,
    TickerResponse,
    TradePublicResponse,
    TradesPublicResponse,
)
from src.cache.price_cache import PriceCache
from src.cache.types import TickerData
from src.database.models import Tick, TradingPair
from src.dependencies import DbSessionDep, PriceCacheDep
from src.price_ingestion.binance_klines import fetch_binance_klines
from src.utils.exceptions import InvalidSymbolError, PriceNotAvailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Supported candle intervals mapped to their TimescaleDB view names.
_CANDLE_VIEWS: dict[str, str] = {
    "1m": "candles_1m",
    "5m": "candles_5m",
    "1h": "candles_1h",
    "1d": "candles_1d",
}

# Simulated spread for the order book: ±0.05% from mid-price.
_SPREAD_PCT = Decimal("0.0005")

# Depth tiers allowed for the order book endpoint.
_ALLOWED_DEPTHS = {5, 10, 20}


# ---------------------------------------------------------------------------
# GET /api/v1/market/pairs
# ---------------------------------------------------------------------------


@router.get(
    "/pairs",
    response_model=PairsListResponse,
    summary="List all trading pairs",
    description="Returns all active and inactive trading pairs with their exchange filter rules.",
)
async def list_pairs(
    db: DbSessionDep,
    cache: PriceCacheDep,
    status: Annotated[
        str | None,
        Query(description="Filter by pair status: 'active' or 'inactive'."),
    ] = None,
) -> PairsListResponse:
    """Return all trading pairs from the ``trading_pairs`` table.

    Each pair includes a ``has_price`` flag indicating whether a live Redis
    price is currently available.  Agents should filter to ``has_price=true``
    before placing orders to avoid ``ORDER_REJECTED / price_unavailable`` errors.

    Args:
        db:     Injected async database session.
        cache:  Injected :class:`~src.cache.price_cache.PriceCache` for
                live-price availability checks.
        status: Optional filter; when provided only pairs with a matching
                ``status`` field are returned.

    Returns:
        :class:`~src.api.schemas.market.PairsListResponse` with the list of
        pairs and a total count.

    Example::

        GET /api/v1/market/pairs
        GET /api/v1/market/pairs?status=active
    """
    stmt = select(TradingPair)
    if status is not None:
        stmt = stmt.where(TradingPair.status == status)
    stmt = stmt.order_by(TradingPair.symbol)

    result = await db.execute(stmt)
    pairs = result.scalars().all()

    # Single HGETALL round-trip to Redis; O(1) lookup per pair.
    live_prices: dict[str, Decimal] = await cache.get_all_prices()

    pair_responses = [
        PairResponse(
            symbol=pair.symbol,
            base_asset=pair.base_asset,
            quote_asset=pair.quote_asset,
            status=pair.status,
            min_qty=Decimal(str(pair.min_qty)) if pair.min_qty is not None else Decimal("0"),
            step_size=Decimal(str(pair.step_size)) if pair.step_size is not None else Decimal("0"),
            min_notional=Decimal(str(pair.min_notional)) if pair.min_notional is not None else Decimal("0"),
            has_price=pair.symbol in live_prices,
        )
        for pair in pairs
    ]

    logger.debug("market.pairs.fetched", extra={"count": len(pair_responses)})

    return PairsListResponse(pairs=pair_responses, total=len(pair_responses))


# ---------------------------------------------------------------------------
# GET /api/v1/market/price/{symbol}
# ---------------------------------------------------------------------------


@router.get(
    "/price/{symbol}",
    response_model=PriceResponse,
    summary="Get current price for a trading pair",
    description="Returns the latest mid-price from the Redis cache for the given symbol.",
)
async def get_price(
    symbol: str,
    cache: PriceCacheDep,
    db: DbSessionDep,
) -> PriceResponse:
    """Return the current cached price for *symbol*.

    First validates that the symbol exists in ``trading_pairs``, then reads
    the price and its timestamp from Redis.

    Args:
        symbol: Uppercase trading pair symbol, e.g. ``"BTCUSDT"``.
        cache:  Injected :class:`~src.cache.price_cache.PriceCache`.
        db:     Injected async DB session (used for symbol validation).

    Returns:
        :class:`~src.api.schemas.market.PriceResponse`.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`: Symbol not in DB (HTTP 400).
        :exc:`~src.utils.exceptions.PriceNotAvailableError`: Price absent from cache (HTTP 503).

    Example::

        GET /api/v1/market/price/BTCUSDT
        → {"symbol": "BTCUSDT", "price": "64521.30000000", "timestamp": "..."}
    """
    symbol = symbol.upper()
    await _validate_symbol(symbol, db)

    price = await cache.get_price(symbol)
    if price is None:
        raise PriceNotAvailableError(symbol=symbol)

    # Retrieve the timestamp from prices:meta
    ts = await _get_price_timestamp(cache, symbol)

    return PriceResponse(symbol=symbol, price=price, timestamp=ts)


# ---------------------------------------------------------------------------
# GET /api/v1/market/prices
# ---------------------------------------------------------------------------


@router.get(
    "/prices",
    response_model=PricesMapResponse,
    summary="Get current prices for all pairs",
    description=(
        "Returns a map of symbol → price for every pair in the cache. "
        "Pass ``symbols`` to filter (comma-separated)."
    ),
)
async def get_prices(
    cache: PriceCacheDep,
    symbols: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated list of symbols to include, "
                "e.g. ``BTCUSDT,ETHUSDT``.  Omit to return all."
            )
        ),
    ] = None,
) -> PricesMapResponse:
    """Return current prices for all (or a filtered subset of) pairs.

    Args:
        cache:   Injected :class:`~src.cache.price_cache.PriceCache`.
        symbols: Optional comma-separated symbol filter.

    Returns:
        :class:`~src.api.schemas.market.PricesMapResponse`.

    Example::

        GET /api/v1/market/prices
        GET /api/v1/market/prices?symbols=BTCUSDT,ETHUSDT
    """
    all_prices: dict[str, Decimal] = await cache.get_all_prices()

    if symbols:
        wanted = {s.strip().upper() for s in symbols.split(",")}
        all_prices = {sym: p for sym, p in all_prices.items() if sym in wanted}

    prices_str: dict[str, str] = {sym: str(p) for sym, p in all_prices.items()}

    logger.debug("market.prices.fetched", extra={"count": len(prices_str)})

    return PricesMapResponse(
        prices=prices_str,
        timestamp=datetime.now(UTC),
        count=len(prices_str),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/market/ticker/{symbol}
# ---------------------------------------------------------------------------


@router.get(
    "/ticker/{symbol}",
    response_model=TickerResponse,
    summary="Get 24h ticker statistics",
    description="Returns rolling 24-hour OHLCV statistics for the given symbol.",
)
async def get_ticker(
    symbol: str,
    cache: PriceCacheDep,
    db: DbSessionDep,
) -> TickerResponse:
    """Return the 24h rolling ticker for *symbol* from Redis.

    Args:
        symbol: Uppercase trading pair symbol, e.g. ``"BTCUSDT"``.
        cache:  Injected :class:`~src.cache.price_cache.PriceCache`.
        db:     Injected async DB session (used for symbol validation).

    Returns:
        :class:`~src.api.schemas.market.TickerResponse`.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`: Symbol not in DB (HTTP 400).
        :exc:`~src.utils.exceptions.PriceNotAvailableError`: No ticker data in cache (HTTP 503).

    Example::

        GET /api/v1/market/ticker/BTCUSDT
    """
    symbol = symbol.upper()
    await _validate_symbol(symbol, db)

    ticker = await cache.get_ticker(symbol)
    if ticker is None:
        raise PriceNotAvailableError(symbol=symbol)

    # Derive computed fields not stored directly in the ticker hash.
    change = ticker.close - ticker.open
    # quote_volume and trade_count are not tracked by PriceCache; use 0 as
    # placeholder values until the ingestion service is extended.
    quote_volume = ticker.volume * ticker.close

    return TickerResponse(
        symbol=symbol,
        open=ticker.open,
        high=ticker.high,
        low=ticker.low,
        close=ticker.close,
        volume=ticker.volume,
        quote_volume=quote_volume,
        change=change,
        change_pct=ticker.change_pct,
        trade_count=0,
        timestamp=ticker.last_update,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/market/tickers  (batch)
# ---------------------------------------------------------------------------


_MAX_BATCH_SYMBOLS = 100


@router.get(
    "/tickers",
    response_model=BatchTickersResponse,
    summary="Get 24h ticker statistics for multiple symbols",
    description=(
        "Returns rolling 24-hour OHLCV statistics for up to 100 symbols in a single "
        "request. Symbols with no cached ticker data are silently omitted from the "
        "response. Accepts a comma-separated ``symbols`` query parameter."
    ),
)
async def get_tickers_batch(
    symbols: Annotated[
        str,
        Query(
            description="Comma-separated list of uppercase trading pair symbols (max 100).",
            examples=["BTCUSDT,ETHUSDT,BNBUSDT"],
        ),
    ],
    cache: PriceCacheDep,
) -> BatchTickersResponse:
    """Return 24h rolling tickers for a batch of symbols from Redis.

    Fetches all symbol tickers **concurrently** using ``asyncio.gather``,
    so the round-trip is bounded by the slowest single Redis call rather
    than the sum of all calls.

    Args:
        symbols: Comma-separated symbol list, e.g. ``"BTCUSDT,ETHUSDT"``.
        cache:   Injected :class:`~src.cache.price_cache.PriceCache`.

    Returns:
        :class:`~src.api.schemas.market.BatchTickersResponse` with a dict
        of ``{symbol: TickerResponse}`` for all symbols that had cached data.

    Example::

        GET /api/v1/market/tickers?symbols=BTCUSDT,ETHUSDT,BNBUSDT
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    symbol_list = symbol_list[:_MAX_BATCH_SYMBOLS]

    results = await asyncio.gather(
        *(cache.get_ticker(s) for s in symbol_list),
        return_exceptions=True,
    )

    tickers: dict[str, TickerResponse] = {}
    now = datetime.now(UTC)
    for sym, result in zip(symbol_list, results):
        if not isinstance(result, TickerData):
            continue
        change = result.close - result.open
        tickers[sym] = TickerResponse(
            symbol=sym,
            open=result.open,
            high=result.high,
            low=result.low,
            close=result.close,
            volume=result.volume,
            quote_volume=result.volume * result.close,
            change=change,
            change_pct=result.change_pct,
            trade_count=0,
            timestamp=result.last_update,
        )

    return BatchTickersResponse(tickers=tickers, count=len(tickers), timestamp=now)


# ---------------------------------------------------------------------------
# GET /api/v1/market/candles/{symbol}
# ---------------------------------------------------------------------------


@router.get(
    "/candles/{symbol}",
    response_model=CandlesListResponse,
    summary="Get OHLCV candle data",
    description=(
        "Returns historical OHLCV bars from TimescaleDB continuous aggregates. "
        "Supported intervals: ``1m``, ``5m``, ``1h``, ``1d``."
    ),
)
async def get_candles(
    symbol: str,
    db: DbSessionDep,
    interval: Annotated[
        str,
        Query(description="Candle interval: '1m', '5m', '1h', '1d'.", examples=["1h"]),
    ] = "1h",
    limit: Annotated[
        int,
        Query(ge=1, le=1000, description="Number of candles to return (1–1000).", examples=[100]),
    ] = 100,
    start_time: Annotated[
        datetime | None,
        Query(description="ISO-8601 start timestamp (UTC). Optional."),
    ] = None,
    end_time: Annotated[
        datetime | None,
        Query(description="ISO-8601 end timestamp (UTC). Optional."),
    ] = None,
) -> CandlesListResponse:
    """Return OHLCV candles for *symbol* from the appropriate TimescaleDB view.

    Queries one of the four continuous-aggregate views (``candles_1m``,
    ``candles_5m``, ``candles_1h``, ``candles_1d``) depending on *interval*.

    Args:
        symbol:     Uppercase trading pair symbol.
        db:         Injected async DB session.
        interval:   Candle granularity; must be one of ``1m``, ``5m``, ``1h``, ``1d``.
        limit:      Maximum number of bars to return (default 100, max 1000).
        start_time: Optional start of the time window (inclusive).
        end_time:   Optional end of the time window (inclusive).

    Returns:
        :class:`~src.api.schemas.market.CandlesListResponse`.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`: Symbol not valid (HTTP 400).
        :exc:`ValueError`: Interval not supported (HTTP 400 via FastAPI validation).

    Example::

        GET /api/v1/market/candles/BTCUSDT?interval=1h&limit=24
    """
    symbol = symbol.upper()
    await _validate_symbol(symbol, db)

    if interval not in _CANDLE_VIEWS:
        raise InvalidSymbolError(
            f"Interval '{interval}' is not supported. Use one of: {', '.join(_CANDLE_VIEWS)}."
        )

    view_name = _CANDLE_VIEWS[interval]

    # Build parameterised SQL for the continuous-aggregate view.
    # TextClause with :param style is safe (no f-string interpolation of user data).
    where_clauses = ["symbol = :symbol"]
    params: dict[str, object] = {"symbol": symbol, "limit": limit}

    if start_time is not None:
        where_clauses.append("bucket >= :start_time")
        params["start_time"] = start_time.astimezone(UTC)

    if end_time is not None:
        where_clauses.append("bucket <= :end_time")
        params["end_time"] = end_time.astimezone(UTC)

    where_sql = " AND ".join(where_clauses)
    # view_name is validated against _CANDLE_VIEWS dict — safe to interpolate.
    raw_sql = text(
        f"SELECT bucket, open, high, low, close, volume, trade_count "  # noqa: S608
        f"FROM {view_name} "
        f"WHERE {where_sql} "
        f"ORDER BY bucket DESC "
        f"LIMIT :limit"
    )

    result = await db.execute(raw_sql, params)
    rows = result.fetchall()

    # Rows are ordered DESC for LIMIT efficiency; reverse for chronological output.
    candles = [
        CandleResponse(
            time=row.bucket,
            open=Decimal(str(row.open)),
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=Decimal(str(row.close)),
            volume=Decimal(str(row.volume)),
            trade_count=int(row.trade_count),
        )
        for row in reversed(rows)
    ]

    # ── Binance klines fallback ──
    # When local TimescaleDB history is insufficient (e.g. platform just
    # started, user asks for 1Y of data), fetch from Binance public API.
    if len(candles) < limit:
        binance_candles = await fetch_binance_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )
        if binance_candles:
            local_times = {c.time for c in candles}
            merged = list(candles)
            for bc in binance_candles:
                if bc["time"] not in local_times:
                    merged.append(
                        CandleResponse(
                            time=bc["time"],
                            open=bc["open"],
                            high=bc["high"],
                            low=bc["low"],
                            close=bc["close"],
                            volume=bc["volume"],
                            trade_count=bc["trade_count"],
                        )
                    )
            candles = sorted(merged, key=lambda c: c.time)[:limit]
            logger.debug(
                "market.candles.binance_fallback",
                extra={"symbol": symbol, "interval": interval, "local": len(rows), "total": len(candles)},
            )

    logger.debug(
        "market.candles.fetched",
        extra={"symbol": symbol, "interval": interval, "count": len(candles)},
    )

    return CandlesListResponse(
        symbol=symbol,
        interval=interval,
        candles=candles,
        count=len(candles),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/market/trades/{symbol}
# ---------------------------------------------------------------------------


@router.get(
    "/trades/{symbol}",
    response_model=TradesPublicResponse,
    summary="Get recent public trades",
    description="Returns the most recent trades for a symbol from the tick history.",
)
async def get_trades(
    symbol: str,
    db: DbSessionDep,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Number of recent trades to return (1–500).", examples=[100]),
    ] = 100,
) -> TradesPublicResponse:
    """Return the *limit* most recent public trades for *symbol*.

    Queries the ``ticks`` hypertable directly, ordered by time descending, then
    reverses the list so the response is newest-first as per the API spec.

    Args:
        symbol: Uppercase trading pair symbol.
        db:     Injected async DB session.
        limit:  Maximum number of trades to return (default 100, max 500).

    Returns:
        :class:`~src.api.schemas.market.TradesPublicResponse`.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`: Symbol not valid (HTTP 400).

    Example::

        GET /api/v1/market/trades/BTCUSDT?limit=50
    """
    symbol = symbol.upper()
    await _validate_symbol(symbol, db)

    stmt = (
        select(Tick)
        .where(Tick.symbol == symbol)
        .order_by(Tick.time.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    ticks = result.scalars().all()

    trades = [
        TradePublicResponse(
            trade_id=tick.trade_id,
            price=Decimal(str(tick.price)),
            quantity=Decimal(str(tick.quantity)),
            time=tick.time,
            is_buyer_maker=tick.is_buyer_maker,
        )
        for tick in ticks  # already newest-first from ORDER BY DESC
    ]

    logger.debug(
        "market.trades.fetched",
        extra={"symbol": symbol, "count": len(trades)},
    )

    return TradesPublicResponse(symbol=symbol, trades=trades)


# ---------------------------------------------------------------------------
# GET /api/v1/market/orderbook/{symbol}
# ---------------------------------------------------------------------------


@router.get(
    "/orderbook/{symbol}",
    response_model=OrderbookResponse,
    summary="Get simulated order book snapshot",
    description=(
        "Returns a simulated order book generated from the current mid-price. "
        "Bids and asks are placed at ±0.05% spread with synthetic quantities. "
        "This is a simulation — depth does not reflect real Binance liquidity."
    ),
)
async def get_orderbook(
    symbol: str,
    cache: PriceCacheDep,
    db: DbSessionDep,
    depth: Annotated[
        int,
        Query(description="Number of levels on each side (5, 10, or 20).", examples=[10]),
    ] = 10,
) -> OrderbookResponse:
    """Return a simulated order book snapshot for *symbol*.

    Generates synthetic bid/ask levels spaced 0.01% apart around the current
    mid-price.  Each level carries a pseudo-random quantity to mimic the visual
    appearance of a real order book.  Quantities are seeded deterministically
    from the symbol so consecutive calls for the same price are stable.

    Args:
        symbol: Uppercase trading pair symbol.
        cache:  Injected :class:`~src.cache.price_cache.PriceCache`.
        db:     Injected async DB session (symbol validation).
        depth:  Levels per side; must be 5, 10, or 20 (default 10).

    Returns:
        :class:`~src.api.schemas.market.OrderbookResponse`.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`: Symbol not valid or depth invalid (HTTP 400).
        :exc:`~src.utils.exceptions.PriceNotAvailableError`: No price in cache (HTTP 503).

    Example::

        GET /api/v1/market/orderbook/BTCUSDT?depth=10
    """
    symbol = symbol.upper()

    if depth not in _ALLOWED_DEPTHS:
        raise InvalidSymbolError(
            f"depth={depth} is not supported. Use one of: {sorted(_ALLOWED_DEPTHS)}."
        )

    await _validate_symbol(symbol, db)

    price = await cache.get_price(symbol)
    if price is None:
        raise PriceNotAvailableError(symbol=symbol)

    now = await _get_price_timestamp(cache, symbol)

    bids, asks = _build_orderbook(price, depth)

    logger.debug(
        "market.orderbook.fetched",
        extra={"symbol": symbol, "depth": depth, "mid_price": str(price)},
    )

    return OrderbookResponse(symbol=symbol, bids=bids, asks=asks, timestamp=now)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _validate_symbol(symbol: str, db: AsyncSession) -> None:
    """Raise :exc:`InvalidSymbolError` if *symbol* is not in ``trading_pairs``.

    Args:
        symbol: Uppercase symbol string.
        db:     Async SQLAlchemy session.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`: If the symbol is not found.
    """
    result = await db.execute(
        select(TradingPair.symbol).where(TradingPair.symbol == symbol).limit(1)
    )
    if result.scalar_one_or_none() is None:
        raise InvalidSymbolError(symbol=symbol)


async def _get_price_timestamp(cache: PriceCache, symbol: str) -> datetime:
    """Return the last-update timestamp for *symbol* from ``prices:meta``.

    Falls back to the current UTC time when no metadata is available.

    Args:
        cache:  :class:`~src.cache.price_cache.PriceCache` instance.
        symbol: Uppercase symbol string.

    Returns:
        ``datetime`` in UTC.
    """
    raw: str | None = await cache._redis.hget("prices:meta", symbol)  # noqa: SLF001
    if raw is None:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(raw)
    except (ValueError, OverflowError):
        return datetime.now(UTC)


def _build_orderbook(
    mid_price: Decimal,
    depth: int,
) -> tuple[list[list[str]], list[list[str]]]:
    """Generate synthetic bid/ask levels around *mid_price*.

    Levels are spaced 0.01% apart on each side.  Quantities are pseudo-random
    but bounded to give a realistic-looking book.  The random seed is fixed so
    the structure is stable within a given price tick.

    Args:
        mid_price: Current mid-price from Redis.
        depth:     Number of levels per side.

    Returns:
        A tuple ``(bids, asks)`` where each element is a list of
        ``[price_str, qty_str]`` pairs.  Bids are ordered highest-first,
        asks lowest-first.
    """
    rng = random.Random(int(mid_price * 100))  # deterministic seed from price  # noqa: S311

    level_spacing = mid_price * Decimal("0.0001")  # 0.01% per level
    precision = _infer_price_precision(mid_price)

    bids: list[list[str]] = []
    asks: list[list[str]] = []

    for i in range(1, depth + 1):
        offset = level_spacing * i
        bid_price = mid_price - offset
        ask_price = mid_price + offset

        # Quantities: random float between 0.1 and 10, rounded to 3 dp.
        bid_qty = round(rng.uniform(0.1, 10.0), 3)
        ask_qty = round(rng.uniform(0.1, 10.0), 3)

        bids.append([f"{bid_price:.{precision}f}", str(bid_qty)])
        asks.append([f"{ask_price:.{precision}f}", str(ask_qty)])

    return bids, asks


def _infer_price_precision(price: Decimal) -> int:
    """Infer a sensible decimal precision for *price* display.

    Coins above $1000 show 2 dp, $1–$1000 show 4 dp, below $1 show 6 dp.

    Args:
        price: Current mid-price.

    Returns:
        Number of decimal places as an ``int``.
    """
    if price >= Decimal("1000"):
        return 2
    if price >= Decimal("1"):
        return 4
    return 6
