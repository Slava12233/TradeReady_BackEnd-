# Agents + Backtesting + Battles Integration — Task Breakdown

> **Created:** 2026-03-17
> **Source:** `development/agents-backtesting-battles-research.md`
> **Branch:** V.0.0.2
> **Total Phases:** 6 | **Total Tasks:** 42

---

## How to Read This File

- **Status:** `[ ]` = not started, `[~]` = in progress, `[x]` = done, `[!]` = blocked
- **Priority:** P0 = must-do first, P1 = important, P2 = nice-to-have
- **Deps:** tasks that must be completed before this one can start
- Each task lists the exact files to create or modify

---

## Phase 1 — Agent-Scoped Backtesting (P0, FOUNDATION)

> **Why:** Backtesting uses legacy `account_id` scoping while live trading enforces `agent_id NOT NULL`.
> Agents cannot own their own backtests. This blocks all downstream improvements.
> **Depends on:** Nothing — this is the foundation.

### 1.1 Database Model

- [x] **T-1.1.1** — Add `agent_id` column to `BacktestSession` model
  - **File:** `src/database/models.py`
  - Add `agent_id: Mapped[UUID | None]` as nullable FK to `agents.id` (ondelete CASCADE)
  - Add `agent: Mapped[Agent | None] = relationship("Agent")`
  - Add `Index("idx_bt_sessions_agent", "agent_id")`
  - Add `Index("idx_bt_sessions_agent_status", "agent_id", "status")`
  - No changes needed to `BacktestTrade` or `BacktestSnapshot` (scoped via session_id FK)

### 1.2 Migration

- [x] **T-1.2.1** — Create Alembic migration: add nullable `agent_id` to `backtest_sessions`
  - **File:** `alembic/versions/013_add_agent_id_to_backtest_sessions.py`
  - Add nullable `agent_id UUID` column with FK constraint
  - Add indexes: `idx_bt_sessions_agent`, `idx_bt_sessions_agent_status`
  - Backfill strategy: for each existing session, assign the first agent of the owning account
  - Follow pattern from migration 008 (add nullable) → later 009 (enforce NOT NULL)
  - **Deps:** T-1.1.1

- [x] **T-1.2.2** — Create backfill script for existing backtest sessions
  - **File:** `scripts/backfill_backtest_agent_ids.py`
  - For each `backtest_session` row where `agent_id IS NULL`:
    - Look up first agent for `account_id` (ORDER BY created_at ASC LIMIT 1)
    - Set `agent_id` to that agent's UUID
  - Log warnings for sessions with no matching agent
  - **Deps:** T-1.2.1

- [x] **T-1.2.3** — Create follow-up migration: enforce `agent_id NOT NULL`
  - **File:** `alembic/versions/014_enforce_backtest_agent_id_not_null.py`
  - ALTER COLUMN `agent_id` SET NOT NULL
  - Only run after backfill script has been verified
  - **Deps:** T-1.2.2

### 1.3 Repository

- [x] **T-1.3.1** — Add `agent_id` filtering to `BacktestRepository`
  - **File:** `src/database/repositories/backtest_repo.py`
  - `list_sessions()` — add optional `agent_id: UUID | None = None` param, filter when provided
  - `get_session()` — add optional `agent_id` for ownership validation
  - `get_best_session()` — add optional `agent_id` filter
  - `get_sessions_for_compare()` — add optional `agent_id` scope
  - When `agent_id` is provided, filter by it; when only `account_id`, show all (cross-agent view)
  - **Deps:** T-1.1.1

### 1.4 Engine

- [x] **T-1.4.1** — Add `agent_id` to `BacktestConfig` and `_ActiveSession`
  - **File:** `src/backtesting/engine.py`
  - `BacktestConfig` dataclass: add `agent_id: UUID | None = None`
  - `_ActiveSession` dataclass: add `agent_id: UUID | None = None`
  - **Deps:** T-1.1.1

- [x] **T-1.4.2** — Update `create_session()` to accept and persist `agent_id`
  - **File:** `src/backtesting/engine.py`
  - Accept `agent_id` from config
  - Set `agent_id` on the `BacktestSession` ORM object before commit
  - **Deps:** T-1.4.1

- [x] **T-1.4.3** — Update `start()` to store `agent_id` in `_ActiveSession`
  - **File:** `src/backtesting/engine.py`
  - Copy `agent_id` from DB session row into the in-memory `_ActiveSession`
  - **Deps:** T-1.4.1

