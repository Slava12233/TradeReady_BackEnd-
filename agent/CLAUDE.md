# agent/ — TradeReady Platform Testing Agent

<!-- last-updated: 2026-03-22 -->

> Autonomous AI agent for end-to-end testing of the AiTradingAgent platform using Pydantic AI + OpenRouter.

## What This Module Does

The `agent/` package is a standalone Python application that drives the AiTradingAgent platform through its full feature surface — trading, backtesting, and strategy management — using an LLM as the reasoning layer. It connects to the platform via three integration channels (AgentExchange SDK, MCP server subprocess, and direct REST calls) and produces structured JSON reports that summarise platform health, bugs found, and improvement suggestions.

It is **not** a trading bot for production use. It is a systematic, autonomous tester whose output is a `WorkflowResult` (per workflow) and a `PlatformValidationReport` (for full sessions).

## Directory Structure

```
agent/
├── __init__.py              # Package root; exposes __version__ = "0.1.0"
├── __main__.py              # Entry point: asyncio.run(main()) — enables python -m agent
├── config.py                # AgentConfig (pydantic-settings BaseSettings)
├── main.py                  # CLI parser, workflow dispatch, report persistence; uses configure_agent_logging()
├── logging.py               # configure_agent_logging() — centralized structlog config with trace_id/span_id/agent_id context
├── logging_middleware.py    # log_api_call() context manager (accepts optional writer: LogBatchWriter), LLM cost estimator, set_agent_id()
├── logging_writer.py        # LogBatchWriter — async batched DB persistence for API call logs
├── metrics.py               # 16 Prometheus metrics in AGENT_REGISTRY (counters, histograms, gauges)
├── server.py                # AgentServer with /metrics endpoint, LogBatchWriter singleton (batch_writer property), IntentRouter registered with 7 handlers; lifecycle managed via _init_dependencies()/_shutdown()
├── server_handlers.py       # 7 async handler functions (trade, analyze, portfolio, status, journal, learn, permissions) + REASONING_LOOP_SENTINEL for general fallback
├── pyproject.toml           # Package config: tradeready-test-agent 0.1.0; adds prometheus-client dependency
├── .env.example             # All required env vars with placeholder values
├── reports/                 # Default output directory for JSON report files
│   └── .gitkeep
├── models/
│   ├── __init__.py          # Re-exports all 6 public models
│   ├── analysis.py          # MarketAnalysis, BacktestAnalysis
│   ├── report.py            # WorkflowResult, PlatformValidationReport
│   └── trade_signal.py      # SignalType (enum), TradeSignal
├── prompts/
│   ├── __init__.py
│   ├── system.py            # SYSTEM_PROMPT constant (used by all LLM agents)
│   └── skill_context.py     # load_skill_context() — loads docs/skill.md
├── tools/
│   ├── __init__.py          # Re-exports all 6 public tool factories
│   ├── sdk_tools.py         # get_sdk_tools() — 13 tools via AsyncAgentExchangeClient; _serialize_order() helper
│   ├── mcp_tools.py         # get_mcp_server(), get_mcp_server_with_jwt()
│   ├── rest_tools.py        # PlatformRESTClient, get_rest_tools() — 11 REST tool functions
│   └── agent_tools.py       # get_agent_tools() — 5 self-reflection/journal/feedback tools
├── conversation/
│   ├── __init__.py          # Re-exports AgentSession, SessionError, IntentRouter, IntentType
│   ├── session.py           # AgentSession — DB-backed session lifecycle, auto-summarisation
│   ├── history.py           # ConversationHistory, Message — read-only message access
│   ├── context.py           # ContextBuilder — 6-section LLM context assembly
│   └── router.py            # IntentRouter, IntentType — 3-layer message classification
├── memory/
│   ├── __init__.py          # Re-exports MemoryType, Memory, MemoryStore, MemoryNotFoundError, PostgresMemoryStore, RedisMemoryCache, MemoryRetriever, RetrievalResult
│   ├── store.py             # MemoryStore ABC, Memory model, MemoryType, MemoryNotFoundError
│   ├── postgres_store.py    # PostgresMemoryStore — durable Postgres implementation
│   ├── redis_cache.py       # RedisMemoryCache — hot cache, working memory, regime/signal state
│   └── retrieval.py         # MemoryRetriever, RetrievalResult — scored two-phase retrieval
├── permissions/
│   ├── __init__.py          # Re-exports all public symbols from all 4 submodules
│   ├── roles.py             # AgentRole, ROLE_HIERARCHY, ROLE_CAPABILITIES, helper functions
│   ├── capabilities.py      # Capability, ALL_CAPABILITIES, CapabilityManager
│   ├── budget.py            # BudgetManager — Redis-backed daily limits
│   └── enforcement.py       # PermissionEnforcer, PermissionDenied, ACTION_CAPABILITY_MAP
├── trading/
│   ├── __init__.py          # Re-exports TradingLoop, SignalGenerator, TradingSignal, StrategyManager, LoopStoppedError, TradeExecutor, PositionMonitor, TradingJournal, ABTestRunner, ABTest, and exceptions
│   ├── loop.py              # TradingLoop — observe→learn cycle, error backoff, shutdown
│   ├── signal_generator.py  # SignalGenerator, TradingSignal — ensemble-backed signals
│   ├── execution.py         # TradeExecutor — idempotent, retried execution with budget
│   ├── monitor.py           # PositionMonitor — stop-loss/take-profit/max-hold exits
│   ├── journal.py           # TradingJournal — decision records, LLM reflections, summaries
│   ├── strategy_manager.py  # StrategyManager — rolling windows, degradation, adjustments
│   ├── ab_testing.py        # ABTestRunner, ABTest — A/B test framework
│   ├── pair_selector.py     # PairSelector, SelectedPairs, PairInfo — volume/momentum pair ranking with TTL cache
│   └── ws_manager.py        # WSManager — WebSocket integration: ticker + order channels, fill notifications, REST fallback
├── workflows/
│   ├── __init__.py          # Re-exports all 4 workflow runner functions
│   ├── smoke_test.py        # run_smoke_test() — 10-step connectivity validation
│   ├── trading_workflow.py  # run_trading_workflow() — 9-step trade lifecycle
│   ├── backtest_workflow.py # run_backtest_workflow() — 8-step MA crossover backtest
│   └── strategy_workflow.py # run_strategy_workflow() — 12-step V1→V2 strategy cycle
├── strategies/
│   ├── __init__.py          # Re-exports all public symbols (RLConfig, StrategyGenome, Population, RiskAgent, RegimeClassifier, MetaLearner, etc.)
│   ├── rl/                  # PPO reinforcement learning (config, train, evaluate, deploy, data_prep, runner)
│   ├── evolutionary/        # Genetic algorithm (genome, operators, population, battle_runner, evolve, analyze, config)
│   ├── regime/              # Market regime detection (labeler, classifier, switcher, strategy_definitions, validate)
│   ├── risk/                # Risk management overlay (risk_agent, veto, sizing, middleware, recovery)
│   ├── ensemble/            # Ensemble combiner (signals, meta_learner, optimize_weights, run, validate, config, circuit_breaker, attribution)
│   ├── drift.py             # DriftDetector — Page-Hinkley test on log-returns; integrated into TradingLoop
│   ├── retrain.py           # RetrainOrchestrator — 4 schedules (ensemble 8h, regime 7d, genome 7d, PPO 30d), A/B gate
│   └── walk_forward.py      # WalkForwardConfig, WalkForwardResult, generate_windows(), compute_wfe(), run_walk_forward()
└── tests/
    ├── __init__.py
    ├── test_config.py              # AgentConfig field validation and defaults
    ├── test_models.py              # All 6 Pydantic output models
    ├── test_rest_tools.py          # PlatformRESTClient and get_rest_tools() functions
    ├── test_sdk_tools.py           # get_sdk_tools() tool functions
    ├── test_logging.py             # 25 tests for configure_agent_logging() and structlog context
    ├── test_logging_middleware.py  # 24 tests for log_api_call() and LLM cost estimator
    └── test_logging_writer.py      # 17 tests for LogBatchWriter async batching
```

