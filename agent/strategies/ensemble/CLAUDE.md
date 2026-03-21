# agent/strategies/ensemble/ — Ensemble Signal Combiner

<!-- last-updated: 2026-03-21 -->

> Combines signals from RL, evolutionary, and regime strategy sources into a single `ConsensusSignal` using weighted voting, with optional weight optimisation via backtest grid search.

## What This Module Does

The `ensemble/` sub-package is the top-level orchestrator of the entire strategy system. It receives typed `WeightedSignal` objects from the three strategy sources (PPO RL weights, evolved genome rule states, regime strategy bias), combines them using weighted confidence voting in `MetaLearner`, routes the result through the `RiskMiddleware` overlay, and executes the final order via the SDK.

A weight optimiser CLI runs 12 backtest configurations to find optimal source weights and writes them to `optimal_weights.json` for use by `EnsembleRunner`.

146 unit tests cover all components.

## Key Files

| File | Purpose |
|------|---------|
| `signals.py` | `SignalSource`, `TradeAction`, `WeightedSignal`, `ConsensusSignal` — typed data models for signal flow. |
| `meta_learner.py` | `MetaLearner` — weighted voting combiner; static converters for RL/genome/regime signals. |
| `optimize_weights.py` | CLI script — 12 weight configurations grid search via backtests; writes `optimal_weights.json`. |
| `run.py` | `EnsembleRunner` — 6-stage step pipeline: candles → signals → MetaLearner → RiskMiddleware → execute → record. |
| `validate.py` | CLI script — 4-strategy comparison: Ensemble vs PPO-only vs Evolved-only vs Regime-only over 3 time periods. |
| `config.py` | `EnsembleConfig` — Pydantic-settings for ensemble parameters. Env prefix `ENSEMBLE_`. |

## Public API

```python
from agent.strategies.ensemble.signals import SignalSource, TradeAction, WeightedSignal, ConsensusSignal
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.run import EnsembleRunner
from agent.strategies.ensemble.config import EnsembleConfig
```

### Signal Types (`signals.py`)

| Class | Fields | Purpose |
|-------|--------|---------|
| `SignalSource` | Str-enum: `RL`, `EVOLVED`, `REGIME` | Identifies which strategy produced a signal |
| `TradeAction` | Str-enum: `BUY`, `SELL`, `HOLD` | Signal direction |
| `WeightedSignal` | `source`, `symbol`, `action`, `confidence` (0–1) | A single source's signal for a symbol |
| `ConsensusSignal` | `symbol`, `action`, `confidence`, `source_votes` (dict) | Final combined signal from MetaLearner |

### `MetaLearner` (`meta_learner.py`)

Voting algorithm per symbol:
1. Group `WeightedSignal` instances by symbol
2. Score each action: `score = sum(signal.confidence × weight[source])`
3. Winning action = highest total score
4. `combined_confidence = winning_score / sum_active_source_weights`
5. If `combined_confidence < confidence_threshold` → override to HOLD
6. If all sources disagree (no clear winner) → HOLD

| Method | Returns | Description |
|--------|---------|-------------|
| `combine(signals: list[WeightedSignal])` | `list[ConsensusSignal]` | Combine signals into one per symbol |
| `rl_weights_to_signals(weights: np.ndarray, symbols: list[str])` | `list[WeightedSignal]` | Convert PPO portfolio weight vector to `WeightedSignal` list |
| `genome_to_signals(genome: StrategyGenome)` | `list[WeightedSignal]` | Convert evolved genome rule state to signals |
| `regime_to_signals(regime_type: RegimeType)` | `list[WeightedSignal]` | Convert active regime to directional bias signals |

`rl_weights_to_signals()` normalises the weight vector and only emits `BUY` signals for assets above a size threshold (default 15% of portfolio). Weights below threshold produce `HOLD`.

### `EnsembleRunner` (`run.py`)

6-stage step cycle:

