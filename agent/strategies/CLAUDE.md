# agent/strategies/ — Agent Trading Strategy System

<!-- last-updated: 2026-03-23 -->

> Five complementary strategy implementations that can operate independently or together through the ensemble combiner. All strategies execute against the platform's backtest or live sandbox APIs using existing SDK and REST tool integrations.

## Overview

The `agent/strategies/` package provides a complete multi-strategy trading agent layer:

| Sub-package / file | Approach | Primary use |
|-------------------|----------|-------------|
| `rl/` | PPO reinforcement learning via Stable-Baselines3 | Learn portfolio weights from raw market observations |
| `evolutionary/` | Genetic algorithm over `StrategyGenome` parameter vectors | Optimise RSI/MACD rule-based strategies via battle-based fitness |
| `regime/` | Market regime classification (XGBoost / RandomForest) | Select the best rule-based strategy for the current market condition |
| `risk/` | Portfolio-level risk overlay | Gate and resize every trade signal before execution |
| `ensemble/` | Weighted meta-learner | Combine RL + EVOLVED + REGIME signals into a single `ConsensusSignal` |
| `walk_forward.py` | Rolling walk-forward validation | Compute WFE for RL, evolutionary, and regime strategies; WFE >= 50% required to deploy |
| `walk_forward_results/` | Walk-forward output | JSON reports from validation runs (e.g., `regime_wf_report.json`) |
| `drift.py` | Distribution drift detection | `DriftDetector` (Page-Hinkley test) on log-returns; integrated into `TradingLoop._observe()` |
| `retrain.py` | Retraining orchestrator | `RetrainOrchestrator`: 4 schedules (ensemble 8h, regime 7d, genome 7d, PPO 30d) with A/B gate |

The strategies layer sits **above** the platform API. It consumes `PlatformRESTClient` and `AsyncAgentExchangeClient` from `agent/tools/` but has no direct DB access. All fitness evaluation happens through the platform's backtest or battle APIs.

---

## Package-level Public API (`agent/strategies/__init__.py`)

```python
from agent.strategies import (
    # RL
    RLConfig,
    # Evolutionary
    StrategyGenome, Population, BattleRunner,
    tournament_select, crossover, mutate, clip_genome,
    # Risk
    RiskConfig, RiskAssessment, TradeApproval, RiskAgent,
    # Regime
    RegimeType, label_candles, generate_training_data, RegimeClassifier,
    TRENDING_STRATEGY, MEAN_REVERTING_STRATEGY,
    HIGH_VOLATILITY_STRATEGY, LOW_VOLATILITY_STRATEGY,
    STRATEGY_BY_REGIME, create_regime_strategies,
    # Ensemble
    SignalSource, TradeAction, WeightedSignal, ConsensusSignal, MetaLearner,
)
```

---

## Sub-package Inventory

### `rl/` — PPO Reinforcement Learning

Trains, evaluates, and deploys a PPO portfolio agent via Stable-Baselines3 on the `TradeReady-Portfolio-v0` gymnasium environment.

| File | Key class / function | Purpose |
|------|---------------------|---------|
| `config.py` | `RLConfig` | Pydantic-settings for all PPO hyperparameters. Env prefix `RL_`. |
| `train.py` | `train(config) -> Path` | Run PPO training; returns path to saved `.zip` model. |
| `evaluate.py` | `ModelEvaluator`, `EvaluationReport`, `StrategyMetrics` | Load models, run on held-out test split, compare against 3 benchmarks. |
| `deploy.py` | `PPODeployBridge` | Load a trained model and drive it against backtest session or live account. |
| `data_prep.py` | CLI script | Validate OHLCV data coverage across train/val/test splits before training. |
| `runner.py` | `SeedMetrics`, CLI script | Orchestrate full pipeline: validate → train multiple seeds → evaluate → compare. |

#### Key class: `RLConfig` (`config.py`)

Pydantic v2 `BaseSettings`, env prefix `RL_`. Key fields:

| Field | Default | Purpose |
|-------|---------|---------|
| `learning_rate` | `3e-4` | Adam optimiser LR |
| `n_steps` | `2048` | Steps per env per update |
| `total_timesteps` | `500_000` | Total training budget |
| `n_envs` | `4` | Parallel training environments |
| `reward_type` | `"sharpe"` | One of: `pnl`, `sharpe`, `sortino`, `drawdown`, `composite` |
| `env_symbols` | `["BTCUSDT","ETHUSDT","SOLUSDT"]` | Assets for `TradeReady-Portfolio-v0` |
| `train_start` / `train_end` | `2024-01-01` / `2024-10-01` | ISO-8601 training window |
| `val_start` / `val_end` | `2024-10-01` / `2024-12-01` | ISO-8601 validation window |
| `test_start` / `test_end` | `2024-12-01` / `2025-01-01` | ISO-8601 held-out test window |
| `platform_api_key` | `""` | TradeReady `ak_live_...` key (required) |
| `models_dir` | `agent/strategies/rl/models/` | Checkpoint and final model output |

#### Key class: `ModelEvaluator` (`evaluate.py`)

| Method | Returns | Description |
|--------|---------|-------------|
| `load_models(model_dir)` | `dict[str, PPO]` | Scan for `ppo_seed*.zip` files and load |
| `evaluate(model_dir, seed_filter)` | `EvaluationReport` | Run test-split evaluation + 3 benchmarks + optional ensemble |

Benchmarks always evaluated: equal-weight rebalancing, buy-and-hold BTC, buy-and-hold ETH.

#### CLI Commands (`rl/`)

```bash
# Validate data availability before training
python -m agent.strategies.rl.data_prep \
    --base-url http://localhost:8000 \
    --assets BTCUSDT ETHUSDT SOLUSDT

# Train a single seed (full run)
python -m agent.strategies.rl.train \
    --timesteps 500000 \
    --reward sharpe

# Quick smoke test (no platform tracking)
python -m agent.strategies.rl.train --timesteps 1000 --no-track

# Train multiple seeds + evaluate (pipeline runner)
python -m agent.strategies.rl.runner --seeds 42,123,456 --timesteps 500000

# Evaluate trained models on test split
python -m agent.strategies.rl.evaluate --model-dir agent/strategies/rl/models/

# Deploy against backtest session
python -m agent.strategies.rl.deploy \
    --model agent/strategies/rl/models/ppo_seed42.zip \
    --mode backtest \
    --session-id <uuid>

# Deploy live (paper-trading sandbox)
python -m agent.strategies.rl.deploy \
    --model agent/strategies/rl/models/ppo_seed42.zip \
    --mode live \
    --steps 100
```

> API keys are read from `agent/.env` via `AgentConfig` — never pass them as `--api-key` CLI arguments.

---

### `evolutionary/` — Genetic Algorithm Optimisation

Evolves `StrategyGenome` parameter vectors using a genetic algorithm whose fitness function is evaluated through the platform's historical battle system.

| File | Key class / function | Purpose |
|------|---------------------|---------|
| `genome.py` | `StrategyGenome` | 12-parameter trading strategy encoded as a numpy float64 vector |
| `operators.py` | `tournament_select`, `crossover`, `mutate`, `clip_genome` | GA operators on `StrategyGenome` vectors |
| `population.py` | `Population`, `PopulationStats` | Manage a generation; `initialize()`, `evolve(scores)`, `stats(scores)` |
| `battle_runner.py` | `BattleRunner` | Provision agents, assign strategies, run historical battles, extract fitness |
| `evolve.py` | CLI script | Full evolution loop: validate → initialise → N generations → champion |
| `analyze.py` | CLI script | Post-run analysis of `evolution_log.json`: fitness curve, parameter convergence |
| `config.py` | `EvolutionConfig` | Pydantic-settings for GA parameters. Env prefix `EVO_`. |

#### Key class: `StrategyGenome` (`genome.py`)

Encodes a strategy as a fixed-length float64 numpy vector. Parameters:

- **Scalars**: `rsi_oversold` [20–40], `rsi_overbought` [60–80], `adx_threshold` [15–35], `stop_loss_pct` [0.01–0.05], `take_profit_pct` [0.02–0.10], `trailing_stop_pct` [0.005–0.03], `position_size_pct` [0.03–0.20]
- **Integers**: `macd_fast` [8–15], `macd_slow` [20–30], `max_hold_candles` [10–200], `max_positions` [1–5]
- **Pairs**: subset bitmask of 6 USDT pairs

`to_strategy_definition()` produces the JSONB-compatible dict for `POST /api/v1/strategies`.

#### Key class: `BattleRunner` (`battle_runner.py`)

Fitness formula: `fitness = sharpe_ratio - 0.5 * max_drawdown_pct`. Agents with missing results receive `FAILURE_FITNESS = -999.0`.

Methods: `setup_agents(n)`, `reset_agents()`, `assign_strategies(genomes)`, `run_battle()`, `get_fitness()`.

#### CLI Commands (`evolutionary/`)

```bash
# Run evolution (30 generations, pop size 12)
python -m agent.strategies.evolutionary.evolve --generations 30 --pop-size 12

# Quick smoke test (2 generations, pop size 4)
python -m agent.strategies.evolutionary.evolve --generations 2 --pop-size 4 --seed 42

# Analyse results from a completed evolution run
python -m agent.strategies.evolutionary.analyze \
    --log-path agent/strategies/evolutionary/results/evolution_log.json
```

---

### `regime/` — Market Regime Detection

Labels market candles into four regime types and trains a classifier (XGBoost preferred, sklearn RandomForest fallback) to predict the current regime. The `RegimeSwitcher` activates the matching pre-built strategy at each decision step.

| File | Key class / function | Purpose |
|------|---------------------|---------|
| `labeler.py` | `RegimeType`, `label_candles`, `generate_training_data` | Rule-based regime labelling using ADX + ATR/close ratio |
| `classifier.py` | `RegimeClassifier` | Train, predict, evaluate, save, load the regime classifier |
| `switcher.py` | `RegimeSwitcher`, `SwitchEvent` | Detect current regime; enforce confidence threshold and cooldown before switching |
| `strategy_definitions.py` | `TRENDING_STRATEGY`, `MEAN_REVERTING_STRATEGY`, etc. | Pre-built `StrategyDefinition`-compatible dicts for each regime |
| `validate.py` | CLI script | 12-month sequential backtests comparing regime-adaptive vs static MACD vs buy-and-hold |
| `__init__.py` | Re-exports | All public symbols listed above |

#### Regime taxonomy

| `RegimeType` | Detection rule |
|-------------|----------------|
| `TRENDING` | ADX > 25 |
| `HIGH_VOLATILITY` | ATR/close > 2× median |
| `LOW_VOLATILITY` | ATR/close < 0.5× median |
| `MEAN_REVERTING` | All remaining candles |

#### Key class: `RegimeClassifier` (`classifier.py`)

6-feature input vector: ADX, ATR/close, Bollinger Band width, RSI-14, MACD histogram, volume_ratio (current volume / 20-period SMA of volume). XGBoost preferred; falls back to `RandomForestClassifier` if xgboost is not installed.

| Method | Description |
|--------|-------------|
| `train(features, labels)` | Fit classifier on labelled data |
| `predict(row_df)` | Return `(RegimeType, confidence: float)` |
| `evaluate(test_features, test_labels)` | Return accuracy, per-class precision/recall |
| `save(path)` / `load(path)` | Persist via joblib |

#### Key class: `RegimeSwitcher` (`switcher.py`)

Tracks the active strategy ID and fires a `SwitchEvent` when the classifier predicts a new regime with confidence above `confidence_threshold` and the `cooldown_candles` since the last switch has elapsed.

`switcher.step(candles) -> (RegimeType, strategy_id, switched: bool)`

#### CLI Commands (`regime/`)

