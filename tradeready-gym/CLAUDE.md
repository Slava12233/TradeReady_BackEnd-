# tradeready-gym/ — Gymnasium RL Environments

<!-- last-updated: 2026-03-22 -->

> Standalone Python package providing OpenAI Gymnasium-compatible trading environments backed by the TradeReady backtest REST API, for training RL agents on real crypto market data.

## What This Module Does

`tradeready-gym` wraps the TradeReady backtest engine as a set of Gymnasium environments. Each `reset()` call creates a new backtest session against the platform API; each `step()` advances the simulation by one candle and translates the agent's action into trading orders. The module ships 7 pre-registered environments, 4 reward functions (plus a custom base), 3 observation wrappers, and a `TrainingTracker` that auto-reports episode metrics back to the platform's training API.

This is an installable package (`pip install -e tradeready-gym/`) that is independent of the main platform source tree. It has its own `pyproject.toml`, dependencies, and test suite. It does **not** import from `src/` — all platform interaction goes through the REST API.

## Directory Structure

```
tradeready-gym/
├── pyproject.toml                    # Package config: tradeready-gym 0.1.0
├── README.md                         # Quick-start and environment table
├── tradeready_gym/
│   ├── __init__.py                   # Package root; all gym.register() calls; __version__ = "0.1.0"
│   ├── envs/
│   │   ├── __init__.py
│   │   ├── base_trading_env.py       # BaseTradingEnv — abstract base, HTTP client, session lifecycle
│   │   ├── single_asset_env.py       # SingleAssetTradingEnv — discrete or continuous single pair
│   │   ├── multi_asset_env.py        # MultiAssetTradingEnv — portfolio weight allocation (N assets)
│   │   └── live_env.py               # LiveTradingEnv — real-time paper trading with step intervals
│   ├── rewards/
│   │   ├── __init__.py
│   │   ├── custom_reward.py          # CustomReward — abstract base class for reward functions
│   │   ├── pnl_reward.py             # PnLReward — equity delta per step
│   │   ├── sharpe_reward.py          # SharpeReward — rolling Sharpe ratio delta
│   │   ├── sortino_reward.py         # SortinoReward — rolling Sortino ratio delta
│   │   └── drawdown_penalty_reward.py # DrawdownPenaltyReward — PnL minus drawdown penalty
│   ├── wrappers/
│   │   ├── __init__.py
│   │   ├── feature_engineering.py    # FeatureEngineeringWrapper — appends SMA/momentum features
│   │   ├── normalization.py          # NormalizationWrapper — online z-score normalization to [-1, 1]
│   │   └── batch_step.py             # BatchStepWrapper — holds action for N steps, sums rewards
│   ├── spaces/
│   │   ├── __init__.py
│   │   ├── action_spaces.py          # discrete_action_space() and continuous_action_space() presets
│   │   └── observation_builders.py   # ObservationBuilder — flat numpy array from candle + portfolio
│   └── utils/
│       ├── __init__.py
│       └── training_tracker.py       # TrainingTracker — reports episodes to /api/v1/training/* endpoints
```

## Key Files

| File | Purpose |
|------|---------|
| `tradeready_gym/__init__.py` | Triggers all `gymnasium.register()` calls on import; re-exports all public classes |
| `tradeready_gym/envs/base_trading_env.py` | `BaseTradingEnv(gym.Env)` — shared HTTP client (`httpx.Client`), session creation, `_get_observation()`, `_api_call()`, `render()`, `close()` |
| `tradeready_gym/envs/single_asset_env.py` | `SingleAssetTradingEnv` — overrides action space (Discrete or Box); translates action to buy/sell/hold order |
| `tradeready_gym/envs/multi_asset_env.py` | `MultiAssetTradingEnv` — `Box(0, 1, shape=(N,))` actions as target portfolio weights; issues rebalancing orders |
| `tradeready_gym/envs/live_env.py` | `LiveTradingEnv` — uses live market endpoints; `step()` sleeps `step_interval_sec` seconds between calls |
| `tradeready_gym/rewards/custom_reward.py` | `CustomReward(ABC)` — implement `compute(prev_equity, curr_equity, info) -> float` |
| `tradeready_gym/spaces/observation_builders.py` | `ObservationBuilder` — computes observation space shape and builds flat `float32` arrays |
| `tradeready_gym/utils/training_tracker.py` | `TrainingTracker` — creates a training run on first episode, reports per-episode metrics, finalizes on `complete_run()` |