### 1.5 API Routes & Schemas

- [x] **T-1.5.1** — Update backtest schemas with `agent_id` field
  - **File:** `src/api/schemas/backtest.py`
  - `BacktestCreateRequest`: add `agent_id: UUID | None = None`
  - `BacktestListItem`: add `agent_id: str | None = None`
  - `BacktestCreateResponse`: add `agent_id: str | None = None`
  - `BacktestStatusResponse`: add `agent_id: str | None = None`

- [x] **T-1.5.2** — Update backtest API routes to extract and pass agent context
  - **File:** `src/api/routes/backtest.py`
  - Add helper: `_get_agent_id(request: Request) -> UUID | None`
    - Check `request.state.agent` (from API key auth)
    - Or check `X-Agent-Id` header (from JWT auth)
  - `create_backtest()`: pass `agent_id` to engine
  - `list_backtests()`: accept optional `agent_id` query param, pass to repo
  - `get_backtest_status()` / `get_backtest_results()`: include `agent_id` in response
  - **Deps:** T-1.5.1, T-1.3.1, T-1.4.2

### 1.6 Tests

- [x] **T-1.6.1** — Unit tests for agent-scoped backtest repository
  - **File:** `tests/unit/test_backtest_repo_agent_scope.py`
  - Test: `list_sessions` with `agent_id` returns only that agent's sessions
  - Test: `list_sessions` without `agent_id` returns all account sessions
  - Test: `get_best_session` scoped to agent
  - **Deps:** T-1.3.1

- [x] **T-1.6.2** — Integration test: agent-scoped backtest lifecycle
  - **File:** `tests/integration/test_agent_scoped_backtest.py`
  - Create 2 agents under same account
  - Run backtest for agent A, run backtest for agent B
  - Verify agent A's list only shows its backtest
  - Verify account-level list shows both
  - **Deps:** T-1.5.2

---

## Phase 2 — Shared Metrics Pipeline (P1)

> **Why:** `results.py` (backtesting) and `ranking.py` (battles) compute the same metrics with different
> implementations and divergent results. Same agent with same trades gets different Sharpe ratios.
> **Depends on:** Nothing — can run in parallel with Phase 1.

### 2.1 Unified Calculator

- [x] **T-2.1.1** — Create `src/metrics/__init__.py`
  - **File:** `src/metrics/__init__.py`
  - Empty init file for the new metrics package

- [x] **T-2.1.2** — Create unified metrics calculator
  - **File:** `src/metrics/calculator.py`
  - Define dataclasses:
    - `MetricTradeInput(realized_pnl, quote_amount, symbol, timestamp)`
    - `MetricSnapshotInput(timestamp, equity)`
    - `UnifiedMetrics(roi_pct, total_pnl, sharpe_ratio, sortino_ratio, max_drawdown_pct, max_drawdown_duration_days, win_rate, profit_factor, total_trades, trades_per_day, avg_win, avg_loss, best_trade, worst_trade)`
  - Implement `calculate_unified_metrics()`:
    - Accept `snapshot_interval_seconds` param for correct Sharpe annualization
    - Use `Decimal` throughout (not `float`)
    - Include Sortino ratio (missing from battles currently)
    - Include max drawdown duration (missing from battles currently)
    - Consistent null/edge handling (profit_factor = None vs 999.99 — pick one)

### 2.2 Adapters

- [x] **T-2.2.1** — Create adapter functions for data type conversion
  - **File:** `src/metrics/adapters.py`
  - `from_sandbox_trades(list[SandboxTrade]) -> list[MetricTradeInput]`
  - `from_sandbox_snapshots(list[SandboxSnapshot]) -> list[MetricSnapshotInput]`
  - `from_db_trades(Sequence[Trade]) -> list[MetricTradeInput]`
  - `from_battle_snapshots(Sequence[BattleSnapshot]) -> list[MetricSnapshotInput]`
  - Each adapter maps the source type's fields to the normalized input type
  - **Deps:** T-2.1.2

### 2.3 Refactor Consumers

