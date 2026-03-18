# Strategy & Gym System — Master Task List

> **Created:** 2026-03-18 | **Total Tasks:** 95 | **Phases:** 7
> **Dependency chain:** STR-1 → STR-2 → STR-4 (MCP) | STR-1 → STR-5 → STR-3 (Gym) | Backend complete → STR-UI-1 → STR-UI-2
> **Parallelizable:** STR-3 + STR-4 can run in parallel after STR-2; STR-UI-1 can start after STR-1 API is stable
> **Next Alembic migration:** `016` (current head: `015`)
> **Key codebase hooks:** `BacktestConfig.strategy_label`, `BacktestEngine` singleton, DI try/except pattern in `dependencies.py`

---

## Phase STR-1: Strategy Registry (5-7 days)

Database tables, models, repository, service, schemas, and REST API for strategy CRUD + versioning.

### Database & Models

- [ ] **STR-1.1** — Create Alembic migration `016_strategy_and_training_tables.py`
  - Tables: `strategies`, `strategy_versions`, `strategy_test_runs`, `strategy_test_episodes`, `training_runs`, `training_episodes`
  - Indexes: `idx_strategies_account`, `idx_strategies_status`, `idx_sv_strategy`, `idx_str_strategy`, `idx_tr_account`
  - All UUIDs use `gen_random_uuid()`, all timestamps `TIMESTAMPTZ DEFAULT NOW()`
  - `strategy_test_episodes` and `training_episodes` FK to `backtest_sessions(session_id)`
  - **Validate with `migration-helper` agent before running**
  - Files: `alembic/versions/016_strategy_and_training_tables.py`

- [ ] **STR-1.2** — Create `src/strategies/__init__.py`
  - Empty package init

- [ ] **STR-1.3** — Create `src/strategies/models.py`
  - `StrategyDefinition(BaseModel)` — `pairs: list[str]`, `timeframe`, `entry_conditions`, `exit_conditions`, `position_size_pct: Decimal`, `max_positions: int`, `filters`, `model_type`, `model_reference`
  - `EntryConditions` / `ExitConditions` — typed condition schemas with all 12 entry + 7 exit condition keys
  - Validator: `pairs` must be non-empty, `timeframe` must be in `{1m, 5m, 15m, 1h, 4h, 1d}`, `position_size_pct` between 1-100
  - Files: `src/strategies/models.py`

### Repository

- [ ] **STR-1.4** — Create `src/database/repositories/strategy_repo.py`
  - `StrategyRepository(session: AsyncSession)`
  - Methods: `create(account_id, name, description, definition)`, `get_by_id(strategy_id)`, `list_by_account(account_id, status_filter, limit, offset)`, `update(strategy_id, **kwargs)`, `archive(strategy_id)`, `create_version(strategy_id, version_num, definition, change_notes, parent_version)`, `get_version(strategy_id, version)`, `list_versions(strategy_id)`, `deploy(strategy_id, version)`, `undeploy(strategy_id)`
  - All queries must filter by `account_id` for tenant isolation (same pattern as `AgentRepository`)
  - Use `NUMERIC(20,8)` for any price/balance fields, `JSONB` for definition
  - Files: `src/database/repositories/strategy_repo.py`

### Service

- [ ] **STR-1.5** — Create `src/strategies/service.py`
  - `StrategyService(repo: StrategyRepository)`
  - Methods: `create_strategy(account_id, name, description, definition) → Strategy`, `get_strategy(account_id, strategy_id) → Strategy + current version`, `list_strategies(account_id, status, limit, offset) → list[Strategy]`, `update_strategy(account_id, strategy_id, name, description)`, `archive_strategy(account_id, strategy_id)`, `create_version(account_id, strategy_id, definition, change_notes) → StrategyVersion`, `get_versions(account_id, strategy_id) → list[StrategyVersion]`, `get_version(account_id, strategy_id, version) → StrategyVersion`, `deploy(account_id, strategy_id, version)`, `undeploy(account_id, strategy_id)`
  - Validation: only one strategy can be `deployed` per account at a time (or allow multiple — decide)
  - Version auto-increment: query max version for strategy, +1
  - Deploy validates version has `validated` or `tested` status
  - Files: `src/strategies/service.py`

### API Schemas

- [ ] **STR-1.6** — Create `src/api/schemas/strategies.py`
  - Request: `CreateStrategyRequest(name, description, definition)`, `UpdateStrategyRequest(name, description)`, `CreateVersionRequest(definition, change_notes)`, `DeployRequest(version: int)`
  - Response: `StrategyResponse(strategy_id, name, description, current_version, status, deployed_at, created_at, updated_at)`, `StrategyDetailResponse(... + current_definition + latest_test_results)`, `StrategyVersionResponse(version_id, strategy_id, version, definition, change_notes, parent_version, status, created_at)`, `StrategyListResponse(strategies: list, total, limit, offset)`
  - Follow existing Pydantic v2 patterns from `src/api/schemas/backtest.py`
  - Files: `src/api/schemas/strategies.py`

### API Routes

- [ ] **STR-1.7** — Create `src/api/routes/strategies.py`
  - Router prefix: `/api/v1/strategies`, tags: `["strategies"]`
  - 10 endpoints:
    1. `POST /` — create strategy (auth required)
    2. `GET /` — list strategies (auth required, pagination)
    3. `GET /{strategy_id}` — get strategy detail (auth required, owner check)
    4. `PUT /{strategy_id}` — update metadata (auth required, owner check)
    5. `DELETE /{strategy_id}` — archive (auth required, owner check)
    6. `POST /{strategy_id}/versions` — create new version (auth required, owner check)
    7. `GET /{strategy_id}/versions` — list versions (auth required, owner check)
    8. `GET /{strategy_id}/versions/{version}` — get specific version (auth required, owner check)
    9. `POST /{strategy_id}/deploy` — deploy to live (auth required, owner check)
    10. `POST /{strategy_id}/undeploy` — stop live (auth required, owner check)
  - Use `request.state.account` for auth (same pattern as battles/backtest routes)
  - Files: `src/api/routes/strategies.py`

