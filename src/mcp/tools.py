"""MCP tool definitions for the AI Agent Crypto Trading Platform.

Defines all 43 trading tools covering the full trading lifecycle:
market data, account management, trading, backtesting, agent management,
battles, and analytics.

Each tool maps to a REST API endpoint via an ``httpx.AsyncClient`` that
is injected at registration time by ``server.py``.

Tools (43 total)
----------------
Market Data (7):
 1.  get_price           — GET /api/v1/market/price/{symbol}
 2.  get_all_prices      — GET /api/v1/market/prices
 3.  get_candles         — GET /api/v1/market/candles/{symbol}
 4.  get_pairs           — GET /api/v1/market/pairs
 5.  get_ticker          — GET /api/v1/market/ticker/{symbol}
 6.  get_orderbook       — GET /api/v1/market/orderbook/{symbol}
 7.  get_recent_trades   — GET /api/v1/market/trades/{symbol}

Account (5):
 8.  get_balance         — GET /api/v1/account/balance
 9.  get_positions       — GET /api/v1/account/positions
10.  get_portfolio       — GET /api/v1/account/portfolio
11.  get_account_info    — GET /api/v1/account/info
12.  reset_account       — POST /api/v1/account/reset

Trading (6):
13.  place_order         — POST /api/v1/trade/order
14.  cancel_order        — DELETE /api/v1/trade/order/{order_id}
15.  get_order_status    — GET /api/v1/trade/order/{order_id}
16.  get_trade_history   — GET /api/v1/trade/history
17.  get_open_orders     — GET /api/v1/trade/orders/open
18.  cancel_all_orders   — DELETE /api/v1/trade/orders/open
19.  list_orders         — GET /api/v1/trade/orders

Analytics (4):
20.  get_performance     — GET /api/v1/analytics/performance
21.  get_pnl             — GET /api/v1/account/pnl
22.  get_portfolio_history — GET /api/v1/analytics/portfolio/history
23.  get_leaderboard     — GET /api/v1/analytics/leaderboard

Backtesting (8):
24.  get_data_range      — GET /api/v1/market/data-range
25.  create_backtest     — POST /api/v1/backtest/create
26.  start_backtest      — POST /api/v1/backtest/{id}/start
27.  step_backtest       — POST /api/v1/backtest/{id}/step
28.  step_backtest_batch — POST /api/v1/backtest/{id}/step/batch
29.  backtest_trade      — POST /api/v1/backtest/{id}/trade/order
30.  get_backtest_results — GET /api/v1/backtest/{id}/results
31.  list_backtests      — GET /api/v1/backtest/list

Agent Management (6):
32.  list_agents         — GET /api/v1/agents
33.  create_agent        — POST /api/v1/agents
34.  get_agent           — GET /api/v1/agents/{id}
35.  reset_agent         — POST /api/v1/agents/{id}/reset
36.  update_agent_risk   — PUT /api/v1/agents/{id}/risk-profile
37.  get_agent_skill     — GET /api/v1/agents/{id}/skill.md

Battles (6):
38.  create_battle       — POST /api/v1/battles
39.  list_battles        — GET /api/v1/battles
40.  start_battle        — POST /api/v1/battles/{id}/start
41.  get_battle_live     — GET /api/v1/battles/{id}/live
42.  get_battle_results  — GET /api/v1/battles/{id}/results
43.  get_battle_replay   — GET /api/v1/battles/{id}/replay

Usage::

    import httpx
    from mcp.server import Server
    from src.mcp.tools import register_tools

    server = Server("agentexchange")
    http_client = httpx.AsyncClient(base_url="http://localhost:8000", ...)
    register_tools(server, http_client)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from mcp.server import Server
import mcp.types as types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool count constant
# ---------------------------------------------------------------------------

TOOL_COUNT = 43

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOOL_DEFINITIONS: list[types.Tool] = [
    # ==================================================================
    # Market Data (7 tools)
    # ==================================================================
    types.Tool(
        name="get_price",
        description="Get the current price of a cryptocurrency trading pair.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="get_all_prices",
        description="Get current prices for all available trading pairs.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_candles",
        description="Get historical OHLCV candle data for a trading pair.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "interval": {
                    "type": "string",
                    "description": "Candle interval",
                    "enum": ["1m", "5m", "15m", "1h", "4h", "1d"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of candles to return (default 100, max 1000)",
                    "default": 100,
                },
            },
            "required": ["symbol", "interval"],
        },
    ),
    types.Tool(
        name="get_pairs",
        description=(
            "List all available trading pairs with filters. "
            "Returns pair name, status, and whether live price data is available."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "exchange": {
                    "type": "string",
                    "description": "Filter by exchange (e.g. binance, okx, bybit). Default: all exchanges.",
                },
                "quote_asset": {
                    "type": "string",
                    "description": "Filter by quote asset (e.g. USDT, BTC). Default: all.",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_ticker",
        description=(
            "Get 24-hour rolling ticker statistics for a trading pair: "
            "open, high, low, close, volume, and price change percentage."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="get_orderbook",
        description=(
            "Get the order book (bid/ask depth) for a trading pair. "
            "Useful for estimating slippage before placing orders."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of price levels per side (default 20, max 100)",
                    "default": 20,
                },
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="get_recent_trades",
        description="Get recent public trades for a trading pair from the tick history.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of trades to return (default 50, max 500)",
                    "default": 50,
                },
            },
            "required": ["symbol"],
        },
    ),
    # ==================================================================
    # Account (5 tools)
    # ==================================================================
    types.Tool(
        name="get_balance",
        description="Get your current account balances for all assets.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_positions",
        description="Get your current open trading positions with unrealized PnL.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_portfolio",
        description=(
            "Get complete portfolio summary including total equity, cash balance, open positions, and unrealized PnL."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_account_info",
        description="Get account details including session info, current risk profile, and account status.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="reset_account",
        description=(
            "Reset your trading account to starting balance. "
            "All open positions will be closed and trade history cleared. "
            "This action is irreversible."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to execute the reset",
                },
            },
            "required": ["confirm"],
        },
    ),
    # ==================================================================
    # Trading (7 tools)
    # ==================================================================
    types.Tool(
        name="place_order",
        description=(
            "Place a buy or sell order for a cryptocurrency. "
            "For limit, stop_loss, and take_profit orders the 'price' field is required."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "side": {
                    "type": "string",
                    "description": "Order direction",
                    "enum": ["buy", "sell"],
                },
                "type": {
                    "type": "string",
                    "description": "Order type",
                    "enum": ["market", "limit", "stop_loss", "take_profit"],
                },
                "quantity": {
                    "type": "number",
                    "description": "Order quantity in base asset",
                },
                "price": {
                    "type": "number",
                    "description": ("Limit / trigger price. Required for limit, stop_loss, and take_profit orders."),
                },
            },
            "required": ["symbol", "side", "type", "quantity"],
        },
    ),
    types.Tool(
        name="cancel_order",
        description="Cancel a pending order by its order ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "UUID of the order to cancel",
                },
            },
            "required": ["order_id"],
        },
    ),
    types.Tool(
        name="get_order_status",
        description="Check the current status and details of an order.",
        inputSchema={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "UUID of the order to look up",
                },
            },
            "required": ["order_id"],
        },
    ),
    types.Tool(
        name="get_trade_history",
        description="Get your historical trade executions.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter by trading pair symbol (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of trades to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_open_orders",
        description="List all pending and partially-filled orders.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="cancel_all_orders",
        description="Cancel all open orders at once. Returns the count of cancelled orders.",
        inputSchema={
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to execute the cancellation",
                },
            },
            "required": ["confirm"],
        },
    ),
    types.Tool(
        name="list_orders",
        description="List orders with optional status and symbol filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by order status",
                    "enum": ["pending", "filled", "partially_filled", "cancelled", "rejected", "expired"],
                },
                "symbol": {
                    "type": "string",
                    "description": "Filter by trading pair symbol",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of orders to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    # ==================================================================
    # Analytics (4 tools)
    # ==================================================================
    types.Tool(
        name="get_performance",
        description=("Get trading performance metrics including Sharpe ratio, win rate, max drawdown, and ROI."),
        inputSchema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period for metrics (default: all)",
                    "enum": ["1d", "7d", "30d", "90d", "all"],
                    "default": "all",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_pnl",
        description="Get PnL breakdown: realized, unrealized, fees, win rate, and profit factor.",
        inputSchema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period for PnL calculation",
                    "enum": ["1d", "7d", "30d", "all"],
                    "default": "all",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_portfolio_history",
        description="Get portfolio equity curve snapshots for charting and analysis over time.",
        inputSchema={
            "type": "object",
            "properties": {
                "interval": {
                    "type": "string",
                    "description": "Snapshot interval",
                    "enum": ["1m", "1h", "1d"],
                    "default": "1h",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of snapshots to return (default 100)",
                    "default": 100,
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_leaderboard",
        description="Get the cross-account leaderboard ranked by ROI. See how your performance compares to others.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of entries to return (default 50, max 200)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    # ==================================================================
    # Backtesting (8 tools)
    # ==================================================================
    types.Tool(
        name="get_data_range",
        description=(
            "Check available historical data timespan. Returns earliest/latest timestamps, "
            "total trading pairs, and available intervals. Call this before creating a backtest "
            "to know what date range is valid."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="create_backtest",
        description=(
            "Create a new backtest session. Specify the time range, starting balance, trading pairs, "
            "and candle interval. Returns a session_id to use with start_backtest."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "Start of backtest period (ISO 8601 UTC), e.g. 2025-01-01T00:00:00Z",
                },
                "end_time": {
                    "type": "string",
                    "description": "End of backtest period (ISO 8601 UTC), e.g. 2025-03-01T00:00:00Z",
                },
                "starting_balance": {
                    "type": "number",
                    "description": "Starting virtual USDT balance (default 10000)",
                    "default": 10000,
                },
                "candle_interval": {
                    "type": "integer",
                    "description": "Candle interval in seconds (default 60 = 1 minute, minimum 60)",
                    "default": 60,
                },
                "pairs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Trading pairs to include (e.g. ['BTCUSDT', 'ETHUSDT']). Omit for all.",
                },
                "strategy_label": {
                    "type": "string",
                    "description": "Label to identify your strategy (default: 'default')",
                    "default": "default",
                },
                "exchange": {
                    "type": "string",
                    "description": "Exchange for historical data (default: binance)",
                    "default": "binance",
                },
            },
            "required": ["start_time", "end_time"],
        },
    ),
    types.Tool(
        name="start_backtest",
        description=(
            "Start a previously created backtest session. This preloads historical price data "
            "and initializes the sandbox. After this, use step_backtest to advance time."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Backtest session UUID from create_backtest",
                },
            },
            "required": ["session_id"],
        },
    ),
    types.Tool(
        name="step_backtest",
        description=(
            "Advance the backtest by one candle interval. Returns current prices, portfolio state, "
            "orders filled, and whether the backtest is complete. Use this in a loop to step through "
            "the backtest, observe market conditions, and make trading decisions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Backtest session UUID",
                },
            },
            "required": ["session_id"],
        },
    ),
    types.Tool(
        name="step_backtest_batch",
        description=(
            "Advance the backtest by N candle intervals at once. Useful for fast-forwarding "
            "through periods when you don't need to make decisions on every bar."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Backtest session UUID",
                },
                "steps": {
                    "type": "integer",
                    "description": "Number of steps to advance (1 to 10000)",
                },
            },
            "required": ["session_id", "steps"],
        },
    ),
    types.Tool(
        name="backtest_trade",
        description=(
            "Place a trade order inside a running backtest sandbox. Supports market, limit, "
            "stop_loss, and take_profit orders. Orders execute against historical prices."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Backtest session UUID",
                },
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "side": {
                    "type": "string",
                    "description": "Order direction",
                    "enum": ["buy", "sell"],
                },
                "type": {
                    "type": "string",
                    "description": "Order type",
                    "enum": ["market", "limit", "stop_loss", "take_profit"],
                    "default": "market",
                },
                "quantity": {
                    "type": "number",
                    "description": "Order quantity in base asset",
                },
                "price": {
                    "type": "number",
                    "description": "Limit / trigger price. Required for limit, stop_loss, and take_profit orders.",
                },
            },
            "required": ["session_id", "symbol", "side", "quantity"],
        },
    ),
    types.Tool(
        name="get_backtest_results",
        description=(
            "Get full results of a completed backtest: metrics (Sharpe, drawdown, win rate), "
            "equity summary, configuration, and per-pair breakdown."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Backtest session UUID",
                },
            },
            "required": ["session_id"],
        },
    ),
    types.Tool(
        name="list_backtests",
        description="List all backtest sessions with their status and summary metrics.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (created, running, completed, failed, cancelled)",
                },
                "strategy_label": {
                    "type": "string",
                    "description": "Filter by strategy label",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of backtests to return (default 50, max 200)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    # ==================================================================
    # Agent Management (6 tools)
    # ==================================================================
    types.Tool(
        name="list_agents",
        description="List all agents under your account with their balances and performance summary.",
        inputSchema={
            "type": "object",
            "properties": {
                "include_archived": {
                    "type": "boolean",
                    "description": "Include archived agents (default: false)",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of agents to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="create_agent",
        description=(
            "Create a new trading agent with its own API key, starting balance, and risk profile. "
            "Returns the agent details including a one-time visible API key."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name for the agent, e.g. 'AlphaBot'",
                },
                "starting_balance": {
                    "type": "number",
                    "description": "Initial virtual USDT balance (default 10000)",
                    "default": 10000,
                },
                "llm_model": {
                    "type": "string",
                    "description": "LLM model powering this agent (e.g. 'claude-sonnet-4-20250514', 'gpt-4o')",
                },
                "framework": {
                    "type": "string",
                    "description": "Agent framework (e.g. 'langchain', 'crewai', 'custom')",
                },
                "strategy_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags describing the agent's strategy (e.g. ['momentum', 'mean-reversion'])",
                },
            },
            "required": ["display_name"],
        },
    ),
    types.Tool(
        name="get_agent",
        description="Get detailed information about a specific agent including balance, performance, and config.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the agent",
                },
            },
            "required": ["agent_id"],
        },
    ),
    types.Tool(
        name="reset_agent",
        description="Reset an agent to its starting balance. Trading history is preserved but positions are closed.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the agent to reset",
                },
            },
            "required": ["agent_id"],
        },
    ),
    types.Tool(
        name="update_agent_risk",
        description="Update risk limits for an agent: max position size, daily loss limit, etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the agent",
                },
                "max_position_size_pct": {
                    "type": "number",
                    "description": "Maximum position size as percentage of portfolio (0-100)",
                },
                "daily_loss_limit_pct": {
                    "type": "number",
                    "description": "Maximum daily loss as percentage of portfolio (0-100)",
                },
                "max_open_orders": {
                    "type": "integer",
                    "description": "Maximum number of concurrent open orders",
                },
            },
            "required": ["agent_id"],
        },
    ),
    types.Tool(
        name="get_agent_skill",
        description=(
            "Get the agent's personalized skill file (Markdown). This contains the full API spec "
            "with the agent's pre-filled API key — drop it into any LLM's context window."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "UUID of the agent",
                },
            },
            "required": ["agent_id"],
        },
    ),
    # ==================================================================
    # Battles (6 tools)
    # ==================================================================
    types.Tool(
        name="create_battle",
        description=(
            "Create a new battle (agent vs agent competition). Specify a name, mode (live or historical), "
            "and optionally a preset configuration. Add agents after creation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Battle name, e.g. 'BTC Momentum Showdown'",
                },
                "battle_mode": {
                    "type": "string",
                    "description": "Battle mode",
                    "enum": ["live", "historical"],
                    "default": "live",
                },
                "ranking_metric": {
                    "type": "string",
                    "description": "Metric to rank agents by",
                    "enum": ["roi_pct", "total_pnl", "sharpe_ratio", "win_rate", "profit_factor"],
                    "default": "roi_pct",
                },
                "preset": {
                    "type": "string",
                    "description": "Use a preset configuration (e.g. 'quick_5min', 'marathon_24h')",
                },
                "config": {
                    "type": "object",
                    "description": "Custom config overrides: duration, pairs, wallet_mode, starting_balance",
                },
            },
            "required": ["name"],
        },
    ),
    types.Tool(
        name="list_battles",
        description="List all battles with optional status filter.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by battle status",
                    "enum": ["draft", "pending", "active", "completed", "cancelled", "paused"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of battles to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="start_battle",
        description=(
            "Start a battle. This locks the configuration, snapshots all agent wallets, "
            "and begins the competition. Requires at least 2 participants."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "battle_id": {
                    "type": "string",
                    "description": "UUID of the battle to start",
                },
            },
            "required": ["battle_id"],
        },
    ),
    types.Tool(
        name="get_battle_live",
        description="Get real-time battle state: current scores, positions, equity, and rankings for all participants.",
        inputSchema={
            "type": "object",
            "properties": {
                "battle_id": {
                    "type": "string",
                    "description": "UUID of the battle",
                },
            },
            "required": ["battle_id"],
        },
    ),
    types.Tool(
        name="get_battle_results",
        description="Get final results of a completed battle: rankings, per-agent metrics, and winner.",
        inputSchema={
            "type": "object",
            "properties": {
                "battle_id": {
                    "type": "string",
                    "description": "UUID of the battle",
                },
            },
            "required": ["battle_id"],
        },
    ),
    types.Tool(
        name="get_battle_replay",
        description="Get step-by-step replay data for a battle. Useful for post-battle analysis and visualization.",
        inputSchema={
            "type": "object",
            "properties": {
                "battle_id": {
                    "type": "string",
                    "description": "UUID of the battle",
                },
            },
            "required": ["battle_id"],
        },
    ),
]


# ---------------------------------------------------------------------------
# REST call helpers
# ---------------------------------------------------------------------------


async def _call_api(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an HTTP request and return the parsed JSON body.

    Args:
        client: Authenticated ``httpx.AsyncClient`` pointed at the platform.
        method: HTTP method in uppercase (``GET``, ``POST``, ``DELETE``, ``PUT``).
        path: URL path relative to the client's base URL, e.g. ``/api/v1/market/price/BTCUSDT``.
        params: Optional query-string parameters.
        json: Optional JSON request body.

    Returns:
        Parsed JSON response as a dictionary.

    Raises:
        httpx.HTTPStatusError: Propagated so the tool handler can format
            a user-readable error message.
    """
    response = await client.request(method, path, params=params, json=json)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


