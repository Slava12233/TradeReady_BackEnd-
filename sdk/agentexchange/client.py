"""Synchronous Python client for the AgentExchange trading platform.

Wraps all 22 REST API methods with automatic JWT authentication, transparent
token refresh, and exponential-backoff retry on transient 5xx errors.

Usage::

    from agentexchange import AgentExchangeClient

    client = AgentExchangeClient(
        api_key="ak_live_...",
        api_secret="sk_live_...",
        base_url="http://localhost:8000",
    )

    price = client.get_price("BTCUSDT")
    order = client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
    client.close()

    # Or use as a context manager:
    with AgentExchangeClient(api_key="...", api_secret="...") as client:
        balance = client.get_balance()
"""

from __future__ import annotations

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


class AgentExchangeClient:
    """Synchronous client for the AgentExchange REST API.

    Authenticates on first use by exchanging the API key + secret for a JWT
    token.  The token is refreshed automatically before it expires.  All 5xx
    responses are retried up to three times with exponential back-off
    (1 s / 2 s / 4 s).

    Args:
        api_key:    Agent API key (``ak_live_...`` format).
        api_secret: Agent API secret (``sk_live_...`` format).
        base_url:   Base URL of the platform REST API.
                    Defaults to ``http://localhost:8000``.
        timeout:    HTTP request timeout in seconds.  Defaults to ``30``.

    Example::

        client = AgentExchangeClient(
            api_key="ak_live_abc",
            api_secret="sk_live_xyz",
            base_url="http://localhost:8000",
        )
        price = client.get_price("BTCUSDT")
        client.close()
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
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={"X-API-Key": self._api_key},
        )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "AgentExchangeClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool.

        Always call this when you are done with the client (or use it as a
        context manager so it is closed automatically).
        """
        self._http.close()

    # ------------------------------------------------------------------
    # Internal: auth & request helpers
    # ------------------------------------------------------------------

    def _login(self) -> None:
        """Exchange API key + secret for a JWT; store it for subsequent calls."""
        response = self._http.post(
            "/api/v1/auth/login",
            json={"api_key": self._api_key, "api_secret": self._api_secret},
        )
        self._raise_for_response(response)
        data: dict[str, Any] = response.json()
        self._jwt = data["token"]
        # Parse expiry; fall back to 15-minute window if missing
        expires_in: int = data.get("expires_in", 900)
        self._jwt_expires_at = time.time() + expires_in - 30  # 30-s buffer

    def _ensure_auth(self) -> None:
        """Ensure a valid JWT is available, refreshing if necessary."""
        if self._jwt is None or time.time() >= self._jwt_expires_at:
            self._login()

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

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an authenticated HTTP request with retry on 5xx errors.

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
        self._ensure_auth()
        headers = {"Authorization": f"Bearer {self._jwt}"}

        last_exc: Exception | None = None
        for attempt, delay in enumerate([0.0, *_RETRY_DELAYS]):
            if attempt > 0:
                logger.debug(
                    "Retrying %s %s (attempt %d) after %.1fs",
                    method,
                    path,
                    attempt + 1,
                    delay,
                )
                time.sleep(delay)
            try:
                response = self._http.request(
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

            logger.debug(
                "%s %s → %d", method, path, response.status_code
            )

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
        self._raise_for_response(response)  # type: ignore[possibly-undefined]
        return {}

    # ------------------------------------------------------------------
    # Market data (6 methods)
    # ------------------------------------------------------------------

    def get_price(self, symbol: str) -> Price:
        """Fetch the current market price for a single symbol.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            :class:`~agentexchange.models.Price` with ``symbol``, ``price``,
            and ``timestamp``.

        Raises:
            InvalidSymbolError: If the symbol is unknown or has no price yet.

        Example::

            price = client.get_price("BTCUSDT")
            print(price.price)  # Decimal('64521.30')
        """
        data = self._request("GET", f"/api/v1/market/price/{symbol}")
        return Price.from_dict(data)

    def get_all_prices(self) -> list[Price]:
        """Fetch current prices for all active trading pairs.

        Returns:
            List of :class:`~agentexchange.models.Price` objects.

        Example::

            prices = client.get_all_prices()
            for p in prices:
                print(p.symbol, p.price)
        """
        data = self._request("GET", "/api/v1/market/prices")
        return [Price.from_dict(item) for item in data.get("prices", [])]

    def get_candles(
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

            candles = client.get_candles("BTCUSDT", interval="1h", limit=24)
            for c in candles:
                print(c.time, c.close)
        """
        data = self._request(
            "GET",
            f"/api/v1/market/candles/{symbol}",
            params={"interval": interval, "limit": limit},
        )
        return [Candle.from_dict(c) for c in data.get("candles", [])]

    def get_ticker(self, symbol: str) -> Ticker:
        """Fetch 24-hour market statistics for a symbol.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            :class:`~agentexchange.models.Ticker` with OHLCV and change data.

        Example::

            ticker = client.get_ticker("BTCUSDT")
            print(ticker.change_pct, ticker.volume)
        """
        data = self._request("GET", f"/api/v1/market/ticker/{symbol}")
        return Ticker.from_dict(data)

    def get_recent_trades(self, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch recent public trades for a symbol.

        Args:
            symbol: Uppercase trading pair.
            limit:  Maximum number of trades to return (1–1000).
                    Defaults to ``50``.

        Returns:
            List of raw trade dicts with ``price``, ``quantity``, ``side``,
            and ``executed_at`` fields.

        Example::

            trades = client.get_recent_trades("BTCUSDT", limit=10)
            for t in trades:
                print(t["price"], t["side"])
        """
        data = self._request(
            "GET",
            f"/api/v1/market/trades/{symbol}",
            params={"limit": limit},
        )
        return data.get("trades", [])

    def get_orderbook(self, symbol: str, depth: int = 10) -> dict[str, Any]:
        """Fetch the current order book snapshot for a symbol.

        Args:
            symbol: Uppercase trading pair.
            depth:  Number of price levels to return on each side (1–100).
                    Defaults to ``10``.

        Returns:
            Dict with ``bids`` and ``asks`` lists; each entry is
            ``[price_str, quantity_str]``.

        Example::

            book = client.get_orderbook("BTCUSDT", depth=5)
            best_bid = book["bids"][0]
        """
        data = self._request(
            "GET",
            f"/api/v1/market/orderbook/{symbol}",
            params={"depth": depth},
        )
        return data

    # ------------------------------------------------------------------
    # Trading (8 methods)
    # ------------------------------------------------------------------

    def place_market_order(
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

            order = client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
            print(order.executed_price, order.fee)
        """
        data = self._request(
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

    def place_limit_order(
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

            order = client.place_limit_order("BTCUSDT", "buy", "0.001", 60000)
            print(order.order_id, order.status)
        """
        data = self._request(
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

    def place_stop_loss(
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

            order = client.place_stop_loss("BTCUSDT", "sell", "0.001", 58000)
        """
        data = self._request(
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

    def place_take_profit(
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

            order = client.place_take_profit("BTCUSDT", "sell", "0.001", 70000)
        """
        data = self._request(
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

    def get_order(self, order_id: str | UUID) -> Order:
        """Fetch the current status and details of a single order.

        Args:
            order_id: UUID of the order (string or :class:`~uuid.UUID`).

        Returns:
            :class:`~agentexchange.models.Order` with the latest status.

        Raises:
            NotFoundError: If no order with this ID exists on the account.

        Example::

            order = client.get_order("550e8400-e29b-41d4-a716-446655440000")
            print(order.status)
        """
        data = self._request("GET", f"/api/v1/trade/order/{order_id}")
        return Order.from_dict(data)

    def get_open_orders(self) -> list[Order]:
        """Fetch all currently pending (open) orders for the account.

        Returns:
            List of :class:`~agentexchange.models.Order` with
            ``status="pending"``.

        Example::

            open_orders = client.get_open_orders()
            for o in open_orders:
                print(o.order_id, o.symbol, o.side)
        """
        data = self._request("GET", "/api/v1/trade/orders/open")
        return [Order.from_dict(o) for o in data.get("orders", [])]

    def cancel_order(self, order_id: str | UUID) -> bool:
        """Cancel a single pending order.

        Args:
            order_id: UUID of the order to cancel.

        Returns:
            ``True`` when the cancellation was accepted.

        Raises:
            NotFoundError: If the order does not exist.
            OrderError: If the order is not in a cancellable state.

        Example::

            client.cancel_order("550e8400-e29b-41d4-a716-446655440000")
        """
        self._request("DELETE", f"/api/v1/trade/order/{order_id}")
        return True

    def cancel_all_orders(self) -> int:
        """Cancel all open (pending) orders for the account.

        Returns:
            Number of orders that were cancelled.

        Example::

            n = client.cancel_all_orders()
            print(f"Cancelled {n} orders")
        """
        data = self._request("DELETE", "/api/v1/trade/orders/open")
        return int(data.get("cancelled_count", 0))

    def get_trade_history(
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

            history = client.get_trade_history(symbol="BTCUSDT", limit=100)
            for t in history:
                print(t.executed_at, t.side, t.price)
        """
        data = self._request(
            "GET",
            "/api/v1/trade/history",
            params={"symbol": symbol, "limit": limit, "offset": offset},
        )
        return [Trade.from_dict(t) for t in data.get("trades", [])]

    # ------------------------------------------------------------------
    # Account (5 methods)
    # ------------------------------------------------------------------

    def get_account_info(self) -> AccountInfo:
        """Fetch full account information, session, and risk profile.

        Returns:
            :class:`~agentexchange.models.AccountInfo` with account metadata
            and configuration.

        Example::

            info = client.get_account_info()
            print(info.display_name, info.status)
        """
        data = self._request("GET", "/api/v1/account/info")
        return AccountInfo.from_dict(data)

    def get_balance(self) -> list[Balance]:
        """Fetch all asset balances for the account.

        Returns:
            List of :class:`~agentexchange.models.Balance` — one per asset
            with non-zero holdings.

        Example::

            balances = client.get_balance()
            usdt = next(b for b in balances if b.asset == "USDT")
            print(usdt.available)
        """
        data = self._request("GET", "/api/v1/account/balance")
        return [Balance.from_dict(b) for b in data.get("balances", [])]

    def get_positions(self) -> list[Position]:
        """Fetch all currently open positions for the account.

        Returns:
            List of :class:`~agentexchange.models.Position` with unrealised P&L.

        Example::

            positions = client.get_positions()
            for p in positions:
                print(p.symbol, p.unrealized_pnl)
        """
        data = self._request("GET", "/api/v1/account/positions")
        return [Position.from_dict(p) for p in data.get("positions", [])]

    def get_portfolio(self) -> Portfolio:
        """Fetch a full portfolio snapshot combining balances, positions, and P&L.

        Returns:
            :class:`~agentexchange.models.Portfolio` with equity and P&L summary.

        Example::

            pf = client.get_portfolio()
            print(pf.total_equity, pf.roi_pct)
        """
        data = self._request("GET", "/api/v1/account/portfolio")
        return Portfolio.from_dict(data)

    def get_pnl(self, period: str = "all") -> PnL:
        """Fetch P&L breakdown for a given time period.

        Args:
            period: Time window: ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``.
                    Defaults to ``"all"``.

        Returns:
            :class:`~agentexchange.models.PnL` with realised/unrealised P&L,
            win rate, and fee summary.

        Example::

            pnl = client.get_pnl(period="7d")
            print(pnl.win_rate, pnl.net_pnl)
        """
        data = self._request("GET", "/api/v1/account/pnl", params={"period": period})
        return PnL.from_dict(data)

    def reset_account(
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

            result = client.reset_account(starting_balance=5000)
            print(result["session_id"])
        """
        data = self._request(
            "POST",
            "/api/v1/account/reset",
            json={"starting_balance": str(Decimal(str(starting_balance)))},
        )
        return data

    # ------------------------------------------------------------------
    # Analytics (3 methods)
    # ------------------------------------------------------------------

    def get_performance(self, period: str = "all") -> Performance:
        """Fetch statistical performance metrics for a given period.

        Args:
            period: Time window: ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``.
                    Defaults to ``"all"``.

        Returns:
            :class:`~agentexchange.models.Performance` with Sharpe ratio,
            max drawdown, win rate, and more.

        Example::

            perf = client.get_performance(period="30d")
            print(perf.sharpe_ratio, perf.max_drawdown_pct)
        """
        data = self._request(
            "GET", "/api/v1/analytics/performance", params={"period": period}
        )
        return Performance.from_dict(data)

    def get_portfolio_history(
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

            history = client.get_portfolio_history(interval="1h")
            for s in history:
                print(s.time, s.total_equity)
        """
        data = self._request(
            "GET",
            "/api/v1/analytics/portfolio/history",
            params={"interval": interval, "limit": limit},
        )
        return [Snapshot.from_dict(s) for s in data.get("snapshots", [])]

    # ------------------------------------------------------------------
    # Strategies (6 methods)
    # ------------------------------------------------------------------

    def create_strategy(
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
        return self._request("POST", "/api/v1/strategies", json=body)

    def get_strategies(
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
        return self._request(
            "GET", "/api/v1/strategies",
            params={"status": status, "limit": limit, "offset": offset},
        )

    def get_strategy(self, strategy_id: str | UUID) -> dict[str, Any]:
        """Get detailed strategy info including current version and test results.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            Strategy detail response dict.
        """
        return self._request("GET", f"/api/v1/strategies/{strategy_id}")

    def create_version(
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
        return self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/versions", json=body
        )

    def deploy_strategy(
        self, strategy_id: str | UUID, version: int
    ) -> dict[str, Any]:
        """Deploy a strategy version for live trading.

        Args:
            strategy_id: UUID of the strategy.
            version:     Version number to deploy.

        Returns:
            Strategy response dict.
        """
        return self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/deploy",
            json={"version": version},
        )

    def undeploy_strategy(self, strategy_id: str | UUID) -> dict[str, Any]:
        """Stop live trading for a deployed strategy.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            Strategy response dict.
        """
        return self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/undeploy"
        )

    # ------------------------------------------------------------------
    # Strategy Testing (4 methods)
    # ------------------------------------------------------------------

    def run_test(
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
        return self._request(
            "POST", f"/api/v1/strategies/{strategy_id}/test", json=body
        )

    def get_test_status(
        self, strategy_id: str | UUID, test_id: str | UUID
    ) -> dict[str, Any]:
        """Get the status and progress of a strategy test run.

        Args:
            strategy_id: UUID of the strategy.
            test_id:     UUID of the test run.

        Returns:
            Test run status dict.
        """
        return self._request(
            "GET", f"/api/v1/strategies/{strategy_id}/tests/{test_id}"
        )

    def get_test_results(
        self, strategy_id: str | UUID, test_id: str | UUID
    ) -> dict[str, Any]:
        """Get full test results with metrics and recommendations.

        Args:
            strategy_id: UUID of the strategy.
            test_id:     UUID of the test run.

        Returns:
            Test results dict with aggregated metrics and recommendations.
        """
        return self._request(
            "GET", f"/api/v1/strategies/{strategy_id}/tests/{test_id}"
        )

    def compare_versions(
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
        return self._request(
            "GET", f"/api/v1/strategies/{strategy_id}/compare-versions",
            params={"v1": v1, "v2": v2},
        )

    # ------------------------------------------------------------------
    # Training (3 methods)
    # ------------------------------------------------------------------

    def get_training_runs(
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
        return self._request(
            "GET", "/api/v1/training/runs",
            params={"status": status, "limit": limit, "offset": offset},
        )

    def get_training_run(self, run_id: str | UUID) -> dict[str, Any]:
        """Get full detail of a training run.

        Args:
            run_id: UUID of the training run.

        Returns:
            Training run detail dict with learning curve and episodes.
        """
        return self._request("GET", f"/api/v1/training/runs/{run_id}")

    def compare_training_runs(
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
        return self._request(
            "GET", "/api/v1/training/compare",
            params={"run_ids": ids_str},
        )

    # ------------------------------------------------------------------
    # Analytics (3 methods)
    # ------------------------------------------------------------------

    def get_leaderboard(
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

            rankings = client.get_leaderboard(period="7d", limit=10)
            for entry in rankings[:3]:
                print(entry.rank, entry.display_name, entry.roi_pct)
        """
        data = self._request(
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


__all__ = ["AgentExchangeClient"]