### Wiring

- [ ] **STR-1.8** — Register strategy routes in `src/main.py`
  - Import `strategies_router` from `src.api.routes.strategies`
  - Add `application.include_router(strategies_router)` after battles router
  - Files: `src/main.py`

- [ ] **STR-1.9** — Add DI aliases to `src/dependencies.py`
  - Add: `StrategyRepoDep`, `StrategyServiceDep`
  - Follow try/except ImportError pattern with lazy imports inside provider functions
  - Files: `src/dependencies.py`

### Tests

- [ ] **STR-1.10** — Unit tests for `StrategyService` (10+ tests)
  - Test: create, get, list, update, archive, create_version (auto-increment), get_versions, deploy (valid/invalid), undeploy
  - Mock: `StrategyRepository`
  - Files: `tests/unit/test_strategy_service.py`

- [ ] **STR-1.11** — Integration tests for strategy CRUD API (8+ tests)
  - Test: full CRUD lifecycle through REST, owner isolation, version creation, deploy/undeploy
  - Use app factory: `from src.main import create_app`
  - Files: `tests/integration/test_strategy_api.py`

### Documentation

- [ ] **STR-1.12** — Create `src/strategies/CLAUDE.md`
  - Purpose, key files, public API, dependency direction, gotchas
  - Files: `src/strategies/CLAUDE.md`

---

## Phase STR-2: Server-Side Strategy Executor (7-10 days)

Indicator engine, strategy executor, test orchestrator, Celery tasks, result aggregation, recommendations.

### Indicator Engine

- [ ] **STR-2.1** — Create `src/strategies/indicators.py`
  - `IndicatorEngine(max_history: int = 200)`
  - Methods: `update(symbol, ohlcv_dict)`, `compute(symbol) → dict`
  - Indicators (all pure numpy, no TA-Lib):
    - `_rsi(prices, period=14) → float`
    - `_macd(prices, fast=12, slow=26, signal=9) → tuple[float, float, float]` (line, signal, histogram)
    - `_sma(data, period) → float`
    - `_ema(data, period) → float`
    - `_bollinger(prices, period=20, std_dev=2) → tuple[float, float, float]` (upper, middle, lower)
    - `_adx(prices, period=14) → float` (needs high/low/close — update `update()` to accept OHLCV)
    - `_atr(prices, period=14) → float` (needs high/low/close)
  - Internal storage: `deque(maxlen=max_history)` per symbol for prices and volumes
  - Returns dict: `{rsi_14, macd_line, macd_signal, macd_hist, sma_20, sma_50, ema_12, ema_26, bb_upper, bb_middle, bb_lower, adx, atr, volume_ma_20, current_price, current_volume}`
  - Files: `src/strategies/indicators.py`

### Strategy Executor

- [ ] **STR-2.2** — Create `src/strategies/executor.py`
  - `StrategyExecutor(definition: dict, indicator_engine: IndicatorEngine)`
  - Methods: `decide(step_result: dict) → list[dict]` — returns list of orders to place
  - `_should_enter(symbol) → bool` — ALL entry conditions must pass
  - `_should_exit(position) → bool` — ANY exit condition triggers
  - `_evaluate_condition(condition_key, value, indicators) → bool` — switch on 19 condition keys
  - `_calculate_quantity(symbol, prices, portfolio) → Decimal` — based on `position_size_pct`
  - `_has_position(symbol, positions) → bool`
  - Exit logic priority: stop_loss → take_profit → trailing_stop → max_hold_candles → indicator exits
  - Trailing stop needs peak tracking: `_peak_prices: dict[str, float]`
  - Max hold candles needs entry candle tracking: `_entry_candles: dict[str, int]`
  - Files: `src/strategies/executor.py`

### Test Orchestrator

- [ ] **STR-2.3** — Create `src/strategies/test_orchestrator.py`
  - `TestOrchestrator(backtest_engine: BacktestEngine, strategy_service: StrategyService, test_run_repo: TestRunRepository)`
  - Methods:
    - `start_test(account_id, strategy_id, version, config) → test_run_id`
      - Creates `strategy_test_runs` record with status `queued`
      - Spawns Celery chord: N episode tasks → aggregation callback
      - Each episode gets randomized date window within `config.date_range`
    - `get_progress(test_run_id) → TestRunProgress` (episodes_completed / total, partial results)
    - `cancel_test(test_run_id)` — revoke pending Celery tasks, update status
  - Files: `src/strategies/test_orchestrator.py`

### Celery Tasks

- [ ] **STR-2.4** — Create `src/tasks/strategy_tasks.py`
  - `run_strategy_episode(test_run_id, episode_number, strategy_definition, backtest_config)` — sync Celery task
    - Creates backtest session via `BacktestEngine.create_session()`
    - Starts backtest via `BacktestEngine.start()`
    - Loop: `step()` → `StrategyExecutor.decide()` → `execute_order()` for each order → repeat until terminated
    - On completion: `BacktestEngine.complete()`, save episode metrics to `strategy_test_episodes`
    - Update `strategy_test_runs.episodes_completed` (atomic increment)
  - `aggregate_test_results(test_run_id)` — Celery callback after all episodes complete
    - Calls `TestAggregator.aggregate()`
    - Calls `RecommendationEngine.generate_recommendations()`
    - Saves to `strategy_test_runs.results` and `.recommendations`
    - Updates status to `completed`
  - Register in `celery_app.py`: add `"src.tasks.strategy_tasks"` to `include` list
  - Files: `src/tasks/strategy_tasks.py`, modify `src/tasks/celery_app.py`