```bash
# Train the regime classifier on 12 months of BTC 1h data
python -m agent.strategies.regime.classifier \
    --train \
    --data-url http://localhost:8000

# Run 12-month validation (regime-adaptive vs static MACD vs buy-and-hold)
python -m agent.strategies.regime.validate \
    --base-url http://localhost:8000 \
    --months 12

# Demo: switcher on synthetic data (no platform connection needed)
python -m agent.strategies.regime.switcher --demo --candles 300
```

---

### `risk/` — Risk Management Overlay

Portfolio-level risk checks that complement the platform's built-in per-order risk manager (`src/risk/manager.py`). Operates at the aggregate exposure level, not per-order.

| File | Key class / function | Purpose |
|------|---------------------|---------|
| `risk_agent.py` | `RiskAgent`, `RiskConfig`, `RiskAssessment`, `TradeApproval`, `DrawdownProfile`, `DrawdownTier` | Assess portfolio state; gate proposed trades; tiered drawdown-based size reduction |
| `veto.py` | `VetoPipeline`, `VetoDecision` | 6-gate sequential pipeline: HALT → confidence → exposure → sector → drawdown; `scale_factor` on `VetoDecision` |
| `sizing.py` | `DynamicSizer`, `SizerConfig`, `KellyFractionalSizer`, `HybridSizer`, `SizingMethod` | Volatility-/drawdown-/Kelly-adjusted position sizing |
| `middleware.py` | `RiskMiddleware`, `ExecutionDecision` | Wires `RiskAgent`, `VetoPipeline`, `DynamicSizer` into a single async middleware; step 5 adds correlation-aware size reduction |

#### Key class: `RiskAgent` (`risk_agent.py`)

`assess(portfolio, positions, pnl) -> RiskAssessment` — returns one of `"OK"`, `"REDUCE"`, `"HALT"`:

- `"HALT"` — daily PnL loss exceeds `daily_loss_halt` threshold
- `"REDUCE"` — portfolio drawdown exceeds `max_drawdown_trigger`
- `"OK"` — within acceptable bounds

`check_trade(signal, assessment) -> TradeApproval` — pre-trade check combining the assessment verdict with signal-level size limits.

`DrawdownProfile` + `DrawdownTier`: tiered size reduction schedule as drawdown deepens. Three presets:

| Preset | Tier thresholds | Behaviour |
|--------|----------------|-----------|
| `AGGRESSIVE` | 5 % / 10 % / 15 % | Reduce to 75% / 50% / 25% |
| `MODERATE` | 3 % / 6 % / 10 % | Reduce to 70% / 45% / 20% |
| `CONSERVATIVE` | 2 % / 4 % / 7 % | Reduce to 60% / 35% / 10% |

#### Key class: `VetoPipeline` (`veto.py`)

Six sequential gates (short-circuit on first VETOED; RESIZED continues):
1. Risk verdict is HALT → VETOED
2. Signal confidence < 0.5 → VETOED
3. Exceeds max portfolio exposure → RESIZED
4. Same-sector concentration (≥ 2 existing positions in sector) → VETOED
5. Recent drawdown > 3% → RESIZED (halve position)
6. All checks passed → APPROVED

#### Key class: `RiskMiddleware` (`middleware.py`)

Full signal processing pipeline per step:
1. Fetch portfolio state via SDK
2. `RiskAgent.assess()` → `RiskAssessment`
3. `VetoPipeline.evaluate()` → `VetoDecision`
4. `DynamicSizer.calculate_size()` → final size
5. (optional) Execute via SDK `place_market_order()`

Returns `ExecutionDecision` — never raises; all errors surfaced in `ExecutionDecision.error`.

No standalone CLI. Used programmatically from `ensemble/run.py` and any strategy's trading loop.

---

### `ensemble/` — Ensemble Signal Combiner

Combines signals from RL, EVOLVED, and REGIME strategy sources into a single `ConsensusSignal` using weighted voting. Includes a weight optimizer that runs 12 backtest configurations to find optimal source weights.