## Key Classes and Functions

### `AgentConfig` (`config.py`)

Pydantic v2 `BaseSettings` that reads from `agent/.env`. All fields map 1-to-1 to entries in `.env.example`.

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `openrouter_api_key` | `str` | required | OpenRouter API key for LLM calls |
| `agent_model` | `str` | `"openrouter:anthropic/claude-sonnet-4-5"` | Primary LLM model ID |
| `agent_cheap_model` | `str` | `"openrouter:google/gemini-2.0-flash-001"` | Cheap model for low-stakes tasks |
| `platform_base_url` | `str` | `"http://localhost:8000"` | Platform REST API base URL |
| `platform_api_key` | `str` | `""` | `ak_live_...` key for SDK + MCP + REST auth |
| `platform_api_secret` | `str` | `""` | `sk_live_...` secret for SDK JWT login |
| `max_trade_pct` | `float` | `0.05` | Maximum fraction of equity per test trade (5%) |
| `symbols` | `list[str]` | `["BTCUSDT", "ETHUSDT", "SOLUSDT"]` | Default symbols for market analysis |
| `platform_root` | `Path` | computed | Absolute path to repo root (parent of `agent/`) — used as MCP server subprocess `cwd` |

The `.env` file is located at `agent/.env` (sibling of `config.py`), not at the repo root.

