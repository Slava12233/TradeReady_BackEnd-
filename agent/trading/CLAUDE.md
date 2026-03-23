# agent/trading/ — Trading Loop, Signal Generator, Executor, Monitor, Journal, Strategy Manager, A/B Testing

<!-- last-updated: 2026-03-22 -->

> Autonomous trading system: an observe-analyse-decide-execute-record cycle, multi-strategy signal generation, position monitoring, trade journaling with LLM reflections, performance tracking, and A/B test framework.

## What This Module Does

The `agent/trading/` package implements the full lifecycle of autonomous agent trading. It provides:

- **Autonomous loop** (`TradingLoop`) — the outer control loop that drives a full observe → analyse → decide → check → execute → record → learn cycle, with error backoff and clean shutdown.
- **Signal generation** (`SignalGenerator`, `TradingSignal`) — wraps the `EnsembleRunner` from `agent/strategies/ensemble/` to produce typed, per-symbol signals from concurrent candle fetches.
- **Trade execution** (`TradeExecutor`) — idempotent, retried execution with budget counter updates and observation persistence.
- **Position monitoring** (`PositionMonitor`) — evaluates open positions against stop-loss, take-profit, and max-hold thresholds; dispatches exit orders.
- **Trade journal** (`TradingJournal`) — records every decision with full context, generates LLM-powered reflections using the cheap model, produces daily summaries and weekly reviews, and saves learnings to `MemoryStore`.
- **Strategy performance** (`StrategyManager`) — rolling per-strategy performance windows, degradation detection, adjustment suggestions, and comparison.
- **A/B testing** (`ABTestRunner`, `ABTest`) — structured framework for running two strategy parameter variants in parallel, measuring outcomes, and promoting the winner.

## Key Files

| File | Purpose |
|------|---------|
| `loop.py` | `TradingLoop` — full observe→learn cycle, error backoff, shutdown logic |
| `signal_generator.py` | `SignalGenerator`, `TradingSignal` — ensemble-backed signal production |
| `execution.py` | `TradeExecutor` — idempotent execution with retry, budget, and observation |
| `monitor.py` | `PositionMonitor` — stop-loss / take-profit / age exit evaluation |
| `journal.py` | `TradingJournal` — decision records, LLM reflections, daily/weekly reviews |
| `strategy_manager.py` | `StrategyManager` — rolling windows, degradation, adjustments, comparison |
| `ab_testing.py` | `ABTestRunner`, `ABTest` — A/B test creation, recording, evaluation, promotion |
| `pair_selector.py` | `PairSelector`, `SelectedPairs`, `PairInfo` — dynamic pair selection by volume + momentum |
| `ws_manager.py` | `WSManager` — WebSocket integration: ticker + order channels, price buffer, fill notifications, REST fallback |
| `__init__.py` | Re-exports all public symbols |

## Public API

### `TradingLoop` — `loop.py`

```python
from agent.trading import TradingLoop, LoopStoppedError

loop = TradingLoop(
    config=agent_config,
    signal_generator=signal_gen,
    executor=trade_executor,
    monitor=position_monitor,
    journal=trading_journal,
    strategy_manager=strategy_manager,
    budget_manager=budget_manager,
    permission_enforcer=enforcer,
)
await loop.start()
await loop.tick()   # one full cycle
await loop.stop()
```

**Constructor parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `config` | `AgentConfig` | yes | Agent configuration (symbols, model IDs, base URL) |
| `signal_generator` | `SignalGenerator` | yes | Produces `TradingSignal` per symbol |
| `executor` | `TradeExecutor` | yes | Executes trade decisions |
| `monitor` | `PositionMonitor` | yes | Monitors open positions for exits |
| `journal` | `TradingJournal` | yes | Records decisions and outcomes |
| `strategy_manager` | `StrategyManager` | yes | Tracks per-strategy performance |
| `budget_manager` | `BudgetManager` | yes | Checks budget before execution |
| `permission_enforcer` | `PermissionEnforcer` | yes | Checks capabilities before execution |

**`LoopStoppedError`:** Raised by `tick()` if called after `stop()` has been invoked.

**Cycle phases (in order):**

