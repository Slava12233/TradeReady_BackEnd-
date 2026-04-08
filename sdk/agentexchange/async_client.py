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
from collections.abc import Callable
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
        api_key:            Agent API key (``ak_live_...`` format).
        api_secret:         Agent API secret (``sk_live_...`` format).
        base_url:           Base URL of the platform REST API.
                            Defaults to ``http://localhost:8000``.
        timeout:            HTTP request timeout in seconds.  Defaults to ``30``.
        trace_id_provider:  Optional zero-argument callable that returns the
                            current trace ID string.  When provided and the
                            returned string is non-empty, an ``X-Trace-Id``
                            header is injected into every outbound request.
                            Defaults to ``None`` (no trace header sent).

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
        trace_id_provider: Callable[[], str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._trace_id_provider = trace_id_provider
        self._jwt: str | None = None
        self._jwt_expires_at: float = 0.0  # UNIX timestamp
        # When True, JWT login has failed (e.g. agent key used instead of account
        # key) and the client falls back to X-API-Key-only auth for all requests.
        self._api_key_only: bool = False
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"X-API-Key": self._api_key},
        )

    # ------------------------------------------------------------------
    # Async context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AsyncAgentExchangeClient:
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
        """Exchange API key + secret for a JWT; store it for subsequent calls.

        If login fails because the key belongs to an agent (not an account),
        the error is swallowed and ``_api_key_only`` is set to ``True`` so that
        all subsequent requests use ``X-API-Key`` header authentication instead.
        This allows agent API keys to work transparently without JWT login.
        """
        response = await self._http.post(
            "/api/v1/auth/login",
            json={"api_key": self._api_key, "api_secret": self._api_secret},
        )
        # If login fails with ACCOUNT_NOT_FOUND or INVALID_API_KEY it means
        # the caller supplied an agent-scoped key.  Fall back to API-key-only auth.
        if response.status_code in (401, 404):
            body: dict[str, Any] = {}
            try:
                body = response.json()
            except Exception:
                pass
            error_code = (body.get("error") or {}).get("code", "")
            if error_code in ("ACCOUNT_NOT_FOUND", "INVALID_API_KEY", "AUTHENTICATION_ERROR"):
                logger.debug(
                    "JWT login unavailable for agent key %s (code=%s); "
                    "falling back to X-API-Key-only auth",
                    self._api_key[:20],
                    error_code,
                )
                self._api_key_only = True
                return
        self._raise_for_response(response)
        data: dict[str, Any] = response.json()
        self._jwt = data["token"]
        expires_in: int = data.get("expires_in", 900)
        self._jwt_expires_at = time.time() + expires_in - 30  # 30-s buffer

    async def _ensure_auth(self) -> None:
        """Ensure a valid JWT is available, refreshing if necessary.

        When ``_api_key_only`` is ``True`` (agent key fall-back), this is a no-op
        because the persistent ``X-API-Key`` header on the httpx client is
        sufficient for all platform endpoints.
        """
        if self._api_key_only:
            return
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
        # In API-key-only mode (agent keys), rely on the persistent X-API-Key
        # header set on the httpx client; no Authorization header is added.
        headers: dict[str, str] = (
            {} if self._api_key_only else {"Authorization": f"Bearer {self._jwt}"}
        )
        if self._trace_id_provider:
            trace_id = self._trace_id_provider()
            if trace_id:
                headers["X-Trace-Id"] = trace_id

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

    async def get_indicators(
        self,
        symbol: str,
        indicators: list[str] | None = None,
        lookback: int = 200,
    ) -> dict[str, Any]:
        """Fetch technical indicator values for a symbol.

        Args:
            symbol:     Uppercase trading pair, e.g. ``"BTCUSDT"``.
            indicators: Optional list of indicator names to return, e.g.
                        ``["rsi_14", "macd_hist"]``.  When ``None`` all
                        available indicators are returned.
            lookback:   Number of candles used to compute the indicators.
                        Defaults to ``200``.

        Returns:
            Dict with ``symbol``, ``lookback``, and ``indicators`` mapping
            each requested indicator name to its current value.

        Example::

            result = await client.get_indicators("BTCUSDT")
            print(result["indicators"]["rsi_14"])

            result = await client.get_indicators(
                "BTCUSDT",
                indicators=["rsi_14", "macd_hist"],
                lookback=100,
            )
        """
        params: dict[str, Any] = {"lookback": lookback}
        if indicators is not None:
            params["indicators"] = ",".join(indicators)
        return await self._request(
            "GET",
            f"/api/v1/market/indicators/{symbol}",
            params=params,
        )

    async def get_available_indicators(self) -> dict[str, Any]:
        """Fetch the list of all indicators supported by the platform.

        Returns:
            Dict with an ``indicators`` list; each entry describes the
            indicator name, display label, and parameter defaults.

        Example::

            info = await client.get_available_indicators()
            for ind in info["indicators"]:
                print(ind["name"], ind["label"])
        """
        return await self._request("GET", "/api/v1/market/indicators/available")

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

    # ------------------------------------------------------------------
    # Strategies (6 methods)
    # ------------------------------------------------------------------

    async def create_strategy(
        self,
        name: str,
        definition: dict[str, Any],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new trading strategy.

        Args:
            name:       Strategy name.
            definition: Strategy definition dict (pairs, conditions, etc.).
            description: Optional strategy description.

        Returns:
            Strategy response dict.
        """
        body: dict[str, Any] = {"name": name, "definition": definition}
        if description:
            body["description"] = description
        return await self._request("POST", "/api/v1/strategies", json=body)

    async def get_strategies(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List all strategies for the account.

        Args:
            status: Optional filter by status.
            limit:  Max results.
            offset: Pagination offset.

        Returns:
            Dict with ``strategies`` list and ``total`` count.
        """
        return await self._request(
            "GET", "/api/v1/strategies",
            params={"status": status, "limit": limit, "offset": offset},
        )

    async def get_strategy(self, strategy_id: str | UUID) -> dict[str, Any]:
        """Get detailed strategy info including current version and test results.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            Strategy detail response dict.
        """
        return await self._request("GET", f"/api/v1/strategies/{strategy_id}")

    async def create_version(
        self,
        strategy_id: str | UUID,
        definition: dict[str, Any],
        change_notes: str | None = None,
    ) -> dict[str, Any]:
        """Create a new version of a strategy.

        Args:
            strategy_id:  UUID of the strategy.
            definition:   Updated strategy definition.
            change_notes: Description of changes.

        Returns:
            Version response dict.
        """
        body: dict[str, Any] = {"definition": definition}
        if change_notes:
            body["change_notes"] = change_notes
        return await self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/versions", json=body
        )

    async def deploy_strategy(
        self, strategy_id: str | UUID, version: int
    ) -> dict[str, Any]:
        """Deploy a strategy version for live trading.

        Args:
            strategy_id: UUID of the strategy.
            version:     Version number to deploy.

        Returns:
            Strategy response dict.
        """
        return await self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/deploy",
            json={"version": version},
        )

    async def undeploy_strategy(self, strategy_id: str | UUID) -> dict[str, Any]:
        """Stop live trading for a deployed strategy.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            Strategy response dict.
        """
        return await self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/undeploy"
        )

    async def compare_strategies(
        self,
        strategy_ids: list[str | UUID],
        ranking_metric: str = "sharpe_ratio",
    ) -> dict[str, Any]:
        """Rank and compare multiple strategies by their latest test results.

        Accepts 2–10 strategy UUIDs, fetches their latest completed test runs,
        and ranks them by the chosen metric.  Returns a ranked list with
        per-strategy metrics, optional Deflated Sharpe data, and a one-line
        recommendation identifying the winner.

        Args:
            strategy_ids:   List of 2–10 strategy UUIDs to compare.
            ranking_metric: Metric used to rank strategies.  Allowed values:
                            ``"sharpe_ratio"``, ``"sortino_ratio"``,
                            ``"max_drawdown_pct"``, ``"win_rate"``,
                            ``"roi_pct"``, ``"profit_factor"``.
                            Defaults to ``"sharpe_ratio"``.

        Returns:
            Dict with keys ``strategies`` (ranked list), ``winner_id``,
            ``ranking_metric``, and ``recommendation``.

        Example::

            result = await client.compare_strategies(
                [strategy_a_id, strategy_b_id],
                ranking_metric="sharpe_ratio",
            )
            print(result["winner_id"])
            print(result["recommendation"])
        """
        return await self._request(
            "POST",
            "/api/v1/strategies/compare",
            json={
                "strategy_ids": [str(sid) for sid in strategy_ids],
                "ranking_metric": ranking_metric,
            },
        )

    # ------------------------------------------------------------------
    # Strategy Testing (4 methods)
    # ------------------------------------------------------------------

    async def run_test(
        self,
        strategy_id: str | UUID,
        version: int,
        *,
        episodes: int = 10,
        date_range: dict[str, str] | None = None,
        episode_duration_days: int = 30,
    ) -> dict[str, Any]:
        """Trigger a multi-episode test of a strategy version.

        Args:
            strategy_id:          UUID of the strategy.
            version:              Version number to test.
            episodes:             Number of test episodes.
            date_range:           Optional ``{"start": "...", "end": "..."}`` dict.
            episode_duration_days: Days per episode.

        Returns:
            Test run response dict with ``test_run_id``.
        """
        body: dict[str, Any] = {"version": version, "episodes": episodes}
        if date_range:
            body["date_range"] = date_range
        body["episode_duration_days"] = episode_duration_days
        return await self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/test", json=body
        )

    async def get_test_status(
        self, strategy_id: str | UUID, test_id: str | UUID
    ) -> dict[str, Any]:
        """Get the status and progress of a strategy test run.

        Args:
            strategy_id: UUID of the strategy.
            test_id:     UUID of the test run.

        Returns:
            Test run status dict.
        """
        return await self._request(
            "GET", f"/api/v1/strategies/{strategy_id}/tests/{test_id}"
        )

    async def get_test_results(
        self, strategy_id: str | UUID, test_id: str | UUID
    ) -> dict[str, Any]:
        """Get full test results with metrics and recommendations.

        Args:
            strategy_id: UUID of the strategy.
            test_id:     UUID of the test run.

        Returns:
            Test results dict with aggregated metrics and recommendations.
        """
        return await self._request(
            "GET", f"/api/v1/strategies/{strategy_id}/tests/{test_id}"
        )

    async def compare_versions(
        self, strategy_id: str | UUID, v1: int, v2: int
    ) -> dict[str, Any]:
        """Compare test results between two strategy versions.

        Args:
            strategy_id: UUID of the strategy.
            v1:          First version number.
            v2:          Second version number.

        Returns:
            Version comparison dict with improvements and verdict.
        """
        return await self._request(
            "GET", f"/api/v1/strategies/{strategy_id}/compare-versions",
            params={"v1": v1, "v2": v2},
        )

    # ------------------------------------------------------------------
    # Training (3 methods)
    # ------------------------------------------------------------------

    async def get_training_runs(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List all training runs.

        Args:
            status: Optional filter by status.
            limit:  Max results.
            offset: Pagination offset.

        Returns:
            List of training run dicts.
        """
        return await self._request(
            "GET", "/api/v1/training/runs",
            params={"status": status, "limit": limit, "offset": offset},
        )

    async def get_training_run(self, run_id: str | UUID) -> dict[str, Any]:
        """Get full detail of a training run.

        Args:
            run_id: UUID of the training run.

        Returns:
            Training run detail dict with learning curve and episodes.
        """
        return await self._request("GET", f"/api/v1/training/runs/{run_id}")

    async def compare_training_runs(
        self, run_ids: list[str | UUID]
    ) -> dict[str, Any]:
        """Compare multiple training runs side-by-side.

        Args:
            run_ids: List of training run UUIDs.

        Returns:
            Comparison dict with per-run metrics.
        """
        # Validate all IDs as UUIDs to prevent injection
        validated = [str(UUID(str(rid))) for rid in run_ids]
        ids_str = ",".join(validated)
        return await self._request(
            "GET", "/api/v1/training/compare",
            params={"run_ids": ids_str},
        )

    # ------------------------------------------------------------------
    # Backtesting (1 method)
    # ------------------------------------------------------------------

    async def batch_step_fast(
        self,
        session_id: str,
        steps: int,
        include_intermediate_trades: bool = False,
    ) -> dict[str, Any]:
        """Advance a backtest session N candles using the optimised fast-batch path.

        The fast-batch endpoint defers per-step overhead (snapshots, portfolio
        computation, DB progress writes) to the end of the batch, making it
        suitable for RL training loops that issue hundreds of thousands of
        sequential step calls.

        Args:
            session_id:                   Backtest session UUID string.
            steps:                        Number of candle steps to advance
                                          (1 – 100 000).
            include_intermediate_trades:  When ``True``, all order fills from
                                          every step in the batch are included
                                          in ``orders_filled``.  When ``False``
                                          (default), only fills from the final
                                          step are returned, reducing response
                                          payload size.

        Returns:
            Dict matching the ``BatchStepFastResponse`` schema with keys:
            ``virtual_time``, ``step``, ``total_steps``, ``progress_pct``,
            ``prices``, ``orders_filled``, ``portfolio``, ``is_complete``,
            ``remaining_steps``, and ``steps_executed``.

        Raises:
            NotFoundError: If no backtest session with this ID exists.
            ServerError:   On engine-level failures.

        Example::

            result = await client.batch_step_fast(session_id, steps=500)
            print(result["steps_executed"], result["is_complete"])
        """
        return await self._request(
            "POST",
            f"/api/v1/backtest/{session_id}/step/batch/fast",
            json={
                "steps": steps,
                "include_intermediate_trades": include_intermediate_trades,
            },
        )

    # ------------------------------------------------------------------
    # Metrics (1 method)
    # ------------------------------------------------------------------

    async def compute_deflated_sharpe(
        self,
        returns: list[float],
        num_trials: int,
        annualization_factor: int = 252,
    ) -> dict[str, Any]:
        """Compute the Deflated Sharpe Ratio for a return series.

        The Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014) corrects the
        observed Sharpe Ratio for multiple-testing bias.  Use this when you have
        tested multiple strategy variants and want to know whether the best-looking
        one is genuinely skilled or just lucky.

        Args:
            returns:              List of per-period returns (not percentages).
                                  Requires at least 10 observations.
            num_trials:           Number of strategy variants tested before
                                  selecting this one.  Must be ≥ 1.
            annualization_factor: Number of return periods per year.  Use 252
                                  for daily returns, 52 for weekly, 12 for
                                  monthly.  Defaults to ``252``.

        Returns:
            Dict with DSR result fields: ``observed_sharpe``,
            ``expected_max_sharpe``, ``deflated_sharpe``, ``p_value``,
            ``is_significant``, ``num_trials``, ``num_returns``,
            ``skewness``, and ``kurtosis``.

        Raises:
            ValidationError: If the request body is rejected by the server
                (e.g., fewer than 10 returns).
            AgentExchangeError subclasses: For all other HTTP error responses.

        Example::

            result = await client.compute_deflated_sharpe(
                returns=[0.001, -0.002, 0.003] * 10,
                num_trials=5,
                annualization_factor=252,
            )
            print(result["is_significant"], result["p_value"])
        """
        return await self._request(
            "POST",
            "/api/v1/metrics/deflated-sharpe",
            json={
                "returns": returns,
                "num_trials": num_trials,
                "annualization_factor": annualization_factor,
            },
        )

    # ------------------------------------------------------------------
    # Webhooks (6 methods)
    # ------------------------------------------------------------------

    async def create_webhook(
        self,
        url: str,
        events: list[str],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new webhook subscription.

        The HMAC-SHA256 signing ``secret`` is returned **only** in this
        response.  Store it securely — it cannot be retrieved again.

        Args:
            url:         HTTPS endpoint that will receive webhook payloads.
            events:      List of event names to subscribe to.
                         Supported: ``backtest.completed``,
                         ``strategy.test.completed``,
                         ``strategy.deployed``, ``battle.completed``.
            description: Optional human-readable label.

        Returns:
            Webhook creation response dict including the one-time ``secret``.

        Example::

            result = await client.create_webhook(
                url="https://example.com/hooks",
                events=["backtest.completed"],
            )
            print(result["secret"])  # store this!
        """
        body: dict[str, Any] = {"url": url, "events": events}
        if description is not None:
            body["description"] = description
        return await self._request("POST", "/api/v1/webhooks", json=body)

    async def list_webhooks(self) -> dict[str, Any]:
        """List all webhook subscriptions for the authenticated account.

        Returns:
            Dict with ``webhooks`` list and ``total`` count.  The signing
            ``secret`` is NOT included in list responses.

        Example::

            result = await client.list_webhooks()
            for wh in result["webhooks"]:
                print(wh["id"], wh["url"])
        """
        return await self._request("GET", "/api/v1/webhooks")

    async def get_webhook(self, webhook_id: str | UUID) -> dict[str, Any]:
        """Get detail for a single webhook subscription.

        Args:
            webhook_id: UUID of the webhook subscription.

        Returns:
            Webhook detail dict (without the signing secret).

        Example::

            wh = await client.get_webhook("550e8400-e29b-41d4-a716-446655440000")
            print(wh["active"], wh["failure_count"])
        """
        return await self._request("GET", f"/api/v1/webhooks/{webhook_id}")

    async def update_webhook(
        self,
        webhook_id: str | UUID,
        *,
        url: str | None = None,
        events: list[str] | None = None,
        active: bool | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update a webhook subscription (partial update).

        Only fields explicitly passed are modified.

        Args:
            webhook_id:  UUID of the webhook subscription.
            url:         New HTTPS endpoint URL.
            events:      Replacement event list.
            active:      Enable (``True``) or disable (``False``) the subscription.
            description: New optional label.

        Returns:
            Updated webhook detail dict.

        Example::

            await client.update_webhook(webhook_id, active=False)
        """
        body: dict[str, Any] = {}
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = events
        if active is not None:
            body["active"] = active
        if description is not None:
            body["description"] = description
        return await self._request("PUT", f"/api/v1/webhooks/{webhook_id}", json=body)

    async def delete_webhook(self, webhook_id: str | UUID) -> None:
        """Delete a webhook subscription.

        Args:
            webhook_id: UUID of the webhook subscription.

        Example::

            await client.delete_webhook("550e8400-e29b-41d4-a716-446655440000")
        """
        await self._request("DELETE", f"/api/v1/webhooks/{webhook_id}")

    async def test_webhook(self, webhook_id: str | UUID) -> dict[str, Any]:
        """Send a test event delivery to a webhook endpoint.

        Enqueues a ``webhook.test`` payload so you can verify your endpoint
        receives and validates HMAC-SHA256 signatures correctly.

        Args:
            webhook_id: UUID of the webhook subscription to test.

        Returns:
            Dict with ``enqueued`` count and ``webhook_id``.

        Example::

            result = await client.test_webhook("550e8400-e29b-41d4-a716-446655440000")
            print(result["enqueued"])
        """
        return await self._request("POST", f"/api/v1/webhooks/{webhook_id}/test")

    # ------------------------------------------------------------------
    # Analytics (3 methods)
    # ------------------------------------------------------------------

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