### Result Aggregation

- [ ] **STR-2.5** — Create `src/strategies/test_aggregator.py`
  - `TestAggregator`
  - Methods: `aggregate(episodes: list[EpisodeResult]) → AggregatedResults`
  - Computes: `episodes_completed`, `episodes_profitable`, `episodes_profitable_pct`, `avg_roi_pct`, `median_roi_pct`, `best_roi_pct`, `worst_roi_pct`, `std_roi_pct`, `avg_sharpe`, `avg_max_drawdown_pct`, `avg_trades_per_episode`, `total_trades`
  - By-pair breakdown: same metrics grouped by trading pair
  - Uses numpy for statistical computations
  - Files: `src/strategies/test_aggregator.py`

### Recommendation Engine

- [ ] **STR-2.6** — Create `src/strategies/recommendation_engine.py`
  - `generate_recommendations(results: dict, by_pair: dict, definition: dict) → list[str]`
  - Rules (10+):
    1. Pair performance disparity > 5% ROI → suggest removing underperformer
    2. Win rate < 50% → suggest tightening entry or widening TP
    3. Win rate > 75% → suggest loosening entry for more trades
    4. Max drawdown > 15% → suggest tighter stop loss
    5. Max drawdown < 3% → suggest loosening SL for potential gains
    6. Few trades per episode → suggest relaxing entry conditions
    7. Too many trades per episode → suggest adding filters
    8. Sharpe < 0.5 → suggest risk-adjusted improvements
    9. ADX analysis if present → suggest threshold adjustment
    10. Stop loss vs take profit ratio → suggest RR improvements
  - Files: `src/strategies/recommendation_engine.py`

### Repository

- [ ] **STR-2.7** — Create `src/database/repositories/test_run_repo.py`
  - `TestRunRepository(session: AsyncSession)`
  - Methods: `create_test_run(strategy_id, version, config, episodes_total)`, `get_test_run(test_run_id)`, `list_test_runs(strategy_id, limit, offset)`, `increment_completed(test_run_id)`, `save_episode(test_run_id, episode_number, session_id, metrics)`, `save_results(test_run_id, results, recommendations)`, `update_status(test_run_id, status)`, `get_latest_results(strategy_id)`
  - Files: `src/database/repositories/test_run_repo.py`

### API Schemas

- [ ] **STR-2.8** — Create `src/api/schemas/strategy_tests.py`
  - Request: `StartTestRequest(version, episodes, date_range: {start, end}, randomize_dates, episode_duration_days)`
  - Response: `TestRunResponse(test_run_id, status, episodes_total, episodes_completed, progress_pct)`, `TestResultsResponse(... + results: AggregatedResults + recommendations: list[str])`, `VersionComparisonResponse(v1: VersionMetrics, v2: VersionMetrics, improvements: dict, verdict: str)`
  - Files: `src/api/schemas/strategy_tests.py`

### API Routes

- [ ] **STR-2.9** — Create `src/api/routes/strategy_tests.py`
  - Router prefix: `/api/v1/strategies`, tags: `["strategy-tests"]`
  - 6 endpoints:
    1. `POST /{strategy_id}/test` — trigger test run
    2. `GET /{strategy_id}/tests` — list test runs for strategy
    3. `GET /{strategy_id}/tests/{test_id}` — get test status + results
    4. `POST /{strategy_id}/tests/{test_id}/cancel` — cancel running test
    5. `GET /{strategy_id}/test-results` — latest completed test results (shortcut)
    6. `GET /{strategy_id}/compare-versions` — compare v1 vs v2 (`?v1=1&v2=2` query params)
  - Files: `src/api/routes/strategy_tests.py`

- [ ] **STR-2.10** — Register strategy_tests routes in `src/main.py`
  - Import and include router
  - Files: `src/main.py`

### Wiring

- [ ] **STR-2.11** — Add DI aliases to `src/dependencies.py`
  - Add: `TestRunRepoDep`, `TestOrchestratorDep`, `IndicatorEngineDep`
  - Files: `src/dependencies.py`

### Tests

- [ ] **STR-2.12** — Unit tests for `IndicatorEngine` (20+ tests)
  - Test each indicator against known values (e.g., RSI of known price series = expected value)
  - Test edge cases: insufficient data, single price, constant prices
  - Verify against manually computed values or reference implementations
  - Files: `tests/unit/test_indicator_engine.py`

- [ ] **STR-2.13** — Unit tests for `StrategyExecutor` (15+ tests)
  - Test: condition evaluation (each of 19 conditions), entry logic (all must pass), exit logic (any triggers), position sizing, max positions limit, trailing stop tracking
  - Mock: `IndicatorEngine`
  - Files: `tests/unit/test_strategy_executor.py`

- [ ] **STR-2.14** — Unit tests for `TestAggregator` + `RecommendationEngine` (10+ tests)
  - Test: aggregation math (avg, median, std, by-pair grouping)
  - Test: each recommendation rule triggers correctly
  - Files: `tests/unit/test_test_aggregator.py`, `tests/unit/test_recommendation_engine.py`

- [ ] **STR-2.15** — Integration test: create strategy → run test → verify results
  - Full flow through REST API: create strategy, trigger test, poll until complete, verify results structure
  - Files: `tests/integration/test_strategy_test_flow.py`

---

## Phase STR-3: Gymnasium Wrapper Package (5-7 days)

Separate PyPI package providing Gymnasium-compatible environments backed by TradeReady's backtest engine.

### Package Scaffold