### Output Models (`models/`)

All models use `ConfigDict(frozen=True)` and extend Pydantic v2 `BaseModel`. They serve as `output_type` on Pydantic AI agents.

| Model | File | Purpose |
|-------|------|---------|
| `SignalType` | `trade_signal.py` | Str-enum: `"buy"`, `"sell"`, `"hold"` |
| `TradeSignal` | `trade_signal.py` | Trade decision: symbol, signal, confidence (0–1), quantity_pct (0.01–0.10), reasoning, risk_notes |
| `MarketAnalysis` | `analysis.py` | Market conditions: symbol, trend, support_level, resistance_level (strings to avoid float precision loss), indicators dict, summary |
| `BacktestAnalysis` | `analysis.py` | Backtest outcome: session_id, sharpe_ratio, max_drawdown, win_rate, total_trades, pnl (string), improvement_plan (list of strings) |
| `WorkflowResult` | `report.py` | Single workflow summary: workflow_name, status (pass/fail/partial), steps_completed, steps_total, findings, bugs_found, suggestions, metrics |
| `PlatformValidationReport` | `report.py` | Full session summary: session_id, model_used, workflows_run (list of WorkflowResult), platform_health (healthy/degraded/broken), summary |

### Tool Factories (`tools/`)

#### `get_sdk_tools(config)` — `sdk_tools.py`

Returns a list of 7 async tool functions backed by a single shared `AsyncAgentExchangeClient` instance. All return plain dicts; errors are returned as `{"error": "<message>"}` rather than raised.

| Tool function | SDK method | Returns |
|---------------|-----------|---------|
| `get_price` | `client.get_price(symbol)` | `{symbol, price, timestamp}` |
| `get_candles` | `client.get_candles(symbol, interval, limit)` | list of OHLCV dicts |
| `get_balance` | `client.get_balance()` | list of `{asset, available, locked, total}` |
| `get_positions` | `client.get_positions()` | list of position dicts |
| `get_performance` | `client.get_performance(period)` | performance metrics dict |
| `get_trade_history` | `client.get_trade_history(limit)` | list of trade dicts |
| `place_market_order` | `client.place_market_order(symbol, side, quantity)` | order dict |

The shared client's connection pool is not closed by the tool functions. The caller is responsible for calling `await client.aclose()` when the agent session ends.

#### `get_mcp_server(config)` — `mcp_tools.py`

Returns a `pydantic_ai.mcp.MCPServerStdio` that spawns `python -m src.mcp.server` as a subprocess. Passes `MCP_API_KEY`, `API_BASE_URL`, and `LOG_LEVEL=WARNING` as environment variables. The subprocess `cwd` is set to `config.platform_root` so `src` is importable.

