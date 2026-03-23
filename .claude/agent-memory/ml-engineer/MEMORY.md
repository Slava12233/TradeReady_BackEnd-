# ML Engineer — Project Memory

## Strategy System Overview (`agent/strategies/`)
Five complementary strategies that can operate independently or together through the ensemble combiner. All sit **above** the platform API — no direct DB access; all HTTP calls go through `PlatformRESTClient` or `AsyncAgentExchangeClient`.

| Sub-package | Approach | Entry point |
|-------------|----------|-------------|
| `rl/` | PPO via Stable-Baselines3 | `RLConfig`, `train()`, `PPODeployBridge` |
| `evolutionary/` | Genetic algorithm over `StrategyGenome` | `Population`, `BattleRunner` |
| `regime/` | XGBoost/RF regime classification | `RegimeClassifier`, `RegimeSwitcher` |
| `risk/` | Portfolio-level risk overlay | `RiskAgent`, `VetoPipeline`, `DynamicSizer`, `RiskMiddleware` |
| `ensemble/` | Weighted meta-learner | `MetaLearner`, `EnsembleRunner` |

## PPO RL (`agent/strategies/rl/`)
- Config via `RLConfig` (Pydantic BaseSettings, env prefix `RL_`)
- Trains on `TradeReady-Portfolio-v0` gymnasium environment (BTC+ETH+SOL portfolio weights)
- `ModelEvaluator` loads `ppo_seed*.zip` files, runs test-split + 3 benchmarks (equal-weight, BTC buy-and-hold, ETH buy-and-hold)
- `PPODeployBridge` needs at least `config.lookback_window` (default 30) candles in buffer before producing valid predictions
- SB3 + torch NOT installed by default — install via `pip install stable-baselines3[extra]`
- `rl/models/` is gitignored — regenerate with `python -m agent.strategies.rl.runner`

## Genetic Algorithm (`agent/strategies/evolutionary/`)
- `StrategyGenome`: 12-parameter float64 numpy vector (RSI, MACD, ADX, stop-loss, take-profit, trailing stop, position size, hold limits, pair subset)
- Fitness formula: `sharpe_ratio - 0.5 * max_drawdown_pct`; missing results = `FAILURE_FITNESS = -999.0`
- `BattleRunner` requires JWT auth — calls `POST /api/v1/auth/login` on construction using `AgentConfig` credentials
- Config via `EvolutionConfig` (env prefix `EVO_`)

## Regime Detection (`agent/strategies/regime/`)
- 4 regime types: `TRENDING` (ADX > 25), `HIGH_VOLATILITY` (ATR/close > 2× median), `LOW_VOLATILITY` (ATR/close < 0.5× median), `MEAN_REVERTING` (remainder)
- `RegimeClassifier`: 5-feature input (ADX, ATR/close, RSI, MACD line, close-vs-SMA20). XGBoost preferred; falls back to `RandomForestClassifier`
- `RegimeSwitcher.step(candles) -> (RegimeType, strategy_id, switched: bool)`. Cooldown default 20 candles — will not switch more than once per cooldown period regardless of confidence
- Persist via joblib

## Risk Overlay (`agent/strategies/risk/`)
- `RiskAgent.assess()` returns `"OK"` / `"REDUCE"` / `"HALT"` based on daily PnL and drawdown thresholds
- `VetoPipeline`: 6 sequential gates (HALT verdict → low confidence → max exposure → sector concentration → recent drawdown → approved). RESIZED continues through all remaining gates; VETOED short-circuits
- `DynamicSizer`: volatility- and drawdown-adjusted position sizing
- `RiskMiddleware` never raises — all errors surfaced in `ExecutionDecision.error`

## Ensemble Combiner (`agent/strategies/ensemble/`)
- `MetaLearner` weighted voting: `score = sum(confidence × weight[source])`. Falls back to HOLD if `combined_confidence < threshold` or all sources disagree
- Static converters: `rl_weights_to_signals()`, `genome_to_signals()`, `regime_to_signals()`
- Config via `EnsembleConfig` (env prefix `ENSEMBLE_`); `weights: dict[str, float]` field (keys: `"rl"`, `"evolved"`, `"regime"`); no `optimal_weights_path` field — weights are set directly
- Weight optimization utilities (Task 14, 2026-03-22):
  - `save_optimal_weights_json(weights, path)` — writes compact `{"rl": 0.45, "evolved": 0.30, "regime": 0.25}` JSON
  - `load_optimal_weights(path)` — reads and validates the compact file
  - `apply_optimal_weights(config, weights)` — returns new `EnsembleConfig` with weights updated via `model_copy()`
  - `validate_ensemble_beats_baseline(optimal, equal_weight)` — returns `(bool, message)` for post-opt gate
  - CLI `--seed` and `--base-url` both present; API key from env only (`ENSEMBLE_PLATFORM_API_KEY` or `PLATFORM_API_KEY`)
  - After optimization, compact `optimal_weights.json` is written alongside the full timestamped report
- Data flow: candles → PPODeployBridge + StrategyGenome + RegimeSwitcher → MetaLearner → RiskMiddleware → ExecutionDecision → SDK/REST order

## tradeready-gym Environments
- Standalone installable package: `pip install -e tradeready-gym/`; does NOT import from `src/`
- Must `import tradeready_gym` before any `gym.make("TradeReady-*")` — triggers `gymnasium.register()` calls
- All environments require `api_key` kwarg to `gym.make()`
- `BaseTradingEnv` uses synchronous `httpx.Client` — intentional; SB3 requires sync step/reset
- `reset()` → `POST /api/v1/backtest/create` + `/start`; `step()` → `POST /api/v1/backtest/{id}/step`

