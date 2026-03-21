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
- Config via `EnsembleConfig` (env prefix `ENSEMBLE_`); disable risk overlay with `enable_risk_overlay=False`
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

## Install Commands
```bash
pip install -e "agent/[rl]"          # SB3 + torch
pip install -e "agent/[evolutionary]"  # GA extras
pip install -e "agent/[ml]"          # all ML deps
pip install -e tradeready-gym/
```