| Phase | Description |
|-------|-------------|
| Observe | Fetch current prices for all configured symbols |
| Analyse | Call `signal_generator.generate()` to produce `TradingSignal` per symbol |
| Decide | Filter signals by confidence threshold and direction |
| Check | `permission_enforcer.check()` + `budget_manager.check_and_record()` |
| Execute | `executor.execute()` for each approved signal |
| Record | `journal.record_decision()` + `strategy_manager.record_outcome()` |
| Monitor | `monitor.check_positions()` + `monitor.execute_exits()` |
| Learn | `journal.generate_reflection()` for completed trades |

**Error handling:**

- On per-symbol errors, the loop logs the error and continues with the next symbol.
- On consecutive errors exceeding `_MAX_CONSECUTIVE_ERRORS = 5`, the loop pauses for `_ERROR_BACKOFF_SECONDS = 10.0` before resuming.
- `stop()` sets a flag checked at the top of each `tick()` call.

**Default order quantities (configurable via `AgentConfig`):**

| Symbol | Default quantity |
|--------|-----------------|
| `BTCUSDT` | `0.0001` |
| `ETHUSDT` | `0.001` |
| `SOLUSDT` | `0.01` |

---

### `SignalGenerator` and `TradingSignal` — `signal_generator.py`

```python
from agent.trading import SignalGenerator, TradingSignal

generator = SignalGenerator(config=agent_config, sdk_client=exchange_client)
signals: list[TradingSignal] = await generator.generate(symbols=["BTCUSDT", "ETHUSDT"])
```

**Constructor:** `SignalGenerator(config, sdk_client)`

Thin adapter around `EnsembleRunner` from `agent.strategies.ensemble`. Fetches `_CANDLE_LIMIT = 50` one-minute candles per symbol concurrently via `asyncio.gather`, then passes the candle data through the ensemble pipeline.

**`TradingSignal` (Pydantic model):**

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | `str` | Trading pair (e.g. `"BTCUSDT"`) |
| `action` | `str` | `"buy"`, `"sell"`, or `"hold"` |
| `confidence` | `float` | Score in `[0.0, 1.0]` from ensemble combiner |
| `quantity` | `Decimal` | Order quantity derived from default symbol quantities |
| `reasoning` | `str` | Human-readable explanation from ensemble |
| `strategy_weights` | `dict[str, float]` | Per-strategy contribution to the final signal |

**`generate(symbols) -> list[TradingSignal]`**

Runs for all symbols concurrently. Symbols that fail (SDK error, insufficient candle history) are silently skipped — `generate()` always returns a list (possibly empty), never raises.

---

### `TradeExecutor` — `execution.py`

```python
from agent.trading import TradeExecutor

executor = TradeExecutor(
    sdk_client=exchange_client,
    budget_manager=budget_manager,
    session_factory=my_async_sessionmaker,
)
result = await executor.execute(
    agent_id="550e8400-...",
    signal=trading_signal,
)
```

**Constructor:** `TradeExecutor(sdk_client, budget_manager, session_factory)`

Idempotent executor with a per-session in-memory dedup cache keyed by `(symbol, action, hash(quantity))`. If the same trade is submitted twice in one session, the second call returns the cached result without placing a second order.

**`execute(agent_id, signal) -> ExecutionResult`**

1. Checks idempotency cache.
2. Places market order via `sdk_client.place_market_order(symbol, side, quantity)`.
3. On failure, retries once after a short delay.
4. Calls `budget_manager.record_trade()` on success.
5. Persists an observation row to `agent_observations` via the session factory.
6. Returns `ExecutionResult` with `order_id`, `status`, `executed_price`, `executed_quantity`, `fee`, `total_cost`.

On persistent failure (both attempts), returns `ExecutionResult(status="failed", error=str)` rather than raising.

---

### `PositionMonitor` — `monitor.py`

```python
from agent.trading import PositionMonitor

monitor = PositionMonitor(sdk_client=exchange_client)
actions: list[PositionAction] = await monitor.check_positions(agent_id)
results: list[ExecutionResult] = await monitor.execute_exits(agent_id, actions, executor)
```

**Constructor:** `PositionMonitor(sdk_client)`

Evaluates open positions against three thresholds:

