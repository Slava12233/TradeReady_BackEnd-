# MCP Server

<!-- last-updated: 2026-03-19 -->

> Exposes 58 trading tools over MCP stdio transport so AI agents (Claude Desktop, cline, etc.) can discover and invoke trading operations against the platform REST API.

## What This Module Does

The MCP (Model Context Protocol) server runs as a standalone process (`python -m src.mcp.server`) that communicates with MCP-compatible clients over **stdio transport** (JSON-RPC over stdin/stdout). It translates MCP tool calls into authenticated REST API requests against the trading platform using `httpx.AsyncClient`.

The server registers 58 tools covering the full trading lifecycle: market data, account management, trading, backtesting, agent management, battles, analytics, strategy management, strategy testing, and training observation. All REST calls are authenticated via `X-API-Key` header (and optionally `Authorization: Bearer` for JWT-protected endpoints).

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package docstring; no exports |
| `server.py` | Entry point: env config, HTTP client factory, MCP `Server` creation, stdio transport loop |
| `tools.py` | 58 tool definitions (`_TOOL_DEFINITIONS`), `register_tools()`, `_dispatch()` routing, REST call helpers. Covers: market data (7), account (5), trading (7), analytics (4), backtesting (8), agent management (6), battles (6), strategies (7), strategy testing (5), training observation (3) |

## Architecture & Patterns

### Startup flow

1. `main()` calls `create_server()` which builds an authenticated `httpx.AsyncClient` and a `mcp.server.Server` instance.
2. `register_tools(server, http_client)` registers two MCP handlers on the server:
   - `list_tools()` -- returns the static `_TOOL_DEFINITIONS` list.
   - `call_tool(name, arguments)` -- dispatches to `_dispatch()` which uses `match/case` to route tool names to REST endpoints.
3. `stdio_server()` opens the stdin/stdout transport; `server.run()` blocks until the client disconnects.
4. On shutdown, the `httpx.AsyncClient` is closed in a `finally` block.

### Tool dispatch pattern

`_dispatch()` uses Python 3.10+ structural pattern matching (`match name: case "get_price": ...`) to map each tool name to an `_call_api()` call with the appropriate HTTP method, path, and parameters. Errors are caught at the `call_tool` level and formatted via `_error_content()`.

### Logging

All logging goes to **stderr** (never stdout) because stdout is owned by the MCP JSON-RPC transport. Default log level is `WARNING` to avoid corrupting the stream.

## Public API / Interfaces

### `register_tools(server: Server, http_client: httpx.AsyncClient) -> None`

Registers all 58 tools on the given MCP server. Called once at startup.

### `create_server() -> tuple[Server, httpx.AsyncClient]`

Factory that builds the configured server and HTTP client. Exits with code 1 if `MCP_API_KEY` is missing.

### `main() -> None`

Async entry point. Run via `python -m src.mcp.server`.

### `TOOL_COUNT = 58`

Constant for the total number of tools. Useful for tests and documentation.

### The 58 Tools

#### Market Data (7 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 1 | `get_price` | GET | `/api/v1/market/price/{symbol}` | `symbol` |
| 2 | `get_all_prices` | GET | `/api/v1/market/prices` | (none) |
| 3 | `get_candles` | GET | `/api/v1/market/candles/{symbol}` | `symbol`, `interval` |
| 4 | `get_pairs` | GET | `/api/v1/market/pairs` | (none; optional `exchange`, `quote_asset`) |
| 5 | `get_ticker` | GET | `/api/v1/market/ticker/{symbol}` | `symbol` |
| 6 | `get_orderbook` | GET | `/api/v1/market/orderbook/{symbol}` | `symbol` |
| 7 | `get_recent_trades` | GET | `/api/v1/market/trades/{symbol}` | `symbol` |

#### Account (5 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 8 | `get_balance` | GET | `/api/v1/account/balance` | (none) |
| 9 | `get_positions` | GET | `/api/v1/account/positions` | (none) |
| 10 | `get_portfolio` | GET | `/api/v1/account/portfolio` | (none) |
| 11 | `get_account_info` | GET | `/api/v1/account/info` | (none) |
| 12 | `reset_account` | POST | `/api/v1/account/reset` | `confirm` (must be `true`) |