## Registered Environments

All environments require at minimum an `api_key` kwarg passed to `gym.make()`.

| ID | Entry Point | Action Space | Symbol(s) | Notes |
|----|------------|--------------|-----------|-------|
| `TradeReady-BTC-v0` | `SingleAssetTradingEnv` | `Discrete(3)` | BTCUSDT | 0=Hold, 1=Buy, 2=Sell |
| `TradeReady-ETH-v0` | `SingleAssetTradingEnv` | `Discrete(3)` | ETHUSDT | 0=Hold, 1=Buy, 2=Sell |
| `TradeReady-SOL-v0` | `SingleAssetTradingEnv` | `Discrete(3)` | SOLUSDT | 0=Hold, 1=Buy, 2=Sell |
| `TradeReady-BTC-Continuous-v0` | `SingleAssetTradingEnv` | `Box(-1, 1, (1,))` | BTCUSDT | Negative=sell, positive=buy, magnitude=size |
| `TradeReady-ETH-Continuous-v0` | `SingleAssetTradingEnv` | `Box(-1, 1, (1,))` | ETHUSDT | Negative=sell, positive=buy, magnitude=size |
| `TradeReady-Portfolio-v0` | `MultiAssetTradingEnv` | `Box(0, 1, (3,))` | BTC+ETH+SOL | Each element = target portfolio weight |
| `TradeReady-Live-v0` | `LiveTradingEnv` | `Discrete(3)` | BTCUSDT | Real-time; blocks per candle interval |

## `BaseTradingEnv` Constructor Parameters

All subclasses pass `**kwargs` to `BaseTradingEnv`. These are the shared parameters:

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `api_key` | `str` | required | TradeReady `ak_live_...` key |
| `base_url` | `str` | `"http://localhost:8000"` | Platform REST API base URL |
| `starting_balance` | `float` | `10000.0` | Virtual USDT per episode |
| `timeframe` | `str` | `"1m"` | Candle interval (`"1m"`, `"5m"`, `"15m"`, `"1h"`, `"4h"`, `"1d"`) |
| `lookback_window` | `int` | `30` | Number of historical candles in observation |
| `reward_function` | `CustomReward \| None` | `PnLReward()` | Reward calculator |
| `observation_features` | `list[str] \| None` | `["ohlcv", "rsi_14", "macd", "balance", "position"]` | Features to include in observation |
| `start_time` | `str` | `"2025-01-01T00:00:00Z"` | Backtest start (ISO 8601) |
| `end_time` | `str` | `"2025-02-01T00:00:00Z"` | Backtest end (ISO 8601) |
| `track_training` | `bool` | `True` | Report episodes to the training API |
| `strategy_label` | `str` | `"gym_training"` | Label for created backtest sessions |
| `render_mode` | `str \| None` | `None` | `"human"` or `"ansi"` |

## Reward Functions

| Class | Formula | Key Parameter(s) |
|-------|---------|-----------------|
| `CustomReward` | Abstract base — implement `compute()` | — |
| `PnLReward` | `curr_equity - prev_equity` | None |
| `SharpeReward` | Delta of rolling Sharpe ratio | `window` (default 50) |
| `SortinoReward` | Delta of rolling Sortino ratio (downside vol only) | `window` (default 50) |
| `DrawdownPenaltyReward` | `(curr_equity - prev_equity) - penalty_coeff * drawdown` | `penalty_coeff` (default 1.0) |
| `CompositeReward` | `0.4*sortino_increment + 0.3*pnl_normalized + 0.2*activity_bonus + 0.1*drawdown_penalty` | `sortino_weight`, `pnl_weight`, `activity_weight`, `drawdown_weight`, `sortino_window` (default 50), `activity_bonus` (default 1.0) |