Raises `ValueError` if `config.platform_api_key` is empty, because the MCP server will immediately exit without a key.

#### `get_mcp_server_with_jwt(config, jwt_token)` — `mcp_tools.py`

Identical to `get_mcp_server()` but additionally injects `MCP_JWT_TOKEN`. Required when the agent needs to call JWT-only endpoints under `/api/v1/agents/` or `/api/v1/battles/`.

#### `PlatformRESTClient` — `rest_tools.py`

Async HTTP client wrapping `httpx.AsyncClient`. Supports async context manager. Methods cover the backtest lifecycle and strategy management surfaces that the SDK does not expose.

| Method | HTTP call | Purpose |
|--------|-----------|---------|
| `create_backtest(...)` | `POST /api/v1/backtest/create` | Create a new backtest session |
| `start_backtest(session_id)` | `POST /api/v1/backtest/{id}/start` | Bulk-preload candles and start session |
| `step_backtest_batch(session_id, steps)` | `POST /api/v1/backtest/{id}/step/batch` | Advance N candle intervals |
| `backtest_trade(session_id, ...)` | `POST /api/v1/backtest/{id}/trade/order` | Place order in sandbox |
| `get_backtest_results(session_id)` | `GET /api/v1/backtest/{id}/results` | Fetch completed results |
| `get_backtest_candles(session_id, symbol, ...)` | `GET /api/v1/backtest/{id}/market/candles/{symbol}` | Get candles up to virtual clock |
| `create_strategy(name, description, definition)` | `POST /api/v1/strategies` | Create a new strategy |
| `test_strategy(strategy_id, version, ...)` | `POST /api/v1/strategies/{id}/test` | Trigger Celery test run |
| `get_test_results(strategy_id, test_id)` | `GET /api/v1/strategies/{id}/tests/{test_id}` | Poll test status + results |
| `create_version(strategy_id, definition, ...)` | `POST /api/v1/strategies/{id}/versions` | Create immutable new version |
| `compare_versions(strategy_id, v1, v2)` | `GET /api/v1/strategies/{id}/compare-versions` | Compare two versions |

#### `get_rest_tools(config)` — `rest_tools.py`

Returns a list of 11 async tool functions wrapping the `PlatformRESTClient` methods above. Tool functions match the client methods 1-to-1 with identical signatures, but errors are caught and returned as `{"error": "<message>"}` instead of raised. The shared `PlatformRESTClient` instance is not closed inside the tool functions.

### Workflows (`workflows/`)

All workflow runners have the signature `async def run_*(config: AgentConfig) -> WorkflowResult`.

#### `run_smoke_test` — `smoke_test.py`

10-step connectivity validation. No LLM involved; every call goes directly to the SDK or httpx. Steps:

1. SDK `get_price("BTCUSDT")` — non-zero price
2. SDK `get_balance()` — USDT balance present
3. SDK `get_candles("BTCUSDT", "1h", 10)` — historical data available
4. SDK `place_market_order("BTCUSDT", "buy", "0.0001")` — order accepted
5. SDK `get_positions()` — BTC position exists after buy
6. SDK `get_trade_history(limit=5)` — trade recorded
7. SDK `get_performance()` — metrics calculate without error
8. REST `GET /api/v1/health` — platform health endpoint responds 200
9. REST `GET /api/v1/market/prices` — market data accessible, non-empty prices list
10. Compilation — summarise all findings

#### `run_trading_workflow` — `trading_workflow.py`

9-step full trade lifecycle. Uses Pydantic AI agents with `output_type=TradeSignal` and `output_type=MarketAnalysis`. Steps:

1. Fetch 100 1h OHLCV candles for BTC, ETH, SOL via SDK
2. LLM agent generates a `TradeSignal` (symbol, direction, confidence, quantity_pct)
3. Validate signal against 0.5 confidence threshold and `max_trade_pct` cap
4. Execute entry trade via SDK `place_market_order`
5. Monitor position — 3 price checks with 10-second intervals
6. Close position with opposite-side market order
7. Fetch performance metrics via SDK `get_performance()`
8. Evaluation LLM agent produces a `MarketAnalysis` of the completed trade
9. Build and return `WorkflowResult`

