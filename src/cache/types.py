"""Shared data types for the cache layer.

Defines canonical in-flight data carriers shared across the price ingestion
service, tick buffer, broadcaster, and cache modules.  Centralising these
types here removes the backwards import dependency that previously forced
ingestion modules to import from ``src.cache.price_cache``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple


class Tick(NamedTuple):
    """Single trade tick received from Binance WebSocket.

    This namedtuple is the canonical in-flight data carrier shared between
    the price ingestion service, the tick buffer, the broadcaster, and the
    cache module.

    Attributes:
        symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.
        price: Trade price as ``Decimal``.
        quantity: Trade quantity (base asset) as ``Decimal``.
        timestamp: UTC timestamp of the trade.
        is_buyer_maker: ``True`` if the buyer is the market maker.
        trade_id: Unique Binance trade identifier.
    """

    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    is_buyer_maker: bool
    trade_id: int


@dataclass(slots=True)
class TickerData:
    """24-hour rolling statistics for a single trading pair.

    All monetary fields use ``Decimal`` for exact arithmetic.
    ``change_pct`` is the percentage change from the session open.

    Attributes:
        symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.
        open: Session open price.
        high: 24-hour high price.
        low: 24-hour low price.
        close: Latest close (current) price.
        volume: Cumulative base-asset volume.
        change_pct: Percentage change relative to ``open``.
        last_update: UTC timestamp of the most recent tick.
    """

    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    change_pct: Decimal
    last_update: datetime
