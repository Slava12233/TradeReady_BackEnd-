"""Pydantic v2 request/response schemas for market data endpoints.

Covers the following REST endpoints (Section 15.2):
- ``GET /api/v1/market/pairs``
- ``GET /api/v1/market/price/{symbol}``
- ``GET /api/v1/market/prices``
- ``GET /api/v1/market/ticker/{symbol}``
- ``GET /api/v1/market/candles/{symbol}``
- ``GET /api/v1/market/trades/{symbol}``
- ``GET /api/v1/market/orderbook/{symbol}``

All ``Decimal`` price/volume fields serialise as strings to preserve
full 8-decimal precision without floating-point rounding.

Example::

    from src.api.schemas.market import PairResponse, PriceResponse

    pair = PairResponse(
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        status="active",
        min_qty=Decimal("0.00001"),
        step_size=Decimal("0.00001"),
        min_notional=Decimal("10.00"),
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ---------------------------------------------------------------------------
# Shared config base
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Trading pairs  –  GET /market/pairs
# ---------------------------------------------------------------------------


class PairResponse(_BaseSchema):
    """A single tradeable symbol with its exchange filters.

    Attributes:
        symbol:       Binance pair symbol (e.g. ``"BTCUSDT"``).
        base_asset:   Asset being bought/sold (e.g. ``"BTC"``).
        quote_asset:  Quote currency (e.g. ``"USDT"``).
        status:       ``"active"`` or ``"inactive"``.
        min_qty:      Minimum order quantity (step-size aligned).
        step_size:    Minimum quantity increment allowed.
        min_notional: Minimum order value in quote asset.
        has_price:    ``True`` when a live price is currently in the Redis cache.
                      Orders placed against symbols with ``has_price=False`` will
                      be rejected with ``ORDER_REJECTED / price_unavailable``.
    """

    symbol: str = Field(..., description="Pair symbol (e.g. BTCUSDT).", examples=["BTCUSDT"])
    base_asset: str = Field(..., description="Base asset (e.g. BTC).", examples=["BTC"])
    quote_asset: str = Field(..., description="Quote asset (e.g. USDT).", examples=["USDT"])
    status: str = Field(..., description="Pair status: 'active' or 'inactive'.", examples=["active"])
    min_qty: Decimal = Field(..., description="Minimum order quantity.", examples=["0.00001"])
    step_size: Decimal = Field(..., description="Minimum quantity increment.", examples=["0.00001"])
    min_notional: Decimal = Field(..., description="Minimum order value in USDT.", examples=["10.00"])
    has_price: bool = Field(
        ...,
        description=(
            "True when a live price is available in Redis. "
            "Orders for symbols with has_price=False will be rejected."
        ),
        examples=[True],
    )

    @field_serializer("min_qty", "step_size", "min_notional")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class PairsListResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/pairs``.

    Attributes:
        pairs: List of all available trading pairs.
        total: Total count of pairs returned.
    """

    pairs: list[PairResponse] = Field(..., description="List of trading pairs.")
    total: int = Field(..., description="Total number of pairs returned.", examples=[647])


# ---------------------------------------------------------------------------
# Current price  –  GET /market/price/{symbol}
# ---------------------------------------------------------------------------


class PriceResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/price/{symbol}``.

    Attributes:
        symbol:    The trading pair symbol.
        price:     Current mid-price from the latest Binance tick.
        timestamp: UTC datetime of the latest tick.
    """

    symbol: str = Field(..., description="Trading pair symbol.", examples=["BTCUSDT"])
    price: Decimal = Field(..., description="Current price.", examples=["64521.30000000"])
    timestamp: datetime = Field(..., description="UTC datetime of the latest tick.")

    @field_serializer("price")
    def _serialize_price(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Prices map  –  GET /market/prices
# ---------------------------------------------------------------------------


class PricesMapResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/prices``.

    All price values in the ``prices`` dict are serialised as strings.

    Attributes:
        prices:    Mapping of symbol → current price string.
        timestamp: UTC datetime when the snapshot was taken.
        count:     Number of symbols included in the response.
    """

    prices: dict[str, str] = Field(
        ...,
        description="Map of symbol → price string.",
        examples=[{"BTCUSDT": "64521.30", "ETHUSDT": "3421.50"}],
    )
    timestamp: datetime = Field(..., description="UTC snapshot timestamp.")
    count: int = Field(..., description="Number of symbols in the response.", examples=[647])


# ---------------------------------------------------------------------------
# 24h ticker  –  GET /market/ticker/{symbol}
# ---------------------------------------------------------------------------


class TickerResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/ticker/{symbol}``.

    All price/volume fields are serialised as strings.

    Attributes:
        symbol:       The trading pair symbol.
        open:         24h opening price.
        high:         24h highest price.
        low:          24h lowest price.
        close:        Latest close price (same as current price).
        volume:       24h traded volume in base asset.
        quote_volume: 24h traded volume in quote asset (USDT).
        change:       Absolute price change over 24h.
        change_pct:   Percentage price change over 24h.
        trade_count:  Number of trades in the 24h window.
        timestamp:    UTC datetime of the statistics snapshot.
    """

    symbol: str = Field(..., description="Trading pair symbol.", examples=["BTCUSDT"])
    open: Decimal = Field(..., description="24h opening price.", examples=["63800.00"])
    high: Decimal = Field(..., description="24h high price.", examples=["65200.00"])
    low: Decimal = Field(..., description="24h low price.", examples=["63500.00"])
    close: Decimal = Field(..., description="Current / latest close price.", examples=["64521.30"])
    volume: Decimal = Field(..., description="24h volume in base asset.", examples=["24531.456"])
    quote_volume: Decimal = Field(..., description="24h volume in USDT.", examples=["1582345678.90"])
    change: Decimal = Field(..., description="Absolute 24h price change.", examples=["721.30"])
    change_pct: Decimal = Field(..., description="Percentage 24h price change.", examples=["1.13"])
    trade_count: int = Field(..., description="Number of trades in 24h window.", examples=[1456789])
    timestamp: datetime = Field(..., description="UTC statistics snapshot timestamp.")

    @field_serializer("open", "high", "low", "close", "volume", "quote_volume", "change", "change_pct")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Batch tickers  –  GET /market/tickers
# ---------------------------------------------------------------------------


class BatchTickersResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/tickers``.

    Returns ticker data for multiple symbols in a single request.

    Attributes:
        tickers:   Map of symbol → :class:`TickerResponse`.
        count:     Number of symbols returned (may be < requested if some lack data).
        timestamp: UTC snapshot timestamp.
    """

    tickers: dict[str, TickerResponse] = Field(
        ..., description="Map of symbol → 24h ticker data."
    )
    count: int = Field(..., description="Number of tickers returned.", examples=[50])
    timestamp: datetime = Field(..., description="UTC snapshot timestamp.")