#### Trading (7 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 13 | `place_order` | POST | `/api/v1/trade/order` | `symbol`, `side`, `type`, `quantity` |
| 14 | `cancel_order` | DELETE | `/api/v1/trade/order/{order_id}` | `order_id` |
| 15 | `get_order_status` | GET | `/api/v1/trade/order/{order_id}` | `order_id` |
| 16 | `get_trade_history` | GET | `/api/v1/trade/history` | (none; optional `symbol`, `limit`) |
| 17 | `get_open_orders` | GET | `/api/v1/trade/orders/open` | (none) |
| 18 | `cancel_all_orders` | DELETE | `/api/v1/trade/orders/open` | `confirm` (must be `true`) |
| 19 | `list_orders` | GET | `/api/v1/trade/orders` | (none; optional `status`, `symbol`, `limit`) |

#### Analytics (4 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 20 | `get_performance` | GET | `/api/v1/analytics/performance` | (none; optional `period`) |
| 21 | `get_pnl` | GET | `/api/v1/account/pnl` | (none; optional `period`) |
| 22 | `get_portfolio_history` | GET | `/api/v1/analytics/portfolio/history` | (none; optional `interval`, `limit`) |
| 23 | `get_leaderboard` | GET | `/api/v1/analytics/leaderboard` | (none; optional `limit`) |

#### Backtesting (8 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 24 | `get_data_range` | GET | `/api/v1/market/data-range` | (none) |
| 25 | `create_backtest` | POST | `/api/v1/backtest/create` | `start_time`, `end_time` |
| 26 | `start_backtest` | POST | `/api/v1/backtest/{id}/start` | `session_id` |
| 27 | `step_backtest` | POST | `/api/v1/backtest/{id}/step` | `session_id` |
| 28 | `step_backtest_batch` | POST | `/api/v1/backtest/{id}/step/batch` | `session_id`, `steps` |
| 29 | `backtest_trade` | POST | `/api/v1/backtest/{id}/trade/order` | `session_id`, `symbol`, `side`, `quantity` |
| 30 | `get_backtest_results` | GET | `/api/v1/backtest/{id}/results` | `session_id` |
| 31 | `list_backtests` | GET | `/api/v1/backtest/list` | (none; optional `status`, `strategy_label`, `limit`) |

#### Agent Management (6 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 32 | `list_agents` | GET | `/api/v1/agents` | (none; optional `include_archived`, `limit`) |
| 33 | `create_agent` | POST | `/api/v1/agents` | `display_name` |
| 34 | `get_agent` | GET | `/api/v1/agents/{id}` | `agent_id` |
| 35 | `reset_agent` | POST | `/api/v1/agents/{id}/reset` | `agent_id` |
| 36 | `update_agent_risk` | PUT | `/api/v1/agents/{id}/risk-profile` | `agent_id` |
| 37 | `get_agent_skill` | GET | `/api/v1/agents/{id}/skill.md` | `agent_id` |

#### Battles (6 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 38 | `create_battle` | POST | `/api/v1/battles` | `name` |
| 39 | `list_battles` | GET | `/api/v1/battles` | (none; optional `status`, `limit`) |
| 40 | `start_battle` | POST | `/api/v1/battles/{id}/start` | `battle_id` |
| 41 | `get_battle_live` | GET | `/api/v1/battles/{id}/live` | `battle_id` |
| 42 | `get_battle_results` | GET | `/api/v1/battles/{id}/results` | `battle_id` |
| 43 | `get_battle_replay` | GET | `/api/v1/battles/{id}/replay` | `battle_id` |

#### Strategy Management (7 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 44 | `create_strategy` | POST | `/api/v1/strategies` | `name`, `definition` |
| 45 | `get_strategies` | GET | `/api/v1/strategies` | (none; optional `status`, `limit`, `offset`) |
| 46 | `get_strategy` | GET | `/api/v1/strategies/{id}` | `strategy_id` |
| 47 | `create_strategy_version` | POST | `/api/v1/strategies/{id}/versions` | `strategy_id`, `definition` |
| 48 | `get_strategy_versions` | GET | `/api/v1/strategies/{id}/versions` | `strategy_id` |
| 49 | `deploy_strategy` | POST | `/api/v1/strategies/{id}/deploy` | `strategy_id`, `version` |
| 50 | `undeploy_strategy` | POST | `/api/v1/strategies/{id}/undeploy` | `strategy_id` |

