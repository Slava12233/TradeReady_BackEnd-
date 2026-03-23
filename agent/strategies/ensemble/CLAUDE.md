# agent/strategies/ensemble/ — Ensemble Signal Combiner

<!-- last-updated: 2026-03-22 -->

> Combines signals from RL, evolutionary, and regime strategy sources into a single `ConsensusSignal` using weighted voting, with optional weight optimisation via backtest grid search.

## What This Module Does

The `ensemble/` sub-package is the top-level orchestrator of the entire strategy system. It receives typed `WeightedSignal` objects from the three strategy sources (PPO RL weights, evolved genome rule states, regime strategy bias), combines them using weighted confidence voting in `MetaLearner`, routes the result through the `RiskMiddleware` overlay, and executes the final order via the SDK.

A weight optimiser CLI runs 12 backtest configurations to find optimal source weights and writes them to `optimal_weights.json` for use by `EnsembleRunner`. Attribution-driven weight adjustment reads 7-day Celery-computed PnL attribution from the DB and feeds it to `MetaLearner` at session start via `EnsembleRunner.load_attribution()`.

231 unit tests cover all components.

## Key Files

| File | Purpose |
|------|---------|
| `signals.py` | `SignalSource`, `TradeAction`, `WeightedSignal`, `ConsensusSignal` — typed data models for signal flow. |
| `meta_learner.py` | `MetaLearner` — weighted voting combiner; static converters for RL/genome/regime signals; `apply_attribution_weights()` for session-level weight bootstrapping. |
| `attribution.py` | `AttributionLoader`, `AttributionResult` — reads 7-day `AgentPerformance` attribution rows, updates `MetaLearner` weights, auto-pauses negative-PnL strategies via `StrategyCircuitBreaker`. |
| `circuit_breaker.py` | `StrategyCircuitBreaker` — per-strategy Redis-backed circuit breaker with 3 trigger rules. |
| `optimize_weights.py` | CLI script — 12 weight configurations grid search via backtests; writes `optimal_weights.json`. |
| `run.py` | `EnsembleRunner` — 6-stage step pipeline: candles → signals → MetaLearner → RiskMiddleware → execute → record. Also exposes `load_attribution()` for session-start weight bootstrapping. |
| `validate.py` | CLI script — 4-strategy comparison: Ensemble vs PPO-only vs Evolved-only vs Regime-only over 3 time periods. |
| `config.py` | `EnsembleConfig` — Pydantic-settings for ensemble parameters. Env prefix `ENSEMBLE_`. |

## Public API

```python
from agent.strategies.ensemble.signals import SignalSource, TradeAction, WeightedSignal, ConsensusSignal
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.circuit_breaker import StrategyCircuitBreaker
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

### `StrategyCircuitBreaker` (`circuit_breaker.py`)

Per-strategy circuit breaker backed by Redis.  Tracks three independent failure signals and triggers automatic pauses stored as Redis keys with TTL.  All methods are async and fail-open on Redis errors.

**Trigger rules:**

| Rule | Threshold | Pause |
|------|-----------|-------|
| Consecutive losses | 3 in a row | 24h (`strategy:circuit:{name}:{agent_id}` key with TTL) |
| Weekly drawdown | Cumulative PnL < −5 % over 7 days | 48h (same key) |
| Ensemble accuracy | >60 % wrong in last 20 signals | No pause — reduce all sizes to 25 % |

**Redis key patterns:**

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `strategy:circuit:{name}:{agent_id}` | String (JSON) | 24h or 48h | Pause sentinel |
| `strategy:losses:{name}:{agent_id}` | List | 49h | Last N outcomes (`"loss"` / `"win"`) |
| `strategy:weekly_pnl:{name}:{agent_id}` | String (float) | 7d | Cumulative PnL fraction |
| `strategy:accuracy:{agent_id}` | List | 7d | Last 20 signal outcomes (`"0"` / `"1"`) |

**Key methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `is_paused(name, agent_id)` | `bool` | Check if strategy is currently paused |
| `pause(name, agent_id, seconds, reason)` | `None` | Set pause key with TTL |
| `resume(name, agent_id)` | `None` | Manually delete pause key |
| `record_loss(name, agent_id)` | `None` | Append loss; triggers 24h pause at threshold |
| `record_win(name, agent_id)` | `None` | Append win (breaks consecutive streak) |
| `record_pnl_contribution(name, agent_id, pnl_pct)` | `None` | Accumulate PnL; triggers 48h pause at −5 % |
| `get_weekly_pnl(name, agent_id)` | `float` | Current cumulative weekly PnL |
| `record_signal_outcome(agent_id, correct)` | `None` | Record 1/0 into accuracy list |
| `ensemble_accuracy(agent_id)` | `float \| None` | Accuracy over last 20 signals; `None` if window not full |
| `size_multiplier(agent_id)` | `float` | 0.25 if accuracy poor, 1.0 otherwise |
| `filter_active_sources(sources, agent_id)` | `list[str]` | Return non-paused subset |
| `apply_size_multiplier(size_pct, agent_id)` | `float` | Scale size by accuracy multiplier |

**Wire into `EnsembleRunner`:**

```python
import redis.asyncio as aioredis
from agent.strategies.ensemble import EnsembleRunner, EnsembleConfig, StrategyCircuitBreaker