| Threshold | Default | Description |
|-----------|---------|-------------|
| Stop-loss | 5% loss | Exit when unrealised PnL % falls below `-0.05` |
| Take-profit | 20% gain | Exit when unrealised PnL % exceeds `+0.20` |
| Max-hold | 24 hours | Exit any position held longer than 24 hours |

**`check_positions(agent_id) -> list[PositionAction]`**

Fetches open positions via `sdk_client.get_positions()`. Returns a list of `PositionAction` objects for each position that breaches any threshold. `PositionAction` contains: `symbol`, `reason` (one of `"stop_loss"`, `"take_profit"`, `"max_hold"`), `current_pnl_pct`, `action` (`"sell"`).

**`execute_exits(agent_id, actions, executor) -> list[ExecutionResult]`**

Calls `executor.execute()` for each `PositionAction`. Returns results for all exits attempted.

---

### `TradingJournal` — `journal.py`

```python
from agent.trading import TradingJournal

journal = TradingJournal(
    config=agent_config,
    session_factory=my_async_sessionmaker,
    memory_store=postgres_memory_store,
)
await journal.record_decision(agent_id, signal, context)
await journal.record_outcome(agent_id, signal, execution_result)
reflection = await journal.generate_reflection(agent_id, trade_id)
summary = await journal.daily_summary(agent_id)
review = await journal.weekly_review(agent_id)
```

**Constructor:** `TradingJournal(config, session_factory, memory_store=None)`

Records every trade decision and outcome to `agent_journal`, generates LLM-powered reflections and summaries, and saves learnings to `MemoryStore`. Uses `config.agent_cheap_model` for all LLM calls to control cost.

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `record_decision(agent_id, signal, context)` | `str` | Persist decision to `agent_journal` (type `"observation"`); returns journal entry ID |
| `record_outcome(agent_id, signal, result)` | `None` | Update journal entry with execution outcome |
| `generate_reflection(agent_id, trade_id)` | `str` | LLM generates a `"reflection"` entry; saves key learning to `MemoryStore` if `memory_store` is set; returns reflection text |
| `daily_summary(agent_id)` | `str` | LLM generates a `"daily_review"` entry covering today's trades; returns summary text |
| `weekly_review(agent_id)` | `str` | LLM generates a `"weekly_review"` entry; returns review text |

All LLM calls use `config.agent_cheap_model` and fall back to plain-text summaries if the LLM call fails. Journal entries are always persisted even if the LLM call fails.

**Journal entry types persisted to `agent_journal`:**

| Type | Generated by |
|------|-------------|
| `"observation"` | `record_decision()` |
| `"reflection"` | `generate_reflection()` |
| `"daily_review"` | `daily_summary()` |
| `"weekly_review"` | `weekly_review()` |

---

### `StrategyManager` — `strategy_manager.py`

```python
from agent.trading import StrategyManager

manager = StrategyManager(
    session_factory=my_async_sessionmaker,
    window_size=20,
)
manager.record_outcome(strategy_name="ensemble_v1", pnl=Decimal("45.20"), win=True)
degraded = manager.detect_degradation(strategy_name="ensemble_v1")
adjustments = manager.suggest_adjustments(strategy_name="ensemble_v1")
comparison = manager.compare_strategies("ensemble_v1", "ensemble_v2")
performance = manager.get_performance(strategy_name="ensemble_v1")
```

**Constructor:** `StrategyManager(session_factory, window_size=20)`

Maintains a rolling `deque` of trade outcomes per strategy. The window size controls how many recent trades are used for degradation detection.

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `record_outcome(strategy_name, pnl, win)` | `None` | Append to the rolling window for the named strategy |
| `detect_degradation(strategy_name)` | `bool` | Returns `True` if win rate in the rolling window has fallen below the historical baseline by a configurable threshold |
| `suggest_adjustments(strategy_name)` | `list[str]` | Returns human-readable suggestion strings based on the current window's patterns |
| `compare_strategies(name_a, name_b)` | `dict` | Side-by-side win rate, average PnL, and Sharpe comparison from rolling windows |
| `get_performance(strategy_name)` | `dict` | Win rate, average PnL, trade count, and last-updated timestamp from the rolling window |

