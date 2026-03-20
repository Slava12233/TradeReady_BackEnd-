# agent/tools — Platform Integration Layers

<!-- last-updated: 2026-03-20 -->

> Three integration layers that wrap platform access for Pydantic AI agents: SDK tools, MCP server factory, and REST tools.

## What This Module Does

Provides all three channels through which the testing agent calls the AiTradingAgent platform. Each layer targets a different surface area: the SDK client covers live trading and market data; the MCP server subprocess exposes all 58 platform tools via JSON-RPC; and the REST client covers the backtest lifecycle and strategy management surfaces that the SDK does not expose. All tool functions follow a consistent error contract — errors are returned as `{"error": "<message>"}` rather than raised, so the LLM can handle failures gracefully without crashing the workflow.

## Key Files

| File | Purpose |
|------|---------|
| `sdk_tools.py` | `get_sdk_tools()` — 7 async tool functions backed by `AsyncAgentExchangeClient` |
| `mcp_tools.py` | `get_mcp_server()`, `get_mcp_server_with_jwt()` — spawns the platform MCP server subprocess |
| `rest_tools.py` | `PlatformRESTClient` class and `get_rest_tools()` — 11 REST tool functions for backtest + strategy |
| `__init__.py` | Re-exports all 5 public names: `PlatformRESTClient`, `get_mcp_server`, `get_mcp_server_with_jwt`, `get_rest_tools`, `get_sdk_tools` |

## Public API / Key Classes

### `get_sdk_tools(config)` — `sdk_tools.py`

Factory that instantiates a single `AsyncAgentExchangeClient` shared across all returned tools, then builds 7 async closure functions over it. Returns a `list` suitable for `Agent(tools=...)`.

| Tool function | SDK method called | Return type on success |
|---------------|------------------|------------------------|
| `get_price(ctx, symbol)` | `client.get_price(symbol)` | `{symbol, price (str), timestamp (ISO-8601)}` |
| `get_candles(ctx, symbol, interval="1h", limit=50)` | `client.get_candles(...)` | `list[{time, open, high, low, close, volume (all str), trade_count (int)}]` |
| `get_balance(ctx)` | `client.get_balance()` | `list[{asset, available, locked, total (all str)}]` |
| `get_positions(ctx)` | `client.get_positions()` | `list[{symbol, asset, quantity, avg_entry_price, current_price, market_value, unrealized_pnl, unrealized_pnl_pct (all str), opened_at (ISO-8601)}]` |
| `get_performance(ctx, period="all")` | `client.get_performance(period=period)` | `{period, sharpe_ratio, sortino_ratio, max_drawdown_pct, max_drawdown_duration_days (int), win_rate, profit_factor, avg_win, avg_loss, total_trades (int), avg_trades_per_day, best_trade, worst_trade (all str), current_streak (int)}` |
| `get_trade_history(ctx, limit=20)` | `client.get_trade_history(limit=limit)` | `list[{trade_id, order_id, symbol, side, quantity, price, fee, total (all str), executed_at (ISO-8601)}]` |
| `place_market_order(ctx, symbol, side, quantity)` | `client.place_market_order(...)` | `{order_id, status, symbol, side, type, executed_price, executed_quantity, fee, total_cost (str or null), filled_at (ISO-8601 or null)}` |

All tools catch `AgentExchangeError` and return `{"error": "<message>"}` instead of raising. The `ctx` parameter is the Pydantic AI `RunContext` injected automatically — declare it as `Any` to avoid import overhead.

The shared `AsyncAgentExchangeClient` is **not** closed by the tool functions. Callers must call `await client.aclose()` when the agent session ends. The smoke test and trading workflow do this in `finally` blocks.

### `get_mcp_server(config)` — `mcp_tools.py`

Returns a `pydantic_ai.mcp.MCPServerStdio` that spawns `python -m src.mcp.server` as a child process. The subprocess uses the same Python interpreter (`sys.executable`) and inherits the current process environment, overlaid with:

| Env var | Value |
|---------|-------|
| `MCP_API_KEY` | `config.platform_api_key` |
| `API_BASE_URL` | `config.platform_base_url` |
| `LOG_LEVEL` | `"WARNING"` (prevents stderr noise on the stdio transport) |

The subprocess `cwd` is `config.platform_root` (repo root) so `python -m src.mcp.server` resolves without `PYTHONPATH` manipulation.

Raises `ValueError` eagerly if `config.platform_api_key` is empty — the MCP server calls `sys.exit(1)` without a key.

### `get_mcp_server_with_jwt(config, jwt_token)` — `mcp_tools.py`

Identical to `get_mcp_server()` but additionally injects `MCP_JWT_TOKEN` into the subprocess environment. Required when the agent needs to call JWT-only endpoints under `/api/v1/agents/` or `/api/v1/battles/`.

Raises `ValueError` if `jwt_token` is empty or whitespace-only. Internally calls `get_mcp_server()` to validate the API key first, then overlays the JWT.

### `PlatformRESTClient` — `rest_tools.py`

Async HTTP client wrapping `httpx.AsyncClient` with a 30-second timeout. Every request carries the `X-API-Key` header from the config. Supports async context manager (`async with PlatformRESTClient(config) as client:`).