redis_client = aioredis.from_url("redis://localhost:6379")
cb = StrategyCircuitBreaker(redis_client=redis_client)
runner = EnsembleRunner(
    config=EnsembleConfig(),
    sdk_client=sdk,
    rest_client=rest,
    circuit_breaker=cb,
    agent_id="550e8400-...",
)
await runner.initialize()
# Paused sources are now automatically skipped each step.
# Sizes are reduced to 25 % when ensemble accuracy drops.
```

### `EnsembleRunner` (`run.py`)

6-stage step cycle (now 7 with circuit breaker):

| Stage | Action |
|-------|--------|
| 0 | Check `StrategyCircuitBreaker.is_paused()` for each source (if CB wired) |
| 1 | Fetch latest candles for all configured symbols via SDK |
| 2 | Collect signals from active (non-paused) strategy sources; paused → HOLD |
| 3 | `MetaLearner.combine()` → `ConsensusSignal` per symbol |
| 3b | Resolve accuracy size multiplier via `StrategyCircuitBreaker.size_multiplier()` |
| 4 | `RiskMiddleware.process()` → `ExecutionDecision` (vetoed/resized/approved) |
| 4b | Apply accuracy size multiplier to final `size_pct` |
| 5 | Execute approved trades via SDK `place_market_order()` |
| 6 | Record step metrics for performance tracking |

`EnsembleRunner.step()` is the main entry point. It never raises; errors are logged and recorded in step metrics.

The `circuit_breaker` parameter is optional — pass `None` to disable circuit-breaker logic without changing any other behaviour.

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
- `2026-03-22` — Task 15: Extended `EnsembleReport` with financial metrics fields (Sharpe, win rate, ROI, max drawdown, final equity). Added `_fetch_backtest_metrics()` to `EnsembleRunner` (fetches `GET /api/v1/backtest/{id}/results` after the trading loop). Added `BacktestValidationReport` Pydantic model and `build_validation_report()` with 5 acceptance criteria. `_cli_main()` now saves a second `validation-report-backtest-*.json` in addition to the ensemble report. 40 new tests in `agent/tests/test_ensemble_backtest_validation.py`.
- `2026-03-22` — Added `circuit_breaker.py`: `StrategyCircuitBreaker` with 3 trigger rules (consecutive losses → 24h pause, weekly drawdown >5 % → 48h pause, ensemble accuracy <40 % → 25 % size reduction). Wired into `EnsembleRunner.__init__()` as optional `circuit_breaker` param; `step()` now skips paused sources and applies size multiplier. 56 new unit tests in `agent/tests/test_circuit_breaker.py`. `__init__.py` exports `StrategyCircuitBreaker`.
- `2026-03-22` — Dynamic ensemble weights (Task 23): `MetaLearner` now maintains per-source rolling Sharpe (deque maxlen=50) and exposes `update_weights(recent_outcomes, current_regime)`. `TradeOutcome` dataclass added. Regime-conditional modifiers (TRENDING RL+30%/EVOLVED-10%, MEAN_REVERTING EVOLVED+30%/RL-10%, HIGH_VOLATILITY all-50%/REGIME-30%, LOW_VOLATILITY RL+20%) applied after Sharpe reweighting, then weights renormalised to 1.0. `apply_attribution_weights()` provides session-level PnL-based bootstrapping. `EnsembleRunner` gains `record_trade_outcome()`, `_drain_pending_outcomes()`, `_last_regime` tracking; `step()` drains outcomes and calls `update_weights()` at step end (non-crashing). 55 new tests in `agent/tests/test_dynamic_weights.py`.
- `2026-03-22` — Task 31: Attribution-driven weight adjustment wired end-to-end. New `attribution.py`: `AttributionLoader` reads 7-day `AgentPerformance` rows with `period="attribution"` (written by the `agent_strategy_attribution` Celery task), calls `MetaLearner.apply_attribution_weights()` to proportionally adjust source weights, and auto-pauses strategies with negative 7-day PnL via `StrategyCircuitBreaker.pause()` (48h TTL). `EnsembleRunner.load_attribution()` added as the session-start entrypoint; it is a no-op before `initialize()`. `__init__.py` exports `AttributionLoader` and `AttributionResult`. 45 new tests in `agent/tests/test_attribution.py`.