**Persistence:** `StrategyManager` periodically persists period summaries to the `agent_performance` table via the session factory. Summaries are written when `record_outcome()` is called and the window fills (every `window_size` trades).

---

### `ABTestRunner` and `ABTest` — `ab_testing.py`

```python
from agent.trading import ABTestRunner, ABTest
from agent.trading import ABTestError, ABTestNotFoundError, ABTestInactiveError
from agent.trading import DuplicateABTestError, InsufficientDataError

runner = ABTestRunner(
    session_factory=my_async_sessionmaker,
    min_trades=30,
)
test: ABTest = await runner.create(
    agent_id="550e8400-...",
    strategy_name="ensemble",
    variant_a_params={"fast_window": 5, "slow_window": 20},
    variant_b_params={"fast_window": 7, "slow_window": 25},
)
variant = runner.allocate(test.test_id)   # "A" or "B" (round-robin)
await runner.record(test.test_id, variant, pnl=Decimal("12.50"), win=True)
result = await runner.evaluate(test.test_id)   # raises InsufficientDataError if < min_trades
await runner.promote_winner(test.test_id)
```

**Constructor:** `ABTestRunner(session_factory, min_trades=30)`

Manages A/B tests between two strategy parameter variants for the same strategy. Enforces one active test per strategy per agent at a time.

**`ABTest` (state object):**

| Field | Type | Description |
|-------|------|-------------|
| `test_id` | `str` | UUID identifying the test |
| `agent_id` | `str` | Owning agent UUID |
| `strategy_name` | `str` | Strategy being tested |
| `variant_a_params` | `dict` | Parameter set for variant A |
| `variant_b_params` | `dict` | Parameter set for variant B |
| `trades_a` | `list[dict]` | Trade outcomes recorded for variant A |
| `trades_b` | `list[dict]` | Trade outcomes recorded for variant B |
| `status` | `str` | `"active"` or `"completed"` |
| `winner` | `str \| None` | `"A"`, `"B"`, or `None` if not yet evaluated |
| `created_at` | `datetime` | UTC timestamp |

**`ABTestRunner` methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `create(agent_id, strategy_name, variant_a_params, variant_b_params)` | `ABTest` | Create a new test; raises `DuplicateABTestError` if already active |
| `allocate(test_id)` | `"A" \| "B"` | Round-robin allocation; raises `ABTestNotFoundError`, `ABTestInactiveError` |
| `record(test_id, variant, pnl, win)` | `None` | Record one trade outcome; raises `ABTestNotFoundError`, `ABTestInactiveError` |
| `evaluate(test_id)` | `dict` | Compare win rates and average PnL; raises `InsufficientDataError` if `< min_trades` per variant |
| `promote_winner(test_id)` | `str` | Mark test as completed, set `winner`; returns `"A"` or `"B"` |
| `get(test_id)` | `ABTest` | Fetch test state; raises `ABTestNotFoundError` |
| `list_active(agent_id)` | `list[ABTest]` | All active tests for an agent |

**Exceptions:**

| Exception | Raised when |
|-----------|-------------|
| `ABTestError` | Base class for all A/B testing errors |
| `ABTestNotFoundError` | `test_id` does not exist |
| `ABTestInactiveError` | Operation requires `status="active"` but test is completed |
| `DuplicateABTestError` | Creating a second active test for the same `(agent_id, strategy_name)` pair |
| `InsufficientDataError` | `evaluate()` called before `min_trades` recorded per variant |

**Persistence:** Each `ABTest` is persisted as a single `agent_journal` row with `entry_type="insight"` and the full test state serialised in the JSONB `metadata` field. `record()` updates the row in place. This avoids requiring a dedicated A/B test table in the database schema.

---

---

### `PairSelector`, `SelectedPairs`, `PairInfo` — `pair_selector.py`

```python
from agent.trading import PairSelector, SelectedPairs, PairInfo

selector = PairSelector(config=agent_config, rest_client=httpx_client)
pairs: SelectedPairs = await selector.get_active_pairs()
# Feed into signal generator:
signals = await generator.generate(pairs.all_symbols[:20])
```