| Method | HTTP call | Key response fields |
|--------|-----------|---------------------|
| `create_backtest(start_time, end_time, symbols, interval=60, starting_balance="10000", strategy_label="default")` | `POST /api/v1/backtest/create` | `session_id, status, total_steps, estimated_pairs, agent_id` |
| `start_backtest(session_id)` | `POST /api/v1/backtest/{id}/start` | `status, session_id` |
| `step_backtest_batch(session_id, steps)` | `POST /api/v1/backtest/{id}/step/batch` | `virtual_time, step, total_steps, progress_pct, prices, orders_filled, portfolio, is_complete, remaining_steps` |
| `backtest_trade(session_id, symbol, side, quantity, order_type="market", price=None)` | `POST /api/v1/backtest/{id}/trade/order` | `order_id, status, executed_price, executed_qty, fee, realized_pnl` |
| `get_backtest_results(session_id)` | `GET /api/v1/backtest/{id}/results` | `session_id, status, config, summary, metrics, by_pair` |
| `get_backtest_candles(session_id, symbol, interval=60, limit=100)` | `GET /api/v1/backtest/{id}/market/candles/{symbol}` | `symbol, interval, candles, count` |
| `create_strategy(name, description, definition)` | `POST /api/v1/strategies` | `strategy_id, name, description, current_version, status, deployed_at, created_at, updated_at` |
| `test_strategy(strategy_id, version, date_range, episodes=10, episode_duration_days=30, starting_balance="10000", randomize_dates=True)` | `POST /api/v1/strategies/{id}/test` | `test_run_id, status, episodes_total, episodes_completed, progress_pct, version` |
| `get_test_results(strategy_id, test_id)` | `GET /api/v1/strategies/{id}/tests/{test_id}` | `test_run_id, status, episodes_total, episodes_completed, progress_pct, version, results, recommendations, config` |
| `create_version(strategy_id, definition, change_notes=None)` | `POST /api/v1/strategies/{id}/versions` | `version_id, strategy_id, version, definition, change_notes, parent_version, status, created_at` |
| `compare_versions(strategy_id, v1, v2)` | `GET /api/v1/strategies/{id}/compare-versions?v1=N&v2=M` | `v1 (metrics dict), v2 (metrics dict), improvements (delta dict), verdict` |

Internal `_get()` and `_post()` helpers raise `httpx.HTTPStatusError` on non-2xx responses. `_post()` returns `{}` for empty response bodies (e.g. 204).

### `get_rest_tools(config)` — `rest_tools.py`

Factory that instantiates a shared `PlatformRESTClient` and wraps all 11 client methods as Pydantic AI-compatible async tool functions. The 11 tool names match the client methods with one difference: `create_version` becomes `create_strategy_version` and `compare_versions` becomes `compare_strategy_versions` for clarity at the tool layer.

All tool functions catch `httpx.HTTPStatusError` and `httpx.RequestError` and return `{"error": "<message>"}` instead of raising.

The shared `PlatformRESTClient` is **not** closed inside the tool functions. Workflows that use these tools (`backtest_workflow`, `strategy_workflow`) use `PlatformRESTClient` as an `async with` context manager directly rather than going through the tool factory.

## Patterns

- **Closure-based tools**: Both `get_sdk_tools` and `get_rest_tools` use nested `async def` functions that close over a shared client instance. This avoids creating redundant connection pools per tool invocation.
- **Error contract**: `{"error": "<message>"}` is always returned instead of raising. The LLM treats the presence of an `"error"` key as a failure signal and continues to the next step.
- **Lazy imports**: `agentexchange` and `pydantic_ai` are imported inside the factory functions (`# noqa: PLC0415`) to avoid circular imports and to keep startup fast if only a subset of tools is needed.
- **`ctx: Any` pattern**: All SDK tool functions accept a first `ctx` argument typed as `Any`. This is the Pydantic AI `RunContext` injected automatically by the framework. Using `Any` avoids the `pydantic_ai` import at the tool-definition level.
- **dict return types**: All tool functions return plain `dict` or `list[dict]`, never Pydantic models. This ensures JSON compatibility with the LLM output layer.

## Gotchas

- **SDK client lifecycle**: `get_sdk_tools()` creates an `AsyncAgentExchangeClient` that is never auto-closed. The smoke test and trading workflow call `await client.aclose()` in `finally` blocks. If you call `get_sdk_tools()` outside those workflows, you are responsible for closing the client.
- **REST client lifecycle**: `get_rest_tools()` creates a `PlatformRESTClient` that is never auto-closed by the tool functions. The backtest and strategy workflows use `PlatformRESTClient` directly as an `async with` context manager, bypassing `get_rest_tools()` entirely.
- **MCP subprocess stdout**: The MCP server subprocess communicates over stdout using JSON-RPC. Any `print()` output from the subprocess will corrupt the transport. `LOG_LEVEL=WARNING` is set to suppress most logging.
- **`platform_api_secret` is not forwarded to MCP as a JWT**: `get_mcp_server()` intentionally does not forward `platform_api_secret` as `MCP_JWT_TOKEN`. A pre-issued JWT must be obtained separately (e.g. via SDK login) and passed to `get_mcp_server_with_jwt()`.
- **`create_strategy` omits `description` when empty**: The `description` field is only included in the POST body when it is a non-empty string. This matches the server's optional field handling.
- **`step_backtest_batch` range**: The `steps` argument is valid from 1 to 10,000. Passing 0 or a negative value will result in a server-side 422 error.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