To use a non-default reward, pass it as `reward_function=SharpeReward(window=100)` to `gym.make()`.

## Wrappers

| Class | Base | What It Does |
|-------|------|-------------|
| `FeatureEngineeringWrapper` | `gym.ObservationWrapper` | Appends SMA ratio and momentum features for configurable `periods` list |
| `NormalizationWrapper` | `gym.ObservationWrapper` | Online Welford z-score normalization clipped to `[-clip, clip]` (default `clip=1.0`) |
| `BatchStepWrapper` | `gym.Wrapper` | Repeats the same action for `n_steps` candles; reward is the sum; reduces HTTP call frequency |

Wrappers are composable and follow the standard Gymnasium wrapper API:

```python
env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...")
env = FeatureEngineeringWrapper(env, periods=[5, 20, 50])
env = NormalizationWrapper(env)
env = BatchStepWrapper(env, n_steps=5)
```

## Observation Features

The `ObservationBuilder` constructs a flat `float32` numpy array. Features are split into two groups:

**Candle features** (per candle, per asset, repeated `lookback_window` times):

| Feature Name | Dimensions | Description |
|-------------|-----------|-------------|
| `ohlcv` | 5 | open, high, low, close, volume |
| `rsi_14` | 1 | RSI value computed from close prices |
| `macd` | 3 | macd_line, macd_signal, macd_histogram |
| `bollinger` | 3 | upper band, middle band, lower band |
| `volume` | 1 | raw volume |
| `adx` | 1 | ADX value |
| `atr` | 1 | ATR value |

**Scalar features** (appended once, not windowed):

| Feature Name | Dimensions | Description |
|-------------|-----------|-------------|
| `balance` | 1 | available cash / starting_balance |
| `position` | 1 | position value / total equity |
| `unrealized_pnl` | 1 | unrealized PnL / total equity |

**Total observation dimension formula:**
`(lookback_window × sum_candle_dims × n_assets) + sum_scalar_dims`

Default features `["ohlcv", "rsi_14", "macd", "balance", "position"]` with `lookback_window=30`, `n_assets=1`:
`(30 × (5+1+3) × 1) + (1+1) = 272`

## Key Patterns

### Creating and Using an Environment

```python
import gymnasium as gym
import tradeready_gym  # must import to trigger registration

env = gym.make(
    "TradeReady-BTC-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-02-01T00:00:00Z",
    reward_function=tradeready_gym.SharpeReward(window=50),
)

obs, info = env.reset()
for _ in range(1000):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        obs, info = env.reset()

env.close()
```

### Implementing a Custom Reward

```python
from tradeready_gym.rewards.custom_reward import CustomReward

class MyReward(CustomReward):
    def compute(self, prev_equity: float, curr_equity: float, info: dict) -> float:
        pnl = curr_equity - prev_equity
        n_trades = info.get("n_trades", 0)
        return pnl - 0.01 * n_trades  # penalise overtrading
```

### Reset / Step Cycle

1. `reset()` — calls `_create_session()` which POSTs to `/api/v1/backtest/create` then `/start`. Returns the first observation.
2. `step(action)` — translates action to an order (or no-op for hold), calls `/api/v1/backtest/{id}/step`, builds the next observation, computes reward via `reward_fn.compute()`, checks for termination.
3. Termination — `terminated=True` when the backtest engine signals the end of the time range (last candle reached). `truncated=True` is not currently used by the base environments.
4. `close()` — shuts down the `httpx.Client`. If `TrainingTracker` is active, calls `complete_run()` to finalize the training run on the platform.

### TrainingTracker Integration

When `track_training=True` (default), `BaseTradingEnv` instantiates a `TrainingTracker`. It creates a training run on the platform's training API during the first episode and posts per-episode metrics (total reward, steps, final equity, trades) after each `reset()` that follows a completed episode. Disable with `track_training=False` if you do not want to record training runs.

### `BaseTradingEnv` Uses Synchronous HTTP