## Registered Gym Environments
| ID | Action Space | Symbol(s) |
|----|--------------|-----------|
| `TradeReady-BTC-v0` | `Discrete(3)` (Hold/Buy/Sell) | BTCUSDT |
| `TradeReady-ETH-v0` | `Discrete(3)` | ETHUSDT |
| `TradeReady-SOL-v0` | `Discrete(3)` | SOLUSDT |
| `TradeReady-BTC-Continuous-v0` | `Box(-1, 1, (1,))` | BTCUSDT |
| `TradeReady-ETH-Continuous-v0` | `Box(-1, 1, (1,))` | ETHUSDT |
| `TradeReady-Portfolio-v0` | `Box(0, 1, (3,))` portfolio weights | BTC+ETH+SOL |
| `TradeReady-Live-v0` | `Discrete(3)` | BTCUSDT (real-time, blocks per interval) |

## Reward Functions
- `PnLReward`: `curr_equity - prev_equity`
- `SharpeReward`: rolling Sharpe ratio delta (window default 50)
- `SortinoReward`: rolling Sortino ratio delta (window default 50)
- `DrawdownPenaltyReward`: PnL minus `penalty_coeff * drawdown` (default coeff 1.0)
- Custom: implement `CustomReward.compute(prev_equity, curr_equity, info) -> float`

## Wrappers
- `FeatureEngineeringWrapper` — appends SMA ratio and momentum features
- `NormalizationWrapper` — online Welford z-score, clipped to `[-1, 1]`; stats accumulate across episodes within same instance
- `BatchStepWrapper` — holds action for N steps, sums rewards; early termination on truncation

## Key Conventions
- All financial values as `Decimal` internally; convert to `float` only at JSON output boundaries
- ISO-8601 strings for all date/time config fields — never `datetime` objects
- No `--api-key` CLI arguments — keys read exclusively from `agent/.env` via `AgentConfig`
- Concurrent API calls via `asyncio.gather`; blocking I/O via `asyncio.to_thread`
- Bounded caches via `collections.deque(maxlen=N)` for observation buffers
- Model integrity via SHA-256: call `save_checksum()` after every model save, `verify_checksum()` before every model load; raises `SecurityError` on mismatch
- Always call `env.close()` at end of training to finalize `TrainingTracker` run on platform

## Walk-Forward Validation (`agent/strategies/walk_forward.py`)
- `WalkForwardConfig` (Pydantic BaseSettings, env prefix `WF_`): `data_start`, `data_end`, `train_months` (default 6), `oos_months` (default 1), `min_wfe_threshold` (default 0.5), `results_dir`
- `generate_windows()` → list of `(train_start, train_end, oos_start, oos_end)` date tuples; uses `_add_months()` with end-of-month clamping; stops when OOS end exceeds data range
- `compute_wfe(is_metrics, oos_metrics) -> float | None` — returns `None` when IS mean is zero or lists empty; raises `ValueError` on length mismatch
- `run_walk_forward()` — async orchestrator; exceptions per-window are caught and stored as `WindowResult(is_successful=False, error=...)`; JSON report written to `results_dir`
- `WalkForwardResult.is_deployable` — `False` when `wfe < min_wfe_threshold`; also `overfit_warning=True`
- `_create_evo_battle_runner(evo_config)` — named async factory for BattleRunner; primary test seam for evolutionary integration tests (patch `agent.strategies.walk_forward._create_evo_battle_runner`)
- Do NOT call `configure_agent_logging()` at module level — causes `AttributeError: 'PrintLogger' object has no attribute 'name'` in tests; use `structlog.get_logger(__name__)` directly
- RL integration uses `asyncio.to_thread` for SB3 (synchronous, CPU-bound)
- 94 tests in `agent/tests/test_walk_forward.py` (11 test classes)

## Retraining Pipeline (`agent/strategies/retrain.py`)
- `RetrainOrchestrator` manages 4 schedules: ensemble weights (8h), regime classifier (7d), genome population (7d, 2-3 new generations), PPO RL (30d, rolling 6-month window)
- All 4 `retrain_*()` methods are fully non-crashing — exceptions caught, returned as `RetrainResult(success=False)`
- A/B gate via `_build_comparison()`: no incumbent always deploys; improvement must exceed `config.min_improvement` (default 0.01)
- `run_scheduled_cycle()` checks elapsed hours and runs overdue jobs concurrently via `asyncio.gather`
- All training callables are injectable (constructor kwargs: `rl_trainer`, `genome_evolver`, `regime_trainer`, `ensemble_optimizer`) — primary test seam for mocking
- Schedule state persisted in `ScheduleState` in-memory; results persisted as JSON to `config.results_dir` via fire-and-forget async task
- Config via `RetrainConfig` (Pydantic BaseSettings, env prefix `RETRAIN_`)
- 57 unit tests in `agent/tests/test_retrain.py`

## Install Commands
```bash
pip install -e "agent/[rl]"          # SB3 + torch
pip install -e "agent/[evolutionary]"  # GA extras
pip install -e "agent/[ml]"          # all ML deps
pip install -e tradeready-gym/
```
- [project_reward_system.md](project_reward_system.md) — Reward function patterns, registration points, and CompositeReward implementation notes
- [feedback_test_patterns.md](feedback_test_patterns.md) — Test patterns confirmed in this codebase (gym tests, RLConfig tests, mock patterns)
- [project_evolutionary_oos.md](project_evolutionary_oos.md) — Task 12 OOS fitness upgrade: conventions, weight rationale, BattleRunner API extension
- [feedback_regime_feature_pipeline.md](feedback_regime_feature_pipeline.md) — How to add new features to the regime classifier (the 3-file pipeline pattern)
