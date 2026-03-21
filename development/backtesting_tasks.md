---
type: task-list
title: "Backtesting Engine — Complete Task Breakdown"
status: archived
phase: backtesting
tags:
  - task
  - backtesting
---

# Backtesting Engine — Complete Task Breakdown

> **Last Updated:** 2026-03-09
> **Source:** `backtestingdevelopment.md` v2
> **Status Legend:** `[ ]` To Do · `[~]` In Progress · `[x]` Done · `[-]` Blocked · `[!]` Needs Review
> **Core Principle:** Agent does everything. UI is read-only.

---

## Phase BT-1: Backend Engine (Weeks 1–2)

**Goal:** Agent can create, run, and get results from backtests via API
**Deliverable:** Full backtest lifecycle working through REST endpoints

---

### BT-1.1 Database Schema & Migrations

- [x] **BT-1.1.1** Create Alembic migration for `backtest_sessions` table
  - Columns: id (UUID PK), account_id (FK → accounts), strategy_label, status (created/running/paused/completed/failed/cancelled), candle_interval, start_time, end_time, starting_balance, pairs (JSONB), virtual_clock, current_step, total_steps, progress_pct, final_equity, total_pnl, roi_pct, total_trades, total_fees, metrics (JSONB), started_at, completed_at, duration_real_sec, created_at, updated_at
  - Indexes: account_id, (account_id, status), (account_id, strategy_label), (account_id, roi_pct DESC)
  - All monetary columns: `NUMERIC(20,8)`

- [x] **BT-1.1.2** Create `backtest_trades` table in same migration
  - Columns: id (UUID PK), session_id (FK → backtest_sessions ON DELETE CASCADE), symbol, side, type, quantity, price, quote_amount, fee, slippage_pct, realized_pnl, simulated_at
  - Indexes: session_id, (session_id, simulated_at)

- [x] **BT-1.1.3** Create `backtest_snapshots` table (TimescaleDB hypertable)
  - Columns: id (UUID PK), session_id (FK → backtest_sessions ON DELETE CASCADE), simulated_at, total_equity, available_cash, position_value, unrealized_pnl, realized_pnl, positions (JSONB)
  - Hypertable: `create_hypertable('backtest_snapshots', 'simulated_at', chunk_time_interval => INTERVAL '1 day')`
  - Index: (session_id, simulated_at)

- [x] **BT-1.1.4** Add columns to existing `accounts` table
  - `current_mode VARCHAR(10) DEFAULT 'live'`
  - `active_strategy_label VARCHAR(100)`

- [x] **BT-1.1.5** Create ORM models in `src/database/models.py`
  - `BacktestSession`, `BacktestTrade`, `BacktestSnapshot` SQLAlchemy models
  - Relationships: session → trades, session → snapshots, account → sessions

---

### BT-1.2 Core Engine Components

- [x] **BT-1.2.1** Create `src/backtesting/__init__.py`
  - Export public classes: BacktestEngine, TimeSimulator, DataReplayer, BacktestSandbox

- [x] **BT-1.2.2** Implement `src/backtesting/time_simulator.py` — TimeSimulator
  - `__init__(self, start_time, end_time, interval_seconds=60)`
  - Properties: `current_time`, `is_complete`, `progress_pct`, `elapsed_simulated`, `remaining_steps`
  - Methods: `step() → datetime`, `step_batch(n) → datetime`
  - Step must not advance past end_time
  - All times in UTC

- [x] **BT-1.2.3** Implement `src/backtesting/data_replayer.py` — DataReplayer
  - `__init__(self, db_pool, pairs: list[str] | None)`
  - `async load_prices(self, timestamp) → dict[str, Decimal]` — close prices at timestamp
  - `async load_candles(self, symbol, end_time, interval, limit) → list[Candle]` — candles BEFORE end_time only
  - `async load_ticker_24h(self, symbol, timestamp) → TickerData` — 24h stats ending at timestamp
  - `async get_data_range() → DataRange` — earliest/latest timestamps with data
  - `async get_available_pairs(self, timestamp) → list[str]`
  - **CRITICAL:** Every query MUST filter `WHERE bucket <= virtual_clock` (look-ahead bias prevention)