- [ ] **STR-3.1** — Create `tradeready-gym/` package structure
  - `pyproject.toml` with dependencies: `gymnasium>=0.29`, `numpy`, `httpx`, `tradeready-sdk` (optional)
  - Package name: `tradeready-gym`, import as `tradeready_gym`
  - Directory structure per plan: `envs/`, `spaces/`, `rewards/`, `wrappers/`, `utils/`
  - Files: `tradeready-gym/pyproject.toml`, `tradeready-gym/tradeready_gym/__init__.py`

### Core Environments

- [ ] **STR-3.2** — Implement `BaseTradingEnv(gymnasium.Env)`
  - Constructor: `api_key, base_url, starting_balance, timeframe, lookback_window, reward_function, observation_features`
  - `reset(seed, options) → (observation, info)` — creates new backtest session via API, starts it
  - `step(action) → (observation, reward, terminated, truncated, info)` — calls backtest step, translates action to orders, computes reward
  - `close()` — completes/cancels backtest session
  - `render()` — optional text-mode rendering
  - Internal: `httpx.AsyncClient` wrapped in sync via `asyncio.run()` or threading
  - Files: `tradeready-gym/tradeready_gym/envs/base_trading_env.py`

- [ ] **STR-3.3** — Implement `SingleAssetTradingEnv`
  - Extends `BaseTradingEnv`
  - Discrete mode: `Discrete(3)` — 0=Hold, 1=Buy (position_size_pct), 2=Sell (close position)
  - Continuous mode: `Box(-1, 1, shape=(1,))` — magnitude = position size
  - Registered as: `TradeReady-BTC-v0`, `TradeReady-ETH-v0`, `TradeReady-SOL-v0`, `TradeReady-BTC-Continuous-v0`, `TradeReady-ETH-Continuous-v0`
  - Files: `tradeready-gym/tradeready_gym/envs/single_asset_env.py`

- [ ] **STR-3.4** — Implement `MultiAssetTradingEnv`
  - Extends `BaseTradingEnv`
  - Action: `Box(0, 1, shape=(N,))` — target portfolio weights, generates rebalancing orders
  - Registered as: `TradeReady-Portfolio-v0`
  - Files: `tradeready-gym/tradeready_gym/envs/multi_asset_env.py`

- [ ] **STR-3.5** — Implement `LiveTradingEnv`
  - Uses real-time price feed (not historical replay)
  - Registered as: `TradeReady-Live-v0`
  - Files: `tradeready-gym/tradeready_gym/envs/live_env.py`

### Spaces & Observations

- [ ] **STR-3.6** — Implement 5 action space presets
  - `DiscreteActionSpace(3)` — Hold/Buy/Sell
  - `ContinuousActionSpace(Box(-1, 1))` — direction + magnitude
  - `PortfolioActionSpace(Box(0, 1, N))` — target weights
  - `MultiDiscreteActionSpace` — per-asset discrete actions
  - `ParametricActionSpace` — action + quantity as tuple
  - Files: `tradeready-gym/tradeready_gym/spaces/action_spaces.py`

- [ ] **STR-3.7** — Implement `ObservationBuilder`
  - Builds numpy arrays from API step responses
  - Features: `ohlcv` (window, 5), `rsi_14` (window, 1), `macd` (window, 3), `bollinger` (window, 3), `volume` (window, 1), `balance` (1,), `position` (1,), `unrealized_pnl` (1,), `adx` (window, 1), `atr` (window, 1)
  - Configurable via `observation_features` list param
  - `lookback_window` controls how many candles of history
  - Files: `tradeready-gym/tradeready_gym/spaces/observation_builders.py`

### Reward Functions

- [ ] **STR-3.8** — Implement 5 reward functions
  - `PnLReward` — simple equity delta: `curr_equity - prev_equity`
  - `LogReturnReward` — `log(curr_equity / prev_equity)`
  - `SharpeReward` — rolling Sharpe ratio delta
  - `SortinoReward` — downside-risk-adjusted return
  - `DrawdownPenaltyReward` — PnL minus drawdown penalty coefficient
  - `CustomReward(ABC)` — user-extensible base class with `compute(prev_equity, curr_equity, info) → float`
  - Files: `tradeready-gym/tradeready_gym/rewards/pnl_reward.py`, `sharpe_reward.py`, `sortino_reward.py`, `drawdown_penalty_reward.py`, `custom_reward.py`

### Training Tracker

- [ ] **STR-3.9** — Implement `TrainingTracker`
  - Auto-registers a training run on first episode: `POST /training/runs`
  - Reports each episode completion: `POST /training/runs/{id}/episodes`
  - Completes run on `env.close()` or destructor: `POST /training/runs/{id}/complete`
  - Integrated into `BaseTradingEnv` — set `track_training=True` (default: True)
  - Files: `tradeready-gym/tradeready_gym/utils/training_tracker.py`

### Wrappers

- [ ] **STR-3.10** — Implement Gym wrappers
  - `FeatureEngineeringWrapper` — adds technical indicators to observation
  - `NormalizationWrapper` — normalizes observations to `[-1, 1]` range
  - `BatchStepWrapper` — executes N environment steps per agent action (reduce HTTP overhead)
  - Files: `tradeready-gym/tradeready_gym/wrappers/feature_engineering.py`, `normalization.py`, `batch_step.py`

### Environment Registration

- [ ] **STR-3.11** — Register all environments in `__init__.py`
  - `gymnasium.register(id="TradeReady-BTC-v0", entry_point="tradeready_gym.envs:SingleAssetTradingEnv", kwargs={"symbol": "BTCUSDT"})` etc.
  - All 7 environment IDs from the docs
  - `import tradeready_gym` should make `gym.make("TradeReady-BTC-v0", ...)` work
  - Files: `tradeready-gym/tradeready_gym/__init__.py`

### Tests

