# agent/tools — Platform Integration Layers

<!-- last-updated: 2026-03-21 -->

> Four integration layers that wrap platform access for Pydantic AI agents: SDK tools, MCP server factory, REST tools, and agent self-reflection tools.

## What This Module Does

Provides all four channels through which the agent calls the AiTradingAgent platform. Each layer targets a different surface area: the SDK client covers live trading and market data; the MCP server subprocess exposes all 58 platform tools via JSON-RPC; the REST client covers the backtest lifecycle and strategy management surfaces that the SDK does not expose; and the agent tools provide self-reflection, portfolio review, opportunity scanning, journaling, and platform feature requests backed by direct DB writes. All tool functions follow a consistent error contract — errors are returned as `{"error": "<message>"}` rather than raised, so the LLM can handle failures gracefully without crashing the workflow.

## Key Files

| File | Purpose |
|------|---------|
| `sdk_tools.py` | `get_sdk_tools()` — 7 async tool functions backed by `AsyncAgentExchangeClient` |
| `mcp_tools.py` | `get_mcp_server()`, `get_mcp_server_with_jwt()` — spawns the platform MCP server subprocess |
| `rest_tools.py` | `PlatformRESTClient` class and `get_rest_tools()` — 11 REST tool functions for backtest + strategy |
| `agent_tools.py` | `get_agent_tools()` — 5 async tool functions for self-reflection, portfolio review, opportunity scan, journaling, and feature requests |
| `__init__.py` | Re-exports all 6 public names: `PlatformRESTClient`, `get_agent_tools`, `get_mcp_server`, `get_mcp_server_with_jwt`, `get_rest_tools`, `get_sdk_tools` |

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

### `get_agent_tools(config, agent_id)` — `agent_tools.py`

Factory that instantiates a single `AsyncAgentExchangeClient` shared across all returned tools and closes over `config`, `agent_id`, and the client. Returns a `list` of 5 async tool functions suitable for `Agent(tools=...)`.

These tools write directly to the platform database. They are designed for **co-located deployments** (agent process running on the same host as the database) and are not appropriate for remote-only API integrations.

All tools catch exceptions and return `{"error": "<message>"}` instead of raising.

| Tool function | Purpose | Key parameters | Returns on success |
|---------------|---------|----------------|-------------------|
| `reflect_on_trade(ctx, trade_id)` | Generate a structured reflection on a completed trade | `trade_id: str` — the trade to reflect on | `TradeReflection` dict (see below) |
| `review_portfolio(ctx)` | Evaluate portfolio health, concentration, and budget usage | none | `PortfolioReview` dict (see below) |
| `scan_opportunities(ctx, criteria)` | Scan all live prices for trading opportunities meeting criteria | `criteria: dict` — filter and scoring options | `list[Opportunity]` dicts (see below) |
| `journal_entry(ctx, content, entry_type="reflection")` | Write a journal entry with auto-generated market snapshot and tags | `content: str`, `entry_type: str` | `JournalEntry` dict (see below) |
| `request_platform_feature(ctx, description, category="feature_request")` | Submit a feature request or bug report to the platform feedback table | `description: str`, `category: str` | `FeedbackEntry` dict (see below) |

---

#### `reflect_on_trade(ctx, trade_id)`

Fetches the agent's last 50 trades, finds the matching entry/exit pair for `trade_id`, fetches all observations from `agent_observations` for that trade, then computes:

- `pnl` — realised profit/loss
- `mae` — maximum adverse excursion (worst price vs entry)
- `entry_quality` — heuristic score for how well-timed the entry was
- `exit_quality` — heuristic score for the exit timing

Persists a `"reflection"` row to `agent_journal` and a learning row to `agent_learnings`.

**`TradeReflection` dict fields:**

| Field | Type | Description |
|-------|------|-------------|
| `trade_id` | `str` | The reflected trade |
| `symbol` | `str` | Trading pair |
| `pnl` | `str` (Decimal string) | Realised PnL |
| `mae` | `str` (Decimal string) | Maximum adverse excursion |
| `entry_quality` | `float` | `[0.0, 1.0]` entry quality score |
| `exit_quality` | `float` | `[0.0, 1.0]` exit quality score |
| `key_learning` | `str` | One-sentence learning saved to memory |
| `journal_entry_id` | `str` | UUID of the created journal row |

---

#### `review_portfolio(ctx)`

Fetches balances and positions via the SDK, fetches budget status from the DB, then scores portfolio health.

**Concentration thresholds:**

| Level | Single-asset portfolio share |
|-------|------------------------------|
| Normal | < 30% |
| HIGH | 30%–49% |
| EXTREME | ≥ 50% |

**Health score:** Starts at `1.0`, decremented by:
- Extreme concentration: −0.3 per asset
- High concentration: −0.1 per asset
- Open positions with unrealised PnL < −5%: −0.1 per position
- Budget usage > 75%: −0.2

Persists an `"insight"` row to `agent_journal`.

**`PortfolioReview` dict fields:**

| Field | Type | Description |
|-------|------|-------------|
| `total_value` | `str` | Total portfolio USDT value |
| `health_score` | `float` | `[0.0, 1.0]` overall health |
| `concentration_warnings` | `list[str]` | Symbols with HIGH or EXTREME concentration |
| `position_count` | `int` | Number of open positions |
| `budget_usage_pct` | `float` | Fraction of daily trade budget consumed |
| `recommendations` | `list[str]` | Human-readable action suggestions |
| `journal_entry_id` | `str` | UUID of the created journal row |