| File | Key class / function | Purpose |
|------|---------------------|---------|
| `signals.py` | `SignalSource`, `TradeAction`, `WeightedSignal`, `ConsensusSignal` | Data models for typed signal flow |
| `meta_learner.py` | `MetaLearner` | Weighted voting combiner with RL/genome/regime signal converters |
| `optimize_weights.py` | CLI script | Evaluate 12 weight configurations via backtests; save optimal weights |
| `run.py` | `EnsembleRunner` | Full pipeline orchestrator: candles → signals → MetaLearner → RiskMiddleware → order |
| `validate.py` | CLI script | Cross-strategy comparison: Ensemble vs PPO-only vs Evolved-only vs Regime-only + buy-and-hold |
| `config.py` | `EnsembleConfig` | Pydantic-settings for ensemble parameters. Env prefix `ENSEMBLE_`. |

#### Key class: `MetaLearner` (`meta_learner.py`)

Voting algorithm per symbol:
1. Group `WeightedSignal` instances by symbol
2. Score each action: `score = sum(signal.confidence × weight[source])`
3. Winning action = highest score
4. `combined_confidence = winning_score / total_active_weight`
5. If `combined_confidence < confidence_threshold` → override to HOLD
6. If all sources disagree → HOLD

Static converters: `rl_weights_to_signals(weights, symbols)`, `genome_to_signals(genome)`, `regime_to_signals(regime_type)`.

#### CLI Commands (`ensemble/`)

```bash
# Optimise ensemble source weights (12 configurations, ~7-day backtest each)
python -m agent.strategies.ensemble.optimize_weights \
    --base-url http://localhost:8000 \
    --seed 42

# Run full ensemble pipeline in backtest mode
python -m agent.strategies.ensemble.run \
    --mode backtest \
    --base-url http://localhost:8000

# Validate: Ensemble vs PPO-only vs Evolved-only vs Regime-only (3 periods)
python -m agent.strategies.ensemble.validate \
    --base-url http://localhost:8000 \
    --periods 3
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `stable-baselines3` | PPO training and model inference (`rl/`) |
| `torch` | Neural network backend for SB3 |
| `gymnasium` | RL environment protocol; uses `tradeready-gym` envs |
| `xgboost` | Preferred regime classifier (optional — falls back to sklearn) |
| `scikit-learn` | RandomForest fallback for regime classifier; preprocessing |
| `joblib` | Model persistence for `RegimeClassifier` |
| `numpy` / `pandas` | Feature computation and genome vector operations |
| `pydantic-settings` | Config classes (`RLConfig`, `EvolutionConfig`, `EnsembleConfig`) |
| `structlog` | Structured JSON logging across all modules |

All extra dependencies are declared in `agent/pyproject.toml` under optional extras (e.g., `pip install -e "agent/[rl]"`, `pip install -e "agent/[evolutionary]"`). The core `agent/` package does not require them.

---

## Architecture and Data Flow

```
Incoming candles (from platform API)
        │
        ├── rl/deploy.py (PPODeployBridge)    → PPO portfolio weight vector
        ├── evolutionary/ (StrategyGenome)     → RSI/MACD rule state
        └── regime/ (RegimeSwitcher)           → regime → directional bias
                │
                ▼
        ensemble/meta_learner.py (MetaLearner)
                │
                ▼
        risk/middleware.py (RiskMiddleware)  [optional overlay]
                │
                ▼
        ExecutionDecision → platform SDK / REST (order placement)