A HOLD signal or confidence below 0.5 returns `status="partial"` early without trading.

#### `run_backtest_workflow` — `backtest_workflow.py`

8-step 7-day MA-crossover backtest. The trading loop is LLM-free; LLM is invoked exactly once for analysis. Steps:

1. Health check via `GET /api/v1/health`
2. Discover available data range via `GET /api/v1/market/data-range`; falls back to `2024-02-23 → 2024-03-01`
3. Create BTC + ETH backtest session (1-minute candles, 10 000 USDT)
4. Start session (bulk candle preload)
5. Trading loop — up to 20 iterations × 5 batch steps:
   - Fetch candles, compute fast SMA (5) vs slow SMA (20) signal
   - Place market order on crossover; avoid stacking same-side positions
   - Advance 5 candle steps via `step_backtest_batch`
6. Fetch final results
7. LLM agent produces `BacktestAnalysis` with `improvement_plan`
8. Return `WorkflowResult`

#### `run_strategy_workflow` — `strategy_workflow.py`

12-step create → test → improve → compare cycle. LLM is used once between V1 and V2 for natural-language improvement review. Steps:

1. Create V1 strategy (SMA crossover with RSI + MACD entry conditions)
2. Trigger V1 test run (3 episodes × 30 days via Celery)
3. Poll V1 test until terminal status (timeout 120 s, poll every 5 s)
4. LLM (`agent_cheap_model`) reviews V1 results and proposes improvements
5. Build V2 definition deterministically from V1 results (tighter RSI, volume filter, trailing stop)
6. Create V2 as a new immutable version
7. Trigger V2 test run
8. Poll V2 test until terminal status
9. Compare V1 vs V2 via `compare-versions` endpoint
10. Surface platform recommendations from test engine
11. Validate version auto-increment (V2 == V1 + 1)
12. Compile final status and return `WorkflowResult`

### Prompts (`prompts/`)

#### `SYSTEM_PROMPT` — `prompts/system.py`

String constant used as the system prompt for all Pydantic AI agents in trading and backtest workflows. Covers: purpose (tester, not advisor), integration methods (SDK/MCP/REST), workflow instructions, trading rules (5% max per trade, minimal test quantities), error handling rules, and structured output model descriptions.

#### `load_skill_context(config)` — `prompts/skill_context.py`

Async function. Loads `docs/skill.md` from disk (`config.platform_root / "docs" / "skill.md"`) and returns its content as a string. Falls back to `GET {platform_base_url}/api/v1/docs/skill` if the file is missing. Returns empty string if both sources fail. Never raises.

### CLI Entry Point (`main.py`)

`async def main()` is the primary entry point. It:

1. Configures structlog (JSON output, ISO timestamps) via `_configure_structlog()`
2. Parses CLI arguments (`workflow`, `--model`, `--output-dir`)
3. Loads `AgentConfig()` — exits with code 1 and a friendly message if loading fails or `OPENROUTER_API_KEY` is empty
4. Applies `--model` override via `config.model_copy(update=...)`
5. Dispatches to a single named workflow or runs all four in sequence (`smoke → trade → backtest → strategy`)
6. Saves each `WorkflowResult` as `{workflow_name}-{YYYYMMDD_HHMMSS}.json` under the output directory
7. For `all` runs: saves an additional `platform-validation-{timestamp}.json` containing a `PlatformValidationReport`
8. Exits with code 0 (pass/partial) or 1 (any failure or config error)

## Configuration

All configuration lives in `agent/.env` (not the repo-root `.env`). Copy `.env.example` and fill in your values:

```
OPENROUTER_API_KEY=sk-or-v1-...       # Required — OpenRouter key
PLATFORM_BASE_URL=http://localhost:8000
PLATFORM_API_KEY=ak_live_...           # Platform agent API key
PLATFORM_API_SECRET=sk_live_...        # Platform agent API secret (for JWT login)
AGENT_MODEL=openrouter:anthropic/claude-sonnet-4-5
AGENT_CHEAP_MODEL=openrouter:google/gemini-2.0-flash-001
```

