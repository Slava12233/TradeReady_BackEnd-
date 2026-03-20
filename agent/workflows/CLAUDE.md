# agent/workflows — End-to-End Testing Workflows

<!-- last-updated: 2026-03-20 -->

> Four end-to-end testing workflows that orchestrate platform tool calls and LLM reasoning to validate the full AiTradingAgent feature surface.

## What This Module Does

Implements the four runnable workflows that exercise different platform surfaces. Each workflow is a standalone async function with the signature `async def run_*(config: AgentConfig) -> WorkflowResult`. Workflows never crash on step failures — all errors are caught per-step and appended to `bugs_found` or `findings`. Every workflow returns a valid `WorkflowResult` regardless of how many steps fail.

## Key Files

| File | Purpose |
|------|---------|
| `smoke_test.py` | `run_smoke_test()` — 10-step connectivity validation, no LLM |
| `trading_workflow.py` | `run_trading_workflow()` — 9-step live trade lifecycle with LLM |
| `backtest_workflow.py` | `run_backtest_workflow()` — 8-step MA-crossover backtest, LLM once at end |
| `strategy_workflow.py` | `run_strategy_workflow()` — 12-step V1→V2 strategy create/test/compare cycle |
| `__init__.py` | Re-exports all 4 runner functions |

## Public API / Key Classes

### `run_smoke_test(config: AgentConfig) -> WorkflowResult`

10-step connectivity check. No LLM is used — every call goes directly to the SDK client or httpx. Does not use `get_sdk_tools()` (which creates a Pydantic AI tool layer); instead, it instantiates `AsyncAgentExchangeClient` directly and calls methods on it.

| Step | Action | Failure mode |
|------|--------|--------------|
| 1 | `client.get_price("BTCUSDT")` — non-zero price | bug |
| 2 | `client.get_balance()` — USDT balance present and positive | bug |
| 3 | `client.get_candles("BTCUSDT", "1h", 10)` — non-empty list | bug |
| 4 | `client.place_market_order("BTCUSDT", "buy", "0.0001")` — order accepted | bug |
| 5 | `client.get_positions()` — BTCUSDT position present after buy | bug (if step 4 passed) |
| 6 | `client.get_trade_history(limit=5)` — trade recorded | bug (if step 4 passed) |
| 7 | `client.get_performance(period="all")` — response received | bug |
| 8 | `GET /api/v1/health` via httpx — status 200 | bug |
| 9 | `GET /api/v1/market/prices` via httpx — non-empty prices list | bug |
| 10 | Compile results | always passes |

Status logic: `"pass"` if no bugs, `"partial"` if bugs but > 1 step completed, `"fail"` if only 0–1 steps completed.

### `run_trading_workflow(config: AgentConfig) -> WorkflowResult`

9-step live trade lifecycle. Uses Pydantic AI `Agent` with `output_type=TradeSignal` (step 2) and `output_type=MarketAnalysis` (step 8).

| Step | Action | LLM? |
|------|--------|-------|
| 1 | Fetch 100 1h OHLCV candles for BTC, ETH, SOL | No |
| 2 | LLM agent generates `TradeSignal` from candle data | Yes (`agent_model`) |
| 3 | Validate signal: reject HOLD or confidence ≤ 0.5; clamp `quantity_pct` to `max_trade_pct` | No |
| 4 | Execute entry trade via `client.place_market_order()` | No |
| 5 | Monitor position — 3 price checks with 10 s sleep between each | No |
| 6 | Close position with opposite-side market order | No |
| 7 | Fetch performance metrics via `client.get_performance("all")` | No |
| 8 | Evaluation LLM agent produces `MarketAnalysis` of the completed trade | Yes (`agent_model`) |
| 9 | Build and return `WorkflowResult` | No |

Early returns with `status="partial"`: HOLD signal (step 3), confidence ≤ 0.5 (step 3), LLM agent failure (step 2), no candle data at all (step 1 — returns `"fail"`).

Status logic: `"pass"` if no bugs and all 9 steps complete; `"partial"` if bugs but ≥ 5 steps completed; `"fail"` otherwise.

The `AsyncAgentExchangeClient` is closed in a `finally` block after step 8.

### `run_backtest_workflow(config: AgentConfig, *, max_iterations: int = 20, batch_size: int = 5) -> WorkflowResult`

8-step MA-crossover backtest. Trading loop is entirely LLM-free. LLM is invoked exactly once after the loop for result analysis.