#### Strategy Testing (5 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 51 | `run_strategy_test` | POST | `/api/v1/strategies/{id}/test` | `strategy_id`, `version` |
| 52 | `get_test_status` | GET | `/api/v1/strategies/{id}/tests/{test_id}` | `strategy_id`, `test_id` |
| 53 | `get_test_results` | GET | `/api/v1/strategies/{id}/tests/{test_id}` | `strategy_id`, `test_id` |
| 54 | `compare_versions` | GET | `/api/v1/strategies/{id}/compare-versions` | `strategy_id`, `v1`, `v2` |
| 55 | `get_strategy_recommendations` | GET | `/api/v1/strategies/{id}/test-results` | `strategy_id` |

#### Training Observation (3 tools)

| # | Tool | Method | REST Endpoint | Required Args |
|---|------|--------|---------------|---------------|
| 56 | `get_training_runs` | GET | `/api/v1/training/runs` | (none; optional `status`, `limit`, `offset`) |
| 57 | `get_training_run_detail` | GET | `/api/v1/training/runs/{run_id}` | `run_id` |
| 58 | `compare_training_runs` | GET | `/api/v1/training/compare` | `run_ids` (comma-separated) |

## Dependencies

### External packages

- `mcp` -- MCP SDK (`mcp.server.Server`, `mcp.server.stdio.stdio_server`, `mcp.types`)
- `httpx` -- Async HTTP client for REST API calls (30s timeout, follows redirects)

### Internal

- No imports from other `src.*` modules. The MCP server is fully decoupled from the main application; it communicates exclusively via HTTP.

## Common Tasks

### Running the server

```bash
# Minimal
MCP_API_KEY=ak_live_... python -m src.mcp.server

# With JWT for authenticated endpoints
MCP_API_KEY=ak_live_... MCP_JWT_TOKEN=eyJ... python -m src.mcp.server

# Against a remote instance
API_BASE_URL=https://api.example.com MCP_API_KEY=ak_live_... python -m src.mcp.server
```

### Adding a new tool

1. Add a `types.Tool(...)` entry to `_TOOL_DEFINITIONS` in `tools.py` with name, description, and `inputSchema`.
2. Add a `case "tool_name":` branch in `_dispatch()` that calls the corresponding REST endpoint.
3. Update the `TOOL_COUNT` constant in `tools.py`.
4. Update the tool count in docstrings (`server.py`, `__init__.py`, this CLAUDE.md).
5. Add tests in `tests/unit/test_mcp_tools.py`.

### Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MCP_API_KEY` | Yes | (none) | API key for authenticating REST calls (`X-API-Key` header) |
| `MCP_JWT_TOKEN` | No | (none) | JWT token sent as `Authorization: Bearer` header |
| `API_BASE_URL` | No | `http://localhost:8000` | Base URL of the trading platform REST API |
| `LOG_LEVEL` | No | `WARNING` | Python log level for the MCP process |

## Gotchas & Pitfalls

- **stdout is sacred.** All logging MUST go to stderr. Any stray `print()` or stdout logging will corrupt the JSON-RPC transport and crash the MCP session.
- **`MCP_API_KEY` is mandatory.** The server calls `sys.exit(1)` if it is not set. There is no fallback or interactive prompt.
- **HTTP client is created twice.** `create_server()` builds the client eagerly (outside the lifespan). The `_lifespan` context manager exists but is not used by `main()`. The client cleanup happens in the `finally` block of `main()` instead.
- **`place_order` converts `quantity` and `price` to strings** before sending the JSON body, matching the API's `Decimal`-as-string convention.
- **`reset_account` and `cancel_all_orders` have client-side guards.** If `confirm` is not `true`, the tool returns an abort message without hitting the API.
- **`get_agent_skill` returns plain text**, not JSON. It uses `_call_api_text()` instead of `_call_api()`.
- **No agent scoping.** The MCP server authenticates with a single API key. Agent context depends on which agent's API key is provided via `MCP_API_KEY`.
- **No retry logic.** Failed HTTP requests surface immediately as MCP error content. The client (e.g., Claude) is expected to handle retries at a higher level.

## Recent Changes

- `2026-03-18` -- Expanded from 43 to 58 tools (Phase STR-4): added strategy management (7), strategy testing (5), and training observation (3) tools. Updated TOOL_COUNT, docstrings, and dispatch routes.
- `2026-03-18` -- Expanded from 12 to 43 tools (Phase 2 MCP Server Expansion): added backtesting (8), market+trading (7), agent management (6), battle (6), and account+analytics (4) tools. Added `_call_api_text()` and `_text_content()` helpers. Added `TOOL_COUNT` constant. 142 unit tests, 0 lint errors.
- `2026-03-17` -- Initial CLAUDE.md created
