"""Binance WebSocket Client for streaming all USDT trade ticks.

Responsibilities:
1. Fetch all USDT trading pairs from Binance REST API.
2. Filter for status="TRADING" and quoteAsset="USDT".
3. Build combined stream URLs (max 1024 streams per connection).
4. Manage WebSocket connection lifecycle with exponential backoff reconnection.
5. Parse incoming messages and yield :class:`~src.cache.price_cache.Tick` objects.

Example::

    client = BinanceWebSocketClient()
    await client.fetch_pairs()
    async for tick in client.listen():
        print(tick.symbol, tick.price)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
import json

import httpx
import structlog
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from src.cache.types import Tick

log = structlog.get_logger(__name__)

_EXCHANGE_INFO_URL: str = "https://api.binance.com/api/v3/exchangeInfo"
_WS_BASE_URL: str = "wss://stream.binance.com:9443/stream"
_MAX_STREAMS_PER_CONNECTION: int = 1024
_BACKOFF_BASE: float = 1.0
_BACKOFF_MAX: float = 60.0


class BinanceWebSocketClient:
    """Connects to Binance Combined WebSocket streams for all USDT trading pairs.

    Handles >1024 pairs by transparently multiplexing across multiple
    simultaneous WebSocket connections.  Each connection has its own
    exponential-backoff reconnect loop.

    Args:
        exchange_info_url: Override for the Binance REST exchange-info endpoint.
        ws_base_url: Override for the Binance combined-stream WebSocket base URL.
        max_streams: Maximum streams per single WebSocket connection.

    Example::

        client = BinanceWebSocketClient()
        await client.fetch_pairs()
        async for tick in client.listen():
            process(tick)
    """

    def __init__(
        self,
        exchange_info_url: str = _EXCHANGE_INFO_URL,
        ws_base_url: str = _WS_BASE_URL,
        max_streams: int = _MAX_STREAMS_PER_CONNECTION,
    ) -> None:
        self._exchange_info_url = exchange_info_url
        self._ws_base_url = ws_base_url
        self._max_streams = max_streams
        self._symbols: list[str] = []
        self._stream_urls: list[str] = []

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_pairs(self) -> list[str]:
        """Fetch all active USDT trading pair symbols from Binance REST API.

        Filters for ``status="TRADING"`` and ``quoteAsset="USDT"``.

        Returns:
            Sorted list of uppercase symbol strings, e.g. ``["BTCUSDT", "ETHUSDT", ...]``.

        Raises:
            httpx.HTTPStatusError: If the Binance API returns a non-2xx status.
        """
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.get(self._exchange_info_url)
            response.raise_for_status()
            data = response.json()

        self._symbols = sorted(
            s["symbol"] for s in data["symbols"] if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"
        )
        log.info("Fetched active USDT trading pairs from Binance", count=len(self._symbols))

        self._stream_urls = self._build_stream_urls(self._symbols)
        return self._symbols

    def get_all_pairs(self) -> list[str]:
        """Return the cached list of symbols.

        Returns:
            List of symbol strings populated by :meth:`fetch_pairs`.
        """
        return list(self._symbols)

    async def listen(self) -> AsyncGenerator[Tick, None]:
        """Async generator that yields :class:`~src.cache.price_cache.Tick` objects.

        Spawns one concurrent listener task per WebSocket URL (needed when
        there are >1024 pairs).  All connections share the same output queue
        so callers receive a single unified stream.

        Yields:
            :class:`~src.cache.price_cache.Tick` namedtuples as they arrive.
        """
        if not self._stream_urls:
            await self.fetch_pairs()

        queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=50_000)

        tasks = [
            asyncio.create_task(
                self._connection_loop(url, queue),
                name=f"binance-ws-{i}",
            )
            for i, url in enumerate(self._stream_urls)
        ]

        try:
            while True:
                tick = await queue.get()
                yield tick
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_stream_urls(self, symbols: list[str]) -> list[str]:
        """Partition symbols into chunks of :attr:`_max_streams` and build URLs.

        Args:
            symbols: All uppercase USDT pair symbols.

        Returns:
            List of complete combined-stream WebSocket URLs.
        """
        urls: list[str] = []
        for i in range(0, len(symbols), self._max_streams):
            chunk = symbols[i : i + self._max_streams]
            streams = "/".join(f"{sym.lower()}@trade" for sym in chunk)
            urls.append(f"{self._ws_base_url}?streams={streams}")
        log.debug("Built WebSocket connection URLs", url_count=len(urls), symbol_count=len(symbols))
        return urls

    async def _connection_loop(
        self,
        url: str,
        queue: asyncio.Queue[Tick],
    ) -> None:
        """Maintain a single WebSocket connection with exponential-backoff reconnect.

        On any disconnect or parse error the connection is re-established after
        a delay that doubles each attempt up to :data:`_BACKOFF_MAX` seconds.

        Args:
            url: Full combined-stream WebSocket URL.
            queue: Shared output queue to put parsed :class:`Tick` objects into.
        """
        backoff = _BACKOFF_BASE
        while True:
            try:
                log.info("Connecting to Binance WebSocket", url=url[:80])
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    backoff = _BACKOFF_BASE  # reset on successful connection
                    log.info("Binance WebSocket connected")
                    async for raw_message in ws:
                        tick = self._parse_message(raw_message)
                        if tick is not None:
                            await queue.put(tick)

            except asyncio.CancelledError:
                log.info("Binance WebSocket listener cancelled")
                return
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                log.warning(
                    "Binance WebSocket disconnected — reconnecting",
                    error=str(exc),
                    backoff=backoff,
                )
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "Unexpected error in Binance WebSocket loop — reconnecting",
                    error=str(exc),
                    backoff=backoff,
                )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    @staticmethod
    def _parse_message(raw: str | bytes) -> Tick | None:
        """Parse a single combined-stream message into a :class:`Tick`.

        Binance combined-stream messages have the shape::

            {"stream": "btcusdt@trade", "data": {"e": "trade", "s": "BTCUSDT", ...}}

        Args:
            raw: Raw WebSocket message (JSON string or bytes).

        Returns:
            Parsed :class:`Tick` or ``None`` if the message is not a trade event.
        """
        try:
            msg = json.loads(raw)
            data = msg.get("data", {})
            if data.get("e") != "trade":
                return None
            return Tick(
                symbol=data["s"],
                price=Decimal(data["p"]),
                quantity=Decimal(data["q"]),
                timestamp=datetime.fromtimestamp(data["T"] / 1000.0, tz=UTC),
                is_buyer_maker=bool(data["m"]),
                trade_id=int(data["t"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            log.debug("Failed to parse Binance message", error=str(exc))
            return None
