"""REST client and Pydantic AI tool functions for platform endpoints not in the SDK.

Covers the backtest lifecycle, strategy management, and strategy testing surfaces
that the AsyncAgentExchangeClient SDK does not expose.  A single
``PlatformRESTClient`` handles auth, connection reuse, and error handling.
``get_rest_tools`` returns a list of plain async functions ready to be passed to
a Pydantic AI ``Agent`` as tools.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx
import structlog

from agent.config import AgentConfig
from agent.logging import get_trace_id
from agent.logging_middleware import log_api_call

logger = structlog.get_logger(__name__)


class PlatformRESTClient:
    """Async HTTP client for platform endpoints not covered by the SDK.

    Uses a single ``httpx.AsyncClient`` (30 s timeout) for the lifetime of the
    instance.  Every request carries the ``X-API-Key`` header derived from the
    supplied ``AgentConfig``.  Call :meth:`close` (or use as an async context
    manager) to release the underlying connection pool.

    Example::

        async with PlatformRESTClient(config) as client:
            result = await client.create_backtest(
                start_time="2024-01-01T00:00:00Z",
                end_time="2024-03-01T00:00:00Z",
                symbols=["BTCUSDT"],
                interval=60,
            )

    Args:
        config: Loaded :class:`AgentConfig` instance.
    """

    def __init__(self, config: AgentConfig) -> None:
        self._base_url = config.platform_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-API-Key": config.platform_api_key},
            timeout=30.0,
        )

    # ── Async context manager ─────────────────────────────────────────────────

    async def __aenter__(self) -> PlatformRESTClient:
        """Enter the async context, returning self."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close the underlying HTTP client."""
        await self.close()

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` and release connections.

        Must be called when the client is no longer needed unless used as an
        async context manager.
        """
        await self._client.aclose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _trace_headers(self) -> dict[str, str]:
        """Return a headers dict carrying the current trace ID, if one is set.

        Returns:
            A dict with the ``X-Trace-Id`` key when a trace ID is active in the
            current ``asyncio`` context, or an empty dict otherwise.  Pass the
            result as the ``headers`` keyword argument to ``httpx`` request
            methods to propagate the trace across service boundaries.
        """
        trace_id = get_trace_id()
        if trace_id:
            return {"X-Trace-Id": trace_id}
        return {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an authenticated GET request and return parsed JSON.

        Args:
            path: URL path relative to the base URL (must start with ``/``).
            params: Optional query parameters.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses after logging.
        """
        try:
            response = await self._client.get(path, params=params, headers=self._trace_headers())
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            logger.error(
                "agent.api.get.http_error",
                path=path,
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            raise
        except httpx.RequestError as exc:
            logger.error("agent.api.get.network_error", path=path, error=str(exc))
            raise

    async def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an authenticated POST request and return parsed JSON.

        Args:
            path: URL path relative to the base URL (must start with ``/``).
            body: Optional JSON-serialisable request body.

        Returns:
            Parsed JSON response body as a dict.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses after logging.
        """
        try:
            response = await self._client.post(path, json=body, headers=self._trace_headers())
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            logger.error(
                "agent.api.post.http_error",
                path=path,
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            raise
        except httpx.RequestError as exc:
            logger.error("agent.api.post.network_error", path=path, error=str(exc))
            raise

    # ── Backtest methods ──────────────────────────────────────────────────────

    async def create_backtest(
        self,
        start_time: str,
        end_time: str,
        symbols: list[str],
        interval: int = 60,
        starting_balance: str = "10000",
        strategy_label: str = "default",
    ) -> dict[str, Any]:
        """Create a new backtest session.

        Sends ``POST /api/v1/backtest/create``.  The session must then be started
        with :meth:`start_backtest` before stepping.

        Args:
            start_time: ISO-8601 UTC start timestamp (e.g. ``"2024-01-01T00:00:00Z"``).
            end_time: ISO-8601 UTC end timestamp.
            symbols: List of trading pair symbols to include (e.g. ``["BTCUSDT"]``).
                Pass an empty list for all available pairs.
            interval: Candle interval in seconds (minimum 60, default 60).
            starting_balance: Starting virtual USDT balance as a string decimal.
            strategy_label: Human-readable label for the strategy (max 100 chars).

        Returns:
            Dict with keys: ``session_id``, ``status``, ``total_steps``,
            ``estimated_pairs``, ``agent_id``.
        """
        async with log_api_call("rest", "/api/v1/backtest/create", method="POST") as ctx:
            response = await self._client.post(
                "/api/v1/backtest/create",
                headers=self._trace_headers(),
                json={
                    "start_time": start_time,
                    "end_time": end_time,
                    "pairs": symbols if symbols else None,
                    "candle_interval": interval,
                    "starting_balance": starting_balance,
                    "strategy_label": strategy_label,
                },
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def start_backtest(self, session_id: str) -> dict[str, Any]:
        """Start a created backtest session.

        Sends ``POST /api/v1/backtest/{session_id}/start``.  This bulk-preloads
        all candle data into the in-memory sandbox — it may take several seconds.
        Do not call step endpoints until this returns successfully.

        Args:
            session_id: UUID string of the backtest session to start.

        Returns:
            Dict with keys: ``status`` (``"running"``), ``session_id``.
        """
        path = f"/api/v1/backtest/{session_id}/start"
        async with log_api_call("rest", path, method="POST") as ctx:
            response = await self._client.post(path, headers=self._trace_headers())
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]

    async def step_backtest_batch(self, session_id: str, steps: int) -> dict[str, Any]:
        """Advance the backtest sandbox by N candle steps.

        Sends ``POST /api/v1/backtest/{session_id}/step/batch``.  Returns state
        after the final step of the batch.  Use this instead of single-step to
        fast-forward through periods with no intended trading activity.

        Args:
            session_id: UUID string of the running backtest session.
            steps: Number of candle intervals to advance (1 – 10 000).

        Returns:
            ``StepResponse`` dict with keys: ``virtual_time``, ``step``,
            ``total_steps``, ``progress_pct``, ``prices``, ``orders_filled``,
            ``portfolio``, ``is_complete``, ``remaining_steps``.
        """
        path = f"/api/v1/backtest/{session_id}/step/batch"
        async with log_api_call("rest", path, method="POST") as ctx:
            response = await self._client.post(path, headers=self._trace_headers(), json={"steps": steps})
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]

    async def backtest_trade(
        self,
        session_id: str,
        symbol: str,
        side: str,
        quantity: str,
        order_type: str = "market",
        price: str | None = None,
    ) -> dict[str, Any]:
        """Place an order inside the backtest sandbox.

        Sends ``POST /api/v1/backtest/{session_id}/trade/order``.  Market orders
        fill immediately at the current virtual price.  Limit / stop-loss /
        take-profit orders queue and are matched on subsequent steps.

        Args:
            session_id: UUID string of the running backtest session.
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
            side: ``"buy"`` or ``"sell"``.
            quantity: Order quantity as a decimal string (e.g. ``"0.001"``).
            order_type: One of ``"market"``, ``"limit"``, ``"stop_loss"``,
                ``"take_profit"``  (default ``"market"``).
            price: Required for ``"limit"``, ``"stop_loss"``, and
                ``"take_profit"`` order types.

        Returns:
            Dict with keys: ``order_id``, ``status``, ``executed_price``,
            ``executed_qty``, ``fee``, ``realized_pnl``.
        """
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }
        if price is not None:
            body["price"] = price
        path = f"/api/v1/backtest/{session_id}/trade/order"
        async with log_api_call("rest", path, method="POST") as ctx:
            response = await self._client.post(path, headers=self._trace_headers(), json=body)
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]

    async def get_backtest_results(self, session_id: str) -> dict[str, Any]:
        """Retrieve full results for a completed or cancelled backtest session.

        Sends ``GET /api/v1/backtest/{session_id}/results``.

        Args:
            session_id: UUID string of the backtest session.

        Returns:
            ``BacktestResultsResponse`` dict with keys: ``session_id``,
            ``status``, ``config``, ``summary``, ``metrics``, ``by_pair``.
            ``metrics`` may be ``None`` if there was insufficient data.
        """
        path = f"/api/v1/backtest/{session_id}/results"
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(path, headers=self._trace_headers())
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_backtest_candles(
        self,
        session_id: str,
        symbol: str,
        interval: int = 60,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get OHLCV candles up to the current virtual clock time.

        Sends ``GET /api/v1/backtest/{session_id}/market/candles/{symbol}``.
        Only returns candles at or before the sandbox's ``virtual_time`` —
        look-ahead bias is impossible by design.

        Args:
            session_id: UUID string of the running backtest session.
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
            interval: Candle interval in seconds (default 60).
            limit: Number of candles to return (1 – 1 000, default 100).

        Returns:
            Dict with keys: ``symbol``, ``interval``, ``candles`` (list of OHLCV
            dicts), ``count``.
        """
        path = f"/api/v1/backtest/{session_id}/market/candles/{symbol}"
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(
                path,
                headers=self._trace_headers(),
                params={"interval": interval, "limit": limit},
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Strategy methods ──────────────────────────────────────────────────────

    async def create_strategy(
        self,
        name: str,
        description: str,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new trading strategy.

        Sends ``POST /api/v1/strategies``.  The ``definition`` field is required
        by the backend and will be rejected if omitted.

        Args:
            name: Strategy name (1 – 200 characters).
            description: Optional human-readable description (max 2 000 chars).
                Pass an empty string for no description.
            definition: Strategy logic dict.  Must contain at least ``pairs``,
                ``timeframe``, ``entry_conditions``, and ``exit_conditions``.

        Returns:
            ``StrategyResponse`` dict with keys: ``strategy_id``, ``name``,
            ``description``, ``current_version``, ``status``, ``deployed_at``,
            ``created_at``, ``updated_at``.
        """
        body: dict[str, Any] = {
            "name": name,
            "definition": definition,
        }
        if description:
            body["description"] = description
        async with log_api_call("rest", "/api/v1/strategies", method="POST") as ctx:
            response = await self._client.post("/api/v1/strategies", headers=self._trace_headers(), json=body)
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]

    async def test_strategy(
        self,
        strategy_id: str,
        version: int,
        date_range: dict[str, str],
        episodes: int = 10,
        episode_duration_days: int = 30,
        starting_balance: str = "10000",
        randomize_dates: bool = True,
    ) -> dict[str, Any]:
        """Trigger a new strategy test run via Celery.

        Sends ``POST /api/v1/strategies/{strategy_id}/test``.  Test episodes run
        as background Celery tasks (5-min soft / 6-min hard time limit each).
        Poll :meth:`get_test_results` until ``status`` reaches a terminal state
        (``"completed"``, ``"failed"``, or ``"cancelled"``).

        Args:
            strategy_id: UUID string of the strategy to test.
            version: Strategy version number to test (integer >= 1).
            date_range: Dict with ``"start"`` and ``"end"`` ISO-8601 strings.
            episodes: Number of test episodes to run (1 – 100, default 10).
            episode_duration_days: Length of each episode in days (1 – 365,
                default 30).
            starting_balance: Starting virtual USDT per episode as a string
                decimal (default ``"10000"``).
            randomize_dates: If ``True``, each episode picks a random sub-range
                within ``date_range`` (default ``True``).

        Returns:
            ``TestRunResponse`` dict with keys: ``test_run_id``, ``status``,
            ``episodes_total``, ``episodes_completed``, ``progress_pct``,
            ``version``.
        """
        path = f"/api/v1/strategies/{strategy_id}/test"
        async with log_api_call("rest", path, method="POST") as ctx:
            response = await self._client.post(
                path,
                headers=self._trace_headers(),
                json={
                    "version": version,
                    "episodes": episodes,
                    "date_range": date_range,
                    "randomize_dates": randomize_dates,
                    "episode_duration_days": episode_duration_days,
                    "starting_balance": starting_balance,
                },
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]

    async def get_test_results(self, strategy_id: str, test_id: str) -> dict[str, Any]:
        """Get test run status and results for a specific test run.

        Sends ``GET /api/v1/strategies/{strategy_id}/tests/{test_id}``.  This
        endpoint doubles as both a status poll and a results fetch — results are
        included in the response whenever they are available.

        Args:
            strategy_id: UUID string of the parent strategy.
            test_id: UUID string of the test run.

        Returns:
            ``TestResultsResponse`` dict with keys: ``test_run_id``, ``status``,
            ``episodes_total``, ``episodes_completed``, ``progress_pct``,
            ``version``, ``results`` (nullable), ``recommendations`` (nullable),
            ``config``.
        """
        path = f"/api/v1/strategies/{strategy_id}/tests/{test_id}"
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(path, headers=self._trace_headers())
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def create_version(
        self,
        strategy_id: str,
        definition: dict[str, Any],
        change_notes: str | None = None,
    ) -> dict[str, Any]:
        """Create a new immutable version of an existing strategy.

        Sends ``POST /api/v1/strategies/{strategy_id}/versions``.  Each version
        is immutable after creation — updating a strategy means creating a new
        version, not editing the old one.

        Args:
            strategy_id: UUID string of the parent strategy.
            definition: Updated strategy logic dict.
            change_notes: Optional description of what changed in this version.

        Returns:
            ``StrategyVersionResponse`` dict with keys: ``version_id``,
            ``strategy_id``, ``version``, ``definition``, ``change_notes``,
            ``parent_version``, ``status``, ``created_at``.
        """
        body: dict[str, Any] = {"definition": definition}
        if change_notes is not None:
            body["change_notes"] = change_notes
        path = f"/api/v1/strategies/{strategy_id}/versions"
        async with log_api_call("rest", path, method="POST") as ctx:
            response = await self._client.post(path, headers=self._trace_headers(), json=body)
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()  # type: ignore[no-any-return]

    async def compare_versions(
        self,
        strategy_id: str,
        v1: int,
        v2: int,
    ) -> dict[str, Any]:
        """Compare test results between two versions of a strategy.

        Sends ``GET /api/v1/strategies/{strategy_id}/compare-versions?v1=N&v2=M``.
        Both versions must have at least one completed test run; otherwise the
        ``verdict`` field will report that no data is available.

        Args:
            strategy_id: UUID string of the parent strategy.
            v1: First version number (integer >= 1).
            v2: Second version number to compare against (integer >= 1).

        Returns:
            ``VersionComparisonResponse`` dict with keys: ``v1`` (metrics dict),
            ``v2`` (metrics dict), ``improvements`` (delta values; positive means
            v2 is better), ``verdict`` (human-readable summary string).
        """
        path = f"/api/v1/strategies/{strategy_id}/compare-versions"
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(
                path,
                headers=self._trace_headers(),
                params={"v1": v1, "v2": v2},
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Backtest analysis methods ─────────────────────────────────────────────

    async def compare_backtests(self, session_ids: list[str]) -> dict[str, Any]:
        """Compare multiple backtest sessions side-by-side.

        Sends ``GET /api/v1/backtest/compare?sessions=id1,id2,...``.  All
        sessions must belong to the authenticated account.

        Args:
            session_ids: List of backtest session UUID strings to compare.
                Must contain at least two entries.

        Returns:
            ``BacktestCompareResponse`` dict with keys: ``comparisons`` (list of
            per-session dicts with ``session_id``, ``strategy_label``,
            ``roi_pct``, ``sharpe_ratio``, ``max_drawdown_pct``,
            ``total_trades``, ``win_rate``, ``profit_factor``),
            ``best_by_roi``, ``best_by_sharpe``, ``best_by_drawdown``
            (session ID strings), ``recommendation`` (best session ID).
        """
        path = "/api/v1/backtest/compare"
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(
                path,
                headers=self._trace_headers(),
                params={"sessions": ",".join(session_ids)},
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_best_backtest(
        self,
        metric: str = "roi_pct",
        strategy_label: str | None = None,
    ) -> dict[str, Any]:
        """Find the best completed backtest for the account by a given metric.

        Sends ``GET /api/v1/backtest/best?metric=<metric>``.  Optionally
        filters to a specific strategy label.

        Args:
            metric: Metric to rank by.  Common values: ``"roi_pct"``
                (default), ``"sharpe_ratio"``, ``"max_drawdown_pct"``.
            strategy_label: If provided, only considers sessions with this
                exact strategy label.

        Returns:
            ``BacktestBestResponse`` dict with keys: ``session_id``,
            ``strategy_label``, ``metric``, ``value`` (string representation
            of the best metric value).
        """
        path = "/api/v1/backtest/best"
        params: dict[str, Any] = {"metric": metric}
        if strategy_label is not None:
            params["strategy_label"] = strategy_label
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(
                path,
                headers=self._trace_headers(),
                params=params,
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    async def get_equity_curve(
        self,
        session_id: str,
        interval: int = 1,
    ) -> dict[str, Any]:
        """Get time-series equity curve data for a completed backtest.

        Sends ``GET /api/v1/backtest/{session_id}/results/equity-curve``.
        Returns every N-th snapshot point to allow downsampling.

        Args:
            session_id: UUID string of the completed backtest session.
            interval: Stride for downsampling — only every ``interval``-th
                snapshot is returned (default 1 = all points, minimum 1).

        Returns:
            Dict with keys: ``session_id``, ``interval`` (str),
            ``snapshots`` (list of dicts each with ``simulated_at`` (ISO-8601),
            ``total_equity``, ``available_cash``, ``position_value``,
            ``unrealized_pnl``, ``realized_pnl`` — all as Decimal strings).
        """
        path = f"/api/v1/backtest/{session_id}/results/equity-curve"
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(
                path,
                headers=self._trace_headers(),
                params={"interval": interval},
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Agent decision analysis ───────────────────────────────────────────────

    async def analyze_decisions(
        self,
        agent_id: str,
        start: str | None = None,
        end: str | None = None,
        min_confidence: float | None = None,
        direction: str | None = None,
        pnl_outcome: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Analyze decision quality for an agent.

        Sends ``GET /api/v1/agents/{agent_id}/decisions/analyze``.  Returns
        aggregate win/loss statistics and the filtered list of decisions.
        Requires JWT authentication (the endpoint is under ``/agents/``).

        Args:
            agent_id: UUID string of the target agent.
            start: ISO-8601 UTC lower bound for ``created_at`` (inclusive).
                Example: ``"2026-01-01T00:00:00Z"``.
            end: ISO-8601 UTC upper bound for ``created_at`` (exclusive).
            min_confidence: Only include decisions with confidence >=
                this value (0.0 – 1.0).
            direction: Filter by trade direction: ``"buy"``, ``"sell"``, or
                ``"hold"``.  ``None`` means no direction filter.
            pnl_outcome: Filter by PnL outcome: ``"positive"``,
                ``"negative"``, or ``"all"`` (default server-side).
            limit: Maximum number of decision rows to return (1 – 500,
                default 200).

        Returns:
            ``DecisionAnalysisResponse`` dict with keys: ``total``, ``wins``,
            ``losses``, ``win_rate``, ``avg_pnl`` (nullable), ``avg_confidence``
            (nullable), ``by_direction`` (dict keyed by direction), ``decisions``
            (list of decision dicts).
        """
        path = f"/api/v1/agents/{agent_id}/decisions/analyze"
        params: dict[str, Any] = {"limit": limit}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if min_confidence is not None:
            params["min_confidence"] = min_confidence
        if direction is not None:
            params["direction"] = direction
        if pnl_outcome is not None:
            params["pnl_outcome"] = pnl_outcome
        async with log_api_call("rest", path, method="GET") as ctx:
            response = await self._client.get(
                path,
                headers=self._trace_headers(),
                params=params,
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]

    # ── Risk profile management ───────────────────────────────────────────────

    async def update_risk_profile(
        self,
        max_position_size_pct: int,
        daily_loss_limit_pct: int,
        max_open_orders: int,
    ) -> dict[str, Any]:
        """Update the risk limits for the authenticated account or agent.

        Sends ``PUT /api/v1/account/risk-profile``.  When an agent API key or
        ``X-Agent-Id`` header is in use, the limits are applied to the agent's
        risk profile; otherwise they apply to the account.

        Args:
            max_position_size_pct: Maximum single-position size as a
                percentage of total equity (1 – 100).
            daily_loss_limit_pct: Maximum daily loss allowed as a percentage
                of total equity (1 – 100).
            max_open_orders: Maximum number of concurrently open orders
                (minimum 1).

        Returns:
            ``RiskProfileInfo`` dict with the same three keys reflecting the
            persisted values.
        """
        path = "/api/v1/account/risk-profile"
        async with log_api_call("rest", path, method="PUT") as ctx:
            response = await self._client.put(
                path,
                headers=self._trace_headers(),
                json={
                    "max_position_size_pct": max_position_size_pct,
                    "daily_loss_limit_pct": daily_loss_limit_pct,
                    "max_open_orders": max_open_orders,
                },
            )
            ctx["response_status"] = response.status_code
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]


# ── Tool factory ──────────────────────────────────────────────────────────────


def get_rest_tools(config: AgentConfig) -> list[Any]:
    """Build and return a list of Pydantic AI tool functions backed by REST.

    Each returned function is a plain ``async def`` that the Pydantic AI
    framework can register as a tool.  The functions share a single
    :class:`PlatformRESTClient` instance created from ``config``.

    The client is intentionally not closed inside these tool functions — it is
    expected to live for the lifetime of the agent run.  The caller is
    responsible for calling ``client.close()`` when the agent session ends.

    Args:
        config: Loaded :class:`AgentConfig` instance used for base URL and
            API key.

    Returns:
        List of async callable tool functions suitable for passing to
        ``pydantic_ai.Agent(tools=...)``.
    """
    client = PlatformRESTClient(config)

    # ------------------------------------------------------------------
    # Backtest tools
    # ------------------------------------------------------------------

    async def create_backtest(
        start_time: str,
        end_time: str,
        symbols: list[str],
        interval: int = 60,
        starting_balance: str = "10000",
        strategy_label: str = "default",
    ) -> dict[str, Any]:
        """Create a new backtest session on the platform.

        Call this before any other backtest tool.  The returned ``session_id``
        must be passed to ``start_backtest`` before stepping or trading.

        Args:
            start_time: ISO-8601 UTC start of the backtest period
                (e.g. ``"2024-01-01T00:00:00Z"``).
            end_time: ISO-8601 UTC end of the backtest period.
            symbols: Trading pairs to include (e.g. ``["BTCUSDT", "ETHUSDT"]``).
                An empty list means all available pairs.
            interval: Candle interval in seconds (minimum 60).
            starting_balance: Virtual USDT to start with (decimal string).
            strategy_label: Label to tag this backtest session.

        Returns:
            Dict with ``session_id``, ``status``, ``total_steps``,
            ``estimated_pairs``, ``agent_id``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.create_backtest(
                start_time=start_time,
                end_time=end_time,
                symbols=symbols,
                interval=interval,
                starting_balance=starting_balance,
                strategy_label=strategy_label,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def start_backtest(session_id: str) -> dict[str, Any]:
        """Start a previously created backtest session.

        Bulk-preloads all candle data into the in-memory sandbox.  This may take
        a few seconds for long date ranges.  Only call ``step_backtest_batch``
        or ``backtest_trade`` after this returns ``status: running``.

        Args:
            session_id: UUID string returned by ``create_backtest``.

        Returns:
            Dict with ``status`` and ``session_id``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.start_backtest(session_id)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def step_backtest_batch(session_id: str, steps: int) -> dict[str, Any]:
        """Advance the backtest sandbox by N candle intervals.

        Returns the sandbox state after the final step.  When
        ``is_complete`` is ``True`` the backtest has finished and results are
        available via ``get_backtest_results``.

        Args:
            session_id: UUID string of the running backtest session.
            steps: Number of candle intervals to advance (1 – 10 000).

        Returns:
            ``StepResponse`` dict with ``virtual_time``, ``step``,
            ``total_steps``, ``progress_pct``, ``prices``, ``orders_filled``,
            ``portfolio``, ``is_complete``, ``remaining_steps``.  On error,
            returns ``{"error": "<message>"}``.
        """
        try:
            return await client.step_backtest_batch(session_id, steps)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def backtest_trade(
        session_id: str,
        symbol: str,
        side: str,
        quantity: str,
        order_type: str = "market",
        price: str | None = None,
    ) -> dict[str, Any]:
        """Place an order inside a running backtest sandbox.

        Market orders fill immediately at the current virtual price.  For limit,
        stop-loss, and take-profit orders supply a ``price`` value; they will be
        matched on subsequent steps.

        Args:
            session_id: UUID string of the running backtest session.
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
            side: ``"buy"`` or ``"sell"``.
            quantity: Order quantity as a decimal string (e.g. ``"0.001"``).
            order_type: ``"market"``, ``"limit"``, ``"stop_loss"``, or
                ``"take_profit"`` (default ``"market"``).
            price: Required for non-market order types.

        Returns:
            Dict with ``order_id``, ``status``, ``executed_price``,
            ``executed_qty``, ``fee``, ``realized_pnl``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.backtest_trade(
                session_id=session_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                price=price,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def get_backtest_results(session_id: str) -> dict[str, Any]:
        """Retrieve full results for a completed or cancelled backtest session.

        Args:
            session_id: UUID string of the backtest session.

        Returns:
            Dict with ``session_id``, ``status``, ``config``, ``summary``
            (``final_equity``, ``roi_pct``, ``total_trades``, etc.),
            ``metrics`` (``sharpe_ratio``, ``max_drawdown_pct``, etc. — may be
            ``None`` if insufficient trades), ``by_pair``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.get_backtest_results(session_id)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def get_backtest_candles(
        session_id: str,
        symbol: str,
        interval: int = 60,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get OHLCV candles up to the current virtual clock time.

        Only returns candles at or before the sandbox virtual time — look-ahead
        bias is impossible.  Use these candles for indicator calculation to
        decide whether to place an order.

        Args:
            session_id: UUID string of the running backtest session.
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
            interval: Candle interval in seconds (default 60).
            limit: Maximum number of candles to return (1 – 1 000).

        Returns:
            Dict with ``symbol``, ``interval``, ``candles`` (list of dicts each
            with ``bucket``, ``open``, ``high``, ``low``, ``close``,
            ``volume``), ``count``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.get_backtest_candles(
                session_id=session_id,
                symbol=symbol,
                interval=interval,
                limit=limit,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Strategy tools
    # ------------------------------------------------------------------

    async def create_strategy(
        name: str,
        description: str,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new trading strategy on the platform.

        The ``definition`` field is required and validated server-side.  A
        minimal valid definition must contain ``pairs``, ``timeframe``,
        ``entry_conditions``, and ``exit_conditions`` keys.

        Args:
            name: Strategy name (1 – 200 characters).
            description: Human-readable description (max 2 000 chars, or empty
                string for none).
            definition: Strategy logic dict.  Example::

                {
                    "pairs": ["BTCUSDT"],
                    "timeframe": "1h",
                    "entry_conditions": {"rsi_below": 30},
                    "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
                    "position_size_pct": 10,
                    "max_positions": 3,
                }

        Returns:
            ``StrategyResponse`` dict with ``strategy_id``, ``name``,
            ``description``, ``current_version``, ``status``, ``deployed_at``,
            ``created_at``, ``updated_at``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.create_strategy(
                name=name,
                description=description,
                definition=definition,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def test_strategy(
        strategy_id: str,
        version: int,
        date_range: dict[str, str],
        episodes: int = 10,
        episode_duration_days: int = 30,
        starting_balance: str = "10000",
        randomize_dates: bool = True,
    ) -> dict[str, Any]:
        """Trigger a strategy test run (Celery background task).

        Each episode is executed by a Celery worker (5-min soft / 6-min hard
        limit per episode).  Poll ``get_test_results`` at intervals until the
        ``status`` field reaches ``"completed"``, ``"failed"``, or
        ``"cancelled"``.

        Args:
            strategy_id: UUID string of the strategy to test.
            version: Version number to test (integer >= 1).
            date_range: Dict with ``"start"`` and ``"end"`` ISO-8601 strings
                (e.g. ``{"start": "2023-06-01T00:00:00Z",
                "end": "2024-01-01T00:00:00Z"}``).
            episodes: Number of test episodes (1 – 100).
            episode_duration_days: Length of each episode in calendar days
                (1 – 365).
            starting_balance: Starting virtual USDT per episode (decimal
                string).
            randomize_dates: Randomise episode start dates within
                ``date_range`` when ``True``.

        Returns:
            ``TestRunResponse`` dict with ``test_run_id``, ``status``,
            ``episodes_total``, ``episodes_completed``, ``progress_pct``,
            ``version``.  On error, returns ``{"error": "<message>"}``.
        """
        try:
            return await client.test_strategy(
                strategy_id=strategy_id,
                version=version,
                date_range=date_range,
                episodes=episodes,
                episode_duration_days=episode_duration_days,
                starting_balance=starting_balance,
                randomize_dates=randomize_dates,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def get_test_results(strategy_id: str, test_id: str) -> dict[str, Any]:
        """Poll status and retrieve results for a strategy test run.

        This endpoint doubles as status + results: always call it to check
        progress, and the ``results`` key will be populated once the run
        completes.  Terminal statuses are ``"completed"``, ``"failed"``, and
        ``"cancelled"``.

        Args:
            strategy_id: UUID string of the parent strategy.
            test_id: UUID string of the test run (from ``test_strategy``).

        Returns:
            ``TestResultsResponse`` dict with ``test_run_id``, ``status``,
            ``episodes_total``, ``episodes_completed``, ``progress_pct``,
            ``version``, ``results`` (nullable aggregated metrics dict),
            ``recommendations`` (nullable list of strings), ``config``.  On
            error, returns ``{"error": "<message>"}``.
        """
        try:
            return await client.get_test_results(strategy_id, test_id)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def create_strategy_version(
        strategy_id: str,
        definition: dict[str, Any],
        change_notes: str | None = None,
    ) -> dict[str, Any]:
        """Create a new immutable version of an existing strategy.

        Versions are append-only.  Existing versions are permanently accessible
        for audit and comparison.

        Args:
            strategy_id: UUID string of the parent strategy.
            definition: Updated strategy logic dict.
            change_notes: Optional description of changes in this version.

        Returns:
            ``StrategyVersionResponse`` dict with ``version_id``,
            ``strategy_id``, ``version``, ``definition``, ``change_notes``,
            ``parent_version``, ``status``, ``created_at``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.create_version(
                strategy_id=strategy_id,
                definition=definition,
                change_notes=change_notes,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def compare_strategy_versions(
        strategy_id: str,
        v1: int,
        v2: int,
    ) -> dict[str, Any]:
        """Compare test results between two versions of a strategy.

        Both versions must have at least one completed test run for metrics to
        be available.  The ``improvements`` dict shows the delta (positive means
        v2 is better).

        Args:
            strategy_id: UUID string of the parent strategy.
            v1: First version number (integer >= 1).
            v2: Second version number (integer >= 1).

        Returns:
            ``VersionComparisonResponse`` dict with ``v1`` (metrics),
            ``v2`` (metrics), ``improvements`` (delta dict), ``verdict``
            (human-readable summary).  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.compare_versions(
                strategy_id=strategy_id,
                v1=v1,
                v2=v2,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Backtest analysis tools
    # ------------------------------------------------------------------

    async def compare_backtests(session_ids: list[str]) -> dict[str, Any]:
        """Compare multiple completed backtest sessions side-by-side.

        Use this to select the best-performing strategy among several
        backtests.  The response highlights the top session by ROI, Sharpe
        ratio, and minimum drawdown, plus an overall recommendation.

        Args:
            session_ids: List of backtest session UUID strings to compare
                (minimum 2 entries).

        Returns:
            ``BacktestCompareResponse`` dict with ``comparisons`` (list of
            per-session metrics), ``best_by_roi``, ``best_by_sharpe``,
            ``best_by_drawdown`` (session ID strings), ``recommendation``
            (recommended session ID).  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.compare_backtests(session_ids=session_ids)
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def get_best_backtest(
        metric: str = "roi_pct",
        strategy_label: str | None = None,
    ) -> dict[str, Any]:
        """Find the best completed backtest for the account by a metric.

        Useful for auto-selecting the top-performing configuration without
        manually comparing each session.

        Args:
            metric: The metric to rank by.  Common choices: ``"roi_pct"``
                (default), ``"sharpe_ratio"``, ``"max_drawdown_pct"``.
            strategy_label: If provided, restrict the search to sessions
                tagged with this exact strategy label.

        Returns:
            Dict with ``session_id``, ``strategy_label``, ``metric``,
            ``value`` (best metric value as a string).  Returns
            ``{"error": "<message>"}`` if no completed sessions exist or on
            network failure.
        """
        try:
            return await client.get_best_backtest(
                metric=metric,
                strategy_label=strategy_label,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    async def get_equity_curve(
        session_id: str,
        interval: int = 1,
    ) -> dict[str, Any]:
        """Retrieve time-series equity curve data for a completed backtest.

        Returns portfolio equity snapshots taken during the backtest.
        Optionally downsample by returning every N-th point.  Use this to
        chart equity growth, identify drawdown periods, or compute
        custom metrics.

        Args:
            session_id: UUID string of the completed backtest session.
            interval: Return every ``interval``-th snapshot (default 1 = all
                points, minimum 1).  Higher values reduce response size.

        Returns:
            Dict with ``session_id``, ``interval`` (str), ``snapshots``
            (list of dicts with ``simulated_at``, ``total_equity``,
            ``available_cash``, ``position_value``, ``unrealized_pnl``,
            ``realized_pnl`` — all as Decimal strings).  On error,
            returns ``{"error": "<message>"}``.
        """
        try:
            return await client.get_equity_curve(
                session_id=session_id,
                interval=interval,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Agent decision analysis tool
    # ------------------------------------------------------------------

    async def analyze_agent_decisions(
        agent_id: str,
        start: str | None = None,
        end: str | None = None,
        min_confidence: float | None = None,
        direction: str | None = None,
        pnl_outcome: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Analyze decision quality for an agent.

        Returns aggregate win/loss statistics and the filtered list of
        decision records.  Use this for self-analysis — inspect which
        signals performed best, which directions are most profitable, and
        whether higher-confidence decisions outperform lower-confidence ones.

        Requires a JWT token in the ``Authorization`` header (the endpoint
        is under ``/api/v1/agents/`` which is JWT-only).

        Args:
            agent_id: UUID string of the target agent.
            start: ISO-8601 UTC lower bound for decision timestamp
                (e.g. ``"2026-01-01T00:00:00Z"``).  ``None`` = no lower bound.
            end: ISO-8601 UTC upper bound (exclusive).  ``None`` = no upper bound.
            min_confidence: Only include decisions with model confidence >=
                this value (0.0 – 1.0).
            direction: Filter to one direction: ``"buy"``, ``"sell"``, or
                ``"hold"``.  ``None`` = all directions.
            pnl_outcome: Filter by PnL outcome: ``"positive"``,
                ``"negative"``, or ``"all"`` (default).
            limit: Maximum number of decision rows in the response (1 – 500).

        Returns:
            ``DecisionAnalysisResponse`` dict with ``total``, ``wins``,
            ``losses``, ``win_rate``, ``avg_pnl`` (nullable str),
            ``avg_confidence`` (nullable str), ``by_direction`` (dict keyed
            by direction), ``decisions`` (list of decision records).  On
            error, returns ``{"error": "<message>"}``.
        """
        try:
            return await client.analyze_decisions(
                agent_id=agent_id,
                start=start,
                end=end,
                min_confidence=min_confidence,
                direction=direction,
                pnl_outcome=pnl_outcome,
                limit=limit,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Risk profile self-tuning tool
    # ------------------------------------------------------------------

    async def update_risk_profile(
        max_position_size_pct: int,
        daily_loss_limit_pct: int,
        max_open_orders: int,
    ) -> dict[str, Any]:
        """Update risk limits for the authenticated account or agent.

        Use this for autonomous self-tuning — the agent can tighten its own
        risk limits after a drawdown, or loosen them when confidence is high.
        When called with an agent API key, the limits apply only to that
        agent's risk profile; they do not affect the parent account.

        Args:
            max_position_size_pct: Maximum size of a single position as a
                percentage of total equity (1 – 100).
            daily_loss_limit_pct: Maximum daily loss allowed as a percentage
                of total equity (1 – 100).  The circuit breaker trips at this
                level.
            max_open_orders: Maximum number of concurrently open orders
                (minimum 1).

        Returns:
            ``RiskProfileInfo`` dict with the three updated fields:
            ``max_position_size_pct``, ``daily_loss_limit_pct``,
            ``max_open_orders``.  On error, returns
            ``{"error": "<message>"}``.
        """
        try:
            return await client.update_risk_profile(
                max_position_size_pct=max_position_size_pct,
                daily_loss_limit_pct=daily_loss_limit_pct,
                max_open_orders=max_open_orders,
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": str(exc)}

    return [
        create_backtest,
        start_backtest,
        step_backtest_batch,
        backtest_trade,
        get_backtest_results,
        get_backtest_candles,
        create_strategy,
        test_strategy,
        get_test_results,
        create_strategy_version,
        compare_strategy_versions,
        compare_backtests,
        get_best_backtest,
        get_equity_curve,
        analyze_agent_decisions,
        update_risk_profile,
    ]