| Step | Action | LLM? |
|------|--------|-------|
| 1 | `GET /api/v1/health` — platform health check | No |
| 2 | `GET /api/v1/market/data-range` — discover available data; fallback to `2024-02-23 → 2024-03-01` | No |
| 3 | `create_backtest` — BTC+ETH, 1-min candles, 10,000 USDT, 7-day window | No |
| 4 | `start_backtest` — bulk-preloads candles; must return `status="running"` | No |
| 5 | Trading loop (up to `max_iterations` iterations × `batch_size` steps): fetch candles → compute dual-SMA signal (`_MA_FAST=5`, `_MA_SLOW=20`) → place market order on crossover (avoiding duplicate positions) → `step_backtest_batch` | No |
| 6 | `get_backtest_results` — fetch final metrics | No |
| 7 | LLM agent produces `BacktestAnalysis` with `improvement_plan` | Yes (`agent_model`) |
| 8 | (Implicit) Determine overall status and build `WorkflowResult` | No |

The `steps_total` is declared as 7 (health, data-range, create, start, loop, results, analysis). The trading loop counts as one composite step.

`PlatformRESTClient` is used directly as `async with PlatformRESTClient(config) as client:` — the LLM analysis step happens outside the `async with` block because the REST client is closed after fetching results.

Status logic: `"pass"` if no bugs and all 7 steps complete; `"partial"` if bugs but ≥ 5 steps completed; `"fail"` otherwise.

### `run_strategy_workflow(config: AgentConfig) -> WorkflowResult`

12-step create → test → improve → compare cycle. LLM is used once (step 4) for natural-language review of V1 results using `agent_cheap_model`.

| Step | Action | LLM? |
|------|--------|-------|
| 1 | `create_strategy` — SMA crossover V1 with RSI + MACD entry conditions | No |
| 2 | `test_strategy` — trigger V1 test run (3 episodes × 30 days) | No |
| 3 | Poll V1 test until terminal status (timeout 120 s, poll every 5 s) | No |
| 4 | LLM cheap-model reviews V1 results and proposes improvements in text | Yes (`agent_cheap_model`) |
| 5 | `_build_v2_definition()` — derive V2 deterministically from V1 metrics | No |
| 6 | `create_version` — create V2 as a new immutable strategy version | No |
| 7 | `test_strategy` — trigger V2 test run (3 episodes × 30 days) | No |
| 8 | Poll V2 test until terminal status (timeout 120 s, poll every 5 s) | No |
| 9 | `compare_versions` — compare V1 vs V2 metrics (non-critical; failure recorded as finding) | No |
| 10 | Surface platform recommendations from test engine responses | No |
| 11 | Validate version auto-increment (V2 == V1 + 1) | No |
| 12 | Compile final status and return `WorkflowResult` | No |

`PlatformRESTClient` is used as `async with PlatformRESTClient(config) as client:` wrapping steps 1–12.

Status logic: `"pass"` if no bugs and all 12 steps complete; `"partial"` if any bugs regardless of step count; `"fail"` if a critical step fails (create strategy, trigger V1 test, or create V2 version).

## Patterns

- All workflow runners follow the same signature: `async def run_*(config: AgentConfig) -> WorkflowResult`.
- Each step increments `steps_completed` only on success; partial/failed steps do not increment it.
- Per-step `try/except` blocks catch exceptions, append to `bugs_found` or `findings`, and continue. The workflow never re-raises.
- structlog is bound at the start of each workflow: `log = logger.bind(workflow="workflow_name")`. Every significant event is logged at `INFO` level with structured key-value pairs.
- `metrics` dict collects numeric and string performance data throughout the workflow for inclusion in the `WorkflowResult`.
- The trading and backtest workflows both close their SDK/REST clients in `finally` blocks or `async with` exit paths.

## Gotchas

- **`run_backtest_workflow` has a `steps_total = 7`**, not 8. The 8 steps mentioned in the module docstring include the implicit status-determination step which is not counted separately.
- **Trading workflow uses `place_market_order` directly**, not the `place_market_order` SDK tool from `get_sdk_tools()`. This is because the workflow manages the client lifecycle itself and uses the raw `AsyncAgentExchangeClient` for all SDK calls.
- **Backtest workflow's trading loop is LLM-free by design**. The `_sma()` and `_ma_signal()` helper functions compute the crossover signal locally. This keeps run time predictable (no LLM latency per iteration) and results deterministic.
- **Strategy workflow LLM failure is non-critical**. If the `agent_cheap_model` review agent fails in step 4, the workflow logs a finding and falls through to the deterministic `_build_v2_definition()` call. V2 is always created.
- **Poll timeout**: Both `_poll_test_run` calls in the strategy workflow time out after 120 seconds. If Celery workers are busy or slow, V1 or V2 tests may not reach terminal status within the timeout, resulting in a `"partial"` status.
- **HTTP 404/409/410 in backtest loop**: These status codes indicate the session has already completed. The loop breaks gracefully and records a finding, not a bug.
- **HTTP 400/422 from backtest orders**: These indicate risk rejections (e.g. position limit exceeded). They are recorded as `findings`, not `bugs_found`, because risk rejection is expected behaviour.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