Optional fields (not in `.env.example`, set as env vars or add to `.env`):

| Field | Default | Purpose |
|-------|---------|---------|
| `MAX_TRADE_PCT` | `0.05` | Cap test trade size at 5% of equity |
| `SYMBOLS` | `["BTCUSDT","ETHUSDT","SOLUSDT"]` | Default symbols for market analysis |

## Usage Patterns

### Install

```bash
pip install -e agent/
# Or install with dev dependencies:
pip install -e "agent/[dev]"
# Or install with ML/strategy dependencies (SB3, torch, xgboost, etc.):
pip install -e "agent/[ml]"
# Or install everything (dev + ml):
pip install -e "agent/[all]"
```

### Docker (containerised run)

The agent ships with a `Dockerfile` and is wired into `docker-compose.yml` as an opt-in service under the `agent` profile. The image installs the SDK, `tradeready-gym`, and `agent[all]` in editable mode. Volumes persist RL model checkpoints, regime classifier models, evolutionary results, and JSON reports across runs.

```bash
# Run all four workflows inside Docker (reads agent/.env for credentials)
docker compose --profile agent up agent

# Run only the smoke test
docker compose --profile agent run --rm agent python -m agent.main smoke

# Build the image manually (build context must be repo root)
docker build -f agent/Dockerfile -t tradeready-agent .
```

The service depends on `api` being healthy (`condition: service_healthy`) and connects via the `internal` Docker network. Set `PLATFORM_BASE_URL=http://api:8000` in `agent/.env` when running inside Docker.

### CLI Commands

```bash
# Run connectivity smoke test (no LLM — fast)
python -m agent.main smoke

# Run full trading lifecycle
python -m agent.main trade

# Run MA-crossover backtest with LLM analysis
python -m agent.main backtest

# Run strategy create → test → improve → compare cycle
python -m agent.main strategy

# Run all four workflows in sequence; writes platform-validation-*.json
python -m agent.main all

# Override LLM model at runtime
python -m agent.main trade --model openrouter:anthropic/claude-opus-4-5

# Write reports to a custom directory
python -m agent.main all --output-dir /tmp/test-reports

# Short form via __main__.py
python -m agent smoke
```

### Programmatic Use

```python
import asyncio
from agent.config import AgentConfig
from agent.workflows import run_smoke_test, run_trading_workflow

config = AgentConfig()
result = asyncio.run(run_smoke_test(config))
print(result.status)          # "pass", "partial", or "fail"
print(result.bugs_found)      # list of bug descriptions
```

## Dependencies

Defined in `agent/pyproject.toml` under `[project.dependencies]`:

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic-ai-slim[openrouter]` | `>=0.2` | LLM agent framework with OpenRouter provider |
| `agentexchange` | (local SDK) | Platform SDK — sync/async clients, WS client |
| `httpx` | `>=0.28` | Async HTTP for `PlatformRESTClient` and `skill_context` fallback |
| `python-dotenv` | `>=1.0` | `.env` file loading (transitively used by pydantic-settings) |
| `structlog` | `>=24.0` | Structured JSON logging |
| `pydantic-settings` | `>=2.0` | `AgentConfig` BaseSettings with `.env` support |
| `prometheus-client` | `>=0.20` | 16 Prometheus metrics in `AGENT_REGISTRY`; `/metrics` endpoint |

Dev dependencies (`pip install -e "agent/[dev]"`):

| Package | Purpose |
|---------|---------|
| `pytest>=8.0` | Test runner |
| `pytest-asyncio>=0.24` | Async test support (`asyncio_mode = "auto"`) |
| `ruff>=0.8` | Linting (line-length 120, Python 3.12 target) |

ML/strategy optional dependencies (`pip install -e "agent/[ml]"`):

| Package | Strategies | Purpose |
|---------|------------|---------|
| `stable-baselines3[extra]>=2.3` | `rl/` | PPO algorithm, VecEnv, callbacks |
| `torch>=2.2` | `rl/` | Neural network backend for SB3 |
| `xgboost>=2.0` | `regime/` | Preferred regime classifier (fallback: sklearn) |
| `scikit-learn>=1.4` | `regime/`, `risk/` | RandomForest fallback, feature preprocessing |
| `joblib>=1.3` | `regime/` | Regime classifier model persistence |
| `numpy>=1.26` | All | Feature computation, genome vector math |
| `pandas>=2.2` | `regime/` | Feature DataFrame construction |
| `tradeready-gym` | `rl/` | Gymnasium RL environments for PPO training |

The `[all]` extra (`pip install -e "agent/[all]"`) installs both `[dev]` and `[ml]` together. This is what the Docker image uses.

## Testing

```bash
# Run all agent tests
pytest agent/tests/ -v