# ---------------------------------------------------------------------------
# OHLCV candles  –  GET /market/candles/{symbol}
# ---------------------------------------------------------------------------


class CandleResponse(_BaseSchema):
    """A single OHLCV candle bar.

    Attributes:
        time:        Candle open time (UTC).
        open:        Opening price for the interval.
        high:        Highest price during the interval.
        low:         Lowest price during the interval.
        close:       Closing price for the interval.
        volume:      Traded volume in base asset during the interval.
        trade_count: Number of trades during the interval.
    """

    time: datetime = Field(..., description="Candle open timestamp (UTC).")
    open: Decimal = Field(..., description="Opening price.", examples=["64200.00"])
    high: Decimal = Field(..., description="Highest price.", examples=["64600.00"])
    low: Decimal = Field(..., description="Lowest price.", examples=["64100.00"])
    close: Decimal = Field(..., description="Closing price.", examples=["64521.30"])
    volume: Decimal = Field(..., description="Volume in base asset.", examples=["1234.567"])
    trade_count: int = Field(..., description="Number of trades in this candle.", examples=[45678])

    @field_serializer("open", "high", "low", "close", "volume")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class CandlesListResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/candles/{symbol}``.

    Attributes:
        symbol:   The trading pair symbol.
        interval: Candle interval (e.g. ``"1m"``, ``"1h"``, ``"1d"``).
        candles:  Ordered list of OHLCV bars (oldest first).
        count:    Number of candles returned.
    """

    symbol: str = Field(..., description="Trading pair symbol.", examples=["BTCUSDT"])
    interval: str = Field(
        ...,
        description="Candle interval: '1m', '5m', '1h', '4h', '1d'.",
        examples=["1h"],
    )
    candles: list[CandleResponse] = Field(..., description="OHLCV bars, oldest first.")
    count: int = Field(..., description="Number of candles returned.", examples=[100])


# ---------------------------------------------------------------------------
# Public recent trades  –  GET /market/trades/{symbol}
# ---------------------------------------------------------------------------


class TradePublicResponse(_BaseSchema):
    """A single public trade from the tick history.

    Attributes:
        trade_id:       Binance trade ID (from the tick record).
        price:          Execution price.
        quantity:       Traded quantity in base asset.
        time:           UTC timestamp of the trade.
        is_buyer_maker: True when the buy side was the maker (passive order).
    """

    trade_id: int = Field(..., description="Binance trade ID.", examples=[123456789])
    price: Decimal = Field(..., description="Execution price.", examples=["64521.30"])
    quantity: Decimal = Field(..., description="Traded quantity.", examples=["0.01200"])
    time: datetime = Field(..., description="UTC trade timestamp.")
    is_buyer_maker: bool = Field(
        ...,
        description="True if the buyer was the maker (passive order).",
        examples=[False],
    )

    @field_serializer("price", "quantity")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class TradesPublicResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/trades/{symbol}``.

    Attributes:
        symbol: The trading pair symbol.
        trades: List of recent public trades, newest first.
    """

    symbol: str = Field(..., description="Trading pair symbol.", examples=["BTCUSDT"])
    trades: list[TradePublicResponse] = Field(..., description="Recent trades, newest first.")


# ---------------------------------------------------------------------------
# Simulated order book  –  GET /market/orderbook/{symbol}
# ---------------------------------------------------------------------------


class OrderbookResponse(_BaseSchema):
    """Response body for ``GET /api/v1/market/orderbook/{symbol}``.

    The order book is **simulated**: bids and asks are generated from the
    current mid-price plus a configurable spread, so the depth never
    reflects real liquidity.

    Each entry in ``bids`` and ``asks`` is a ``[price, quantity]`` pair
    represented as a list of two strings (Binance REST convention).

    Attributes:
        symbol:    The trading pair symbol.
        bids:      List of ``[price, qty]`` pairs, highest bid first.
        asks:      List of ``[price, qty]`` pairs, lowest ask first.
        timestamp: UTC datetime of the snapshot.
    """

    symbol: str = Field(..., description="Trading pair symbol.", examples=["BTCUSDT"])
    bids: list[list[str]] = Field(
        ...,
        description="Bid levels as [price, qty] string pairs, highest first.",
        examples=[[["64520.00", "1.234"], ["64519.00", "2.567"]]],
    )
    asks: list[list[str]] = Field(
        ...,
        description="Ask levels as [price, qty] string pairs, lowest first.",
        examples=[[["64522.00", "0.987"], ["64523.00", "1.456"]]],
    )
    timestamp: datetime = Field(..., description="UTC snapshot timestamp.")