- [x] **BT-1.2.4** Implement `src/backtesting/sandbox.py` — BacktestSandbox
  - `__init__(self, session_id, starting_balance, slippage_calculator)`
  - In-memory state: balances dict, positions dict, orders list, trades list, snapshots list
  - `place_order(order, current_prices) → OrderResult`
  - `cancel_order(order_id) → bool`
  - `check_pending_orders(current_prices) → list[OrderResult]` — trigger limit/stop orders
  - `get_balance() → list[Balance]`
  - `get_positions() → list[Position]`
  - `get_portfolio(current_prices) → PortfolioSummary`
  - `get_orders(filters) → list[Order]`
  - `get_trades(filters) → list[Trade]`
  - `capture_snapshot(current_prices, virtual_time) → Snapshot`
  - `close_all_positions(current_prices) → list[Trade]`
  - `export_results() → dict` — full state for DB persistence
  - Must use identical business logic to live OrderEngine (fees, slippage)
  - All monetary values as `Decimal`

- [x] **BT-1.2.5** Implement `src/backtesting/engine.py` — BacktestEngine (orchestrator)
  - `async create_session(self, account_id, config: BacktestConfig) → BacktestSession`
  - `async start(self, session_id) → None` — initialize sandbox + time simulator
  - `async step(self, session_id) → StepResult` — advance one candle, return prices + fills + portfolio + progress
  - `async step_batch(self, session_id, steps: int) → BatchStepResult` — advance N candles
  - `async get_price(self, session_id, symbol) → PriceAtTime`
  - `async get_candles(self, session_id, symbol, interval, limit) → list[Candle]`
  - `async execute_order(self, session_id, order: OrderRequest) → OrderResult`
  - `async cancel_order(self, session_id, order_id) → bool`
  - `async get_balance(self, session_id) → list[Balance]`
  - `async get_positions(self, session_id) → list[Position]`
  - `async get_portfolio(self, session_id) → PortfolioSummary`
  - `async complete(self, session_id) → BacktestResult` — persist all results to DB
  - `async cancel(self, session_id) → BacktestResult` — save partial results
  - Must manage active sessions in-memory (dict of session_id → sandbox+simulator)
  - Must validate: time range has data, balance is reasonable, account exists

- [x] **BT-1.2.6** Implement `src/backtesting/results.py` — metrics calculator
  - `calculate_metrics(trades, snapshots, starting_balance, duration_days) → BacktestMetrics`
  - Metrics: sharpe_ratio, sortino_ratio, max_drawdown_pct, max_drawdown_duration_days, win_rate, profit_factor, avg_win, avg_loss, best_trade, worst_trade, avg_trade_duration_minutes, trades_per_day
  - `calculate_per_pair_stats(trades) → list[PairStats]`
  - `generate_equity_curve(snapshots, interval) → list[EquityPoint]`
  - All calculations use `Decimal` for precision

---

### BT-1.3 Database Repository

- [x] **BT-1.3.1** Implement `src/database/repositories/backtest_repo.py`
  - `async create_session(session: BacktestSession) → BacktestSession`
  - `async get_session(session_id, account_id) → BacktestSession | None`
  - `async update_session(session_id, **fields) → None`
  - `async list_sessions(account_id, strategy_label?, status?, sort_by?, limit?) → list[BacktestSession]`
  - `async save_trades(session_id, trades: list[BacktestTrade]) → None` (bulk insert)
  - `async save_snapshots(session_id, snapshots: list[BacktestSnapshot]) → None` (bulk insert)
  - `async get_trades(session_id, limit?, offset?) → list[BacktestTrade]`
  - `async get_snapshots(session_id) → list[BacktestSnapshot]`
  - `async get_best_session(account_id, metric, strategy_label?) → BacktestSession | None`
  - `async get_sessions_for_compare(session_ids: list[UUID]) → list[BacktestSession]`
  - `async delete_old_detail_data(days=90) → int` — keep summaries, delete trades/snapshots

---

### BT-1.4 Pydantic Schemas

