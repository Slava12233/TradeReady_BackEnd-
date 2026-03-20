# Backtesting Engine

<!-- last-updated: 2026-03-19 -->

> Historical market data replay engine that lets AI agents test trading strategies against real Binance price data in an isolated, in-memory sandbox.

## What This Module Does

The backtesting module provides a complete simulation environment for replaying historical market data and executing trades without touching live systems. An AI agent creates a session (date range, balance, pairs), then drives the simulation step-by-step via the REST API -- reading prices, placing orders, and observing results. The engine enforces strict look-ahead bias prevention (agents can never see future prices), applies realistic fees and slippage, tracks equity over time, and computes performance metrics on completion.

The entire execution state lives in memory during a run (no Redis, no live DB writes per step). Results are persisted to the database only on completion or cancellation.

## Key Files

| File | Purpose |
|------|---------|
| `engine.py` | **BacktestEngine** -- singleton orchestrator managing the full session lifecycle: create, start, step, step_batch, complete, cancel. Holds active sessions in `_active` dict keyed by session_id. |
| `sandbox.py` | **BacktestSandbox** -- in-memory exchange replica with balances, positions, orders, trades, and snapshots. Handles market/limit/stop-loss/take-profit orders with fee and slippage logic identical to the live engine. |
| `time_simulator.py` | **TimeSimulator** -- virtual UTC clock that advances by a fixed interval (default 60s). Tracks step count, progress percentage, and clamps to end_time. |
| `data_replayer.py` | **DataReplayer** -- loads historical prices from TimescaleDB (`candles_1m` UNION `candles_backfill`). Supports bulk preloading into an in-memory dict for zero per-step DB queries. |
| `results.py` | Thin adapter layer: converts sandbox trades/snapshots into unified metric inputs, delegates to `src.metrics.calculator`, and adds backtest-specific fields (avg trade duration). Also computes per-pair stats. |
| `__init__.py` | Re-exports `BacktestEngine`, `TimeSimulator`, `DataReplayer`, `BacktestSandbox`. |

## Architecture & Patterns

### Session Lifecycle
```
create_session() -> start() -> step()/step_batch() [loop] -> complete()/cancel()
```

- **create_session**: Validates data availability and time range against DB, writes a `backtest_sessions` row with status `"created"`.
- **start**: Loads session from DB, creates `TimeSimulator` + `BacktestSandbox` + `DataReplayer`, bulk-preloads all price data via `preload_range()`, captures initial snapshot, sets status to `"running"`.
- **step**: Advances the virtual clock one interval, loads prices from cache, checks pending orders against new prices, captures equity snapshots periodically (every 60 steps, or on fills, or on last step), writes DB progress every 500 steps. Auto-calls `complete()` on the last step.
- **complete**: Closes all open positions at current prices, captures final snapshot, computes metrics via unified calculator, bulk-inserts all trades and snapshots to DB, removes session from `_active`.
- **cancel**: Saves partial results without closing positions, marks status `"cancelled"`.

### In-Memory State
Each active session is held in an `_ActiveSession` dataclass containing the simulator, sandbox, replayer, current prices, and wall-clock start time. The `_active` dict is the single source of truth for running backtests -- if the server restarts, these sessions are lost (orphan detection in the API layer marks them as `"failed"`).

### Singleton Engine
`BacktestEngine` is instantiated once at module level (`_backtest_engine_instance` in `src/dependencies.py`) and shared across all requests. The `session_factory` passed to its constructor is used for creating new DB sessions when needed.

### Look-Ahead Bias Prevention
`DataReplayer` enforces `WHERE bucket <= virtual_clock` on every query. After `preload_range()`, the in-memory cache uses `bisect_right()` to find the nearest bucket at or before the requested timestamp. The agent can never access future prices.

### Bulk Preload Optimization
`DataReplayer.preload_range()` executes a single SQL query that UNIONs `candles_1m` and `candles_backfill` for the full date range, loading all `(bucket, symbol, close)` tuples into `_price_cache`. Subsequent `load_prices()` calls do an O(log n) bisect lookup with zero DB round-trips.

