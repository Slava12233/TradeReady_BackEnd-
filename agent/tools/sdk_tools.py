"""SDK-based tool functions wrapping AsyncAgentExchangeClient for Pydantic AI.

Exposes market data, account, and trading operations as plain async functions
that can be passed directly to the Pydantic AI ``Agent`` constructor via
``tools=``.  A single ``AsyncAgentExchangeClient`` instance is shared across
all returned tools via closure to avoid creating redundant HTTP connections.

Usage::

    from agent.config import AgentConfig
    from agent.tools.sdk_tools import get_sdk_tools

    config = AgentConfig()
    tools = get_sdk_tools(config)

    agent = Agent(model=config.agent_model, tools=tools)
"""

from __future__ import annotations

from typing import Any

import structlog

from agent.config import AgentConfig
from agent.logging_middleware import log_api_call

logger = structlog.get_logger(__name__)


def get_sdk_tools(config: AgentConfig) -> list[Any]:
    """Build and return SDK-based tool functions for a Pydantic AI agent.

    Instantiates a single :class:`~agentexchange.AsyncAgentExchangeClient`
    shared across all returned tools.  The client's HTTP connection pool is
    reused for the lifetime of the agent — call ``await client.aclose()`` when
    the agent session ends (or manage it with an async context manager at the
    call site).

    Args:
        config: Resolved :class:`~agent.config.AgentConfig` with platform
                connectivity settings.

    Returns:
        List of async tool functions ready to be passed to the Pydantic AI
        ``Agent`` constructor's ``tools=`` parameter.
    """
    from agentexchange.async_client import AsyncAgentExchangeClient  # noqa: PLC0415
    from agentexchange.exceptions import AgentExchangeError  # noqa: PLC0415

    from agent.logging import get_trace_id  # noqa: PLC0415

    client = AsyncAgentExchangeClient(
        api_key=config.platform_api_key,
        api_secret=config.platform_api_secret,
        base_url=config.platform_base_url,
        trace_id_provider=get_trace_id,
    )

    # ------------------------------------------------------------------
    # Market data tools
    # ------------------------------------------------------------------

    async def get_price(ctx: Any, symbol: str) -> dict[str, Any]:  # noqa: ANN401
        """Get the current market price for a trading symbol.

        Fetches the latest tick price for a single USDT trading pair from the
        platform's real-time price feed.

        Args:
            ctx:    Pydantic AI run context (injected automatically).
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"`` or
                    ``"ETHUSDT"``.

        Returns:
            Dict with keys ``symbol`` (str), ``price`` (str), and
            ``timestamp`` (ISO-8601 str).  On failure returns
            ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call("sdk", "get_price", symbol=symbol) as log_ctx:
                result = await client.get_price(symbol)
                log_ctx["response_status"] = 200
                return {
                    "symbol": result.symbol,
                    "price": str(result.price),
                    "timestamp": result.timestamp.isoformat(),
                }
        except AgentExchangeError as exc:
            logger.warning("agent.api.get_price.failed", symbol=symbol, error=str(exc))
            return {"error": str(exc)}

    async def get_candles(
        ctx: Any,  # noqa: ANN401
        symbol: str,
        interval: str = "1h",
        limit: int = 50,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Fetch OHLCV candle bars for a trading symbol.

        Returns historical candle data for the requested symbol and interval,
        ordered oldest-first.  Use this data to analyse trends, calculate
        technical indicators, and make trading decisions.

        Args:
            ctx:      Pydantic AI run context (injected automatically).
            symbol:   Uppercase trading pair, e.g. ``"BTCUSDT"``.
            interval: Candle interval.  Valid values: ``"1m"``, ``"5m"``,
                      ``"15m"``, ``"1h"``, ``"4h"``, ``"1d"``.
                      Defaults to ``"1h"``.
            limit:    Number of candles to return (1–1000).
                      Defaults to ``50``.

        Returns:
            List of dicts, each with keys ``time`` (ISO-8601 str), ``open``,
            ``high``, ``low``, ``close``, ``volume`` (all str), and
            ``trade_count`` (int).  On failure returns
            ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call(
                "sdk", "get_candles", symbol=symbol, interval=interval, limit=limit
            ) as log_ctx:
                candles = await client.get_candles(symbol, interval=interval, limit=limit)
                log_ctx["response_status"] = 200
                return [
                    {
                        "time": c.time.isoformat(),
                        "open": str(c.open),
                        "high": str(c.high),
                        "low": str(c.low),
                        "close": str(c.close),
                        "volume": str(c.volume),
                        "trade_count": c.trade_count,
                    }
                    for c in candles
                ]
        except AgentExchangeError as exc:
            logger.warning(
                "agent.api.get_candles.failed",
                symbol=symbol,
                interval=interval,
                limit=limit,
                error=str(exc),
            )
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Account tools
    # ------------------------------------------------------------------

    async def get_balance(ctx: Any) -> list[dict[str, Any]] | dict[str, Any]:  # noqa: ANN401
        """Get all asset balances for the trading account.

        Returns the available, locked, and total balance for every asset
        with a non-zero holding.  The primary currency is USDT.

        Args:
            ctx: Pydantic AI run context (injected automatically).

        Returns:
            List of dicts, each with keys ``asset`` (str), ``available``
            (str), ``locked`` (str), and ``total`` (str).  On failure returns
            ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call("sdk", "get_balance") as log_ctx:
                balances = await client.get_balance()
                log_ctx["response_status"] = 200
                return [
                    {
                        "asset": b.asset,
                        "available": str(b.available),
                        "locked": str(b.locked),
                        "total": str(b.total),
                    }
                    for b in balances
                ]
        except AgentExchangeError as exc:
            logger.warning("agent.api.get_balance.failed", error=str(exc))
            return {"error": str(exc)}

    async def get_positions(ctx: Any) -> list[dict[str, Any]] | dict[str, Any]:  # noqa: ANN401
        """Get all currently open positions for the trading account.

        Returns a snapshot of every open position including current market
        value and unrealised profit or loss.

        Args:
            ctx: Pydantic AI run context (injected automatically).

        Returns:
            List of dicts with keys: ``symbol`` (str), ``asset`` (str),
            ``quantity`` (str), ``avg_entry_price`` (str),
            ``current_price`` (str), ``market_value`` (str),
            ``unrealized_pnl`` (str), ``unrealized_pnl_pct`` (str),
            ``opened_at`` (ISO-8601 str).  On failure returns
            ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call("sdk", "get_positions") as log_ctx:
                positions = await client.get_positions()
                log_ctx["response_status"] = 200
                return [
                    {
                        "symbol": p.symbol,
                        "asset": p.asset,
                        "quantity": str(p.quantity),
                        "avg_entry_price": str(p.avg_entry_price),
                        "current_price": str(p.current_price),
                        "market_value": str(p.market_value),
                        "unrealized_pnl": str(p.unrealized_pnl),
                        "unrealized_pnl_pct": str(p.unrealized_pnl_pct),
                        "opened_at": p.opened_at.isoformat(),
                    }
                    for p in positions
                ]
        except AgentExchangeError as exc:
            logger.warning("agent.api.get_positions.failed", error=str(exc))
            return {"error": str(exc)}

    async def get_performance(
        ctx: Any,  # noqa: ANN401
        period: str = "all",
    ) -> dict[str, Any]:
        """Get statistical performance metrics for the trading account.

        Returns risk-adjusted return metrics including Sharpe ratio, maximum
        drawdown, win rate, and profit factor.  Use this to evaluate how well
        a strategy is performing before deciding on next actions.

        Args:
            ctx:    Pydantic AI run context (injected automatically).
            period: Time window for the calculation.  Valid values: ``"1d"``,
                    ``"7d"``, ``"30d"``, ``"all"``.  Defaults to ``"all"``.

        Returns:
            Dict with keys: ``period`` (str), ``sharpe_ratio``,
            ``sortino_ratio``, ``max_drawdown_pct``,
            ``max_drawdown_duration_days`` (int), ``win_rate``,
            ``profit_factor``, ``avg_win``, ``avg_loss``,
            ``total_trades`` (int), ``avg_trades_per_day``, ``best_trade``,
            ``worst_trade`` (all str), ``current_streak`` (int).  On failure
            returns ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call("sdk", "get_performance", period=period) as log_ctx:
                perf = await client.get_performance(period=period)
                log_ctx["response_status"] = 200
                return {
                    "period": perf.period,
                    "sharpe_ratio": str(perf.sharpe_ratio),
                    "sortino_ratio": str(perf.sortino_ratio),
                    "max_drawdown_pct": str(perf.max_drawdown_pct),
                    "max_drawdown_duration_days": perf.max_drawdown_duration_days,
                    "win_rate": str(perf.win_rate),
                    "profit_factor": str(perf.profit_factor),
                    "avg_win": str(perf.avg_win),
                    "avg_loss": str(perf.avg_loss),
                    "total_trades": perf.total_trades,
                    "avg_trades_per_day": str(perf.avg_trades_per_day),
                    "best_trade": str(perf.best_trade),
                    "worst_trade": str(perf.worst_trade),
                    "current_streak": perf.current_streak,
                }
        except AgentExchangeError as exc:
            logger.warning("agent.api.get_performance.failed", period=period, error=str(exc))
            return {"error": str(exc)}

    async def get_trade_history(
        ctx: Any,  # noqa: ANN401
        limit: int = 20,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Get recent executed trade history for the account.

        Returns the most recent filled trades ordered newest-first.  Use this
        to review recent activity, calculate realised P&L, and understand the
        account's trading pattern.

        Args:
            ctx:   Pydantic AI run context (injected automatically).
            limit: Maximum number of trades to return (1–500).
                   Defaults to ``20``.

        Returns:
            List of dicts with keys: ``trade_id`` (str), ``order_id`` (str),
            ``symbol`` (str), ``side`` (str), ``quantity`` (str),
            ``price`` (str), ``fee`` (str), ``total`` (str),
            ``executed_at`` (ISO-8601 str).  On failure returns
            ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call("sdk", "get_trade_history", limit=limit) as log_ctx:
                trades = await client.get_trade_history(limit=limit)
                log_ctx["response_status"] = 200
                return [
                    {
                        "trade_id": str(t.trade_id),
                        "order_id": str(t.order_id),
                        "symbol": t.symbol,
                        "side": t.side,
                        "quantity": str(t.quantity),
                        "price": str(t.price),
                        "fee": str(t.fee),
                        "total": str(t.total),
                        "executed_at": t.executed_at.isoformat(),
                    }
                    for t in trades
                ]
        except AgentExchangeError as exc:
            logger.warning("agent.api.get_trade_history.failed", limit=limit, error=str(exc))
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Trading tools
    # ------------------------------------------------------------------

    async def place_market_order(
        ctx: Any,  # noqa: ANN401
        symbol: str,
        side: str,
        quantity: str,
    ) -> dict[str, Any]:
        """Place a market order that executes immediately at the current price.

        Submits a buy or sell order that fills instantly at the best available
        price with minimal slippage.  The order goes through full risk
        management checks before execution.

        Args:
            ctx:      Pydantic AI run context (injected automatically).
            symbol:   Uppercase trading pair, e.g. ``"BTCUSDT"``.
            side:     Order direction: ``"buy"`` or ``"sell"``.
            quantity: Base-asset quantity as a decimal string, e.g.
                      ``"0.001"`` for 0.001 BTC.  Must be a positive number.

        Returns:
            Dict with keys: ``order_id`` (str), ``status`` (str),
            ``symbol`` (str), ``side`` (str), ``type`` (str),
            ``executed_price`` (str or null), ``executed_quantity``
            (str or null), ``fee`` (str or null), ``total_cost``
            (str or null), ``filled_at`` (ISO-8601 str or null).
            On failure returns ``{"error": "<message>"}``.
        """
        try:
            async with log_api_call(
                "sdk", "place_market_order", symbol=symbol, side=side, quantity=quantity
            ) as log_ctx:
                order = await client.place_market_order(symbol, side, quantity)
                log_ctx["response_status"] = 200
                return {
                    "order_id": str(order.order_id),
                    "status": order.status,
                    "symbol": order.symbol,
                    "side": order.side,
                    "type": order.type,
                    "executed_price": str(order.executed_price) if order.executed_price is not None else None,
                    "executed_quantity": str(order.executed_quantity) if order.executed_quantity is not None else None,
                    "fee": str(order.fee) if order.fee is not None else None,
                    "total_cost": str(order.total_cost) if order.total_cost is not None else None,
                    "filled_at": order.filled_at.isoformat() if order.filled_at is not None else None,
                }
        except AgentExchangeError as exc:
            logger.warning(
                "agent.api.place_market_order.failed",
                symbol=symbol,
                side=side,
                quantity=quantity,
                error=str(exc),
            )
            return {"error": str(exc)}

    return [
        get_price,
        get_balance,
        place_market_order,
        get_candles,
        get_performance,
        get_positions,
        get_trade_history,
    ]