- [x] **BT-1.4.1** Implement `src/api/schemas/backtest.py`
  - Request models:
    - `BacktestCreateRequest` — start_time, end_time, starting_balance, candle_interval, pairs, strategy_label
    - `BacktestStepBatchRequest` — steps: int
    - `BacktestOrderRequest` — symbol, side, type, quantity (reuse from trading schemas if possible)
    - `ModeSwitchRequest` — mode, strategy_label
  - Response models:
    - `BacktestCreateResponse` — session_id, status, total_steps, estimated_pairs
    - `StepResponse` — virtual_time, step, total_steps, progress_pct, prices, orders_filled, portfolio, is_complete, remaining_steps
    - `BacktestResultsResponse` — session_id, status, config, summary, metrics, by_pair
    - `EquityCurveResponse` — interval, snapshots[]
    - `BacktestListResponse` — backtests[]
    - `BacktestListItem` — session_id, strategy_label, period, status, roi_pct, sharpe_ratio, max_drawdown_pct, total_trades, created_at
    - `BacktestCompareResponse` — comparisons[], best_by_roi, best_by_sharpe, best_by_drawdown, recommendation
    - `BacktestBestResponse` — session_id, strategy_label, metric value
    - `AccountModeResponse` — mode, live_session, active_backtests, total_backtests_completed
    - `DataRangeResponse` — earliest, latest, total_pairs, intervals_available, data_gaps

---

### BT-1.5 API Routes

- [x] **BT-1.5.1** Implement `GET /api/v1/market/data-range` (add to existing market routes)
  - Returns: earliest, latest, total_pairs, intervals_available, data_gaps
  - Agent uses this to know what periods it can backtest

- [x] **BT-1.5.2** Implement `src/api/routes/backtest.py` — backtest lifecycle routes
  - `POST /api/v1/backtest/create` — create session with agent-provided config
  - `POST /api/v1/backtest/{session_id}/start` — initialize sandbox, start session
  - `POST /api/v1/backtest/{session_id}/step` — advance one candle
  - `POST /api/v1/backtest/{session_id}/step/batch` — advance N candles
  - `POST /api/v1/backtest/{session_id}/cancel` — abort early, save partial results

- [x] **BT-1.5.3** Implement backtest-scoped trading routes
  - `POST /api/v1/backtest/{sid}/trade/order` — place order in sandbox
  - `GET  /api/v1/backtest/{sid}/trade/order/{order_id}` — order status
  - `GET  /api/v1/backtest/{sid}/trade/orders` — all orders
  - `GET  /api/v1/backtest/{sid}/trade/orders/open` — pending orders
  - `DELETE /api/v1/backtest/{sid}/trade/order/{order_id}` — cancel order
  - `GET  /api/v1/backtest/{sid}/trade/history` — trade log

- [x] **BT-1.5.4** Implement backtest-scoped market routes
  - `GET /api/v1/backtest/{sid}/market/price/{symbol}` — price at virtual_time
  - `GET /api/v1/backtest/{sid}/market/prices` — all prices at virtual_time
  - `GET /api/v1/backtest/{sid}/market/ticker/{symbol}` — 24h stats at virtual_time
  - `GET /api/v1/backtest/{sid}/market/candles/{symbol}` — candles BEFORE virtual_time

- [x] **BT-1.5.5** Implement backtest-scoped account routes
  - `GET /api/v1/backtest/{sid}/account/balance` — sandbox balances
  - `GET /api/v1/backtest/{sid}/account/positions` — sandbox positions
  - `GET /api/v1/backtest/{sid}/account/portfolio` — sandbox portfolio summary

- [x] **BT-1.5.6** Implement results & analysis routes
  - `GET /api/v1/backtest/{session_id}/results` — full results + metrics
  - `GET /api/v1/backtest/{session_id}/results/equity-curve` — equity curve data
  - `GET /api/v1/backtest/{session_id}/results/trades` — full trade log
  - `GET /api/v1/backtest/list` — list all backtests (filters: strategy_label, status, sort_by, limit)
  - `GET /api/v1/backtest/compare` — compare multiple sessions side-by-side
  - `GET /api/v1/backtest/best` — best session by metric

- [x] **BT-1.5.7** Implement mode management routes
  - `GET  /api/v1/account/mode` — current operating mode
  - `POST /api/v1/account/mode` — switch mode (live ↔ backtest)

- [x] **BT-1.5.8** Register backtest router in `src/main.py`
  - Add `backtest_router` to app factory
  - Ensure auth middleware applies to all backtest routes

---

### BT-1.6 Background Tasks

- [x] **BT-1.6.1** Implement `src/tasks/backtest_cleanup.py`
  - Task: auto-cancel backtest sessions idle for >1 hour (no step in last hour)
  - Task: delete backtest detail data (trades, snapshots) older than 90 days, keep session summary
  - Register in celery-beat schedule (run cleanup every hour)

---

### BT-1.7 Unit Tests