```

The `risk/` overlay is inserted between the MetaLearner output and order execution. It can be disabled (`enable_risk_overlay=False` in `EnsembleConfig`) for raw signal testing.

---

## Patterns and Conventions

- **All financial values as `Decimal`** — money amounts and size fractions use `decimal.Decimal` internally; converted to `float` only at JSON output boundaries.
- **ISO-8601 strings for dates** — all date/time config fields are plain strings, never `datetime` objects, to avoid precision loss when forwarding to the backtest API.
- **Env prefixes per sub-package** — `RL_` for `RLConfig`, `EVO_` for `EvolutionConfig`, `ENSEMBLE_` for `EnsembleConfig`. All read from `agent/.env`.
- **No platform logic in strategies layer** — all HTTP calls go through `PlatformRESTClient` or `AsyncAgentExchangeClient` from `agent/tools/`. Strategies never call `httpx` directly.
- **Fitness is always scalar** — evolutionary and regime modules reduce multi-metric results to a single float so the population/switcher logic stays algorithm-agnostic.
- **Non-crashing middleware** — `RiskMiddleware` and `BattleRunner` catch all exceptions per signal/generation and surface them in result models. Callers always receive a valid result object.
- **Concurrent API calls via `asyncio.gather`** — N+1 sequential API call patterns have been replaced with `asyncio.gather` where multiple independent requests are made (e.g., fetching candles for multiple symbols simultaneously).
- **Blocking I/O via `asyncio.to_thread`** — file system operations (model load/save, checksum read/write) are wrapped in `asyncio.to_thread` to avoid blocking the event loop.
- **Bounded caches via `collections.deque`** — observation buffers and rolling windows use `collections.deque(maxlen=N)` to prevent unbounded memory growth during long runs.
- **Model integrity via SHA-256 checksums** — `checksum.py` provides `save_checksum()` / `verify_checksum()` for `.zip` and `.joblib` model files. Call `save_checksum()` after every model save and `verify_checksum()` before every model load. `SecurityError` is raised on digest mismatch. `verify_checksum(path, strict=True)` is the default — missing sidecars raise `SecurityError`. Pass `strict=False` only in development.
- **No `--api-key` CLI arguments** — API keys are read exclusively from `agent/.env` via `AgentConfig`. Passing secrets on the command line would expose them in shell history and `ps` output.

## Recent Changes

- `2026-03-23` — R3-01: Regime classifier trained (99.92% accuracy, WFE 97.46%, Sharpe 1.14 vs MACD 0.74). R3-04: `walk_forward_regime()` added to `walk_forward.py`. Checksum `strict=True` now default (missing sidecars raise `SecurityError`). 0 HIGH security issues remaining across all strategy files.
- `2026-03-22` — Tasks 28/31/attribution: Added `retrain.py` (`RetrainOrchestrator`, 4 schedules, A/B gate, 57 tests), `drift.py` (`DriftDetector` Page-Hinkley test, integrated into `TradingLoop`), `ensemble/attribution.py` (`AttributionLoader`, `AttributionResult`, auto-pause via `StrategyCircuitBreaker`, 45 tests). All 37/37 Trading Agent Master Plan tasks complete.
- `2026-03-22` — Task 29: Added `walk_forward.py` with rolling walk-forward validation. `WalkForwardConfig` (env prefix `WF_`), `WindowResult`, `WalkForwardResult` Pydantic models; `generate_windows()`, `compute_wfe()` pure functions; `run_walk_forward()` algorithm-agnostic orchestrator; `walk_forward_rl()` integration (mocked SB3 train/eval via `asyncio.to_thread`); `walk_forward_evolutionary()` integration (mocked BattleRunner via `_create_evo_battle_runner` factory); `TrainingRunner.walk_forward_train()` synchronous wrapper; `walk_forward_evolve()` in `evolve.py`. WFE < 50% triggers `overfit_warning=True` and `is_deployable=False`. Report written as JSON to `walk_forward_results/`. CLI entry point via `python -m agent.strategies.walk_forward --strategy rl`. 94 unit tests in `agent/tests/test_walk_forward.py`.
- `2026-03-22` — Task 28: Added `retrain.py` with `RetrainOrchestrator`. Manages 4 retraining schedules: ensemble weights (8h), regime classifier (7d), genome population (7d, 2–3 new generations), PPO RL (30d, rolling 6-month window). A/B gate on all deployments (`_build_comparison` + `min_improvement` threshold). All training callables injectable for testing. 57 unit tests in `agent/tests/test_retrain.py`.
- `2026-03-22` — Phase 1 branch + Phase 2 independent upgrades. Regime: `volume_ratio` added as 6th feature (189 tests). RL: `composite` reward type + 5 config fields. Evolutionary: 5-factor OOS composite fitness, `oos_split_ratio`, `get_detailed_metrics()`. Risk: `KellyFractionalSizer`, `HybridSizer`, `SizingMethod`; `DrawdownProfile`/`DrawdownTier` + 3 presets; `_check_correlation()` step 5 in middleware; `scale_factor` on `VetoDecision`. Ensemble: `StrategyCircuitBreaker` (Redis-backed, 3 triggers, TTL). 361 new tests.
- `2026-03-20` — Perf fixes, security fixes, CLI --api-key removed.
- `2026-03-21` — All strategy submodules migrated to `configure_agent_logging()`: `rl/` (5 files), `evolutionary/` (2 files), `ensemble/` (3 files), `regime/` (2 files) now call `configure_agent_logging()` at startup and use standardized structlog event names. `ensemble/run.py` adds `LogBatchWriter` for per-strategy signal persistence to `agent_strategy_signals` DB table.

---

## Security Utilities

### `checksum.py` — Model File Integrity

`agent/strategies/checksum.py` provides SHA-256 checksum verification for pickle-based model files (SB3 `.zip` and joblib `.joblib`). Defends against insecure deserialization (OWASP A8).

| Symbol | Purpose |
|--------|---------|
| `SecurityError` | Exception raised when a digest mismatch is detected |
| `compute_checksum(path)` | Compute SHA-256 hex digest (streaming, 8 KiB chunks) |
| `save_checksum(path)` | Write `<file>.sha256` sidecar; returns sidecar path |
| `verify_checksum(path)` | Read sidecar and compare; raises `SecurityError` on mismatch; returns `True` on pass or missing sidecar (with WARNING) |

Sidecar naming: `ppo_seed42.zip` → `ppo_seed42.zip.sha256`.

---

## Sub-CLAUDE.md Index

Each sub-package has its own `CLAUDE.md` with full file inventories, public API docs, CLI commands, and gotchas:

| Path | Description |
|------|-------------|
| `agent/strategies/rl/CLAUDE.md` | `RLConfig`, `train()`, `ModelEvaluator`, `PPODeployBridge`; SB3 pipeline, CLI commands, model output gotchas |
| `agent/strategies/evolutionary/CLAUDE.md` | `StrategyGenome` (12 params), `Population`, `BattleRunner`; GA operators, fitness formula, CLI commands |
| `agent/strategies/regime/CLAUDE.md` | `RegimeClassifier` (XGBoost/RF), `RegimeSwitcher` (cooldown+confidence), 4 pre-built strategy dicts, CLI |
| `agent/strategies/risk/CLAUDE.md` | `RiskAgent`, `VetoPipeline` (6 gates), `DynamicSizer`, `RiskMiddleware` async entry point |
| `agent/strategies/ensemble/CLAUDE.md` | `MetaLearner` (weighted voting), `EnsembleRunner` (6-stage pipeline), weight optimiser CLI |

---

## Gotchas

- **`stable-baselines3` + `torch` are not installed by default** — `rl/train.py` and `rl/evaluate.py` will fail with `ImportError` if these packages are missing. Install via `pip install stable-baselines3[extra]`.
- **`xgboost` is optional** — `RegimeClassifier` detects at import time whether xgboost is available; if not, it silently uses `RandomForestClassifier`. Both produce a `.joblib` file.
- **`rl/models/` is gitignored** — trained `.zip` files are not committed. Regenerate them with `python -m agent.strategies.rl.runner`.
- **`BattleRunner` requires JWT auth** — the evolutionary battle endpoints (`POST /api/v1/battles`) require `Authorization: Bearer` JWT. The runner calls `POST /api/v1/auth/login` on construction using credentials from `AgentConfig`.
- **`RegimeSwitcher` cooldown** — the switcher will not change strategy more than once per `cooldown_candles` (default 20) regardless of classifier confidence. This prevents thrashing in choppy regimes.
- **`VetoPipeline` RESIZED does not short-circuit** — a RESIZED decision continues through remaining gates. The final size is the product of all resize factors applied in sequence.
- **`PPODeployBridge` needs `lookback_window` candles** — the bridge must have at least `config.lookback_window` (default 30) candles in the observation buffer before producing valid weight predictions.