# Run a specific test file
pytest agent/tests/test_models.py -v

# With coverage (from repo root)
pytest agent/tests/ --cov=agent --cov-report=term-missing
```

The agent test suite is independent of the main platform test suite in `tests/`. It does not use the platform's `conftest.py` or app factory. Tests mock the SDK client and httpx calls; no running platform is required.

`asyncio_mode = "auto"` is configured in `agent/pyproject.toml` — no `@pytest.mark.asyncio` decorator needed on async tests.

The full agent test suite (including `agent/strategies/` and all 37 master plan tasks) covers 2200+ tests across 50 test files in `agent/tests/`.

## Gotchas and Pitfalls

- **`agent/.env`, not `.env`**. `AgentConfig` reads from `agent/.env` (resolved relative to `config.py`). The repo-root `.env` is not read. This is intentional — the agent has its own separate key set.
- **`OPENROUTER_API_KEY` is the only required field**. If it is missing or empty, `main()` prints a friendly error and exits with code 1. All other fields have defaults.
- **SDK client must be closed manually**. `get_sdk_tools()` creates a shared `AsyncAgentExchangeClient` that is not closed inside the tool functions. Callers must call `await client.aclose()` when done (or use the client as an async context manager at the call site). The smoke test and trading workflow handle this in `finally` blocks.
- **`PlatformRESTClient` is also not auto-closed by tool functions**. The `get_rest_tools()` factory creates a `PlatformRESTClient` that lives for the lifetime of the agent run. The strategy and backtest workflows use it as an `async with` context manager which handles this correctly.
- **MCP server requires `platform_api_key`**. `get_mcp_server()` raises `ValueError` eagerly if `config.platform_api_key` is empty, because the MCP subprocess will immediately call `sys.exit(1)` without a key.
- **`agent_cheap_model` is used for low-stakes tasks**. The strategy workflow uses `agent_cheap_model` (default: Gemini Flash) for the V1 review step to reduce token costs. All other LLM calls use `agent_model`.
- **Backtest trading loop is LLM-free**. The `backtest_workflow` trading loop uses a local dual-SMA calculation (`_sma()`, `_ma_signal()`) for speed and determinism. The LLM is only invoked once at the end to analyse the completed results.
- **Workflow failures are non-crashing**. All workflow runners catch exceptions per-step and append them to `bugs_found` or `findings`. The runner always returns a valid `WorkflowResult`. Only critical setup failures (e.g., no backtest `session_id`) trigger an early return with `status="fail"`.
- **`platform_root` is computed**. `AgentConfig.platform_root` is a `@computed_field` that returns `Path(__file__).parent.parent.resolve()`. It is the repo root (parent of `agent/`). This is used as the MCP server subprocess `cwd`.
- **Report files accumulate in `agent/reports/`**. The directory is `.gitignore`d. Each run appends timestamped files; old reports are not cleaned up automatically.
- **Model files are checksum-verified before loading**. `agent/strategies/checksum.py` provides `save_checksum()` / `verify_checksum()` utilities that write and check SHA-256 `.sha256` sidecar files. `verify_checksum()` raises `SecurityError` on digest mismatch. Missing sidecars produce a WARNING but do not block loading (backwards compatibility). Call `save_checksum()` immediately after saving any `.zip` or `.joblib` model file.
- **No `--api-key` CLI argument in strategy scripts**. API keys are read from `agent/.env` via `AgentConfig` (pydantic-settings) — they are never passed as command-line arguments, which would expose secrets in shell history and process listings.

## Sub-CLAUDE.md Index

Each subdirectory has its own `CLAUDE.md` with full details. Read the local file before working in that folder.

| Path | Description |
|------|-------------|
| `agent/models/CLAUDE.md` | All 6 Pydantic output models — fields, constraints, frozen pattern, gotchas |
| `agent/tools/CLAUDE.md` | Four integration layers — SDK tools (7), MCP server factory, REST tools (11), agent tools (5) |
| `agent/prompts/CLAUDE.md` | `SYSTEM_PROMPT` content summary and `load_skill_context` disk/REST fallback |
| `agent/workflows/CLAUDE.md` | Four workflow runners — step tables, LLM usage, status logic, gotchas |
| `agent/tests/CLAUDE.md` | 117 unit tests — mock patterns, test counts per file, running instructions |
| `agent/strategies/CLAUDE.md` | 5-strategy system — RL, evolutionary, regime, risk, ensemble; file inventory, CLI commands, dependencies, checksum security |
| `agent/conversation/CLAUDE.md` | Session management, message history, LLM context assembly, intent routing |
| `agent/memory/CLAUDE.md` | Memory store (abstract + Postgres + Redis), scored retrieval, working memory |
| `agent/permissions/CLAUDE.md` | Roles, capabilities, budget limits, enforcement with audit logging |
| `agent/trading/CLAUDE.md` | Trading loop, signal generator, executor, position monitor, journal, strategy manager, A/B testing |

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
- `2026-03-20` — Added Sub-CLAUDE.md Index with references to all 5 sub-module files.
- `2026-03-20` — Added `strategies/` directory to Directory Structure. Added strategy-specific optional dependencies table. Added `agent/strategies/CLAUDE.md` to Sub-CLAUDE.md Index.
- `2026-03-20` — Added Docker section (Dockerfile + docker-compose `agent` profile). Updated `[ml]` and `[all]` optional dependency tables. Added checksum security gotcha (`agent/strategies/checksum.py`). Added no-CLI-API-key gotcha. Updated total test count to 901.
- `2026-03-21` — Added `conversation/`, `memory/`, `permissions/`, `trading/` packages to Directory Structure. Updated `tools/` entry for new `agent_tools.py`. Added 4 new entries to Sub-CLAUDE.md Index.
- `2026-03-21` — Agent Logging System (34 tasks, 5 phases): added `logging.py`, `logging_middleware.py`, `logging_writer.py`, `metrics.py` to Directory Structure. Added 3 new test files (66 tests). Added `prometheus-client` dependency. Updated test count to 967.
- `2026-03-22` — ALL 37/37 Trading Agent Master Plan tasks complete. Added `drift.py` (DriftDetector, Page-Hinkley), `retrain.py` (RetrainOrchestrator, 4 schedules, A/B gate, 57 tests), `walk_forward.py` (WFE, 94 tests). Added `circuit_breaker.py` (56 tests), `attribution.py` (45 tests), `recovery.py` (53 tests) to strategies. Added `ws_manager.py` (46 tests), `pair_selector.py` (42 tests) to trading. Updated directory structure. Total agent tests: 2200+.
- `2026-03-22` — Tasks 21-37 (13 tasks, 289 new tests): RecoveryManager (53 tests), security review PASS, get_ticker/get_pnl tools + volume confirmation filter (35 tests), PairSelector (42 tests), WSManager (46 tests), settle_agent_decisions Celery task (16 tests), memory-driven learning loop (29 tests), 5 new REST tools (24 tests). Total: 1689+.
- `2026-03-22` — Phase 1 branch + Phase 2 independent: 361 new tests across strategy submodules. Updated test count to 1400+.
- `2026-03-22` — Phase 0 Group A: added `server_handlers.py` to Directory Structure; updated `server.py` and `logging_middleware.py` entries. Added `test_server_writer_wiring.py` (20 tests) + `test_server_handlers.py` (54 tests). Updated test count to 1041+.