- [x] **BT-1.7.1** Write `tests/unit/test_time_simulator.py`
  - test_step_advances_by_interval
  - test_step_does_not_exceed_end_time
  - test_is_complete_at_end
  - test_remaining_steps_calculation
  - test_progress_pct_accurate
  - test_step_batch_advances_n_intervals
  - test_step_batch_stops_at_end

- [x] **BT-1.7.2** Write `tests/unit/test_data_replayer.py`
  - test_load_prices_at_timestamp
  - test_candle_range_only_returns_past_data
  - test_NO_FUTURE_DATA_LEAKAGE (critical)
  - test_ticker_24h_calculation
  - test_handles_pairs_without_data
  - test_get_data_range
  - test_get_available_pairs

- [x] **BT-1.7.3** Write `tests/unit/test_backtest_sandbox.py`
  - test_initial_balance_correct
  - test_market_buy_execution
  - test_market_sell_execution
  - test_limit_order_pending_then_triggered
  - test_stop_loss_triggers
  - test_insufficient_balance_rejected
  - test_position_tracking
  - test_pnl_calculation
  - test_close_all_positions
  - test_export_results
  - test_cancel_order
  - test_snapshot_capture

- [x] **BT-1.7.4** Write `tests/unit/test_backtest_engine.py`
  - test_create_session
  - test_start_initializes_sandbox
  - test_step_returns_correct_data
  - test_step_batch_advances_correctly
  - test_order_during_backtest
  - test_completion_persists_results
  - test_cancel_saves_partial_results
  - test_concurrent_sessions_isolated

- [x] **BT-1.7.5** Write `tests/unit/test_backtest_results.py`
  - test_sharpe_ratio_calculation
  - test_sortino_ratio_calculation
  - test_max_drawdown_calculation
  - test_win_rate_calculation
  - test_profit_factor_calculation
  - test_per_pair_stats
  - test_equity_curve_generation
  - test_empty_trades_edge_case

---

### BT-1.8 Integration Tests

- [x] **BT-1.8.1** Write `tests/integration/test_backtest_e2e.py`
  - Full lifecycle: create → start → step 10 times → verify prices match TimescaleDB → place market buy → verify balance → step 100 more → verify limit order triggered → step until completion → GET results → verify equity curve length → verify trade log → verify metrics are mathematically correct

- [x] **BT-1.8.2** Write `tests/integration/test_no_lookahead.py`
  - Create backtest at specific time → GET candles → assert ALL timestamps < virtual_clock → step forward → GET candles again → assert new candles include stepped period but NOT future

- [x] **BT-1.8.3** Write `tests/integration/test_agent_workflow.py`
  - Create backtest A (strategy_v1) → run → create backtest B (strategy_v2) → run → compare → verify comparison → get best → verify correct → switch mode → verify account mode switched

- [x] **BT-1.8.4** Write `tests/integration/test_concurrent_backtests.py`
  - Run 5 concurrent backtests → verify they don't interfere → verify all complete with independent results

- [x] **BT-1.8.5** Write `tests/integration/test_backtest_api.py`
  - Test every REST endpoint with valid + invalid inputs
  - Test auth required on all endpoints
  - Test session ownership (agent A can't access agent B's backtest)
  - Test error responses match format: `{"error": {"code": "...", "message": "..."}}`

---

## Phase BT-2: Frontend Observation UI (Week 3)

**Goal:** Human can observe everything the agent is doing (read-only)
**Deliverable:** Complete backtesting UI with list, monitor, results, and compare views

---

### BT-2.1 Navigation & Routing

- [x] **BT-2.1.1** Add "Backtesting" to sidebar navigation
  - Icon + label + dynamic badge showing completed count today
  - Route: `/backtest`

- [x] **BT-2.1.2** Create page routes
  - `Frontend/src/app/(dashboard)/backtest/page.tsx` — list view
  - `Frontend/src/app/(dashboard)/backtest/loading.tsx` — loading skeleton
  - `Frontend/src/app/(dashboard)/backtest/[session_id]/page.tsx` — monitor (running) or results (completed)
  - `Frontend/src/app/(dashboard)/backtest/[session_id]/loading.tsx`
  - `Frontend/src/app/(dashboard)/backtest/compare/page.tsx` — comparison view

---

### BT-2.2 Data Hooks