async def _call_api_text(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> str:
    """Execute an HTTP request and return the raw text body.

    Used for endpoints that return non-JSON content (e.g. skill.md).
    """
    response = await client.request(method, path, params=params)
    response.raise_for_status()
    return response.text


def _error_content(exc: Exception) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Format an exception as a single MCP TextContent error message.

    Args:
        exc: The exception that was raised.

    Returns:
        A list containing one ``TextContent`` with the error description.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
            detail = body.get("detail") or body.get("error", {}).get("message") or str(exc)
        except Exception:
            detail = str(exc)
        return [types.TextContent(type="text", text=f"API error: {detail}")]
    return [types.TextContent(type="text", text=f"Error: {exc}")]


def _json_content(
    data: dict[str, Any] | list[Any],
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Wrap a JSON-serialisable value as MCP TextContent.

    Args:
        data: The API response data to serialise.

    Returns:
        A list containing one ``TextContent`` with the JSON string.
    """
    import json

    return [types.TextContent(type="text", text=json.dumps(data, indent=2))]


def _text_content(
    text: str,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Wrap a plain string as MCP TextContent.

    Args:
        text: The text content to return.

    Returns:
        A list containing one ``TextContent``.
    """
    return [types.TextContent(type="text", text=text)]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(server: Server, http_client: httpx.AsyncClient) -> None:
    """Register all 43 trading tools on *server*.

    This function wires the tool list and the call handler to the MCP
    ``Server`` instance.  Call it once during server initialisation after
    the ``http_client`` is configured with the correct base URL and
    authentication headers.

    Args:
        server: The ``mcp.server.Server`` instance to register tools on.
        http_client: An ``httpx.AsyncClient`` already configured with
            ``base_url`` and ``X-API-Key`` / ``Authorization`` headers.
    """

    @server.list_tools()  # type: ignore[misc]
    async def list_tools() -> list[types.Tool]:
        """Return all available trading tools."""
        return _TOOL_DEFINITIONS

    @server.call_tool()  # type: ignore[misc]
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch a tool call to the corresponding REST endpoint.

        Args:
            name: The tool name as registered in ``_TOOL_DEFINITIONS``.
            arguments: Key-value mapping of tool input parameters.

        Returns:
            A list of MCP content items (always ``TextContent`` here).
        """
        logger.debug("MCP tool call: %s  args=%s", name, arguments)

        try:
            return await _dispatch(name, arguments, http_client)
        except httpx.HTTPStatusError as exc:
            logger.warning("Tool %s HTTP error: %s", name, exc)
            return _error_content(exc)
        except Exception as exc:
            logger.exception("Tool %s unexpected error: %s", name, exc)
            return _error_content(exc)


async def _dispatch(
    name: str,
    args: dict[str, Any],
    client: httpx.AsyncClient,
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Route a validated tool call to the appropriate REST endpoint.

    Args:
        name: Tool name.
        args: Validated input arguments from the MCP caller.
        client: Authenticated HTTP client.

    Returns:
        MCP ``TextContent`` list with JSON response payload.

    Raises:
        ValueError: When *name* does not match any known tool.
    """
    match name:
        # ------------------------------------------------------------------
        # Market data (7 tools)
        # ------------------------------------------------------------------
        case "get_price":
            symbol: str = args["symbol"].upper()
            data = await _call_api(client, "GET", f"/api/v1/market/price/{symbol}")
            return _json_content(data)

        case "get_all_prices":
            data = await _call_api(client, "GET", "/api/v1/market/prices")
            return _json_content(data)

        case "get_candles":
            symbol = args["symbol"].upper()
            params: dict[str, Any] = {"interval": args["interval"]}
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", f"/api/v1/market/candles/{symbol}", params=params)
            return _json_content(data)

        case "get_pairs":
            params = {}
            if args.get("exchange"):
                params["exchange"] = args["exchange"]
            if args.get("quote_asset"):
                params["quote_asset"] = args["quote_asset"]
            data = await _call_api(client, "GET", "/api/v1/market/pairs", params=params)
            return _json_content(data)

        case "get_ticker":
            symbol = args["symbol"].upper()
            data = await _call_api(client, "GET", f"/api/v1/market/ticker/{symbol}")
            return _json_content(data)

        case "get_orderbook":
            symbol = args["symbol"].upper()
            params = {}
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", f"/api/v1/market/orderbook/{symbol}", params=params)
            return _json_content(data)

        case "get_recent_trades":
            symbol = args["symbol"].upper()
            params = {}
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", f"/api/v1/market/trades/{symbol}", params=params)
            return _json_content(data)

        # ------------------------------------------------------------------
        # Account (5 tools)
        # ------------------------------------------------------------------
        case "get_balance":
            data = await _call_api(client, "GET", "/api/v1/account/balance")
            return _json_content(data)

        case "get_positions":
            data = await _call_api(client, "GET", "/api/v1/account/positions")
            return _json_content(data)

        case "get_portfolio":
            data = await _call_api(client, "GET", "/api/v1/account/portfolio")
            return _json_content(data)

        case "get_account_info":
            data = await _call_api(client, "GET", "/api/v1/account/info")
            return _json_content(data)

        case "reset_account":
            confirm: bool = args.get("confirm", False)
            if not confirm:
                return [
                    types.TextContent(
                        type="text",
                        text=("Account reset aborted: 'confirm' must be true. Pass confirm=true to execute the reset."),
                    )
                ]
            data = await _call_api(client, "POST", "/api/v1/account/reset", json={"confirm": True})
            return _json_content(data)

        # ------------------------------------------------------------------
        # Trading (7 tools)
        # ------------------------------------------------------------------
        case "place_order":
            body: dict[str, Any] = {
                "symbol": args["symbol"].upper(),
                "side": args["side"],
                "type": args["type"],
                "quantity": str(args["quantity"]),
            }
            if "price" in args and args["price"] is not None:
                body["price"] = str(args["price"])
            data = await _call_api(client, "POST", "/api/v1/trade/order", json=body)
            return _json_content(data)

        case "cancel_order":
            order_id: str = args["order_id"]
            data = await _call_api(client, "DELETE", f"/api/v1/trade/order/{order_id}")
            return _json_content(data)

        case "get_order_status":
            order_id = args["order_id"]
            data = await _call_api(client, "GET", f"/api/v1/trade/order/{order_id}")
            return _json_content(data)

        case "get_trade_history":
            params = {}
            if "symbol" in args and args["symbol"]:
                params["symbol"] = args["symbol"].upper()
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/trade/history", params=params)
            return _json_content(data)

        case "get_open_orders":
            data = await _call_api(client, "GET", "/api/v1/trade/orders/open")
            return _json_content(data)

        case "cancel_all_orders":
            confirm = args.get("confirm", False)
            if not confirm:
                return [
                    types.TextContent(
                        type="text",
                        text="Cancel all orders aborted: 'confirm' must be true.",
                    )
                ]
            data = await _call_api(client, "DELETE", "/api/v1/trade/orders/open")
            return _json_content(data)

        case "list_orders":
            params = {}
            if args.get("status"):
                params["status"] = args["status"]
            if args.get("symbol"):
                params["symbol"] = args["symbol"].upper()
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/trade/orders", params=params)
            return _json_content(data)

        # ------------------------------------------------------------------
        # Analytics (4 tools)
        # ------------------------------------------------------------------
        case "get_performance":
            params = {}
            if "period" in args and args["period"]:
                params["period"] = args["period"]
            data = await _call_api(client, "GET", "/api/v1/analytics/performance", params=params)
            return _json_content(data)

        case "get_pnl":
            params = {}
            if "period" in args and args["period"]:
                params["period"] = args["period"]
            data = await _call_api(client, "GET", "/api/v1/account/pnl", params=params)
            return _json_content(data)

        case "get_portfolio_history":
            params = {}
            if "interval" in args and args["interval"]:
                params["interval"] = args["interval"]
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/analytics/portfolio/history", params=params)
            return _json_content(data)

        case "get_leaderboard":
            params = {}
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/analytics/leaderboard", params=params)
            return _json_content(data)

        # ------------------------------------------------------------------
        # Backtesting (8 tools)
        # ------------------------------------------------------------------
        case "get_data_range":
            data = await _call_api(client, "GET", "/api/v1/market/data-range")
            return _json_content(data)

        case "create_backtest":
            body = {
                "start_time": args["start_time"],
                "end_time": args["end_time"],
            }
            if "starting_balance" in args:
                body["starting_balance"] = str(args["starting_balance"])
            if "candle_interval" in args:
                body["candle_interval"] = int(args["candle_interval"])
            if "pairs" in args and args["pairs"]:
                body["pairs"] = args["pairs"]
            if "strategy_label" in args and args["strategy_label"]:
                body["strategy_label"] = args["strategy_label"]
            if "exchange" in args and args["exchange"]:
                body["exchange"] = args["exchange"]
            data = await _call_api(client, "POST", "/api/v1/backtest/create", json=body)
            return _json_content(data)

        case "start_backtest":
            session_id: str = args["session_id"]
            data = await _call_api(client, "POST", f"/api/v1/backtest/{session_id}/start")
            return _json_content(data)

        case "step_backtest":
            session_id = args["session_id"]
            data = await _call_api(client, "POST", f"/api/v1/backtest/{session_id}/step")
            return _json_content(data)

        case "step_backtest_batch":
            session_id = args["session_id"]
            steps: int = int(args["steps"])
            data = await _call_api(
                client, "POST", f"/api/v1/backtest/{session_id}/step/batch", json={"steps": steps}
            )
            return _json_content(data)

        case "backtest_trade":
            session_id = args["session_id"]
            body = {
                "symbol": args["symbol"].upper(),
                "side": args["side"],
                "quantity": str(args["quantity"]),
            }
            if "type" in args and args["type"]:
                body["type"] = args["type"]
            if "price" in args and args["price"] is not None:
                body["price"] = str(args["price"])
            data = await _call_api(
                client, "POST", f"/api/v1/backtest/{session_id}/trade/order", json=body
            )
            return _json_content(data)

        case "get_backtest_results":
            session_id = args["session_id"]
            data = await _call_api(client, "GET", f"/api/v1/backtest/{session_id}/results")
            return _json_content(data)

        case "list_backtests":
            params = {}
            if args.get("status"):
                params["status"] = args["status"]
            if args.get("strategy_label"):
                params["strategy_label"] = args["strategy_label"]
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/backtest/list", params=params)
            return _json_content(data)

        # ------------------------------------------------------------------
        # Agent Management (6 tools)
        # ------------------------------------------------------------------
        case "list_agents":
            params = {}
            if "include_archived" in args:
                params["include_archived"] = str(args["include_archived"]).lower()
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/agents", params=params)
            return _json_content(data)

        case "create_agent":
            body = {"display_name": args["display_name"]}
            if "starting_balance" in args:
                body["starting_balance"] = str(args["starting_balance"])
            if args.get("llm_model"):
                body["llm_model"] = args["llm_model"]
            if args.get("framework"):
                body["framework"] = args["framework"]
            if args.get("strategy_tags"):
                body["strategy_tags"] = args["strategy_tags"]
            data = await _call_api(client, "POST", "/api/v1/agents", json=body)
            return _json_content(data)

        case "get_agent":
            agent_id: str = args["agent_id"]
            data = await _call_api(client, "GET", f"/api/v1/agents/{agent_id}")
            return _json_content(data)

        case "reset_agent":
            agent_id = args["agent_id"]
            data = await _call_api(client, "POST", f"/api/v1/agents/{agent_id}/reset")
            return _json_content(data)

        case "update_agent_risk":
            agent_id = args["agent_id"]
            body = {}
            if "max_position_size_pct" in args:
                body["max_position_size_pct"] = args["max_position_size_pct"]
            if "daily_loss_limit_pct" in args:
                body["daily_loss_limit_pct"] = args["daily_loss_limit_pct"]
            if "max_open_orders" in args:
                body["max_open_orders"] = args["max_open_orders"]
            data = await _call_api(client, "PUT", f"/api/v1/agents/{agent_id}/risk-profile", json=body)
            return _json_content(data)

        case "get_agent_skill":
            agent_id = args["agent_id"]
            text = await _call_api_text(client, "GET", f"/api/v1/agents/{agent_id}/skill.md")
            return _text_content(text)

        # ------------------------------------------------------------------
        # Battles (6 tools)
        # ------------------------------------------------------------------
        case "create_battle":
            body = {"name": args["name"]}
            if "battle_mode" in args:
                body["battle_mode"] = args["battle_mode"]
            if "ranking_metric" in args:
                body["ranking_metric"] = args["ranking_metric"]
            if args.get("preset"):
                body["preset"] = args["preset"]
            if args.get("config"):
                body["config"] = args["config"]
            data = await _call_api(client, "POST", "/api/v1/battles", json=body)
            return _json_content(data)

        case "list_battles":
            params = {}
            if args.get("status"):
                params["status"] = args["status"]
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/battles", params=params)
            return _json_content(data)

        case "start_battle":
            battle_id: str = args["battle_id"]
            data = await _call_api(client, "POST", f"/api/v1/battles/{battle_id}/start")
            return _json_content(data)

        case "get_battle_live":
            battle_id = args["battle_id"]
            data = await _call_api(client, "GET", f"/api/v1/battles/{battle_id}/live")
            return _json_content(data)

        case "get_battle_results":
            battle_id = args["battle_id"]
            data = await _call_api(client, "GET", f"/api/v1/battles/{battle_id}/results")
            return _json_content(data)

        case "get_battle_replay":
            battle_id = args["battle_id"]
            data = await _call_api(client, "GET", f"/api/v1/battles/{battle_id}/replay")
            return _json_content(data)

        case _:
            raise ValueError(f"Unknown tool: {name!r}")