- [ ] **STR-3.12** — Gymnasium compliance tests
  - `gymnasium.utils.env_checker.check_env()` passes for all env variants
  - Files: `tradeready-gym/tests/test_gymnasium_compliance.py`

- [ ] **STR-3.13** — Unit tests for environments (20+ tests)
  - Test: reset/step/close lifecycle, action translation, observation shape, reward computation
  - Mock: HTTP API calls
  - Files: `tradeready-gym/tests/test_single_asset_env.py`, `test_multi_asset_env.py`, `test_rewards.py`, `test_training_tracker.py`

### Examples & Docs

- [ ] **STR-3.14** — Create 10 example scripts
  - `01_random_agent.py`, `02_ppo_training.py`, `03_dqn_training.py`, `04_continuous_actions.py`, `05_portfolio_allocation.py`, `06_custom_reward.py`, `07_custom_observation.py`, `08_vectorized_training.py`, `09_evaluate_model.py`, `10_live_trading.py`
  - Files: `tradeready-gym/examples/`

- [ ] **STR-3.15** — Write `README.md` with quickstart
  - Installation, quick start, environment reference, action/observation spaces, reward functions, training tracker, examples
  - Files: `tradeready-gym/README.md`

- [ ] **STR-3.16** — Publish to PyPI
  - Build with `python -m build`, upload with `twine`
  - Verify: `pip install tradeready-gym && python -c "import tradeready_gym; import gymnasium; gym.make('TradeReady-BTC-v0', api_key='test')"`

---

## Phase STR-4: MCP Tools & skill.md (2-3 days)

Expose strategy + training endpoints through MCP server and update documentation.

### MCP Tools

- [ ] **STR-4.1** — Add 7 strategy management MCP tools to `src/mcp/tools.py`
  - `create_strategy` — name, definition (JSON)
  - `get_strategies` — list all
  - `get_strategy` — by ID, includes current version + latest results
  - `create_strategy_version` — strategy_id, definition, change_notes
  - `get_strategy_versions` — version history
  - `deploy_strategy` — strategy_id, version
  - `undeploy_strategy` — strategy_id
  - Update `TOOL_COUNT` constant
  - Files: `src/mcp/tools.py`