- [x] **BT-2.2.1** Implement `Frontend/src/hooks/use-backtest-list.ts`
  - Fetch all backtests for account via `GET /api/v1/backtest/list`
  - Support filters: strategy_label, status, sort_by
  - TanStack Query with appropriate stale time

- [x] **BT-2.2.2** Implement `Frontend/src/hooks/use-backtest-status.ts`
  - Poll running backtest status every 2 seconds
  - Auto-stop polling when backtest completes
  - Return: progress, current equity, trades count, virtual time

- [x] **BT-2.2.3** Implement `Frontend/src/hooks/use-backtest-results.ts`
  - Fetch completed results + equity curve + trade log
  - `GET /api/v1/backtest/{id}/results`
  - `GET /api/v1/backtest/{id}/results/equity-curve`
  - `GET /api/v1/backtest/{id}/results/trades`

- [x] **BT-2.2.4** Implement `Frontend/src/hooks/use-backtest-compare.ts`
  - Fetch comparison data via `GET /api/v1/backtest/compare?sessions=...`
  - Support auto-grouping by strategy_label prefix

---

### BT-2.3 TypeScript Types

- [x] **BT-2.3.1** Add backtest types to `Frontend/src/lib/types.ts`
  - `BacktestSession`, `BacktestResult`, `StepResult`, `BacktestMetrics`
  - `BacktestListItem`, `BacktestComparison`, `EquityCurvePoint`
  - `BacktestTrade`, `PairBreakdown`, `AccountMode`

---

### BT-2.4 Shared Components

- [x] **BT-2.4.1** Build `Frontend/src/components/backtest/shared/backtest-status-badge.tsx`
  - Status badges: created (gray), running (blue/pulse), completed (green), failed (red), cancelled (orange)

- [x] **BT-2.4.2** Build `Frontend/src/components/backtest/shared/virtual-time-display.tsx`
  - Shows "Simulating: Jan 15 14:30" with clock icon

- [x] **BT-2.4.3** Build `Frontend/src/components/backtest/shared/strategy-label-badge.tsx`
  - Colored tag for strategy name (auto-assign consistent colors per label)

- [x] **BT-2.4.4** Build `Frontend/src/components/backtest/shared/improvement-indicator.tsx`
  - Shows "Sharpe improved 30% from v2 (1.42) to v3 (1.85)" callouts
  - Compares against previous versions of same strategy_label prefix

---

### BT-2.5 List View Components

- [x] **BT-2.5.1** Build `Frontend/src/components/backtest/list/backtest-list-page.tsx`
  - Main page layout: active backtest card (top) + completed table + agent mode status
  - No create/edit/action buttons (read-only)

- [x] **BT-2.5.2** Build `Frontend/src/components/backtest/list/active-backtest-card.tsx`
  - Highlighted card for running backtest
  - Shows: strategy label, period, progress bar, current equity, PnL, trade count
  - Polls every 2 seconds via use-backtest-status hook
  - Transition to "Completed" state when done

- [x] **BT-2.5.3** Build `Frontend/src/components/backtest/list/completed-backtest-table.tsx`
  - Sortable table: strategy, period, ROI, Sharpe, drawdown, trades, created_at
  - Click row → navigate to results page
  - Highlight best performer

- [x] **BT-2.5.4** Build `Frontend/src/components/backtest/list/backtest-row.tsx`
  - Single row with metrics + status badge (integrated into completed-backtest-table.tsx)
  - Color-code ROI (green positive, red negative)

- [x] **BT-2.5.5** Build `Frontend/src/components/backtest/list/agent-mode-status.tsx`
  - Shows "Agent is Live Trading with strategy X" or "Agent is Backtesting"
  - Live equity, time since mode switch

- [x] **BT-2.5.6** Build `Frontend/src/components/backtest/list/backtest-list-filters.tsx`
  - Filter by strategy_label, status
  - Sort by ROI, Sharpe, drawdown, date

---

### BT-2.6 Monitor View Components (Running Backtest)

- [x] **BT-2.6.1** Build `Frontend/src/components/backtest/monitor/backtest-monitor-page.tsx`
  - Full monitor layout: progress + equity chart + stats cards + positions + trades feed
  - Real-time updates via polling

- [x] **BT-2.6.2** Build `Frontend/src/components/backtest/monitor/progress-timeline.tsx`
  - Visual timeline bar: start date → current virtual date → end date
  - Percentage and step count