**Constructor:** `PairSelector(config, rest_client=None, ttl_seconds=3600.0, min_volume_usd=10_000_000, max_spread_pct=0.05, top_n_pairs=30, momentum_n_pairs=10, min_symbols_threshold=5)`

**`SelectedPairs` fields:**

| Field | Type | Description |
|-------|------|-------------|
| `volume_ranked` | `list[str]` | Top-N pairs by 24h USDT quote-volume (descending) |
| `momentum_tier` | `list[str]` | Top-M pairs by `|change_pct|` (big movers, both directions) |
| `all_symbols` | `list[str]` | Union: `volume_ranked` first, then unique `momentum_tier` additions |
| `refreshed_at` | `float` | `time.monotonic()` timestamp of last refresh |
| `total_scanned` | `int` | Symbols considered before filtering |
| `total_passed_filter` | `int` | Symbols that passed volume + spread filters |

**`PairInfo` fields:** `symbol`, `quote_volume` (Decimal), `change_pct` (Decimal), `spread_pct` (Decimal), `close` (Decimal).

**Key methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `get_active_pairs()` | `SelectedPairs` | Return cached result or refresh if stale |
| `invalidate()` | `None` | Force next call to refresh |
| `cached_result` | `SelectedPairs \| None` | Current cache entry without triggering refresh |

**Filter thresholds (configurable at construction):**
- Volume: `≥ $10M` USDT quote-volume per 24h (constant `MIN_QUOTE_VOLUME_USD`)
- Spread: `≤ 5%` synthetic spread (high−low)/close (constant `MAX_SPREAD_PCT`)

**Concurrency:** `asyncio.Lock` ensures only one HTTP refresh runs at a time. Concurrent callers wait and share the refreshed result.

**Fallback:** Returns `config.symbols` when REST client is `None`, the platform has fewer symbols than `min_symbols_threshold`, the network fails, or all pairs are filtered out.

---

## Dependency Direction

```
agent.trading
    │
    ├── agent.strategies.ensemble (SignalGenerator → EnsembleRunner)
    ├── agent.permissions (BudgetManager, PermissionEnforcer)
    ├── agent.memory (TradingJournal → MemoryStore)
    ├── agent.config (AgentConfig)
    ├── src.database.repositories.agent_journal_repo (journal, ab_testing, strategy_manager)
    ├── src.database.repositories.agent_observation_repo (TradeExecutor)
    ├── src.database.repositories.agent_performance_repo (StrategyManager)
    ├── src.database.models (lazy imports throughout)
    └── agentexchange.AsyncAgentExchangeClient (SignalGenerator, TradeExecutor, PositionMonitor)
```

All `src.database` imports are lazy (inside methods) to keep the module importable without a running database.

## Patterns

- **All errors are non-crashing**: Every component catches exceptions internally and either returns a degraded result, logs a warning, or continues with the next iteration. The `TradingLoop` never propagates exceptions from individual trade operations.
- **LLM is optional**: `TradingJournal` methods fall back to plain-text summaries when the LLM call fails or `agent_cheap_model` is not configured. The journal persists regardless.
- **Idempotent execution**: `TradeExecutor` maintains a session-scoped dedup cache. Passing the same `(symbol, action, quantity)` twice returns the cached first result. This guards against duplicate orders from loop restarts.
- **Round-robin A/B allocation**: `ABTestRunner.allocate()` alternates strictly between variants A and B. This ensures balanced sample sizes without requiring a predetermined split.
- **Rolling window, not cumulative**: `StrategyManager` uses `deque(maxlen=window_size)` per strategy. Only the most recent `window_size` trades influence degradation detection. This makes the system responsive to recent regime changes rather than anchored to historical baselines.
- **Cheap model for reflections**: All `TradingJournal` LLM calls use `config.agent_cheap_model` (Gemini Flash by default). This is a deliberate cost optimisation — reflections are generated frequently (after every trade) so they must be cheap.

## Gotchas

