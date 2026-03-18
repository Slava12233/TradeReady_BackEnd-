"""Shared data types for the exchange abstraction layer.

These types define the canonical shapes returned by any :class:`ExchangeAdapter`
implementation, ensuring downstream code never depends on CCXT-specific structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ExchangeTick:
    """A single trade event from any exchange.

    Attributes:
        symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.
        price: Trade price.
        quantity: Trade quantity in base asset.
        timestamp: UTC timestamp of the trade.
        is_buyer_maker: Whether the buyer was the maker.
        trade_id: Exchange-specific trade identifier (string for universality).
        exchange: Exchange identifier, e.g. ``"binance"``.
    """

    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    is_buyer_maker: bool
    trade_id: str
    exchange: str


@dataclass(frozen=True, slots=True)
class ExchangeCandle:
    """A single OHLCV candle from any exchange.

    Attributes:
        timestamp: Candle open time (UTC).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Base-asset volume.
        trade_count: Number of trades in the candle (0 if unavailable).
        exchange: Exchange identifier.
    """

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    exchange: str


@dataclass(frozen=True, slots=True)
class ExchangeMarket:
    """A trading pair/market from any exchange.

    Attributes:
        symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.
        base_asset: Base currency, e.g. ``"BTC"``.
        quote_asset: Quote currency, e.g. ``"USDT"``.
        status: ``"active"`` or ``"inactive"``.
        min_qty: Minimum order quantity (None if unavailable).
        max_qty: Maximum order quantity (None if unavailable).
        step_size: Quantity step size (None if unavailable).
        min_notional: Minimum order value in quote asset (None if unavailable).
        exchange: Exchange identifier.
    """

    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    min_qty: Decimal | None
    max_qty: Decimal | None
    step_size: Decimal | None
    min_notional: Decimal | None
    exchange: str