- [ ] **STR-4.2** — Add 5 strategy testing MCP tools
  - `run_strategy_test` — strategy_id, episodes, date_range
  - `get_test_status` — strategy_id, test_id
  - `get_test_results` — strategy_id, test_id (full results + recommendations)
  - `compare_versions` — strategy_id, v1, v2
  - `get_strategy_recommendations` — strategy_id (latest test's recommendations)
  - Files: `src/mcp/tools.py`

- [ ] **STR-4.3** — Add 3 training observation MCP tools
  - `get_training_runs` — list all with metrics
  - `get_training_run_detail` — full detail + learning curve
  - `compare_training_runs` — run_ids list
  - Files: `src/mcp/tools.py`

### Tests

- [ ] **STR-4.4** — Unit tests for new MCP tools (15+ tests)
  - Test each tool dispatches to correct API endpoint with correct params
  - Mock: `httpx.AsyncClient`
  - Files: `tests/unit/test_mcp_strategy_tools.py`

### Documentation

- [ ] **STR-4.5** — Add Strategy Development Cycle section to `docs/skill.md`
  - Full workflow: create → test → read results → improve → compare → deploy
  - All condition keys with descriptions
  - Example JSON definitions
  - Files: `docs/skill.md`

- [ ] **STR-4.6** — Add RL Developer section to `docs/skill.md`
  - Pointer to `pip install tradeready-gym`
  - How to query training results via API
  - Files: `docs/skill.md`

- [ ] **STR-4.7** — Update `docs/api_reference.md` with all new endpoints
  - Strategy CRUD (10), Strategy Tests (6), Training (7) = 23 new endpoints
  - Files: `docs/api_reference.md`

- [ ] **STR-4.8** — Update SDK with strategy + training methods
  - Add to `sdk/agentexchange/client.py` (sync) and `async_client.py`:
    - `create_strategy()`, `get_strategies()`, `get_strategy()`, `create_version()`, `deploy_strategy()`, `undeploy_strategy()`
    - `run_test()`, `get_test_status()`, `get_test_results()`, `compare_versions()`
    - `get_training_runs()`, `get_training_run()`, `compare_training_runs()`
  - Files: `sdk/agentexchange/client.py`, `sdk/agentexchange/async_client.py`

### CLAUDE.md Updates

- [ ] **STR-4.9** — Update `src/mcp/CLAUDE.md`
  - Update tool count, add strategy + training tool groups
  - Files: `src/mcp/CLAUDE.md`

---

## Phase STR-5: Training Run Aggregation (3-4 days)

Backend endpoints for observing Gym/RL training runs. Provides the bridge between the Gym package and the UI.

### Service

- [ ] **STR-5.1** — Create `src/training/__init__.py`
  - Empty package init

- [ ] **STR-5.2** — Create `src/training/tracker.py`
  - `TrainingRunService(repo: TrainingRunRepository)`
  - Methods:
    - `register_run(account_id, run_id, config, strategy_id?) → TrainingRun`
    - `record_episode(run_id, episode_number, session_id, metrics) → TrainingEpisode`
    - `complete_run(run_id) → TrainingRun` — computes aggregate_stats, updates learning_curve JSONB
    - `get_run(run_id) → TrainingRun + episodes`
    - `list_runs(account_id, status, limit, offset) → list[TrainingRun]`
    - `get_learning_curve(run_id, metric, window) → LearningCurveData`
    - `compare_runs(run_ids) → ComparisonResult`
  - Learning curve computation: `rolling_mean(values, window)` for smoothing
  - Files: `src/training/tracker.py`

### Repository

- [ ] **STR-5.3** — Create `src/database/repositories/training_repo.py`
  - `TrainingRunRepository(session: AsyncSession)`
  - Methods: `create_run(run_id, account_id, config, strategy_id)`, `get_run(run_id)`, `list_runs(account_id, status, limit, offset)`, `add_episode(run_id, episode_number, session_id, metrics)`, `complete_run(run_id, aggregate_stats, learning_curve)`, `get_episodes(run_id, limit, offset)`, `get_runs_by_ids(run_ids)`
  - Files: `src/database/repositories/training_repo.py`

### API Schemas

- [ ] **STR-5.4** — Create `src/api/schemas/training.py`
  - Request: `RegisterRunRequest(run_id, config, strategy_id?)`, `ReportEpisodeRequest(episode_number, session_id, roi_pct, sharpe_ratio, max_drawdown_pct, total_trades, reward_sum)`, `LearningCurveParams(metric: str = "roi_pct", window: int = 10)`
  - Response: `TrainingRunResponse(run_id, status, config, episodes_total, episodes_completed, started_at, completed_at)`, `TrainingRunDetailResponse(... + learning_curve + aggregate_stats + episodes)`, `LearningCurveResponse(episode_numbers, raw_values, smoothed_values, metric, window)`, `TrainingComparisonResponse(runs: list[RunMetrics])`
  - Files: `src/api/schemas/training.py`

### API Routes

- [ ] **STR-5.5** — Create `src/api/routes/training.py`
  - Router prefix: `/api/v1/training`, tags: `["training"]`
  - 7 endpoints:
    1. `POST /runs` — register new training run (called by Gym wrapper)
    2. `POST /runs/{run_id}/episodes` — report episode result (called by Gym wrapper)
    3. `POST /runs/{run_id}/complete` — mark run complete
    4. `GET /runs` — list all training runs (auth required)
    5. `GET /runs/{run_id}` — full detail + learning curve + episodes
    6. `GET /runs/{run_id}/learning-curve` — learning curve data with metric/window query params
    7. `GET /compare` — compare multiple runs (`?run_ids=id1,id2,id3`)
  - Files: `src/api/routes/training.py`

### Wiring

- [ ] **STR-5.6** — Register training routes in `src/main.py`
  - Import and include router
  - Files: `src/main.py`

- [ ] **STR-5.7** — Add DI aliases to `src/dependencies.py`
  - Add: `TrainingRunRepoDep`, `TrainingRunServiceDep`
  - Files: `src/dependencies.py`

### Tests

- [ ] **STR-5.8** — Unit tests for `TrainingRunService` (8+ tests)
  - Test: register, record episode, complete, learning curve computation, comparison
  - Files: `tests/unit/test_training_tracker.py`

- [ ] **STR-5.9** — Integration tests for training API (5+ tests)
  - Test: register run → report episodes → complete → query results → learning curve
  - Files: `tests/integration/test_training_api.py`

### Documentation

- [ ] **STR-5.10** — Create `src/training/CLAUDE.md`
  - Purpose, key files, public API, dependency direction
  - Files: `src/training/CLAUDE.md`

---

## Phase STR-UI-1: Strategy & Training Pages (5-7 days)

Frontend pages, components, and hooks for strategy management and training observation.

### Type Definitions

- [ ] **STR-UI-1.1** — Add TypeScript type definitions
  - `Strategy`, `StrategyVersion`, `StrategyDefinition`, `StrategyTestRun`, `TestResults`, `AggregatedMetrics`, `PairBreakdown`, `TrainingRun`, `TrainingEpisode`, `LearningCurveData`
  - Files: `Frontend/src/lib/types.ts`

### API Client

- [ ] **STR-UI-1.2** — Add strategy + training API functions to `api-client.ts`
  - Strategy: `getStrategies()`, `getStrategy(id)`, `createStrategy(data)`, `updateStrategy(id, data)`, `archiveStrategy(id)`, `createVersion(id, data)`, `getVersions(id)`, `deployStrategy(id, version)`, `undeployStrategy(id)`
  - Tests: `runTest(id, config)`, `getTestRuns(id)`, `getTestResults(id, testId)`, `compareVersions(id, v1, v2)`
  - Training: `getTrainingRuns()`, `getTrainingRun(id)`, `getLearningCurve(id, metric, window)`, `compareTrainingRuns(ids)`
  - Files: `Frontend/src/lib/api-client.ts`

### Hooks

- [ ] **STR-UI-1.3** — Build `useStrategies` hook
  - TanStack Query: `queryKey: ["strategies"]`, auto-refetch on window focus
  - Files: `Frontend/src/hooks/use-strategies.ts`

- [ ] **STR-UI-1.4** — Build `useStrategyDetail` hook
  - TanStack Query: `queryKey: ["strategy", id]`, includes versions + latest test results
  - Files: `Frontend/src/hooks/use-strategy-detail.ts`

- [ ] **STR-UI-1.5** — Build `useTrainingRuns` hook
  - TanStack Query: `queryKey: ["training-runs"]`, polls every 10s when active runs exist
  - Files: `Frontend/src/hooks/use-training-runs.ts`

- [ ] **STR-UI-1.6** — Build `useActiveTrainingRun` hook
  - Polls every 2s for active run progress
  - Files: `Frontend/src/hooks/use-active-training-run.ts`

- [ ] **STR-UI-1.7** — Build `useTrainingRunDetail` hook
  - Full run detail + episodes list
  - Files: `Frontend/src/hooks/use-training-run-detail.ts`

- [ ] **STR-UI-1.8** — Build `useLearningCurve` hook
  - Parameterized by metric + smoothing window
  - Files: `Frontend/src/hooks/use-learning-curve.ts`

- [ ] **STR-UI-1.9** — Build `useTrainingCompare` hook
  - Compare multiple runs
  - Files: `Frontend/src/hooks/use-training-compare.ts`

### Strategy Components (8)

- [ ] **STR-UI-1.10** — Build `strategy-list-table.tsx`
  - Sortable table: name, status badge, version, last test ROI, Sharpe, created date
  - Click row → navigate to detail
  - Files: `Frontend/src/components/strategies/strategy-list-table.tsx`

- [ ] **STR-UI-1.11** — Build `strategy-status-badge.tsx`
  - Color-coded badges: draft (gray), testing (blue), validated (green), deployed (emerald pulse), archived (muted)
  - Files: `Frontend/src/components/strategies/strategy-status-badge.tsx`

- [ ] **STR-UI-1.12** — Build `strategy-detail-header.tsx`
  - Strategy name, status badge, version number, deployed date, action buttons (deploy/undeploy)
  - Files: `Frontend/src/components/strategies/strategy-detail-header.tsx`

- [ ] **STR-UI-1.13** — Build `version-history.tsx`
  - Timeline view of versions with change notes, click to expand definition
  - Files: `Frontend/src/components/strategies/version-history.tsx`

- [ ] **STR-UI-1.14** — Build `definition-viewer.tsx`
  - Readable JSON viewer: pairs as badges, conditions as labeled rows, position sizing as visual bar
  - Files: `Frontend/src/components/strategies/definition-viewer.tsx`

- [ ] **STR-UI-1.15** — Build `test-results-summary.tsx`
  - Key metrics cards: ROI, Sharpe, drawdown, win rate, trades
  - Per-pair breakdown table
  - Files: `Frontend/src/components/strategies/test-results-summary.tsx`

- [ ] **STR-UI-1.16** — Build `version-comparison.tsx`
  - Side-by-side metric comparison with +/- deltas and color coding
  - Files: `Frontend/src/components/strategies/version-comparison.tsx`

- [ ] **STR-UI-1.17** — Build `recommendations-card.tsx`
  - Bulleted list of AI-generated improvement suggestions
  - Files: `Frontend/src/components/strategies/recommendations-card.tsx`

### Training Components (9)

- [ ] **STR-UI-1.18** — Build `active-training-card.tsx`
  - Live progress: run ID, episode count, elapsed time, mini learning curve
  - Files: `Frontend/src/components/training/active-training-card.tsx`

- [ ] **STR-UI-1.19** — Build `learning-curve-sparkline.tsx`
  - Tiny inline sparkline chart for table rows (recharts or lightweight SVG)
  - Files: `Frontend/src/components/training/learning-curve-sparkline.tsx`

- [ ] **STR-UI-1.20** — Build `completed-runs-table.tsx`
  - Sortable table: run ID, episodes, avg ROI, best ROI, Sharpe, sparkline, duration
  - Files: `Frontend/src/components/training/completed-runs-table.tsx`

- [ ] **STR-UI-1.21** — Build `run-header.tsx`
  - Run ID, status badge, config summary, duration, episode count
  - Files: `Frontend/src/components/training/run-header.tsx`

- [ ] **STR-UI-1.22** — Build `run-summary-cards.tsx`
  - 4-6 stat cards: total episodes, avg ROI, best/worst ROI, avg Sharpe, avg drawdown
  - Files: `Frontend/src/components/training/run-summary-cards.tsx`

- [ ] **STR-UI-1.23** — Build `learning-curve-chart.tsx` (full interactive)
  - Recharts line chart with: metric selector dropdown, smoothing slider, raw + smoothed lines
  - Metrics: ROI, Sharpe, reward sum, drawdown
  - Files: `Frontend/src/components/training/learning-curve-chart.tsx`

- [ ] **STR-UI-1.24** — Build `episode-highlight-card.tsx`
  - Best/worst episode cards with mini equity curve and key metrics
  - Click → navigate to `/backtest/[session_id]`
  - Files: `Frontend/src/components/training/episode-highlight-card.tsx`

- [ ] **STR-UI-1.25** — Build `episodes-table.tsx`
  - Searchable/sortable table of all episodes: number, ROI, Sharpe, trades, drawdown, reward
  - Click row → navigate to backtest detail
  - Files: `Frontend/src/components/training/episodes-table.tsx`

- [ ] **STR-UI-1.26** — Build `run-comparison-view.tsx`
  - Multi-run overlay chart + metrics comparison table
  - Files: `Frontend/src/components/training/run-comparison-view.tsx`

### Pages

- [ ] **STR-UI-1.27** — Create `/strategies` page + loading skeleton
  - Uses `useStrategies` hook, renders `strategy-list-table`
  - Files: `Frontend/src/app/(dashboard)/strategies/page.tsx`, `loading.tsx`

- [ ] **STR-UI-1.28** — Create `/strategies/[id]` page + loading skeleton
  - Uses `useStrategyDetail` hook, renders header + version history + definition + test results + recommendations + comparison
  - Files: `Frontend/src/app/(dashboard)/strategies/[id]/page.tsx`, `loading.tsx`

- [ ] **STR-UI-1.29** — Create `/training` page + loading skeleton
  - Uses `useTrainingRuns` hook, renders active card + completed table
  - Files: `Frontend/src/app/(dashboard)/training/page.tsx`, `loading.tsx`

- [ ] **STR-UI-1.30** — Create `/training/[run_id]` page + loading skeleton
  - Uses `useTrainingRunDetail` + `useLearningCurve` hooks, renders header + summary + chart + episodes
  - Files: `Frontend/src/app/(dashboard)/training/[run_id]/page.tsx`, `loading.tsx`

### Navigation

- [ ] **STR-UI-1.31** — Add sidebar navigation items
  - Add `"Strategies"` and `"Training"` to `NAV_ITEMS` in `Frontend/src/lib/constants.ts`
  - Add routes to `ROUTES` object in constants
  - Add to sidebar group filter in `Frontend/src/components/layout/sidebar.tsx` (likely "Trading" group)
  - Icons: `Brain` for Strategies, `GraduationCap` or `Dumbbell` for Training (from lucide-react)
  - Files: `Frontend/src/lib/constants.ts`, `Frontend/src/components/layout/sidebar.tsx`

---

## Phase STR-UI-2: Integration & Polish (3-4 days)

Dashboard integration, edge cases, responsive design, documentation updates.

- [ ] **STR-UI-2.1** — Dashboard integration: strategy status card
  - Show deployed strategy name, version, live ROI on main dashboard
  - Files: `Frontend/src/app/(dashboard)/dashboard/page.tsx` or relevant dashboard component

- [ ] **STR-UI-2.2** — Dashboard integration: training status card
  - Show active training run, episode count, learning trend
  - Files: same as above

- [ ] **STR-UI-2.3** — Backtest list filter: hide Gym episodes
  - Gym-generated backtest sessions should be hidden from `/backtest` list by default
  - Add `?source=manual` filter or `exclude_training=true` query param
  - Files: `Frontend/src/app/(dashboard)/backtest/page.tsx`, possibly `src/api/routes/backtest.py`

- [ ] **STR-UI-2.4** — Sidebar active badges
  - Show dot/badge on "Strategies" when tests are running
  - Show dot/badge on "Training" when a run is active
  - Files: `Frontend/src/components/layout/sidebar.tsx`

- [ ] **STR-UI-2.5** — Empty states for all new pages
  - `/strategies` with no strategies → CTA explaining the API workflow
  - `/training` with no runs → CTA pointing to `pip install tradeready-gym`
  - Files: various page files

- [ ] **STR-UI-2.6** — Mobile responsive pass
  - All 4 new pages render well on mobile (tables collapse, charts resize)
  - Files: various component files

- [ ] **STR-UI-2.7** — Loading skeletons + error boundaries
  - All pages have proper loading.tsx skeletons and error.tsx boundaries
  - Files: `Frontend/src/app/(dashboard)/strategies/error.tsx`, `training/error.tsx`

- [ ] **STR-UI-2.8** — Update CLAUDE.md files
  - `Frontend/src/components/CLAUDE.md` — add strategies/ and training/ directories
  - `Frontend/src/hooks/CLAUDE.md` — add 7 new hooks
  - `Frontend/src/app/CLAUDE.md` — add new pages
  - `Frontend/CLAUDE.md` — update component count
  - Root `CLAUDE.md` — add strategies and training to module index
  - Files: multiple CLAUDE.md files

---

## Cross-Cutting Tasks

These run after each phase completes (per project rules).

- [ ] **CC-1** — After STR-1: Run `code-reviewer` agent on all new files
- [ ] **CC-2** — After STR-1: Run `test-runner` agent to verify tests pass
- [ ] **CC-3** — After STR-2: Run `code-reviewer` + `test-runner` agents
- [ ] **CC-4** — After STR-2: Run `perf-checker` on indicator engine + Celery tasks
- [ ] **CC-5** — After STR-2: Run `security-auditor` on strategy API routes (input validation)
- [ ] **CC-6** — After STR-4: Run `api-sync-checker` (frontend/backend route sync)
- [ ] **CC-7** — After STR-5: Run `code-reviewer` + `test-runner` agents
- [ ] **CC-8** — After STR-UI-1: Run `api-sync-checker` (TypeScript types vs Pydantic schemas)
- [ ] **CC-9** — After STR-UI-2: Run `deploy-checker` for production readiness
- [ ] **CC-10** — After each phase: Run `context-manager` to update `development/context.md`
- [ ] **CC-11** — After all phases: Integration test: full strategy lifecycle end-to-end
  - Files: `tests/integration/test_full_strategy_cycle.py`
- [ ] **CC-12** — After all phases: Run `doc-updater` for final documentation pass
- [ ] **CC-13** — Lint check: `ruff check src/ tests/` passes with zero errors
- [ ] **CC-14** — Type check: `mypy src/` passes

---

## Execution Order & Parallelization

```
Week 1-2:  STR-1 (Strategy Registry)
Week 2-3:  STR-2 (Strategy Executor) ─────────────┐
Week 3-4:  STR-5 (Training Aggregation) [parallel] │
Week 4-5:  STR-3 (Gym Package) [parallel with 4]   │
Week 4:    STR-4 (MCP Tools) [parallel with 3] ────┘
Week 5-6:  STR-UI-1 (Strategy & Training Pages)
Week 6-7:  STR-UI-2 (Integration & Polish)

Critical path: STR-1 → STR-2 → STR-UI-1 → STR-UI-2
```

### Phase Dependencies

| Phase | Depends On | Can Parallelize With |
|-------|-----------|---------------------|
| STR-1 | None (existing backtesting engine) | Nothing (must go first) |
| STR-2 | STR-1 (strategy models, repo, service) | Nothing |
| STR-3 | STR-2 (executor), STR-5 (training API) | STR-4 |
| STR-4 | STR-2 (strategy API exists), STR-5 (training API exists) | STR-3 |
| STR-5 | STR-1 (migration includes training tables) | STR-2 |
| STR-UI-1 | STR-1 API stable, STR-5 API stable | Nothing |
| STR-UI-2 | STR-UI-1 complete | Nothing |

---

**Total tasks: 95** (STR-1: 12, STR-2: 15, STR-3: 16, STR-4: 9, STR-5: 10, STR-UI-1: 31, STR-UI-2: 8, Cross-cutting: 14)
**New backend files: ~30** | **New frontend files: ~35** | **Gym package files: ~25**