- **`TradingLoop.start()` must be called before `tick()`**: The loop initialises internal state during `start()`. Calling `tick()` before `start()` raises a `RuntimeError`.
- **`tick()` after `stop()` raises `LoopStoppedError`**: Check `loop.is_running` before calling `tick()` in external control loops.
- **`PositionMonitor` thresholds are fixed at construction**: Stop-loss (5%), take-profit (20%), and max-hold (24h) defaults cannot be changed after constructing `PositionMonitor`. To use different thresholds, subclass or reconstruct with a custom initialiser.
- **`ABTestRunner.evaluate()` raises, does not return a partial result**: If either variant has fewer than `min_trades` trades, `InsufficientDataError` is raised. Always catch it and continue trading until sufficient data is collected.
- **`TradingJournal` requires `session_factory` for persistence**: Without it, journal entries are generated in memory but not persisted. Pass a `session_factory` in all production deployments.
- **`SignalGenerator` skips symbols silently**: If candle fetch fails for a symbol (SDK error, no data), that symbol produces no signal. This is intentional — partial results are better than all-or-nothing failures. Check the returned list length if you need guaranteed coverage.
- **`StrategyManager.detect_degradation()` is stateless between process restarts**: The rolling `deque` lives in memory. After a restart, degradation detection resumes from an empty window. The degradation threshold will not fire until `window_size` new trades have been recorded.
- **A/B test state lives in `agent_journal`**: There is no dedicated A/B test table. If you need to query tests directly in SQL, filter `agent_journal` by `entry_type = 'insight'` and parse the JSONB metadata.

## Recent Changes

- `2026-03-21` — Initial CLAUDE.md created.
- `2026-03-21` — Logging instrumentation added: `loop.py` generates a fresh `trace_id` per tick and passes it to `LogBatchWriter` for async DB persistence; includes EMA-based anomaly detection on tick latency. `journal.py` wraps every LLM call with `log_api_call()` context manager from `agent.logging_middleware`. `journal.py` and `loop.py` both call `configure_agent_logging()` at startup.
- `2026-03-22` — Task 24: `SignalGenerator.generate()` now applies two post-ensemble filters: (1) confidence threshold filter (configurable via `AgentConfig.signal_confidence_threshold`, default 0.55) downgrades sub-threshold signals to HOLD; (2) volume confirmation filter (`_apply_volume_filter`) rejects signals when the latest candle volume is < 50% of the 20-period rolling average. New constants: `_VOLUME_LOOKBACK = 20`, `_VOLUME_MIN_RATIO = 0.5`. New methods: `_apply_volume_filter()`, `_compute_volume_ratio()`.
- `2026-03-22` — Task 27: Added `ws_manager.py` with `WSManager` class. `TradingLoop` accepts optional `ws_manager` kwarg; `_observe()` merges buffered WS prices into `portfolio_state["ws_prices"]`; `tick()` checks for order-fill events via `wait_for_order_fill(timeout=0.05)`; `stop()` disconnects ws_manager. `AgentServer` initialises `WSManager` in `_init_ws_manager()` during `start()` and exposes it via `ws_manager` property; `_shutdown()` disconnects it.
- `2026-03-22` — Task 26: Added `pair_selector.py` with `PairSelector`, `SelectedPairs`, `PairInfo`. Fetches all symbols via `GET /api/v1/market/prices`, then batch-fetches 24h tickers via `GET /api/v1/market/tickers` (batches of 100). Filters by `MIN_QUOTE_VOLUME_USD=$10M` and `MAX_SPREAD_PCT=5%`. Ranks top 30 by USDT volume and top 10 by `|change_pct|` (momentum tier). Results cached with configurable TTL (default 1h). `asyncio.Lock` ensures only one refresh runs concurrently. Degrades gracefully to `config.symbols` fallback on network errors. 42 new tests.
- `2026-03-22` — Task 32: Memory-driven learning loop. `TradingJournal` gained two new public methods: `save_episodic_memory()` (encodes entry/exit price, PnL, regime, reasoning into an EPISODIC memory) and `save_procedural_memory()` (encodes rule-pattern learnings as PROCEDURAL, with dedup via `search()` + `reinforce()` before creating a new record). `generate_reflection()` now calls `save_episodic_memory()` on every completed trade in addition to `_save_learnings_to_memory()`. `_save_learnings_to_memory()` updated: PROCEDURAL-keyword learnings with a known regime are routed through `save_procedural_memory()` for automatic reinforcement; others remain EPISODIC. 29 new tests in `agent/tests/test_memory_learning_loop.py`.
