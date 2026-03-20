# Research: SDK/MCP/REST Integration Surfaces

<!-- Task 3 deliverable researched 2026-03-19 by codebase-researcher agent -->

This document is the authoritative reference for building the TradeReady Platform Testing Agent tool layer (Tasks 4-6). It maps every integration surface the agent needs: exact SDK method signatures, MCP server startup and connection patterns, REST endpoint paths with request/response shapes, and auth requirements.

---

## Table of Contents

1. [Auth Patterns](#1-auth-patterns)
2. [SDK AsyncAgentExchangeClient](#2-sdk-asyncagentexchangeclient)
3. [MCP Server Startup and Connection](#3-mcp-server-startup-and-connection)
4. [REST Backtesting Endpoints](#4-rest-backtesting-endpoints)
5. [REST Strategy Endpoints](#5-rest-strategy-endpoints)
6. [REST Strategy Testing Endpoints](#6-rest-strategy-testing-endpoints)
7. [Integration Choice Recommendation](#7-integration-choice-recommendation)

---

## 1. Auth Patterns

### 1.1 X-API-Key auth

**Header:** `X-API-Key: ak_live_<key>`

Resolution order in `AuthMiddleware` (`src/api/middleware/auth.py`):

1. Checks `agents` table first via `AgentRepository.get_by_api_key()`.
2. If not found, falls back to `accounts` table via `AccountRepository.get_by_api_key()`.
3. Sets `request.state.account` and `request.state.agent` (or `None` for legacy auth).

Returns 401 on invalid key, 403 on suspended account, 500 on unexpected errors.

### 1.2 JWT auth

**Header:** `Authorization: Bearer <jwt>`

Flow:

1. JWT decoded via `verify_jwt(token, jwt_secret)`.
2. `account_id` extracted from payload, account fetched from DB.
3. `request.state.account` set; `request.state.agent` is `None` until `get_current_agent()` reads the `X-Agent-Id` header.
4. For agent-scoped JWT calls: add `X-Agent-Id: <agent_uuid>` header alongside the Bearer token.

JWT obtained by: `POST /api/v1/auth/login` with body `{"api_key": "...", "api_secret": "..."}`.
Response: `{"token": "...", "expires_in": 900}`.

### 1.3 Which auth for the testing agent

**X-API-Key is the primary auth method.** An agent API key resolves both the account and agent context in a single header. JWT is only needed for `agents.py` and `battles.py` endpoints which are JWT-only.

For agent management (create/list agents) and battles, obtain a JWT first by calling `POST /api/v1/auth/login`. The SDK handles JWT acquisition automatically on first request.

### 1.4 Public endpoints (no auth)

All `/api/v1/market/*` endpoints, `/api/v1/auth/register`, and `/api/v1/auth/login` are public.

### 1.5 Rate limits

| Group | URL Prefix | Limit |
|-------|-----------|-------|
| orders | `/api/v1/trade/` | 100 req/min |
| market_data | `/api/v1/market/` | 1200 req/min |
| general | `/api/v1/` | 600 req/min |

Response headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`. Rate limiter **fails open** when Redis is down.

---

## 2. SDK AsyncAgentExchangeClient

**Source:** `sdk/agentexchange/async_client.py`

### 2.1 Constructor

```python
AsyncAgentExchangeClient(
    api_key: str,                      # "ak_live_..." required
    api_secret: str,                   # "sk_live_..." required
    base_url: str = "http://localhost:8000",
    timeout: float = 30.0,
)
```

Context manager usage (preferred):

```python
async with AsyncAgentExchangeClient(
    api_key="ak_live_...", api_secret="sk_live_..."
) as client:
    price = await client.get_price("BTCUSDT")
```

Manual lifecycle:

```python
client = AsyncAgentExchangeClient(api_key="...", api_secret="...")
await client.__aenter__()
# ... use client ...
await client.aclose()
```

### 2.2 Internal auth behavior

On first request, `_ensure_auth()` calls `_login()` which POSTs to `/api/v1/auth/login` to exchange key+secret for a JWT. JWT is cached with a 30-second safety buffer before expiry; auto-refreshed when expired. All requests send `Authorization: Bearer <jwt>` plus the `X-API-Key` header set at construction.

### 2.3 Retry behavior

5xx responses and `httpx.TransportError` retried up to 3 times with delays: 1s, 2s, 4s. Non-2xx after all retries raises a typed exception.

### 2.4 Market data methods (6)

```python
async def get_price(self, symbol: str) -> Price
# GET /api/v1/market/price/{symbol}
# Returns Price(symbol: str, price: Decimal, timestamp: datetime)

async def get_all_prices(self) -> list[Price]
# GET /api/v1/market/prices

async def get_candles(
    self,
    symbol: str,
    interval: str = "1m",     # "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
    limit: int = 100,          # 1-1000
) -> list[Candle]
# GET /api/v1/market/candles/{symbol}
# Returns list[Candle(time, open, high, low, close, volume)] oldest-first

async def get_ticker(self, symbol: str) -> Ticker
# GET /api/v1/market/ticker/{symbol}
# Returns Ticker(symbol, open, high, low, close, volume, change_pct)

async def get_recent_trades(self, symbol: str, limit: int = 50) -> list[dict]
# GET /api/v1/market/trades/{symbol}
# Returns list of {price, quantity, side, executed_at}

async def get_orderbook(self, symbol: str, depth: int = 10) -> dict
# GET /api/v1/market/orderbook/{symbol}
# Returns {bids: [[price_str, qty_str], ...], asks: [...]}
# NOTE: Synthetic/simulated order book, not real Binance depth
```

### 2.5 Trading methods (9)

```python
async def place_market_order(
    self, symbol: str, side: str, quantity: Decimal | float | str
) -> Order
# POST /api/v1/trade/order  body: {symbol, side, type:"market", quantity: str(Decimal)}

async def place_limit_order(
    self, symbol: str, side: str, quantity: Decimal | float | str, price: Decimal | float | str
) -> Order
# POST /api/v1/trade/order  body: {symbol, side, type:"limit", quantity, price}

async def place_stop_loss(
    self, symbol: str, side: str, quantity: Decimal | float | str, trigger_price: Decimal | float | str
) -> Order
# POST /api/v1/trade/order  body: {symbol, side, type:"stop_loss", quantity, trigger_price}

async def place_take_profit(
    self, symbol: str, side: str, quantity: Decimal | float | str, trigger_price: Decimal | float | str
) -> Order
# POST /api/v1/trade/order  body: {symbol, side, type:"take_profit", quantity, trigger_price}

async def get_order(self, order_id: str | UUID) -> Order
# GET /api/v1/trade/order/{order_id}

async def get_open_orders(self) -> list[Order]
# GET /api/v1/trade/orders/open  (status="pending" orders only)

async def cancel_order(self, order_id: str | UUID) -> bool
# DELETE /api/v1/trade/order/{order_id}  returns True on success

async def cancel_all_orders(self) -> int
# DELETE /api/v1/trade/orders/open  returns count of cancelled orders

async def get_trade_history(
    self, *, symbol: str | None = None, limit: int = 50, offset: int = 0
) -> list[Trade]
# GET /api/v1/trade/history  returns newest-first
```

### 2.6 Account methods (6)

```python
async def get_account_info(self) -> AccountInfo
# GET /api/v1/account/info  Returns AccountInfo(display_name, status, risk_profile)

async def get_balance(self) -> list[Balance]
# GET /api/v1/account/balance
# Returns list[Balance(asset, available: Decimal, locked: Decimal, total: Decimal)]

async def get_positions(self) -> list[Position]
# GET /api/v1/account/positions
# Returns list[Position(symbol, quantity, avg_entry_price, unrealized_pnl)]

async def get_portfolio(self) -> Portfolio
# GET /api/v1/account/portfolio
# Returns Portfolio(total_equity, available_cash, position_value, roi_pct)

async def get_pnl(self, period: str = "all") -> PnL
# GET /api/v1/account/pnl?period=all
# period: "1d" | "7d" | "30d" | "all"
# Returns PnL(net_pnl, realized_pnl, unrealized_pnl, win_rate, total_fees)

async def reset_account(self, starting_balance: Decimal | float | str = Decimal("10000")) -> dict
# POST /api/v1/account/reset  body: {starting_balance: str}
# Returns {session_id, starting_balance, started_at}
# DESTRUCTIVE: wipes all positions and open orders
```

### 2.7 Analytics methods (3)

```python
async def get_performance(self, period: str = "all") -> Performance
# GET /api/v1/analytics/performance?period=all
# Returns Performance(sharpe_ratio, max_drawdown_pct, win_rate, profit_factor)

async def get_portfolio_history(self, interval: str = "1h", limit: int = 168) -> list[Snapshot]
# GET /api/v1/analytics/portfolio/history
# interval: "5m" | "1h" | "1d"

async def get_leaderboard(self, period: str = "all", limit: int = 20) -> list[LeaderboardEntry]
# GET /api/v1/analytics/leaderboard
# Returns list[LeaderboardEntry(rank, display_name, roi_pct, total_trades)]
```

### 2.8 Strategy methods (6)

```python
async def create_strategy(self, name: str, definition: dict, description: str | None = None) -> dict
# POST /api/v1/strategies  definition is REQUIRED (backend rejects without it)

async def get_strategies(self, *, status: str | None = None, limit: int = 50, offset: int = 0) -> dict
# GET /api/v1/strategies  returns {strategies: [...], total, limit, offset}

async def get_strategy(self, strategy_id: str | UUID) -> dict
# GET /api/v1/strategies/{strategy_id}
# Returns StrategyDetailResponse (includes current_definition and latest_test_results)

async def create_version(self, strategy_id: str | UUID, definition: dict, change_notes: str | None = None) -> dict
# POST /api/v1/strategies/{strategy_id}/versions

async def deploy_strategy(self, strategy_id: str | UUID, version: int) -> dict
# POST /api/v1/strategies/{strategy_id}/deploy  body: {version: int}
# version is REQUIRED (known bug: earlier frontend code was missing this param)

async def undeploy_strategy(self, strategy_id: str | UUID) -> dict
# POST /api/v1/strategies/{strategy_id}/undeploy  no body
```

### 2.9 Strategy testing methods (4)

```python
async def run_test(
    self,
    strategy_id: str | UUID,
    version: int,
    *,
    episodes: int = 10,
    date_range: dict | None = None,    # {"start": "ISO8601", "end": "ISO8601"}
    episode_duration_days: int = 30,
) -> dict
# POST /api/v1/strategies/{strategy_id}/test
# Returns TestRunResponse dict with test_run_id key

async def get_test_status(self, strategy_id: str | UUID, test_id: str | UUID) -> dict
# GET /api/v1/strategies/{strategy_id}/tests/{test_id}

async def get_test_results(self, strategy_id: str | UUID, test_id: str | UUID) -> dict
# GET /api/v1/strategies/{strategy_id}/tests/{test_id}
# NOTE: get_test_status and get_test_results call THE SAME endpoint.
# Response always includes results when available.

async def compare_versions(self, strategy_id: str | UUID, v1: int, v2: int) -> dict
# GET /api/v1/strategies/{strategy_id}/compare-versions?v1=1&v2=2
```

### 2.10 Training methods (3)

```python
async def get_training_runs(self, *, status: str | None = None, limit: int = 20, offset: int = 0) -> dict
# GET /api/v1/training/runs
# NOTE: backend returns raw list, not a {runs: [...]} wrapper dict

async def get_training_run(self, run_id: str | UUID) -> dict
# GET /api/v1/training/runs/{run_id}

async def compare_training_runs(self, run_ids: list[str | UUID]) -> dict
# GET /api/v1/training/compare?run_ids=uuid1,uuid2,...
# run_ids are UUID-validated client-side before sending (injection prevention)
```

### 2.11 Response models (13 frozen dataclasses in sdk/agentexchange/models.py)

All monetary/price fields are `Decimal`. All models have `from_dict(data)` classmethod.

| Model | Key Fields |
|-------|----------|
| `Price` | symbol, price: Decimal, timestamp |
| `Ticker` | symbol, open/high/low/close, volume, change_pct |
| `Candle` | time, open, high, low, close, volume |
| `Balance` | asset, available: Decimal, locked: Decimal, total: Decimal |
| `Position` | symbol, quantity, avg_entry_price, unrealized_pnl |
| `Portfolio` | total_equity, available_cash, position_value, roi_pct |
| `PnL` | net_pnl, realized_pnl, unrealized_pnl, win_rate, total_fees |
| `Order` | order_id, symbol, side, type, status, executed_price, fee |
| `Trade` | trade_id, symbol, side, price, quantity, fee, executed_at |
| `Performance` | sharpe_ratio, max_drawdown_pct, win_rate, profit_factor |
| `Snapshot` | time, total_equity, available_cash |
| `LeaderboardEntry` | rank, display_name, roi_pct, total_trades |
| `AccountInfo` | display_name, status, risk_profile |

### 2.12 Exception hierarchy (sdk/agentexchange/exceptions.py)

```
AgentExchangeError (base)
  +-- AuthenticationError       (401/403)
  +-- RateLimitError            (429)  has .retry_after
  +-- InsufficientBalanceError  (400)  has .asset, .required, .available
  +-- OrderError                (400/404)
  +-- InvalidSymbolError        (400/503)  has .symbol
  +-- NotFoundError             (404)
  +-- ValidationError           (422)  has .field
  +-- ConflictError             (409)
  +-- ServerError               (500/503)
  +-- ConnectionError           (transport-level, status_code=0)
```

**Gotcha:** SDK `ConnectionError` shadows the Python builtin. Import from `agentexchange.exceptions` explicitly.

---

## 3. MCP Server Startup and Connection

**Source:** `src/mcp/server.py`, `src/mcp/tools.py`

### 3.1 Required environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|--------|
| `MCP_API_KEY` | **Yes** | none | `ak_live_...` key for `X-API-Key` header. Server calls `sys.exit(1)` if missing. |
| `MCP_JWT_TOKEN` | No | none | Pre-issued JWT. Required for JWT-only endpoints (agents, battles). |
| `API_BASE_URL` | No | `http://localhost:8000` | Base URL of trading platform REST API |
| `LOG_LEVEL` | No | `WARNING` | Keep at WARNING to avoid corrupting stdio JSON-RPC stream |

### 3.2 Starting the server process

```bash
# Minimal (market data and trading only)
MCP_API_KEY=ak_live_... python -m src.mcp.server

# With JWT (for agent management and battles)
MCP_API_KEY=ak_live_... MCP_JWT_TOKEN=eyJ... python -m src.mcp.server

# Against remote instance
API_BASE_URL=https://api.example.com MCP_API_KEY=ak_live_... python -m src.mcp.server
```

### 3.3 Connecting a Pydantic AI agent via MCPServerStdio

The server uses **stdio transport** (JSON-RPC over stdin/stdout). A Pydantic AI agent connects by launching the server subprocess and piping to its stdio.

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
import os

mcp_server = MCPServerStdio(
    command="python",
    args=["-m", "src.mcp.server"],
    env={
        **os.environ,
        "MCP_API_KEY": "ak_live_...",
        "MCP_JWT_TOKEN": "eyJ...",          # only if /agents or /battles needed
        "API_BASE_URL": "http://localhost:8000",
        "LOG_LEVEL": "WARNING",
    },
)

agent = Agent(
    model="claude-sonnet-4-6",
    mcp_servers=[mcp_server],
)

async with agent.run_context():
    result = await agent.run("Check the BTCUSDT price and place a small buy order")
```

**Critical:** All MCP server logging MUST go to stderr. stdout is owned by JSON-RPC. Any `print()` in the MCP process corrupts the session.

### 3.4 Internal dispatch flow

`server.py:create_server()` flow:

1. `_build_http_client()` creates `httpx.AsyncClient` with `X-API-Key` and optional `Authorization` headers.
2. `Server("agentexchange", version="1.0.0")` instantiated.
3. `register_tools(server, http_client)` registers `list_tools()` and `call_tool(name, arguments)` handlers.
4. `call_tool` dispatches via Python 3.10+ `match/case` on tool name to `_call_api()` REST calls.
5. `stdio_server()` opens stdin/stdout; `server.run()` blocks until disconnect.
6. `finally` block closes httpx client on shutdown.

### 3.5 Key tool names for the testing agent

**Backtesting (8 tools):**
`get_data_range`, `create_backtest`, `start_backtest`, `step_backtest`, `step_backtest_batch`, `backtest_trade`, `get_backtest_results`, `list_backtests`

**Strategy management (7 tools):**
`create_strategy`, `get_strategies`, `get_strategy`, `create_strategy_version`, `get_strategy_versions`, `deploy_strategy`, `undeploy_strategy`

**Strategy testing (5 tools):**
`run_strategy_test`, `get_test_status`, `get_test_results`, `compare_versions`, `get_strategy_recommendations`

**Training observation (3 tools):**
`get_training_runs`, `get_training_run_detail`, `compare_training_runs`

### 3.6 MCP limitations vs SDK/direct REST

- **No retry logic.** Failed HTTP requests surface immediately as MCP error content.
- **No per-agent scoping.** Server is locked to one `MCP_API_KEY`. To scope to a specific agent, that agent's API key must be `MCP_API_KEY`.
- **Confirmation guards.** `reset_account` and `cancel_all_orders` require `confirm="true"` or they return an abort message without hitting the API.
- **Plain-text tool.** `get_agent_skill` returns Markdown text, not JSON. Uses `_call_api_text()` internally.

---

## 4. REST Backtesting Endpoints

**Source:** `src/api/routes/backtest.py`, `src/api/schemas/backtest.py`

**Router prefix:** `/api/v1` (NOT `/api/v1/backtest`. The router uses `/api/v1` because it also owns `/account/mode` and `/market/data-range`.)

**Auth:** API key or JWT required for all backtest endpoints.

### 4.1 POST /api/v1/backtest/create

**Request body** (`BacktestCreateRequest`):

```json
{
  start_time: 2024-01-01T00:00:00Z,
  end_time: 2024-03-01T00:00:00Z,
  starting_balance: 10000,
  candle_interval: 60,
  pairs: [BTCUSDT, ETHUSDT],
  strategy_label: my_strategy,
  agent_id: null,
  exchange: binance
}
```

Field constraints: `starting_balance` Decimal as string ge=1; `candle_interval` seconds ge=60 default 60; `pairs` null = all pairs; `strategy_label` default "default" max 100 chars; `agent_id` optional string UUID overrides auth context; `exchange` pattern `^[a-z][a-z0-9_]{0,19}$` default "binance".

**Response** (`BacktestCreateResponse`):

```json
{
  session_id: uuid-string,
  status: created,
  total_steps: 1440,
  estimated_pairs: 2,
  agent_id: uuid-or-null
}
```

### 4.2 POST /api/v1/backtest/{session_id}/start

No request body. Bulk-preloads all candle data into the in-memory sandbox. This is the expensive step — do not call step until start returns successfully.

**Response:** `{status: running, session_id: uuid}`

### 4.3 POST /api/v1/backtest/{session_id}/step

No request body.

**Response** (`StepResponse`):

```json
{
  virtual_time: 2024-01-01T01:00:00Z,
  step: 1,
  total_steps: 1440,
  progress_pct: 0.069,
  prices: {BTCUSDT: 42000.00},
  orders_filled: [
    {order_id: uuid, status: filled, executed_price: 42000.00, executed_qty: 0.001, fee: 0.042}
  ],
  portfolio: {
    total_equity: 10000.00,
    available_cash: 9957.92,
    position_value: 42.00,
    unrealized_pnl: 0.00,
    realized_pnl: 0.00,
    positions: {}
  },
  is_complete: false,
  remaining_steps: 1439
}
```

### 4.4 POST /api/v1/backtest/{session_id}/step/batch

**Request body** (`BacktestStepBatchRequest`): `{steps: 100}`  (ge=1, le=10000)

**Response:** Same `StepResponse` shape. Returns state after the final step of the batch.

### 4.5 POST /api/v1/backtest/{session_id}/trade/order

**Request body** (`BacktestOrderRequest`):

```json
{symbol: BTCUSDT, side: buy, type: market, quantity: 0.001, price: null}
```

side: "buy" | "sell". type: "market" | "limit" | "stop_loss" | "take_profit". price: required for limit/stop_loss/take_profit.

**Response** (raw dict): `{order_id, status, executed_price, executed_qty, fee, realized_pnl}`

### 4.6 GET /api/v1/backtest/{session_id}/results

**Response** (`BacktestResultsResponse`):

```json
{
  session_id: uuid,
  status: completed,
  config: {start_time: ..., end_time: ..., starting_balance: 10000, candle_interval: 60, pairs: [BTCUSDT]},
  summary: {final_equity: 10500.00, total_pnl: 500.00, roi_pct: 5.00, total_trades: 25, win_rate: 0.60, total_fees: 12.50},
  metrics: {sharpe_ratio: 1.23, sortino_ratio: 1.56, max_drawdown_pct: 3.45, calmar_ratio: 0.87},
  by_pair: [{symbol: BTCUSDT, total_trades: 25, roi_pct: 5.00}]
}
```

Note: `metrics` may be null if insufficient data for calculation.

### 4.7 GET /api/v1/market/data-range

Public endpoint (no auth). Use before create_backtest to validate date ranges fall within available data.

**Response** (`DataRangeResponse`):

```json
{
  earliest: 2023-01-01T00:00:00Z,
  latest: 2024-03-01T00:00:00Z,
  total_pairs: 487,
  intervals_available: [1m, 5m, 1h, 1d],
  data_gaps: []
}
```

### 4.8 GET /api/v1/backtest/list

Query params: `status` (optional), `strategy_label` (optional), `limit` (default 50)

**Response** (`BacktestListResponse`):

```json
{
  backtests: [{ session_id, agent_id, strategy_label, start_time, end_time, status, candle_interval, starting_balance, pairs, progress_pct, current_step, total_steps, virtual_clock, final_equity, total_pnl, roi_pct, total_trades, total_fees, sharpe_ratio, max_drawdown_pct, created_at, started_at, completed_at, duration_real_sec }],
  total: 1
}
```

### 4.9 Backtest lifecycle state machine

```
POST /backtest/create  ->  POST /{id}/start  ->  [POST /{id}/step | POST /{id}/step/batch | POST /{id}/trade/order]*  ->  GET /{id}/results
                                                         |
                                                    POST /{id}/cancel  ->  GET /{id}/results (partial)
```

Session statuses: `created`, `running`, `completed`, `cancelled`, `failed`

**Critical invariant:** `DataReplayer` filters `WHERE bucket <= virtual_clock` — no look-ahead bias possible. In-memory sandbox has zero live dependencies (no Redis, no Binance during a backtest).

---

## 5. REST Strategy Endpoints

**Source:** `src/api/routes/strategies.py`, `src/api/schemas/strategies.py`

**Router prefix:** `/api/v1/strategies`

**Auth:** API key or JWT required.

### 5.1 POST /api/v1/strategies

HTTP 201. name: 1-200 chars required. definition: REQUIRED dict.

**Request body** (`CreateStrategyRequest`):

```json
{
  "name": "BTC RSI Scalper",
  "description": "Optional, max 2000 chars",
  "definition": {
    "pairs": ["BTCUSDT"],
    "timeframe": "1h",
    "entry_conditions": {"rsi_below": 30},
    "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
    "position_size_pct": 10,
    "max_positions": 3
  }
}
```

**Response** (`StrategyResponse`): strategy_id, name, description, current_version, status ("draft"/"active"/"archived"), deployed_at, created_at, updated_at

### 5.2 GET /api/v1/strategies

Query: `status` (optional), `limit` (1-100, default 50), `offset`

**Response** (`StrategyListResponse`): `{strategies: [...], total: 0, limit: 50, offset: 0}`

### 5.3 GET /api/v1/strategies/{strategy_id}

**Response** (`StrategyDetailResponse` extends StrategyResponse): adds `current_definition` and `latest_test_results` (both nullable).

### 5.4 PUT /api/v1/strategies/{strategy_id}

Request (`UpdateStrategyRequest`): both `name` and `description` optional. Response: `StrategyResponse`

### 5.5 DELETE /api/v1/strategies/{strategy_id}

HTTP 200. Soft delete (archive). Response: `StrategyResponse` with `status: archived`

### 5.6 POST /api/v1/strategies/{strategy_id}/versions

HTTP 201. Request: `{definition: {}, change_notes: ...}` (change_notes optional). Versions are immutable after creation.

**Response** (`StrategyVersionResponse`): `{version_id: uuid, strategy_id: uuid, version: 2, definition: {}, change_notes: ..., parent_version: 1, status: active, created_at: ...}`

### 5.7 GET /api/v1/strategies/{strategy_id}/versions

Response: `list[StrategyVersionResponse]`

### 5.8 GET /api/v1/strategies/{strategy_id}/versions/{version}

version path param is integer. Response: `StrategyVersionResponse`

### 5.9 POST /api/v1/strategies/{strategy_id}/deploy

Request: `{version: 2}` (required int >= 1). Response: StrategyResponse with `status: active` and `deployed_at` set.

### 5.10 POST /api/v1/strategies/{strategy_id}/undeploy

No body. Response: StrategyResponse with `status: draft` and `deployed_at: null`

### 5.11 Strategy definition structure

Validated by `StrategyDefinition` Pydantic model in `src/strategies/schemas.py`. Entry conditions use AND logic. Exit conditions use OR logic. Exit priority: stop_loss -> take_profit -> trailing_stop -> max_hold_candles -> indicator exits.

```json
{
  pairs: [BTCUSDT], timeframe: 1h,
  entry_conditions: { rsi_below: 30, rsi_above: null, macd_crossover: false,
    sma_above_price: false, sma_below_price: false, ema_above_price: false, bb_lower_band_touch: false },
  exit_conditions: { take_profit_pct: 5.0, stop_loss_pct: 2.0,
    trailing_stop_pct: null, max_hold_candles: null, rsi_overbought: 70, macd_crossunder: false },
  position_size_pct: 10.0, max_positions: 3
}
```

---

## 6. REST Strategy Testing Endpoints

**Source:** `src/api/routes/strategy_tests.py`, `src/api/schemas/strategy_tests.py`

**Router prefix:** `/api/v1/strategies` (same prefix as strategy CRUD routes)

**Auth:** API key or JWT required.

### 6.1 POST /api/v1/strategies/{strategy_id}/test (HTTP 201)

Tests run as Celery tasks (`run_strategy_episode`), 5-min soft / 6-min hard time limit per episode. Poll status endpoint for progress.

**Request body** (`StartTestRequest`):

```json
{
  "version": 1,
  "episodes": 10,
  "date_range": {"start": "2023-06-01T00:00:00Z", "end": "2024-01-01T00:00:00Z"},
  "randomize_dates": true,
  "episode_duration_days": 30,
  "starting_balance": "10000"
}
```

Constraints: version required int>=1; episodes 1-100 default 10; date_range required; randomize_dates default true; episode_duration_days 1-365 default 30.

**Response** (`TestRunResponse`): {test_run_id, status, episodes_total, episodes_completed, progress_pct, version, created_at, started_at, completed_at}

### 6.2 GET /api/v1/strategies/{strategy_id}/tests

**Response:** `list[TestRunResponse]`

### 6.3 GET /api/v1/strategies/{strategy_id}/tests/{test_id}

**Response** (`TestResultsResponse`):

```json
{
  "test_run_id": "uuid", "status": "completed",
  "episodes_total": 10, "episodes_completed": 10, "progress_pct": 100.0, "version": 1,
  "results": {"avg_roi_pct": 4.5, "avg_sharpe": 1.2, "avg_max_drawdown_pct": 3.1, "total_trades": 120, "win_rate": 0.60},
  "recommendations": ["Consider tightening stop-loss", "RSI threshold of 30 may be too conservative"],
  "config": {"episodes": 10, "episode_duration_days": 30, "starting_balance": "10000"}
}
```

**IMPORTANT:** SDK `get_test_status()` and `get_test_results()` call THE SAME endpoint. The response always includes results when available.

Terminal statuses: `completed`, `failed`, `cancelled`

### 6.4 POST /api/v1/strategies/{strategy_id}/tests/{test_id}/cancel

No body. Response: TestRunResponse with status cancelled.

### 6.5 GET /api/v1/strategies/{strategy_id}/test-results

Latest completed test run. Raises 404 if none. Response: `TestResultsResponse`

### 6.6 GET /api/v1/strategies/{strategy_id}/compare-versions

Query: `v1=1&v2=2` (both required int >= 1)

**Response** (`VersionComparisonResponse`):

```json
{
  "v1": {"version": 1, "avg_roi_pct": 3.2, "avg_sharpe": 0.9, "avg_max_drawdown_pct": 4.5, "total_trades": 100, "episodes_completed": 10},
  "v2": {"version": 2, "avg_roi_pct": 4.5, "avg_sharpe": 1.2, "avg_max_drawdown_pct": 3.1, "total_trades": 120, "episodes_completed": 10},
  "improvements": {"roi_pct": 1.3, "sharpe": 0.3},
  "verdict": "Version 2 improves on version 1 across both ROI and Sharpe ratio."
}
```

improvements: positive means v2 is better. verdict: human-readable summary.

---

## 7. Integration Choice Recommendation

### 7.1 When to use each layer

| Task | Layer | Reason |
|------|-------|--------|
| Get prices, candles, tickers | SDK | Typed models, auto-retry, no boilerplate |
| Place live trades | SDK place_market_order etc. | Typed Order return, handles Decimal conversion |
| Check balances / positions / portfolio | SDK | Typed frozen dataclasses |
| Performance analytics | SDK get_performance | Typed Performance model |
| Manage strategies (CRUD) | SDK | Clear typed API |
| Run strategy tests + poll status | SDK run_test + get_test_status | Maps cleanly to test workflow |
| Compare strategy versions | SDK compare_versions | Direct endpoint wrapper |
| Backtest lifecycle | Direct REST (httpx) | SDK has NO backtest methods |
| Agent management (create/list) | Direct REST or SDK | JWT required for /agents/* endpoints |
| Natural language agentic flow | MCP MCPServerStdio | 58 tools available to Claude |

### 7.2 Auth recommendation

1. Use X-API-Key for all trading, backtest, market data, and analytics calls.
2. For agent management and battles: call `POST /api/v1/auth/login` with api_key + api_secret to obtain JWT. Send `Authorization: Bearer <jwt>`.
3. SDK clients: pass api_key + api_secret at construction — SDK handles JWT acquisition automatically.
4. Direct REST httpx calls: set `X-API-Key` header. For JWT-only endpoints, obtain JWT from `/auth/login` first.

### 7.3 Polling pattern for async operations

Strategy test runs execute as Celery tasks. Poll until terminal status:

```python
import asyncio

async def wait_for_test(
    client,            # AsyncAgentExchangeClient
    strategy_id: str,
    test_id: str,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
) -> dict:
    terminal = {"completed", "failed", "cancelled"}
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        result = await client.get_test_status(strategy_id, test_id)
        if result.get("status") in terminal:
            return result
        if asyncio.get_event_loop().time() >= deadline:
            raise TimeoutError(f"Test {test_id} did not complete within {timeout}s")
        await asyncio.sleep(poll_interval)
```

---

## Key File References

All paths are relative to the project root.

| File | What to find there |
|------|-------------------|
| `sdk/agentexchange/async_client.py` | All 37 async method implementations with full signatures and docstrings |
| `sdk/agentexchange/models.py` | 13 frozen dataclass response models with from_dict classmethod |
| `sdk/agentexchange/exceptions.py` | Exception hierarchy + raise_for_response() factory |
| `src/mcp/server.py` | MCP startup, env config, create_server(), stdio transport loop |
| `src/mcp/tools.py` | All 58 tool definitions (_TOOL_DEFINITIONS) and _dispatch() routing |
| `src/api/routes/backtest.py` | Backtest lifecycle endpoint implementations |
| `src/api/routes/strategies.py` | Strategy CRUD endpoint implementations |
| `src/api/routes/strategy_tests.py` | Strategy testing endpoint implementations |
| `src/api/schemas/backtest.py` | BacktestCreateRequest, StepResponse, BacktestResultsResponse etc. |
| `src/api/schemas/strategies.py` | CreateStrategyRequest, StrategyResponse, StrategyVersionResponse |
| `src/api/schemas/strategy_tests.py` | StartTestRequest, TestRunResponse, TestResultsResponse, VersionComparisonResponse |
| `src/api/middleware/auth.py` | Auth middleware, _resolve_account_from_api_key, _resolve_account_from_jwt |
| `src/mcp/CLAUDE.md` | Complete 58-tool table with required args and REST endpoint mapping |
| `src/api/routes/CLAUDE.md` | All 90+ endpoint paths, auth tiers, method/status tables |
| `sdk/CLAUDE.md` | SDK architecture, method groups, constructor params, gotchas |