### Risk Limits
`BacktestSandbox` accepts an optional `risk_limits` dict (loaded from the agent's `risk_profile` in the DB). Three checks run on every order placement:
- `max_order_size_pct` -- rejects orders exceeding N% of equity
- `max_position_size_pct` -- rejects buys that would make a position exceed N% of equity
- `daily_loss_limit_pct` -- halts trading when daily realized losses exceed N% of starting balance

### Fee & Slippage Model
- Fee: 0.1% of quote amount (`_FEE_FRACTION = 0.001`), matching the live engine
- Slippage: directional adjustment to execution price, clamped between 0.01% and 10% (`_MIN_SLIPPAGE` / `_MAX_SLIPPAGE`), computed as `slippage_factor * 0.001`
- All arithmetic uses `Decimal` with explicit quantization (8 decimal places for prices/quantities, 2 for percentages)

## Public API / Interfaces

### BacktestEngine (engine.py)
```python
class BacktestEngine:
    async def create_session(account_id, config: BacktestConfig, db) -> BacktestSessionModel
    async def start(session_id: str, db) -> None
    async def step(session_id: str, db) -> StepResult
    async def step_batch(session_id: str, steps: int, db) -> StepResult
    async def complete(session_id: str, db) -> BacktestResult
    async def cancel(session_id: str, db) -> BacktestResult
    async def execute_order(session_id, symbol, side, order_type, quantity, price) -> OrderResult
    async def cancel_order(session_id, order_id) -> bool
    async def get_price(session_id, symbol) -> PriceAtTime
    async def get_candles(session_id, symbol, interval, limit) -> list[Candle]
    async def get_balance(session_id) -> list[Any]
    async def get_positions(session_id) -> list[Any]
    async def get_portfolio(session_id) -> PortfolioSummary
    def is_active(session_id) -> bool
```

### BacktestSandbox (sandbox.py)
```python
class BacktestSandbox:
    def place_order(symbol, side, order_type, quantity, price, current_prices, virtual_time) -> OrderResult
    def cancel_order(order_id) -> bool
    def check_pending_orders(current_prices, virtual_time) -> list[OrderResult]
    def get_balance() -> list[SandboxBalance]
    def get_positions() -> list[SandboxPosition]
    def get_portfolio(current_prices) -> PortfolioSummary
    def get_orders(status=None) -> list[SandboxOrder]
    def get_trades() -> list[SandboxTrade]
    def capture_snapshot(current_prices, virtual_time) -> SandboxSnapshot
    def close_all_positions(current_prices, virtual_time) -> list[SandboxTrade]
    def export_results() -> dict
    # Properties: total_trades, total_fees, realized_pnl, snapshots, trades
```

### TimeSimulator (time_simulator.py)
```python
class TimeSimulator:
    def step() -> datetime          # Advance one interval, returns new time
    def step_batch(n: int) -> datetime  # Advance up to n intervals
    # Properties: current_time, start_time, end_time, interval_seconds,
    #             current_step, total_steps, is_complete, progress_pct,
    #             elapsed_simulated, remaining_steps
```

### DataReplayer (data_replayer.py)
```python
class DataReplayer:
    async def preload_range(start_time, end_time) -> int  # Returns data point count
    async def load_prices(timestamp) -> dict[str, Decimal]
    async def load_candles(symbol, end_time, interval, limit) -> list[Candle]
    async def load_ticker_24h(symbol, timestamp) -> TickerData | None
    async def get_data_range() -> DataRange | None
    async def get_available_pairs(timestamp) -> list[str]
```

### Key Data Classes
- `BacktestConfig` -- session configuration (start/end time, balance, pairs, interval, strategy_label, agent_id)
- `StepResult` -- returned by step/step_batch (virtual_time, prices, filled orders, portfolio, progress)
- `BacktestResult` -- returned by complete/cancel (final equity, ROI, metrics, per-pair stats)
- `BacktestMetrics` -- Sharpe, Sortino, max drawdown, win rate, profit factor, etc.
- `PairStats` -- per-symbol trade count, win rate, net PnL, volume
- `SandboxTrade`, `SandboxSnapshot`, `SandboxOrder`, `SandboxPosition`, `SandboxBalance` -- in-memory state types
- `Candle`, `TickerData`, `DataRange` -- price data containers

## Dependencies

**Internal:**
- `src.metrics.calculator` -- `calculate_unified_metrics()`, `UnifiedMetrics` (shared with battle system)
- `src.metrics.adapters` -- `from_sandbox_trades()`, `from_sandbox_snapshots()` (type converters)
- `src.database.models` -- `BacktestSession`, `BacktestTrade`, `BacktestSnapshot`, `Agent`
- `src.utils.exceptions` -- `BacktestNotFoundError`, `BacktestInvalidStateError`, `BacktestNoDataError`, `InsufficientBalanceError`

**External:**
- `sqlalchemy.ext.asyncio` -- async DB sessions for DataReplayer queries and result persistence
- `structlog` -- structured logging in engine and data_replayer
- `decimal.Decimal` -- all monetary arithmetic (never float)

**Not used (by design):**
- No Redis -- all prices served from in-memory cache after preload
- No Celery -- stepping is synchronous within the async request
- No Binance WS -- historical data only, from TimescaleDB

## Common Tasks

**Adding a new order type:** Modify `BacktestSandbox.place_order()` routing logic and add trigger conditions in `check_pending_orders()`. Both methods use the same `_execute_market_order()` for fills.

**Changing snapshot frequency:** Edit the modulo check in `BacktestEngine.step()` (currently `step_num % 60 == 0`). Lower values increase memory usage.

**Changing DB write frequency:** Edit the modulo check in `BacktestEngine.step()` (currently `step_num % 500 == 0`). Lower values increase DB I/O.

**Adding a new risk limit:** Add the check to `BacktestSandbox._check_risk_limits()`, reading the key from `self._risk_limits`. The agent's `risk_profile` JSON in the DB must include the new key.

**Adding a new metric:** Add it to `src/metrics/calculator.py` (shared), then map it in `results.py::_unified_to_backtest_metrics()` and add the field to `BacktestMetrics`.

**Testing:** Unit tests in `tests/unit/test_backtest_engine.py`, `test_sandbox_risk_limits.py`, `test_unified_metrics.py`. Integration tests in `tests/integration/test_backtest_e2e.py`, `test_no_lookahead.py`, `test_backtest_api.py`.

## Gotchas & Pitfalls

- **Orphan sessions:** If the server crashes mid-backtest, the in-memory `_active` dict is lost but the DB row stays `"running"`. The API layer detects this mismatch and auto-marks orphans as `"failed"`. Do not rely on DB status alone to determine if a session is truly running.

- **`_price_cache` overwrites:** When `candles_1m` and `candles_backfill` both have data for the same `(bucket, symbol)`, the last writer wins in the cache. This is intentional -- we just need *some* price at each timestamp.

- **Auto-complete removes session from `_active`:** After `step()` auto-calls `complete()` on the last step, the session is popped from `_active`. Any subsequent call with that session_id will raise `BacktestNotFoundError`. The `step_batch()` method handles this by checking `session_id not in self._active` before each iteration.

- **Frozen dataclasses for orders:** `SandboxOrder` is frozen, so status updates require creating a new instance and replacing it in the list by index. This is deliberate for immutability but means order updates do a linear scan of `_orders`.

- **Base asset extraction:** The sandbox derives the base asset by stripping `"USDT"` from the symbol string (`symbol.replace("USDT", "")`). This breaks for symbols where `USDT` appears in the base asset name (edge case, but worth knowing).

- **TimeSimulator raises `StopIteration`:** Calling `step()` after completion raises `StopIteration`, not a custom exception. The engine checks `is_complete` before stepping to avoid this.

- **`Decimal` everywhere:** All prices, quantities, balances, and fees use `Decimal`. Mixing in `float` will cause type errors or precision loss. Use `Decimal(str(value))` when converting from DB rows.

- **DB session lifetime:** The `DataReplayer` holds a reference to the SQLAlchemy session passed at construction. If that session is closed before `preload_range()` or `load_candles()` is called, queries will fail. The engine creates the replayer during `start()` using the request's DB session.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
- `2026-03-18` -- Added `exchange` field to `BacktestConfig` and `BacktestCreateRequest`. `DataReplayer` accepts `exchange` param (data filtering pending DB migration — logs warning for non-Binance). Fixed backtest metrics returning None: changed `db.flush()` to `db.commit()` in `_persist_results()` so results are visible to concurrent GET requests.