- [x] **BT-2.6.3** Build `Frontend/src/components/backtest/monitor/live-equity-chart.tsx`
  - Equity curve building in real-time as backtest progresses
  - Chart updates as new snapshots arrive

- [x] **BT-2.6.4** Build `Frontend/src/components/backtest/monitor/live-stats-cards.tsx`
  - Cards: equity, PnL, trades count, win rate, max drawdown
  - Update on each poll

- [x] **BT-2.6.5** Build `Frontend/src/components/backtest/monitor/live-positions-table.tsx`
  - Agent's current positions at virtual time

- [x] **BT-2.6.6** Build `Frontend/src/components/backtest/monitor/live-trades-feed.tsx`
  - Reverse-chronological trade list with simulated timestamps
  - Shows: time, side, quantity, symbol, price, fee, PnL

---

### BT-2.7 Results View Components (Completed Backtest)

- [x] **BT-2.7.1** Build `Frontend/src/components/backtest/results/backtest-results-page.tsx`
  - Full results layout: summary cards + equity curve + drawdown + daily PnL + pair breakdown + trade log

- [x] **BT-2.7.2** Build `Frontend/src/components/backtest/results/results-summary-cards.tsx`
  - Cards: ROI, Sharpe, max drawdown, win rate, profit factor, total trades
  - Include improvement indicators if previous versions exist

- [x] **BT-2.7.3** Build `Frontend/src/components/backtest/results/results-equity-curve.tsx`
  - Full period equity chart (reuse/adapt analytics chart components)

- [x] **BT-2.7.4** Build `Frontend/src/components/backtest/results/results-drawdown-chart.tsx`
  - Drawdown visualization over time

- [x] **BT-2.7.5** Build `Frontend/src/components/backtest/results/results-daily-pnl.tsx`
  - Daily PnL bar chart (green/red bars)

- [x] **BT-2.7.6** Build `Frontend/src/components/backtest/results/results-trade-log.tsx`
  - Complete trade table (reuse/adapt trades page components)
  - Sortable, filterable

- [x] **BT-2.7.7** Build `Frontend/src/components/backtest/results/results-pair-breakdown.tsx`
  - Per-pair performance: symbol, trades, win rate, net PnL
  - Sortable table or cards

---

### BT-2.8 Compare View Components

- [x] **BT-2.8.1** Build `Frontend/src/components/backtest/compare/backtest-compare-page.tsx`
  - Layout: overlaid equity curves + metrics table + auto-selector

- [x] **BT-2.8.2** Build `Frontend/src/components/backtest/compare/overlaid-equity-chart.tsx`
  - Multiple equity curves on one chart, different colors
  - Legend with strategy labels

- [x] **BT-2.8.3** Build `Frontend/src/components/backtest/compare/compare-metrics-table.tsx`
  - Side-by-side metrics table: ROI, Sharpe, drawdown, win rate, trades, profit factor
  - Highlight best value in each row

- [x] **BT-2.8.4** Build `Frontend/src/components/backtest/compare/compare-auto-selector.tsx`
  - Auto-groups backtests by strategy_label prefix
  - Dropdown: "Compare momentum versions (3)" | "Compare scalping versions (2)"

---

### BT-2.9 Responsive & Polish

- [x] **BT-2.9.1** Mobile responsive pass on all backtest pages
  - List view: cards stack vertically, table scrolls horizontally
  - Monitor: charts full-width, stats cards 2-column
  - Results: single column layout on mobile
  - Compare: metrics table scrolls, chart responsive

- [x] **BT-2.9.2** Add loading skeletons for all pages
  - Skeleton for list page (card + table) — pre-existing
  - Skeleton for monitor page (timeline + chart + cards) — pre-existing
  - Skeleton for results page (cards + chart + table) — inline in results-page
  - Skeleton for compare page (chart + table) — created compare/loading.tsx

- [x] **BT-2.9.3** Verify: NO create/edit/action buttons anywhere in the backtest UI
  - Audited every component: no forms, no "Create Backtest" button, no "Start" button
  - All interaction is observation-only (view, filter, sort, navigate)

---

## Phase BT-3: Skill.md & Agent Integration (Week 4)

**Goal:** Any agent can use backtesting through skill.md and SDK/MCP
**Deliverable:** Production-ready backtesting, fully agent-driven

---

### BT-3.1 Skill.md Update

