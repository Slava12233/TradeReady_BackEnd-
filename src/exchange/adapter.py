"""Abstract base class for exchange adapters.

Every exchange integration implements this interface.  Downstream code
(price ingestion, backfill scripts, order engine) depends **only** on
:class:`ExchangeAdapter` — never on CCXT or any other library directly.

This ensures:
- Exchange implementations are swappable without changing consumers.
- CCXT can be replaced without a platform-wide refactor.
- Unit tests can use lightweight mock adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal

from src.exchange.types import ExchangeCandle, ExchangeMarket, ExchangeTick


class ExchangeAdapter(ABC):
    """Unified interface for all exchange operations.

    Implementations must convert between the exchange's native symbol format
    and the platform's canonical format (``"BTCUSDT"``) internally.
    """

    # ── Market data (REST) ─────────────────────────────────────────────────

    @abstractmethod
    async def fetch_markets(self, quote_asset: str = "USDT") -> list[ExchangeMarket]:
        """Fetch all active trading pairs filtered by quote asset.

        Args:
            quote_asset: Quote currency to filter by (default ``"USDT"``).

        Returns:
            List of :class:`ExchangeMarket` in platform symbol format.
        """

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> dict:  # type: ignore[type-arg]
        """Fetch 24-hour rolling stats for a single symbol.

        Args:
            symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.

        Returns:
            Dict with keys: ``open``, ``high``, ``low``, ``close``,
            ``volume``, ``change_pct``, ``last_update``.
        """

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[ExchangeCandle]:
        """Fetch historical OHLCV candles.

        Args:
            symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.
            timeframe: Candle interval (``"1m"``, ``"5m"``, ``"15m"``,
                ``"1h"``, ``"4h"``, ``"1d"``).
            since: Start time (UTC). If ``None``, fetch the most recent candles.
            limit: Maximum number of candles to return.

        Returns:
            List of :class:`ExchangeCandle` ordered oldest-first.
        """

    @abstractmethod
    async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:  # type: ignore[type-arg]
        """Fetch current order book depth.

        Args:
            symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.
            limit: Number of price levels per side.

        Returns:
            Dict with keys ``bids`` and ``asks``, each a list of
            ``[price, quantity]`` pairs as Decimal.
        """

    @abstractmethod
    async def fetch_trades(self, symbol: str, limit: int = 50) -> list[ExchangeTick]:
        """Fetch recent public trades.

        Args:
            symbol: Platform-format symbol, e.g. ``"BTCUSDT"``.
            limit: Maximum number of trades to return.

        Returns:
            List of :class:`ExchangeTick` ordered newest-first.
        """

    # ── Real-time streaming (WebSocket) ────────────────────────────────────

    @abstractmethod
    async def watch_trades(self, symbols: list[str]) -> AsyncGenerator[ExchangeTick, None]:
        """Stream real-time trades for the given symbols.

        Args:
            symbols: Platform-format symbols, e.g. ``["BTCUSDT", "ETHUSDT"]``.

        Yields:
            :class:`ExchangeTick` as trades arrive.
        """
        yield  # type: ignore[misc]  # pragma: no cover — make this a generator  # noqa: B027

    # ── Trading (Phase 8 — live execution) ─────────────────────────────────

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: Decimal,
        price: Decimal | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Place an order on the exchange.

        Args:
            symbol: Platform-format symbol.
            order_type: ``"market"``, ``"limit"``, etc.
            side: ``"buy"`` or ``"sell"``.
            amount: Order quantity in base asset.
            price: Limit price (required for limit orders).

        Returns:
            Exchange order response as a dict.
        """

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> dict:  # type: ignore[type-arg]
        """Cancel an open order.

        Args:
            order_id: Exchange-specific order identifier.
            symbol: Platform-format symbol.

        Returns:
            Cancellation response as a dict.
        """

    @abstractmethod
    async def fetch_balance(self) -> dict[str, Decimal]:
        """Fetch account balances.

        Returns:
            Dict mapping asset symbol to free balance, e.g.
            ``{"USDT": Decimal("10000"), "BTC": Decimal("0.5")}``.
        """

    # ── Lifecycle ──────────────────────────────────────────────────────────

    @abstractmethod
    async def close(self) -> None:
        """Release all connections and resources."""

    # ── Metadata ───────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def exchange_id(self) -> str:
        """Short identifier for this exchange, e.g. ``"binance"``, ``"okx"``."""

    @property
    @abstractmethod
    def has_websocket(self) -> bool:
        """Whether this exchange adapter supports WebSocket streaming."""