| Stage | Action |
|-------|--------|
| 1 | Fetch latest candles for all configured symbols via SDK |
| 2 | Collect signals from all active strategy sources |
| 3 | `MetaLearner.combine()` → `ConsensusSignal` per symbol |
| 4 | `RiskMiddleware.process()` → `ExecutionDecision` (vetoed/resized/approved) |
| 5 | Execute approved trades via SDK `place_market_order()` |
| 6 | Record step metrics for performance tracking |

`EnsembleRunner.step()` is the main entry point. It never raises; errors are logged and recorded in step metrics.

### `EnsembleConfig` (`config.py`)

Pydantic-settings, env prefix `ENSEMBLE_`. Key fields:

| Field | Default | Purpose |
|-------|---------|---------|
| `rl_weight` | `0.4` | Relative weight for RL signals |
| `evolved_weight` | `0.35` | Relative weight for evolutionary signals |
| `regime_weight` | `0.25` | Relative weight for regime signals |
| `confidence_threshold` | `0.55` | Minimum combined confidence to act (below → HOLD) |
| `enable_risk_overlay` | `True` | Whether to route through `RiskMiddleware` |
| `symbols` | `["BTCUSDT","ETHUSDT","SOLUSDT"]` | Symbols the runner operates on |
| `optimal_weights_path` | `None` | Path to `optimal_weights.json`; overrides `rl_weight` etc. if set |

## CLI Commands

```bash
# Optimise source weights (12 backtest configurations, ~7-day window each)
python -m agent.strategies.ensemble.optimize_weights \
    --base-url http://localhost:8000 \
    --api-key ak_live_... \
    --seed 42

# Run the full ensemble pipeline in backtest mode
python -m agent.strategies.ensemble.run \
    --mode backtest \
    --base-url http://localhost:8000 \
    --api-key ak_live_...

# Validate: Ensemble vs PPO-only vs Evolved-only vs Regime-only (3 time periods)
python -m agent.strategies.ensemble.validate \
    --base-url http://localhost:8000 \
    --api-key ak_live_... \
    --periods 3
```

## Patterns

- **MetaLearner falls back to HOLD** when `combined_confidence < confidence_threshold` or all sources disagree. Missing or conflicting signals never produce speculative trades.
- **`enable_risk_overlay=False`** in `EnsembleConfig` disables the `RiskMiddleware` for raw signal testing. Always enable in live or backtest evaluation.
- **Weight optimisation is recommended** before production use. Run `optimize_weights.py` after major strategy updates; save optimal weights to `optimal_weights.json` and point `EnsembleConfig.optimal_weights_path` at it.
- **Data flow** (see `agent/strategies/CLAUDE.md` for the full architecture diagram):
  `candles → [rl/deploy.py, evolutionary/genome.py, regime/switcher.py] → ensemble/meta_learner.py → risk/middleware.py → SDK order`

## Gotchas

- **All strategy sources must be pre-warmed.** `PPODeployBridge` needs `lookback_window` candles; `RegimeSwitcher` needs enough candles for ADX/ATR computation (≥20). Start `EnsembleRunner` with a warm-up period before evaluating performance.
- **`rl_weights_to_signals()` normalises the weight vector.** PPO outputs raw weights; this converter normalises them to sum to 1 before thresholding. Do not pre-normalise before calling.
- **`EnsembleRunner.step()` is synchronous from the caller's perspective** but internally awaits SDK calls. Use it in an async context (`asyncio.run()` or inside an async loop).
- **Weight sum does not need to be 1.** `MetaLearner` normalises by active source weight sum, so `rl_weight=0.4`, `evolved_weight=0.35`, `regime_weight=0.25` and `rl_weight=4.0`, `evolved_weight=3.5`, `regime_weight=2.5` produce identical results.
- **`optimal_weights.json` is not gitignored.** Unlike trained model files, the weights JSON is small and deterministic — commit it after running `optimize_weights.py` for reproducibility.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
- `2026-03-21` — `run.py` integrates `LogBatchWriter`: after each step, per-strategy signal data (source, action, confidence, symbol) is written to the `agent_strategy_signals` DB table via async batched flush. `run.py`, `meta_learner.py`, and `config.py` all call `configure_agent_logging()` at startup and use standardized event names.