The base environment uses `httpx.Client` (synchronous), not `httpx.AsyncClient`. This is intentional — Gymnasium's `step()` and `reset()` are synchronous by convention and are used with synchronous RL frameworks (Stable-Baselines3, RLlib). Do not switch to async unless you are wrapping the env in a custom async training loop.

## API Endpoints Used

| Env Method | HTTP Call |
|-----------|-----------|
| `reset()` | `POST /api/v1/backtest/create`, `POST /api/v1/backtest/{id}/start` |
| `step()` | `POST /api/v1/backtest/{id}/step` (or `/step/batch` via `BatchStepWrapper`) |
| `_get_observation()` | `GET /api/v1/backtest/{id}/market/candles/{symbol}` |
| `TrainingTracker` | `POST /api/v1/training/runs`, `POST /api/v1/training/runs/{id}/episodes` |
| `LiveTradingEnv.step()` | Live market + order endpoints (not backtest) |

## Dependencies

Defined in `pyproject.toml` under `[project.dependencies]`:

| Package | Version | Purpose |
|---------|---------|---------|
| `gymnasium` | `>=0.29` | RL environment base classes |
| `numpy` | `>=1.26` | Observation arrays |
| `httpx` | `>=0.28` | Synchronous HTTP calls to the platform API |

Optional:
- `tradeready-sdk` (`pip install -e "tradeready-gym/[sdk]"`) — not required; gym uses raw HTTP

Dev (`pip install -e "tradeready-gym/[dev]"`): `pytest`, `pytest-asyncio`, `respx`, `ruff`

## Installation

```bash
# From source (development)
pip install -e tradeready-gym/

# With SDK extras
pip install -e "tradeready-gym/[sdk]"
```

The package registers its environments via the `gymnasium.envs` entry point in `pyproject.toml`, so importing `tradeready_gym` is sufficient to make all IDs available to `gym.make()`.

## Gotchas

- **Import side-effect is required.** `gymnasium.register()` calls only execute when `tradeready_gym` is imported. Always add `import tradeready_gym` before any `gym.make("TradeReady-*")` call. Forgetting this produces a `gymnasium.error.UnregisteredEnv`.
- **`starting_balance` is `float`, not `Decimal`.** RL frameworks (SB3, numpy) work with floats. The base env stores it as `float` but converts to `Decimal` via `str(Decimal(str(...)))` before sending to the API to avoid float precision issues in JSON.
- **`base_url` is SSRF-validated.** `_validate_base_url()` rejects non-http/https schemes and URLs without a host. This prevents redirecting API calls to internal services.
- **`symbol` inputs are uppercased and regex-validated.** `_validate_symbol()` enforces `^[A-Z0-9]{2,20}$`. Passing a slash-separated pair like `"BTC/USDT"` will raise `ValueError`.
- **`LiveTradingEnv.step()` blocks for `step_interval_sec` seconds (default 60).** It is not suitable for fast batch training. Use backtest environments for training; live env is for paper trading only.
- **`BatchStepWrapper` sums rewards across sub-steps.** The observation returned is from the final sub-step. If any sub-step terminates the episode, the wrapper stops early and returns `terminated=True`.
- **`NormalizationWrapper` uses running statistics.** Stats are updated online using Welford's algorithm and accumulate across episodes within the same env instance. Stats reset only if you create a new wrapper instance. This means early episodes have poorly calibrated normalization.
- **`TrainingTracker` is not closed automatically by `step()`.** It is finalized inside `env.close()`. Always call `env.close()` at the end of training (or use a `try/finally` block) to ensure the training run is marked as complete on the platform.
- **`MultiAssetTradingEnv` portfolio weights are not constrained to sum to 1.** The env accepts any non-negative weight vector. Weights are normalized internally before computing order sizes.
- **`observation_features` default includes `rsi_14` and `macd`.** These require enough historical candles to compute (14 for RSI, 26 for slow MACD EMA). If `lookback_window` is set below 26, the computed values will be NaN or zero for early candles.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
- `2026-03-22` — Added `CompositeReward` class (rewards/composite.py). Updated rewards/__init__.py and tradeready_gym/__init__.py to export it. Added 41-test suite in tests/test_composite_reward.py.