---

#### `scan_opportunities(ctx, criteria)`

Reads all current prices from Redis `HGETALL prices` (falls back to SDK `get_price()` per symbol in `config.symbols`). Scores each symbol as a potential opportunity.

**`criteria` dict options:**

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `trending_up` | `bool` | `False` | Only include symbols with positive 1h change |
| `trending_down` | `bool` | `False` | Only include symbols with negative 1h change |
| `min_price` | `float \| None` | `None` | Minimum price in USDT |
| `max_price` | `float \| None` | `None` | Maximum price in USDT |
| `symbols` | `list[str] \| None` | `None` | Restrict scan to these symbols only |
| `top_n` | `int` | `10` | Maximum number of opportunities to return |

**Signal strength formula:** `min(1.0, abs_change_pct / 10.0)`
**Minimum threshold:** `0.30` (signals below this are filtered out)
**Risk/reward requirement:** ≥ 1.5 (using stop-loss 2%, take-profit 4%)

**`Opportunity` dict fields:**

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | `str` | Trading pair |
| `signal_strength` | `float` | `[0.0, 1.0]` — higher is stronger |
| `direction` | `str` | `"buy"` or `"sell"` |
| `current_price` | `str` | Current price as Decimal string |
| `suggested_stop_loss` | `str` | 2% below/above entry as Decimal string |
| `suggested_take_profit` | `str` | 4% above/below entry as Decimal string |
| `reasoning` | `str` | Brief explanation of why this symbol qualifies |

Results are sorted by `signal_strength` descending.

---

#### `journal_entry(ctx, content, entry_type="reflection")`

Captures a market snapshot (top prices from Redis + portfolio state from SDK) at the time of the call. Auto-generates tags by matching `content` against `_TAG_KEYWORD_MAP` keyword sets. Persists to `agent_journal`.

**Valid `entry_type` values:**

| Input value | Stored as | Notes |
|-------------|-----------|-------|
| `"reflection"` | `"reflection"` | — |
| `"insight"` | `"insight"` | — |
| `"observation"` | `"observation"` | — |
| `"daily_review"` | `"daily_review"` | — |
| `"weekly_review"` | `"weekly_review"` | — |
| `"daily_summary"` | `"daily_review"` | Remapped for consistency |
| `"ab_test"` | `"insight"` | Remapped for consistency |

**`JournalEntry` dict fields:**

| Field | Type | Description |
|-------|------|-------------|
| `entry_id` | `str` | UUID of the created journal row |
| `entry_type` | `str` | Stored entry type (after remapping) |
| `tags` | `list[str]` | Auto-generated tags from keyword matching |
| `market_snapshot` | `dict` | Prices and portfolio state at call time |
| `created_at` | `str` | ISO-8601 UTC timestamp |

---

#### `request_platform_feature(ctx, description, category="feature_request")`

Deduplicates against existing feedback rows by checking for an existing entry with an ILIKE match on the first 60 characters of `description`. If a duplicate is found, returns the existing entry's ID without creating a new row.

**`category` mapping:**

| Input category | Stored category | Priority |
|----------------|----------------|---------|
| `"feature_request"` | `"feature_request"` | `"medium"` |
| `"bug_report"` | `"bug"` | `"high"` |
| `"performance"` | `"performance_issue"` | `"medium"` |
| `"ux"` | `"missing_tool"` | `"low"` |

**`FeedbackEntry` dict fields:**

| Field | Type | Description |
|-------|------|-------------|
| `feedback_id` | `str` | UUID of the feedback row |
| `category` | `str` | Stored category (after mapping) |
| `priority` | `str` | `"high"`, `"medium"`, or `"low"` |
| `description` | `str` | The submitted description |
| `is_duplicate` | `bool` | `True` if an existing similar entry was found |
| `created_at` | `str` | ISO-8601 UTC timestamp |

---

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
- **`get_agent_tools()` requires database access**: Unlike the other three factories, `get_agent_tools()` writes directly to the platform database via `session_factory`. It is not suitable for use in environments where only the REST API is accessible. Pass a valid `session_factory` that connects to the same database as the running platform.
- **`get_agent_tools()` SDK client is shared and must be closed**: Same lifecycle rules as `get_sdk_tools()` — the `AsyncAgentExchangeClient` created inside `get_agent_tools()` is never auto-closed. The caller must call `await client.aclose()` when the agent session ends.
- **`scan_opportunities()` Redis fallback may be slow**: If Redis is unavailable, `scan_opportunities()` falls back to calling `sdk_client.get_price()` for each symbol in `config.symbols` sequentially. For large symbol lists this adds meaningful latency. Keep `config.symbols` short (3–5 symbols) for fast fallback behaviour.
- **`request_platform_feature()` dedup is approximate**: The ILIKE check on the first 60 characters of `description` may miss near-duplicates that differ in their opening words, and may falsely match unrelated descriptions that happen to start identically. Review the feedback table periodically to merge true duplicates.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
- `2026-03-21` — Added `agent_tools.py` section documenting `get_agent_tools()` and all 5 tool functions (reflect_on_trade, review_portfolio, scan_opportunities, journal_entry, request_platform_feature). Updated header description, Key Files table, and `__init__.py` export count. Added 4 new gotchas for agent tools.