- [x] **T-2.3.1** — Refactor `results.py` to use unified calculator
  - **File:** `src/backtesting/results.py`
  - Keep `calculate_metrics()` as public API (backward compat)
  - Internally: convert inputs via adapters → call `calculate_unified_metrics()` → map to `BacktestMetrics`
  - Keep `calculate_per_pair_stats()` as-is (battle ranking doesn't need it)
  - Keep `generate_equity_curve()` as-is
  - Remove private helpers: `_compute_sharpe`, `_compute_sortino`, `_compute_daily_returns`
  - **Deps:** T-2.2.1

- [x] **T-2.3.2** — Refactor `ranking.py` to use unified calculator
  - **File:** `src/battles/ranking.py`
  - `compute_participant_metrics()`: use adapters → `calculate_unified_metrics()` → map to `ParticipantMetrics`
  - Remove static methods: `calculate_sharpe_ratio`, `calculate_win_rate`, `calculate_profit_factor`, `calculate_max_drawdown`, `calculate_roi`, `calculate_total_pnl`
  - Keep `rank_participants()` as-is
  - Add Sortino ratio and max drawdown duration to `ParticipantMetrics`
  - **Deps:** T-2.2.1

### 2.4 Tests

- [x] **T-2.4.1** — Unit tests for unified metrics calculator
  - **File:** `tests/unit/test_unified_metrics.py`
  - Test: known trades → expected Sharpe, Sortino, win rate, profit factor, drawdown
  - Test: empty trades → safe defaults (no division by zero)
  - Test: single snapshot → Sharpe = None (not enough data)
  - Test: different `snapshot_interval_seconds` → different annualization
  - **Deps:** T-2.1.2

- [x] **T-2.4.2** — Consistency test: same data through both pipelines
  - **File:** `tests/unit/test_metrics_consistency.py`
  - Generate mock trades and snapshots
  - Run through old `results.py` and old `ranking.py` (before refactor, capture expected)
  - Run through unified calculator via both adapters
  - Assert results match (within rounding tolerance)
  - **Deps:** T-2.3.1, T-2.3.2

---

## Phase 3 — Risk Profile Integration in Backtesting (P1)

> **Why:** Agent's `risk_profile` JSONB is enforced during live trading (RiskManager 8-step chain)
> but completely ignored during backtesting. Strategies that pass backtest may fail live.
> **Depends on:** Phase 1 (need agent_id on sessions to load the agent's risk profile).

### 3.1 Sandbox Risk Enforcement

- [x] **T-3.1.1** — Add `risk_limits` parameter to `BacktestSandbox`
  - **File:** `src/backtesting/sandbox.py`
  - Constructor: accept `risk_limits: dict | None = None`
  - Store as `self._risk_limits`
  - Expected keys: `max_position_size_pct`, `max_order_size_pct`, `daily_loss_limit_pct`

- [x] **T-3.1.2** — Implement lightweight risk checks in `place_order()`
  - **File:** `src/backtesting/sandbox.py`
  - Before executing an order, if `self._risk_limits` is set:
    - **Max order size:** reject if `order_value > equity * max_order_size_pct / 100`
    - **Max position size:** reject if resulting position value > `equity * max_position_size_pct / 100`
    - **Daily loss halt:** track daily realized PnL, reject if loss exceeds `daily_loss_limit_pct`
  - Return rejection reason in order result (don't raise — match live behavior)
  - **Deps:** T-3.1.1

### 3.2 Engine Loading

- [x] **T-3.2.1** — Load agent risk profile in `engine.start()`
  - **File:** `src/backtesting/engine.py`
  - In `start()`, if `_ActiveSession.agent_id` is set:
    - Query Agent row from DB
    - Extract `agent.risk_profile` dict
    - Pass as `risk_limits` to `BacktestSandbox()` constructor
  - If no agent_id or no risk_profile → sandbox runs without risk limits (backward compat)
  - **Deps:** T-1.4.3 (Phase 1), T-3.1.1

### 3.3 Tests

- [x] **T-3.3.1** — Unit tests for sandbox risk enforcement
  - **File:** `tests/unit/test_sandbox_risk_limits.py`
  - Test: order rejected when exceeding `max_order_size_pct`
  - Test: order rejected when position would exceed `max_position_size_pct`
  - Test: order rejected after daily loss limit hit
  - Test: orders pass when within all limits
  - Test: no `risk_limits` set → all orders pass (backward compat)
  - **Deps:** T-3.1.2

---

## Phase 4 — Fix SnapshotEngine Unrealized PnL (P1)

> **Why:** `SnapshotEngine._get_unrealized_pnl()` returns hardcoded `Decimal("0")`.
> Battle snapshots, live views, and replay charts show incomplete PnL data.
> **Depends on:** Nothing — independent of other phases.

### 4.1 Inject PriceCache

- [x] **T-4.1.1** — Add `PriceCache` dependency to `SnapshotEngine`
  - **File:** `src/battles/snapshot_engine.py`
  - Change constructor: `def __init__(self, session: AsyncSession, price_cache: PriceCache) -> None`
  - Store `self._price_cache = price_cache`
  - Add import: `from src.cache.price_cache import PriceCache`

- [x] **T-4.1.2** — Update Celery task to pass PriceCache
  - **File:** `src/tasks/battle_snapshots.py`
  - Get Redis connection in task
  - Instantiate `PriceCache(redis)`
  - Pass to `SnapshotEngine(session, price_cache)`
  - **Deps:** T-4.1.1

- [x] **T-4.1.3** — Update dependency injection if `SnapshotEngine` is used via DI
  - **File:** `src/dependencies.py`
  - If there's a `get_snapshot_engine()` dependency, update it to inject PriceCache
  - **Deps:** T-4.1.1

### 4.2 Implement Real Calculation

- [x] **T-4.2.1** — Implement `_get_unrealized_pnl()` with real price lookups
  - **File:** `src/battles/snapshot_engine.py`
  - Query open positions for agent (Position WHERE agent_id = X AND quantity > 0)
  - For each position:
    - Get current price from PriceCache (Redis HGET)
    - Calculate: `(current_price - avg_entry_price) * quantity`
    - Sum all unrealized PnL
  - Handle missing prices gracefully (skip position, log warning)
  - **Deps:** T-4.1.1

- [x] **T-4.2.2** — Add `_get_open_positions()` helper method
  - **File:** `src/battles/snapshot_engine.py`
  - Query: `SELECT * FROM positions WHERE agent_id = X AND quantity > 0`
  - Return list of Position ORM objects
  - **Deps:** T-4.2.1

### 4.3 Tests

- [x] **T-4.3.1** — Unit tests for unrealized PnL calculation
  - **File:** `tests/unit/test_snapshot_engine_pnl.py`
  - Test: agent with 2 open positions → correct unrealized PnL sum
  - Test: agent with no positions → returns 0
  - Test: price not available for a symbol → skip that position, log warning
  - Test: negative unrealized PnL (price below entry)
  - Mock PriceCache and DB session
  - **Deps:** T-4.2.1

---

## Phase 5 — Historical Battles (P1)

> **Why:** Battles only work with live trading. No way to run deterministic, reproducible competitions
> on historical data. Agents can't be fairly compared without real-time waiting.
> **Depends on:** Phases 1 (agent-scoped backtesting), 2 (shared metrics), 3 (risk in sandbox).

### 5.1 Database Model

- [x] **T-5.1.1** — Add `battle_mode` and `backtest_config` to Battle model
  - **File:** `src/database/models.py`
  - `battle_mode: Mapped[str]` — default `"live"`, CHECK constraint `IN ("live", "historical")`
  - `backtest_config: Mapped[dict | None]` — JSONB, nullable
    - Schema: `{ start_time, end_time, candle_interval, pairs: list[str] }`

- [x] **T-5.1.2** — Add `backtest_session_id` to BattleParticipant model
  - **File:** `src/database/models.py`
  - `backtest_session_id: Mapped[UUID | None]` — nullable FK to `backtest_sessions.id`
  - Links participant to their per-agent backtest session (for result persistence)
  - **Deps:** T-5.1.1

### 5.2 Migration

- [x] **T-5.2.1** — Create Alembic migration for historical battle support
  - **File:** `alembic/versions/015_add_historical_battle_support.py`
  - Add `battle_mode VARCHAR(20) DEFAULT 'live' NOT NULL` to `battles`
  - Add CHECK constraint: `battle_mode IN ('live', 'historical')`
  - Add `backtest_config JSONB` (nullable) to `battles`
  - Add `backtest_session_id UUID` (nullable FK) to `battle_participants`
  - All additive — safe for production, no data loss
  - **Deps:** T-5.1.1, T-5.1.2

### 5.3 Historical Battle Engine

- [x] **T-5.3.1** — Create `HistoricalBattleEngine` class
  - **New file:** `src/battles/historical_engine.py`
  - Constructor: `battle_id`, `config` (backtest_config dict), `participant_agent_ids: list[UUID]`
  - Internal state:
    - `_simulator: TimeSimulator` (shared — one clock for all agents)
    - `_replayer: DataReplayer` (shared — one price feed)
    - `_sandboxes: dict[UUID, BacktestSandbox]` (per-agent isolated exchange)
    - `_current_prices: dict[str, Decimal]`

- [x] **T-5.3.2** — Implement `initialize()` method
  - **File:** `src/battles/historical_engine.py`
  - Create shared `TimeSimulator(start_time, end_time, candle_interval)`
  - Create shared `DataReplayer(db)` and call `preload_range()` for all pairs
  - For each participant agent:
    - Load agent from DB (for risk_profile)
    - Create `BacktestSandbox(agent_id, starting_balance, risk_limits=agent.risk_profile)`
  - **Deps:** T-5.3.1

- [x] **T-5.3.3** — Implement `step()` method
  - **File:** `src/battles/historical_engine.py`
  - Advance `TimeSimulator` by one interval
  - Load prices at new `virtual_time` via `DataReplayer`
  - For each sandbox: `sandbox.update_prices(prices)` → check pending orders
  - Capture snapshot for each agent (equity, pnl, trade count)
  - Return step result with per-agent status
  - **Deps:** T-5.3.2

- [x] **T-5.3.4** — Implement `step_batch()` method
  - **File:** `src/battles/historical_engine.py`
  - Call `step()` N times in a loop
  - Return aggregated results
  - **Deps:** T-5.3.3

- [x] **T-5.3.5** — Implement `place_order()` method
  - **File:** `src/battles/historical_engine.py`
  - Accept `agent_id` + order params
  - Delegate to the correct agent's `BacktestSandbox.place_order()`
  - Validate agent is a participant
  - **Deps:** T-5.3.1

- [x] **T-5.3.6** — Implement `complete()` method
  - **File:** `src/battles/historical_engine.py`
  - For each agent sandbox:
    - Collect trades and snapshots
    - Convert via adapters → `calculate_unified_metrics()`
  - Use `RankingCalculator.rank_participants()` by battle's `ranking_metric`
  - Persist:
    - Create `BacktestSession` per agent with results
    - Create `BacktestTrade` rows per agent
    - Create `BattleSnapshot` rows from collected snapshots
    - Update `BattleParticipant` with final_equity, final_rank
    - Update `Battle` status → completed, set ended_at
  - **Deps:** T-5.3.3, T-2.3.2 (Phase 2 — shared metrics)

### 5.4 Module-Level Engine Tracking

- [x] **T-5.4.1** — Add in-memory tracking for active historical battles
  - **File:** `src/battles/historical_engine.py`
  - Module-level dict: `_active_engines: dict[str, HistoricalBattleEngine] = {}`
  - Functions: `get_engine(battle_id)`, `register_engine(battle_id, engine)`, `remove_engine(battle_id)`
  - Mirrors `BacktestEngine._active` pattern
  - **Deps:** T-5.3.1

### 5.5 Service Integration

- [x] **T-5.5.1** — Update `BattleService.create_battle()` for historical mode
  - **File:** `src/battles/service.py`
  - Accept `battle_mode: str = "live"` and `backtest_config: dict | None = None`
  - Validate: if `battle_mode == "historical"` then `backtest_config` is required
  - Validate: `backtest_config` has `start_time`, `end_time`, `candle_interval`
  - Store both on the Battle model
  - **Deps:** T-5.1.1

- [x] **T-5.5.2** — Update `BattleService.start_battle()` to branch on mode
  - **File:** `src/battles/service.py`
  - If `battle.battle_mode == "live"`: existing wallet snapshot/provision flow
  - If `battle.battle_mode == "historical"`:
    - Do NOT snapshot/provision real wallets
    - Instantiate `HistoricalBattleEngine`
    - Call `engine.initialize()`
    - Register in `_active_engines`
  - **Deps:** T-5.3.2, T-5.4.1

- [x] **T-5.5.3** — Update `BattleService.stop_battle()` to branch on mode
  - **File:** `src/battles/service.py`
  - If historical: call `engine.complete()` for rankings and persistence
  - If live: existing ranking + wallet restore flow
  - Remove engine from `_active_engines`
  - **Deps:** T-5.3.6

### 5.6 API Routes & Schemas

- [x] **T-5.6.1** — Update battle schemas for historical mode
  - **File:** `src/api/schemas/battles.py`
  - `BattleCreateRequest`: add `battle_mode: str = "live"`, `backtest_config: HistoricalBattleConfig | None`
  - New schema: `HistoricalBattleConfig(start_time, end_time, candle_interval, pairs)`
  - `BattleResponse`: add `battle_mode`, `backtest_config`
  - New schema: `HistoricalStepResponse` (per-participant virtual_time, equity, trades)

- [x] **T-5.6.2** — Add historical battle API endpoints
  - **File:** `src/api/routes/battles.py`
  - `POST /battles/{id}/step` — advance one step (historical only, reject if live)
  - `POST /battles/{id}/step/batch` — advance N steps (body: `{"steps": N}`)
  - `POST /battles/{id}/trade/order` — place order for agent (body includes `agent_id`)
  - `GET /battles/{id}/market/prices` — current prices at virtual_time
  - **Deps:** T-5.5.2, T-5.6.1

### 5.7 Historical Presets

- [x] **T-5.7.1** — Add historical battle presets
  - **File:** `src/battles/presets.py`
  - `historical_day`: 1-day range, 1m candles, 10,000 USDT, all pairs
  - `historical_week`: 7-day range, 5m candles, 10,000 USDT, all pairs
  - `historical_month`: 30-day range, 1h candles, 10,000 USDT, all pairs
  - Each preset includes `battle_mode: "historical"` and default `backtest_config`
  - Date ranges: relative to current date (e.g., "last 7 days")
  - **Deps:** T-5.1.1

### 5.8 Tests

- [x] **T-5.8.1** — Unit tests for HistoricalBattleEngine
  - **File:** `tests/unit/test_historical_battle_engine.py`
  - Test: initialize creates sandbox per agent
  - Test: step advances all sandboxes simultaneously
  - Test: place_order routes to correct sandbox
  - Test: complete calculates rankings correctly
  - Test: reject step/order for non-participant agent
  - Mock DataReplayer and DB
  - **Deps:** T-5.3.6

- [x] **T-5.8.2** — Integration test: historical battle end-to-end
  - **File:** `tests/integration/test_historical_battle_e2e.py`
  - Create 2 agents
  - Create historical battle with 1-hour range
  - Start battle → step through all candles
  - Place some orders for each agent during stepping
  - Stop battle → verify rankings computed
  - Verify backtest sessions created per agent
  - Verify battle snapshots persisted
  - **Deps:** T-5.6.2

---

## Phase 6 — Battle Replay (P2)

> **Why:** Users should be able to re-run a completed battle on historical data to compare
> what-if scenarios with different agents or config.
> **Depends on:** Phase 5 (historical battles must exist).

### 6.1 Service

- [x] **T-6.1.1** — Implement `BattleService.replay_battle()` method
  - **File:** `src/battles/service.py`
  - Accept: `battle_id`, `account_id`, optional `override_config`, optional `override_agents`
  - Load source battle
  - For live battles: use `started_at → ended_at` as historical time range
  - For historical battles: reuse `backtest_config`
  - Create new Battle in draft state with `battle_mode="historical"`
  - Copy participants (or use override_agents)
  - Return new Battle
  - **Deps:** T-5.5.1

### 6.2 API

- [x] **T-6.2.1** — Add replay endpoint
  - **File:** `src/api/routes/battles.py`
  - `POST /battles/{id}/replay`
  - Body: `{ "override_config": {}, "agent_ids": [] }` (both optional)
  - Returns new battle in draft state
  - **Deps:** T-6.1.1

- [x] **T-6.2.2** — Add replay schema
  - **File:** `src/api/schemas/battles.py`
  - `BattleReplayRequest(override_config: dict | None, agent_ids: list[UUID] | None)`
  - Response: existing `BattleResponse`
  - **Deps:** T-6.2.1

### 6.3 Tests

- [x] **T-6.3.1** — Unit test for replay_battle service method
  - **File:** `tests/unit/test_battle_replay.py`
  - Test: replay a completed live battle → creates historical draft with correct time range
  - Test: replay a historical battle → reuses backtest_config
  - Test: override_agents swaps participants
  - Test: override_config merges with source config
  - Test: cannot replay a draft/active battle (only completed)
  - **Deps:** T-6.1.1

---

## Cross-Phase Checklist

### Before Each Phase

- [ ] Run `ruff check src/ tests/` — zero errors
- [ ] Run `mypy src/` — passes
- [ ] Run `pytest tests/unit/` — all pass
- [ ] Review existing tests for affected areas

### After Each Phase

- [ ] Run full test suite: `pytest --cov=src`
- [ ] Run `ruff check src/ tests/` — zero errors
- [ ] Run `mypy src/` — passes
- [ ] Manual API test via Swagger docs (`/docs`)
- [ ] Commit with format: `feat(scope): description`

### Migration Safety

- [ ] Test migration on dev DB first: `alembic upgrade head`
- [ ] Verify rollback works: `alembic downgrade -1`
- [ ] Run backfill scripts and verify data integrity
- [ ] Only apply NOT NULL enforcement after backfill is verified

---

## Dependency Graph

```
Phase 1 (Agent-Scoped Backtesting)  ──────┐
    │                                      │
    │                                      ▼
    │                              Phase 3 (Risk in Sandbox)
    │                                      │
    ▼                                      │
Phase 2 (Shared Metrics) ─────────────────►│
                                           │
Phase 4 (Fix Unrealized PnL) [independent] │
                                           ▼
                                   Phase 5 (Historical Battles)
                                           │
                                           ▼
                                   Phase 6 (Battle Replay)
```

**Parallelizable:**
- Phase 1 + Phase 2 + Phase 4 can all start simultaneously
- Phase 3 starts after Phase 1 completes
- Phase 5 starts after Phases 1, 2, 3 complete
- Phase 6 starts after Phase 5 completes

---

## File Index

### New Files to Create

| File | Phase | Purpose |
|------|-------|---------|
| `alembic/versions/013_add_agent_id_to_backtest_sessions.py` | 1 | Migration: nullable agent_id |
| `alembic/versions/014_enforce_backtest_agent_id_not_null.py` | 1 | Migration: NOT NULL enforcement |
| `scripts/backfill_backtest_agent_ids.py` | 1 | Backfill script |
| `src/metrics/__init__.py` | 2 | Package init |
| `src/metrics/calculator.py` | 2 | Unified metrics calculator |
| `src/metrics/adapters.py` | 2 | Data type adapters |
| `src/battles/historical_engine.py` | 5 | Historical battle engine |
| `alembic/versions/015_add_historical_battle_support.py` | 5 | Migration: battle_mode + backtest_config |
| `tests/unit/test_backtest_repo_agent_scope.py` | 1 | Tests |
| `tests/unit/test_unified_metrics.py` | 2 | Tests |
| `tests/unit/test_metrics_consistency.py` | 2 | Tests |
| `tests/unit/test_sandbox_risk_limits.py` | 3 | Tests |
| `tests/unit/test_snapshot_engine_pnl.py` | 4 | Tests |
| `tests/unit/test_historical_battle_engine.py` | 5 | Tests |
| `tests/unit/test_battle_replay.py` | 6 | Tests |
| `tests/integration/test_agent_scoped_backtest.py` | 1 | Tests |
| `tests/integration/test_historical_battle_e2e.py` | 5 | Tests |

### Existing Files to Modify

| File | Phases | Changes |
|------|--------|---------|
| `src/database/models.py` | 1, 5 | Add agent_id to BacktestSession; add battle_mode/backtest_config to Battle |
| `src/database/repositories/backtest_repo.py` | 1 | Add agent_id filtering to all methods |
| `src/backtesting/engine.py` | 1, 3 | Add agent_id to config/session; load risk profile |
| `src/backtesting/sandbox.py` | 3 | Add risk_limits parameter; implement risk checks |
| `src/backtesting/results.py` | 2 | Refactor to use unified calculator |
| `src/battles/ranking.py` | 2 | Refactor to use unified calculator |
| `src/battles/service.py` | 5, 6 | Branch on battle_mode; replay_battle() |
| `src/battles/snapshot_engine.py` | 4 | Inject PriceCache; implement unrealized PnL |
| `src/battles/presets.py` | 5 | Add historical presets |
| `src/api/routes/backtest.py` | 1 | Extract agent context; pass agent_id |
| `src/api/routes/battles.py` | 5, 6 | Historical step/order endpoints; replay endpoint |
| `src/api/schemas/backtest.py` | 1 | Add agent_id fields |
| `src/api/schemas/battles.py` | 5, 6 | Add battle_mode, historical config, replay schemas |
| `src/tasks/battle_snapshots.py` | 4 | Pass PriceCache to SnapshotEngine |
| `src/dependencies.py` | 4 | Update SnapshotEngine DI if applicable |
