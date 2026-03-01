"""Asynchronous Python client for the AgentExchange trading platform.

Wraps all 22 REST API methods with automatic JWT authentication, transparent
token refresh, and exponential-backoff retry on transient 5xx errors.

Usage::

    from agentexchange import AsyncAgentExchangeClient

    async with AsyncAgentExchangeClient(
        api_key="ak_live_...",
        api_secret="sk_live_...",
        base_url="http://localhost:8000",
    ) as client:
        price = await client.get_price("BTCUSDT")
        order = await client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))

    # Manual lifecycle:
    client = AsyncAgentExchangeClient(api_key="...", api_secret="...")
    await client.__aenter__()
    balance = await client.get_balance()
    await client.aclose()
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx

from agentexchange.exceptions import ConnectionError, raise_for_response
from agentexchange.models import (
    AccountInfo,
    Balance,
    Candle,
    LeaderboardEntry,
    Order,
    Performance,
    PnL,
    Portfolio,
    Position,
    Price,
    Snapshot,
    Ticker,
    Trade,
)

logger = logging.getLogger(__name__)

_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)
_DEFAULT_BASE_URL = "http://localhost:8000"


class AsyncAgentExchangeClient:
    """Asynchronous client for the AgentExchange REST API.

    Mirrors the :class:`~agentexchange.client.AgentExchangeClient` interface
    with all methods declared ``async``.  Authenticates on first use by
    exchanging the API key + secret for a JWT token.  The token is refreshed
    automatically before it expires.  All 5xx responses are retried up to
    three times with exponential back-off (1 s / 2 s / 4 s).

    Args:
        api_key:    Agent API key (``ak_live_...`` format).
        api_secret: Agent API secret (``sk_live_...`` format).
        base_url:   Base URL of the platform REST API.
                    Defaults to ``http://localhost:8000``.
        timeout:    HTTP request timeout in seconds.  Defaults to ``30``.

    Example::

        async with AsyncAgentExchangeClient(
            api_key="ak_live_abc",
            api_secret="sk_live_xyz",
        ) as client:
            price = await client.get_price("BTCUSDT")
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._jwt: str | None = None
        self._jwt_expires_at: float = 0.0  # UNIX timestamp
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"X-API-Key": self._api_key},
        )

    # ------------------------------------------------------------------
    # Async context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AsyncAgentExchangeClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying async HTTP connection pool.

        Always call this when you are done with the client (or use it as an
        async context manager so it is closed automatically).
        """
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Internal: auth & request helpers
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        """Exchange API key + secret for a JWT; store it for subsequent calls."""
        response = await self._http.post(
            "/api/v1/auth/login",
            json={"api_key": self._api_key, "api_secret": self._api_secret},
        )
        self._raise_for_response(response)
        data: dict[str, Any] = response.json()
        self._jwt = data["token"]
        expires_in: int = data.get("expires_in", 900)
        self._jwt_expires_at = time.time() + expires_in - 30  # 30-s buffer

    async def _ensure_auth(self) -> None:
        """Ensure a valid JWT is available, refreshing if necessary."""
        if self._jwt is None or time.time() >= self._jwt_expires_at:
            await self._login()

    def _raise_for_response(self, response: httpx.Response) -> None:
        """Parse the response and raise a typed SDK exception for non-2xx status."""
        if 200 <= response.status_code < 300:
            return
        retry_after: int | None = None
        raw = response.headers.get("Retry-After")
        if raw is not None:
            try:
                retry_after = int(raw)
            except ValueError:
                pass
        body: dict[str, Any] | None = None
        try:
            body = response.json()
        except Exception:
            pass
        raise_for_response(response.status_code, body, retry_after=retry_after)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an authenticated async HTTP request with retry on 5xx errors.

        Args:
            method: HTTP method (GET, POST, DELETE, …).
            path:   URL path relative to ``base_url``.
            params: Optional query parameters.
            json:   Optional JSON request body.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            ConnectionError: On network-level failures after all retries.
            AgentExchangeError subclasses: For all HTTP error responses.
        """
        await self._ensure_auth()
        headers = {"Authorization": f"Bearer {self._jwt}"}

        last_exc: Exception | None = None
        response: httpx.Response | None = None
        for attempt, delay in enumerate([0.0, *_RETRY_DELAYS]):
            if attempt > 0:
                logger.debug(
                    "Retrying %s %s (attempt %d) after %.1fs",
                    method,
                    path,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=_clean_params(params),
                    json=json,
                    headers=headers,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning("Transport error on %s %s: %s", method, path, exc)
                continue

            logger.debug("%s %s → %d", method, path, response.status_code)

            if response.status_code >= 500 and attempt < len(_RETRY_DELAYS):
                last_exc = None
                continue

            self._raise_for_response(response)

            if response.status_code == 204 or not response.content:
                return {}
            return response.json()  # type: ignore[return-value]

        if last_exc is not None:
            raise ConnectionError(
                f"Network error after {len(_RETRY_DELAYS) + 1} attempts: {last_exc}",
                code="CONNECTION_ERROR",
            ) from last_exc

        # 5xx persisted through all retries — raise from the last response
        self._raise_for_response(response)  # type: ignore[arg-type]
        return {}

    # ------------------------------------------------------------------
    # Market data (6 methods)
    # ------------------------------------------------------------------

    async def get_price(self, symbol: str) -> Price:
        """Fetch the current market price for a single symbol.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            :class:`~agentexchange.models.Price` with ``symbol``, ``price``,
            and ``timestamp``.

        Raises:
            InvalidSymbolError: If the symbol is unknown or has no price yet.

        Example::

            price = await client.get_price("BTCUSDT")
            print(price.price)  # Decimal('64521.30')
        """
        data = await self._request("GET", f"/api/v1/market/price/{symbol}")
        return Price.from_dict(data)

    async def get_all_prices(self) -> list[Price]:
        """Fetch current prices for all active trading pairs.

        Returns:
            List of :class:`~agentexchange.models.Price` objects.

        Example::

            prices = await client.get_all_prices()
            for p in prices:
                print(p.symbol, p.price)
        """
        data = await self._request("GET", "/api/v1/market/prices")
        return [Price.from_dict(item) for item in data.get("prices", [])]

    async def get_candles(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 100,
    ) -> list[Candle]:
        """Fetch OHLCV candle bars for a symbol.

        Args:
            symbol:   Uppercase trading pair, e.g. ``"BTCUSDT"``.
            interval: Candle interval: ``"1m"``, ``"5m"``, ``"15m"``,
                      ``"1h"``, ``"4h"``, ``"1d"``.  Defaults to ``"1m"``.
            limit:    Maximum number of candles to return (1–1000).
                      Defaults to ``100``.

        Returns:
            List of :class:`~agentexchange.models.Candle` ordered oldest-first.

        Example::

            candles = await client.get_candles("BTCUSDT", interval="1h", limit=24)
            for c in candles:
                print(c.time, c.close)
        """
        data = await self._request(
            "GET",
            f"/api/v1/market/candles/{symbol}",
            params={"interval": interval, "limit": limit},
        )
        return [Candle.from_dict(c) for c in data.get("candles", [])]

    async def get_ticker(self, symbol: str) -> Ticker:
        """Fetch 24-hour market statistics for a symbol.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            :class:`~agentexchange.models.Ticker` with OHLCV and change data.

        Example::

            ticker = await client.get_ticker("BTCUSDT")
            print(ticker.change_pct, ticker.volume)
        """
        data = await self._request("GET", f"/api/v1/market/ticker/{symbol}")
        return Ticker.from_dict(data)

    async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent public trades for a symbol.

        Args:
            symbol: Uppercase trading pair.
            limit:  Maximum number of trades to return (1–1000).
                    Defaults to ``50``.

        Returns:
            List of raw trade dicts with ``price``, ``quantity``, ``side``,
            and ``executed_at`` fields.

        Example::

            trades = await client.get_recent_trades("BTCUSDT", limit=10)
            for t in trades:
                print(t["price"], t["side"])
        """
        data = await self._request(
            "GET",
            f"/api/v1/market/trades/{symbol}",
            params={"limit": limit},
        )
        return data.get("trades", [])

    async def get_orderbook(self, symbol: str, depth: int = 10) -> dict[str, Any]:
        """Fetch the current order book snapshot for a symbol.

        Args:
            symbol: Uppercase trading pair.
            depth:  Number of price levels to return on each side (1–100).
                    Defaults to ``10``.

        Returns:
            Dict with ``bids`` and ``asks`` lists; each entry is
            ``[price_str, quantity_str]``.

        Example::

            book = await client.get_orderbook("BTCUSDT", depth=5)
            best_bid = book["bids"][0]
        """
        data = await self._request(
            "GET",
            f"/api/v1/market/orderbook/{symbol}",
            params={"depth": depth},
        )
        return data

    # ------------------------------------------------------------------
    # Trading (8 methods)
    # ------------------------------------------------------------------

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal | float | str,
    ) -> Order:
        """Place a market order that executes immediately at the current price.

        Args:
            symbol:   Uppercase trading pair, e.g. ``"BTCUSDT"``.
            side:     ``"buy"`` or ``"sell"``.
            quantity: Base-asset quantity to trade.

        Returns:
            :class:`~agentexchange.models.Order` with execution details.

        Raises:
            InsufficientBalanceError: If the account lacks sufficient funds.
            InvalidSymbolError: If the symbol is unknown.
            OrderError: For any other order rejection.

        Example::

            order = await client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
            print(order.executed_price, order.fee)
        """
        data = await self._request(
            "POST",
            "/api/v1/trade/order",
            json={
                "symbol": symbol,
                "side": side,
                "type": "market",
                "quantity": str(Decimal(str(quantity))),
            },
        )
        return Order.from_dict(data)

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal | float | str,
        price: Decimal | float | str,
    ) -> Order:
        """Place a limit order that rests in the order book until filled.

        Args:
            symbol:   Uppercase trading pair.
            side:     ``"buy"`` or ``"sell"``.
            quantity: Base-asset quantity.
            price:    Limit price in quote asset (USDT).

        Returns:
            :class:`~agentexchange.models.Order` with ``status="pending"``.

        Example::

            order = await client.place_limit_order("BTCUSDT", "buy", "0.001", 60000)
            print(order.order_id, order.status)
        """
        data = await self._request(
            "POST",
            "/api/v1/trade/order",
            json={
                "symbol": symbol,
                "side": side,
                "type": "limit",
                "quantity": str(Decimal(str(quantity))),
                "price": str(Decimal(str(price))),
            },
        )
        return Order.from_dict(data)

    async def place_stop_loss(
        self,
        symbol: str,
        side: str,
        quantity: Decimal | float | str,
        trigger_price: Decimal | float | str,
    ) -> Order:
        """Place a stop-loss order that executes when the market hits a trigger.

        Args:
            symbol:        Uppercase trading pair.
            side:          ``"buy"`` or ``"sell"``.
            quantity:      Base-asset quantity.
            trigger_price: Price at which the stop-loss triggers.

        Returns:
            :class:`~agentexchange.models.Order` with ``type="stop_loss"``.

        Example::

            order = await client.place_stop_loss("BTCUSDT", "sell", "0.001", 58000)
        """
        data = await self._request(
            "POST",
            "/api/v1/trade/order",
            json={
                "symbol": symbol,
                "side": side,
                "type": "stop_loss",
                "quantity": str(Decimal(str(quantity))),
                "trigger_price": str(Decimal(str(trigger_price))),
            },
        )
        return Order.from_dict(data)

    async def place_take_profit(
        self,
        symbol: str,
        side: str,
        quantity: Decimal | float | str,
        trigger_price: Decimal | float | str,
    ) -> Order:
        """Place a take-profit order that executes when the market hits a target.

        Args:
            symbol:        Uppercase trading pair.
            side:          ``"buy"`` or ``"sell"``.
            quantity:      Base-asset quantity.
            trigger_price: Price at which the take-profit triggers.

        Returns:
            :class:`~agentexchange.models.Order` with ``type="take_profit"``.

        Example::

            order = await client.place_take_profit("BTCUSDT", "sell", "0.001", 70000)
        """
        data = await self._request(
            "POST",
            "/api/v1/trade/order",
            json={
                "symbol": symbol,
                "side": side,
                "type": "take_profit",
                "quantity": str(Decimal(str(quantity))),
                "trigger_price": str(Decimal(str(trigger_price))),
            },
        )
        return Order.from_dict(data)

    async def get_order(self, order_id: str | UUID) -> Order:
        """Fetch the current status and details of a single order.

        Args:
            order_id: UUID of the order (string or :class:`~uuid.UUID`).

        Returns:
            :class:`~agentexchange.models.Order` with the latest status.

        Raises:
            NotFoundError: If no order with this ID exists on the account.

        Example::

            order = await client.get_order("550e8400-e29b-41d4-a716-446655440000")
            print(order.status)
        """
        data = await self._request("GET", f"/api/v1/trade/order/{order_id}")
        return Order.from_dict(data)

    async def get_open_orders(self) -> list[Order]:
        """Fetch all currently pending (open) orders for the account.

        Returns:
            List of :class:`~agentexchange.models.Order` with
            ``status="pending"``.

        Example::

            open_orders = await client.get_open_orders()
            for o in open_orders:
                print(o.order_id, o.symbol, o.side)
        """
        data = await self._request("GET", "/api/v1/trade/orders/open")
        return [Order.from_dict(o) for o in data.get("orders", [])]

    async def cancel_order(self, order_id: str | UUID) -> bool:
        """Cancel a single pending order.

        Args:
            order_id: UUID of the order to cancel.

        Returns:
            ``True`` when the cancellation was accepted.

        Raises:
            NotFoundError: If the order does not exist.
            OrderError: If the order is not in a cancellable state.

        Example::

            await client.cancel_order("550e8400-e29b-41d4-a716-446655440000")
        """
        await self._request("DELETE", f"/api/v1/trade/order/{order_id}")
        return True

    async def cancel_all_orders(self) -> int:
        """Cancel all open (pending) orders for the account.

        Returns:
            Number of orders that were cancelled.

        Example::

            n = await client.cancel_all_orders()
            print(f"Cancelled {n} orders")
        """
        data = await self._request("DELETE", "/api/v1/trade/orders/open")
        return int(data.get("cancelled_count", 0))

    async def get_trade_history(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Trade]:
        """Fetch the paginated trade execution history for the account.

        Args:
            symbol: Optional filter to a single trading pair.
            limit:  Maximum number of records to return (1–500).
                    Defaults to ``50``.
            offset: Number of records to skip for pagination.
                    Defaults to ``0``.

        Returns:
            List of :class:`~agentexchange.models.Trade` ordered newest-first.

        Example::

            history = await client.get_trade_history(symbol="BTCUSDT", limit=100)
            for t in history:
                print(t.executed_at, t.side, t.price)
        """
        data = await self._request(
            "GET",
            "/api/v1/trade/history",
            params={"symbol": symbol, "limit": limit, "offset": offset},
        )
        return [Trade.from_dict(t) for t in data.get("trades", [])]

    # ------------------------------------------------------------------
    # Account (5 methods)
    # ------------------------------------------------------------------

    async def get_account_info(self) -> AccountInfo:
        """Fetch full account information, session, and risk profile.

        Returns:
            :class:`~agentexchange.models.AccountInfo` with account metadata
            and configuration.

        Example::

            info = await client.get_account_info()
            print(info.display_name, info.status)
        """
        data = await self._request("GET", "/api/v1/account/info")
        return AccountInfo.from_dict(data)

    async def get_balance(self) -> list[Balance]:
        """Fetch all asset balances for the account.

        Returns:
            List of :class:`~agentexchange.models.Balance` — one per asset
            with non-zero holdings.

        Example::

            balances = await client.get_balance()
            usdt = next(b for b in balances if b.asset == "USDT")
            print(usdt.available)
        """
        data = await self._request("GET", "/api/v1/account/balance")
        return [Balance.from_dict(b) for b in data.get("balances", [])]

    async def get_positions(self) -> list[Position]:
        """Fetch all currently open positions for the account.

        Returns:
            List of :class:`~agentexchange.models.Position` with unrealised P&L.

        Example::

            positions = await client.get_positions()
            for p in positions:
                print(p.symbol, p.unrealized_pnl)
        """
        data = await self._request("GET", "/api/v1/account/positions")
        return [Position.from_dict(p) for p in data.get("positions", [])]

    async def get_portfolio(self) -> Portfolio:
        """Fetch a full portfolio snapshot combining balances, positions, and P&L.

        Returns:
            :class:`~agentexchange.models.Portfolio` with equity and P&L summary.

        Example::

            pf = await client.get_portfolio()
            print(pf.total_equity, pf.roi_pct)
        """
        data = await self._request("GET", "/api/v1/account/portfolio")
        return Portfolio.from_dict(data)

    async def get_pnl(self, period: str = "all") -> PnL:
        """Fetch P&L breakdown for a given time period.

        Args:
            period: Time window: ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``.
                    Defaults to ``"all"``.

        Returns:
            :class:`~agentexchange.models.PnL` with realised/unrealised P&L,
            win rate, and fee summary.

        Example::

            pnl = await client.get_pnl(period="7d")
            print(pnl.win_rate, pnl.net_pnl)
        """
        data = await self._request("GET", "/api/v1/account/pnl", params={"period": period})
        return PnL.from_dict(data)

    async def reset_account(
        self, starting_balance: Decimal | float | str = Decimal("10000")
    ) -> dict[str, Any]:
        """Reset the account to start a fresh trading session.

        This wipes all positions and open orders and creates a new session
        with the specified starting balance.

        Args:
            starting_balance: USDT balance for the new session.
                              Defaults to ``10000``.

        Returns:
            Dict with ``session_id``, ``starting_balance``, and
            ``started_at`` of the new session.

        Example::

            result = await client.reset_account(starting_balance=5000)
            print(result["session_id"])
        """
        data = await self._request(
            "POST",
            "/api/v1/account/reset",
            json={"starting_balance": str(Decimal(str(starting_balance)))},
        )
        return data

    # ------------------------------------------------------------------
    # Analytics (3 methods)
    # ------------------------------------------------------------------

    async def get_performance(self, period: str = "all") -> Performance:
        """Fetch statistical performance metrics for a given period.

        Args:
            period: Time window: ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``.
                    Defaults to ``"all"``.

        Returns:
            :class:`~agentexchange.models.Performance` with Sharpe ratio,
            max drawdown, win rate, and more.

        Example::

            perf = await client.get_performance(period="30d")
            print(perf.sharpe_ratio, perf.max_drawdown_pct)
        """
        data = await self._request(
            "GET", "/api/v1/analytics/performance", params={"period": period}
        )
        return Performance.from_dict(data)

    async def get_portfolio_history(
        self,
        interval: str = "1h",
        limit: int = 168,
    ) -> list[Snapshot]:
        """Fetch historical equity snapshots for the account.

        Args:
            interval: Snapshot bucket size: ``"5m"``, ``"1h"``, or ``"1d"``.
                      Defaults to ``"1h"``.
            limit:    Maximum number of snapshots to return.
                      Defaults to ``168`` (7 days at 1 h).

        Returns:
            List of :class:`~agentexchange.models.Snapshot` ordered
            oldest-first.

        Example::

            history = await client.get_portfolio_history(interval="1h")
            for s in history:
                print(s.time, s.total_equity)
        """
        data = await self._request(
            "GET",
            "/api/v1/analytics/portfolio/history",
            params={"interval": interval, "limit": limit},
        )
        return [Snapshot.from_dict(s) for s in data.get("snapshots", [])]

    async def get_leaderboard(
        self,
        period: str = "all",
        limit: int = 20,
    ) -> list[LeaderboardEntry]:
        """Fetch the cross-account performance leaderboard.

        Args:
            period: Ranking window: ``"1d"``, ``"7d"``, ``"30d"``, or
                    ``"all"``.  Defaults to ``"all"``.
            limit:  Maximum number of entries to return.  Defaults to ``20``.

        Returns:
            List of :class:`~agentexchange.models.LeaderboardEntry` ordered
            by rank ascending (rank 1 = best performer).

        Example::

            rankings = await client.get_leaderboard(period="7d", limit=10)
            for entry in rankings[:3]:
                print(entry.rank, entry.display_name, entry.roi_pct)
        """
        data = await self._request(
            "GET",
            "/api/v1/analytics/leaderboard",
            params={"period": period, "limit": limit},
        )
        return [
            LeaderboardEntry.from_dict(e) for e in data.get("rankings", [])
        ]


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _clean_params(
    params: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Remove ``None`` values from a query-parameter dict.

    httpx encodes ``None`` as the string ``"None"``; strip those keys so the
    server receives only explicitly provided parameters.

    Args:
        params: Raw parameter dict that may contain ``None`` values.

    Returns:
        Cleaned dict with ``None`` values removed, or ``None`` when the
        input is ``None`` or would become empty after filtering.
    """
    if params is None:
        return None
    cleaned = {k: v for k, v in params.items() if v is not None}
    return cleaned or None


__all__ = ["AsyncAgentExchangeClient"]