- [x] **BT-3.1.1** Add backtesting section to `docs/skill.md`
  - Document all backtesting endpoints with examples
  - Include recommended workflow (backtest → validate → compare → go live → re-validate)
  - Include tips for effective backtesting (multi-period, versioning, early cancel, benchmarking)
  - Match Section 11 of backtestingdevelopment.md exactly

---

### BT-3.2 SDK Update

- [ ] **BT-3.2.1** Add backtest methods to Python SDK sync client (`sdk/agentexchange/client.py`)
  - `get_data_range() → DataRange`
  - `create_backtest(config) → BacktestCreateResponse`
  - `start_backtest(session_id) → None`
  - `step_backtest(session_id) → StepResult`
  - `step_batch_backtest(session_id, steps) → StepResult`
  - `cancel_backtest(session_id) → BacktestResult`
  - `backtest_order(session_id, order) → OrderResult`
  - `get_backtest_price(session_id, symbol) → Price`
  - `get_backtest_candles(session_id, symbol, interval, limit) → list[Candle]`
  - `get_backtest_balance(session_id) → list[Balance]`
  - `get_backtest_positions(session_id) → list[Position]`
  - `get_backtest_portfolio(session_id) → Portfolio`
  - `get_backtest_results(session_id) → BacktestResult`
  - `get_backtest_equity_curve(session_id) → EquityCurve`
  - `get_backtest_trades(session_id) → list[Trade]`
  - `list_backtests(strategy_label?, status?, sort_by?, limit?) → list[BacktestListItem]`
  - `compare_backtests(session_ids) → CompareResult`
  - `get_best_backtest(metric, strategy_label?) → BacktestBestResult`
  - `get_account_mode() → AccountMode`
  - `set_account_mode(mode, strategy_label?) → AccountMode`

- [ ] **BT-3.2.2** Add backtest methods to Python SDK async client (`sdk/agentexchange/async_client.py`)
  - Same methods as sync client but async

- [ ] **BT-3.2.3** Add backtest models to SDK (`sdk/agentexchange/models.py`)
  - DataRange, BacktestConfig, StepResult, BacktestResult, BacktestMetrics, etc.

- [ ] **BT-3.2.4** Write SDK backtest unit tests

---

### BT-3.3 MCP Server Update

- [ ] **BT-3.3.1** Add backtest tools to MCP server (`src/mcp/tools.py`)
  - `create_backtest` — create a new backtest session
  - `start_backtest` — start a created session
  - `step_backtest` — advance one candle
  - `step_batch_backtest` — advance multiple candles
  - `backtest_order` — place order in backtest sandbox
  - `get_backtest_results` — get completed results
  - `compare_backtests` — compare multiple sessions
  - `get_best_backtest` — find best session by metric
  - `list_backtests` — list all sessions
  - `get_data_range` — check available historical data
  - `switch_mode` — switch between live and backtest mode

- [ ] **BT-3.3.2** Test MCP backtest tool discovery and execution

---

### BT-3.4 End-to-End Tests

- [ ] **BT-3.4.1** E2E test: agent reads skill.md, creates backtest, runs to completion, reviews results
  - Simulates a real agent workflow using the SDK

- [ ] **BT-3.4.2** E2E test: agent runs 3 backtests, compares them, picks the best one
  - Tests the full optimization loop

- [ ] **BT-3.4.3** E2E test: agent backtests → switches to live → periodically re-backtests
  - Tests mode switching and continuous improvement loop

---

### BT-3.5 Operations & Monitoring

- [ ] **BT-3.5.1** Add backtest metrics to Prometheus/Grafana
  - Metrics: active_backtests_count, completed_backtests_total, avg_backtest_duration_seconds, steps_per_second
  - Dashboard panel for backtest activity

- [ ] **BT-3.5.2** Configure cleanup task schedules
  - Auto-cancel stale backtests: every hour, cancel sessions with no step in >1 hour
  - Delete old detail data: daily, remove trades/snapshots older than 90 days (keep session summary)

---

## Summary

| Phase | Tasks | Estimated Duration |
|-------|-------|--------------------|
| BT-1: Backend Engine | 31 tasks | 2 weeks |
| BT-2: Frontend UI | 31 tasks | 1 week |
| BT-3: Integration | 14 tasks | 1 week |
| **Total** | **76 tasks** | **4 weeks** |

---

*Update this file as tasks are started, completed, or reprioritized.*
