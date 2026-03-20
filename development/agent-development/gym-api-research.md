# Gym-API Research: Gymnasium Environments and Backtest API Interface

**Date:** 2026-03-20
**Researcher:** codebase-researcher agent
**Scope:** tradeready-gym/ package vs src/backtesting/engine.py + src/strategies/indicators.py

---

## Executive Summary

The tradeready-gym package wraps the TradeReady backtest REST API as Gymnasium-compatible environments.
Every reset() fires 3 HTTP calls (create + start + initial step) plus 1 candle fetch per asset.
Every step() fires 1 call minimum (advance time) plus 1 per placed order plus 1 candle fetch per asset.
The training tracker adds 1-2 background calls at episode boundaries.
Observations are flat float32 numpy arrays assembled client-side from candle data fetched each step.
Nine concrete gaps are documented in section 7.

---

## 1. API Calls per env.reset()

**Count: 3 core HTTP calls + 1 per asset + 1 on first episode.**

Source: base_trading_env.py lines 145-208.

| # | Method | Endpoint | Purpose |
|---|--------|----------|---------|
| 1 | POST | /api/v1/backtest/create | Creates backtest session; returns session_id |
| 2 | POST | /api/v1/backtest/{id}/start | Starts session, bulk-preloads all price data |
| 3 | POST | /api/v1/backtest/{id}/step | First step to populate prices and portfolio |

After call 3, _get_observation() issues one GET per asset in self.pairs:

    GET /api/v1/backtest/{id}/market/candles/{symbol}?interval={tf}&limit={window}

TrainingTracker calls (when track_training=True, the default):

- First reset() only: POST /api/v1/training/runs (idempotent via _registered flag)
- Subsequent reset() calls: register_run() is a no-op

| Scenario | HTTP Calls |
|----------|-----------|
| 1-asset env, first episode | 5 (create + start + step + 1 candle + register_run) |
| 1-asset env, subsequent episodes | 4 (create + start + step + 1 candle) |
| 5-asset portfolio, first episode | 9 (create + start + step + 5 candles + register_run) |
| 5-asset portfolio, subsequent episodes | 8 (create + start + step + 5 candles) |

---

## 2. API Calls per env.step() -- HOLD vs BUY/SELL

Source: base_trading_env.py lines 210-261; single_asset_env.py lines 58-114; multi_asset_env.py lines 46-98.

### HOLD Action (SingleAssetTradingEnv, action=0)

_execute_action() returns an empty list. The order loop executes zero times.

| Call | Method | Endpoint |
|------|--------|----------|
| 1 | POST | /api/v1/backtest/{id}/step |
| 2 | GET | /api/v1/backtest/{id}/market/candles/{symbol} |

HOLD total: 2 calls (single-asset), 1+N calls (N-asset portfolio).

Terminal step additional calls (when is_complete=True):

| Call | Method | Endpoint |
|------|--------|----------|
| +1 | GET | /api/v1/backtest/{id}/results |
| +1 | POST | /api/v1/training/runs/{run_id}/episodes |

Terminal HOLD = 4 calls (single-asset) or 3+N calls (N-asset).

### BUY Action (SingleAssetTradingEnv, action=1)

Returns 1 order dict when equity > 0 and price > 0.

| Call | Method | Endpoint |
|------|--------|----------|
| 1 | POST | /api/v1/backtest/{id}/trade/order |
| 2 | POST | /api/v1/backtest/{id}/step |
| 3 | GET | /api/v1/backtest/{id}/market/candles/{symbol} |

BUY total: 3 calls. Order rejection (httpx.HTTPStatusError) is caught silently; step still advances.

### SELL Action (SingleAssetTradingEnv, action=2)

- Position exists for symbol: 3 calls (order + step + candles)
- No position: _execute_action() returns [], same as HOLD -- 2 calls

### Continuous Action (continuous=True)

- |action[0]| < 0.05 dead zone: 2 calls (step + candles)
- Outside dead zone: 3 calls (order + step + candles)

### MultiAssetTradingEnv Step

Generates 0 to N rebalancing orders (one per asset where |diff| > equity * 0.01).

| Rebalance orders (K) | HTTP Calls |
|----------------------|-----------|
| 0 | 1 (step) + N (candles) |
| K > 0 | K (orders) + 1 (step) + N (candles) |

### Step Call Summary Table

| Action | SingleAsset | MultiAsset (N assets, K rebalance orders) |
|--------|-------------|------------------------------------------|
| HOLD / no rebalance | 2 | 1 + N |
| BUY or SELL (with position) | 3 | K + 1 + N |
| Any terminal step | +2 | +2 |

---

## 3. Observation Space Dimensions

Source: tradeready_gym/spaces/observation_builders.py

### Feature Dimension Table

**Candle features** (repeated lookback_window times per asset):

| Feature | Dims | Notes |
|---------|------|-------|
| ohlcv | 5 | open, high, low, close, volume |
| rsi_14 | 1 | RSI from close prices |
| macd | 3 | macd_line, macd_signal, macd_histogram |
| bollinger | 3 | upper_band, middle_band, lower_band |
| volume | 1 | raw volume -- redundant with ohlcv[4], see Gap 3 |
| adx | 1 | placeholder implementation, see Gap 1 |
| atr | 1 | ATR value |
| **total candle** | **15** | sum of all candle feature dims |

**Scalar features** (appended once, after all candle windows):

| Feature | Dims | Notes |
|---------|------|-------|
| balance | 1 | available_cash / starting_balance |
| position | 1 | position_value / total_equity |
| unrealized_pnl | 1 | unrealized_pnl / total_equity |
| **total scalar** | **3** | sum of all scalar dims |

### Formula

    obs_dim = (lookback_window * candle_feature_dims * n_assets) + scalar_feature_dims

### Concrete Examples

| Scenario | lookback | candle_dims | n_assets | scalar | Total |
|----------|---------|-------------|----------|--------|-------|
| Default 1-asset (ohlcv+rsi_14+macd, balance+position) | 30 | 9 | 1 | 2 | 272 |
| 1-asset, all 7 candle features + all 3 scalars | 30 | 15 | 1 | 3 | 453 |
| 5-asset portfolio, default features | 30 | 9 | 5 | 2 | 1352 |
| 5-asset portfolio, all features | 30 | 15 | 5 | 3 | 2253 |

Default observation_features = [ohlcv, rsi_14, macd, balance, position].
Gives 9 candle dims (5+1+3) and 2 scalar dims: (30*9*1)+2 = 272 for single-asset.

For 5-asset portfolio with all features: (30 * 15 * 5) + 3 = 2253.

### MACD Minimum Lookback

RSI requires 14 candles; MACD requires 26 (slow EMA period). If lookback_window < 26,
early candles produce NaN or 0 for those features. The default lookback_window=30 provides
only a 4-candle buffer above the minimum.

---

## 4. Reward Function Formulas

Source: tradeready_gym/rewards/

### PnLReward (pnl_reward.py)

    reward = curr_equity - prev_equity

Pure equity delta per step. Positive when equity grows. No windowing or normalization.

### SharpeReward (sharpe_reward.py)

    return_t = curr_equity - prev_equity
    _returns.append(return_t)   # rolling deque, window default 50
    if len(_returns) >= 2:
        mean = sum(_returns) / len(_returns)
        variance = sum((r-mean)**2 for r in _returns) / len(_returns)  # population variance
        sharpe = mean / sqrt(variance)  if sqrt(variance) > 1e-8  else 0.0
        reward = sharpe - _prev_sharpe
        _prev_sharpe = sharpe
    else:
        reward = 0.0

Key: reward is the DELTA of the Sharpe ratio per step, not the ratio itself.
reset() clears _returns and sets _prev_sharpe = 0.0.

### SortinoReward (sortino_reward.py)

    return_t = curr_equity - prev_equity
    _returns.append(return_t)
    if len(_returns) >= 2:
        mean = sum(_returns) / len(_returns)
        downside = [r for r in _returns if r < 0]
        if downside:
            downside_var = sum(r**2 for r in downside) / len(_returns)  # full window denominator
            sortino = mean / sqrt(downside_var)
        else:
            sortino = mean / 1e-8
        reward = sortino - _prev_sortino
        _prev_sortino = sortino
    else:
        reward = 0.0

Key: denominator uses len(_returns) (full window), not len(downside_returns).
reset() clears state identically to SharpeReward.

### DrawdownPenaltyReward (drawdown_penalty_reward.py)

    _peak_equity = max(_peak_equity, curr_equity)
    drawdown = (_peak_equity - curr_equity) / _peak_equity  if _peak_equity > 0  else 0.0
    pnl = curr_equity - prev_equity
    reward = pnl - penalty_coeff * drawdown

penalty_coeff default: 1.0. _peak_equity initialized to 0.0 (not starting_balance),
so first step sets peak = starting equity. reset() sets _peak_equity = 0.0.

### CustomReward (custom_reward.py)

Abstract base class. Implement compute(prev_equity, curr_equity, info) -> float.

The info dict contains the raw step response from the backtest API: virtual_time, prices,
orders_filled, portfolio (with total_equity, available_balance, unrealized_pnl), and n_trades.

reset() on CustomReward is a no-op by default -- override if your reward has per-episode state.

---

## 5. What Wrappers Add to Observation Space

Source: tradeready_gym/wrappers/

### FeatureEngineeringWrapper (feature_engineering.py)

Extends observation with SMA ratio and momentum for each period in periods.

    # periods default: [5, 10, 20]
    # For each period p:
    #   sma_ratio = current_close / sma_p      (1 dim)
    #   momentum  = current_close / close[t-p] (1 dim)
    # Plus 1 dim for current_close itself
    # Dims added = len(periods) * 2 + 1

For default periods=[5,10,20]: 3*2+1 = 7 dims added.

| Input obs shape | periods | Output obs shape |
|----------------|---------|------------------|
| 272 (1-asset default) | [5,10,20] | 279 |
| 453 (1-asset all features) | [5,10,20] | 460 |
| 2253 (5-asset all features) | [5,10,20] | 2260 |

Critical gotcha (Gap 5): reads observation[3] as close price (hardcoded index).
Only correct when ohlcv is the first feature (index 3 = close in OHLCV order).

### NormalizationWrapper (normalization.py)

Online Welford z-score normalization. Does NOT change observation shape.

    # For each dim i:
    #   mean_i, var_i updated via Welford algorithm each step
    #   normalized = (obs[i] - mean_i) / sqrt(var_i + eps)
    #   clipped to [-clip, clip], default clip=1.0

Stats accumulate across episodes within the same env instance.
Early episodes have poorly calibrated normalization until sufficient data accumulates.
Stats reset only when a new wrapper instance is created.

### BatchStepWrapper (batch_step.py)

Repeats the same action for n_steps underlying steps. Does NOT change observation shape.
Reward = sum of per-step rewards.

    # For each of n_steps sub-steps:
    #   obs, r, term, trunc, info = env.step(action)
    #   total_reward += r
    #   if term or trunc: break early
    # Returns: last_obs, total_reward, terminated, truncated, last_info

HTTP calls per wrapper step = n_steps * (underlying calls per action).
Observation and info are from the final sub-step only.

### Wrapper Composition Example

    env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...")
    # obs dim = 272
    env = FeatureEngineeringWrapper(env, periods=[5, 10, 20])
    # obs dim = 279  (+7)
    env = NormalizationWrapper(env)
    # obs dim = 279  (no change)
    env = BatchStepWrapper(env, n_steps=5)
    # obs dim = 279  (no change), each step() fires 5 underlying steps

---

## 6. TrainingTracker Payload Fields and Timing

Source: tradeready_gym/utils/training_tracker.py

### Registration -- POST /api/v1/training/runs

Called once per env instance (guarded by _registered flag). Called from reset().

    {
      "run_id": "<uuid4, generated at __init__ time>",
      "config": {
        "strategy_label": "<strategy_label param, default gym_training>"
      },
      "strategy_id": "<strategy_id if provided, else field omitted>"
    }

If registration fails (HTTP error), error is caught and track_training is silently disabled.

### Episode Report -- POST /api/v1/training/runs/{run_id}/episodes

Called from BaseTradingEnv.step() when is_complete=True, after _get_episode_results().

    {
      "episode_number": <int, incremented per completed episode>,
      "session_id": "<backtest session_id>",
      "roi_pct": <float from backtest results>,
      "sharpe_ratio": <float from backtest results>,
      "max_drawdown_pct": <float from backtest results>,
      "total_trades": <int from backtest results>,
      "reward_sum": null
    }

reward_sum is always null -- see Gap 2 for details.

### Completion -- POST /api/v1/training/runs/{run_id}/complete

Called from BaseTradingEnv.close() via tracker.complete_run(). Payload: empty body {}.
Always call env.close() at end of training to finalize the run.

### Timing Summary

| Event | API Call | Timing |
|-------|----------|--------|
| First reset() | POST /training/runs | Once per env instance |
| Subsequent reset() | register_run() no-op | No HTTP call |
| Terminal step() (is_complete=True) | POST /training/runs/{id}/episodes | Per completed episode |
| env.close() | POST /training/runs/{id}/complete | Once per env instance |

---

## 7. Gaps and Broken Integrations

Nine concrete issues found between the gym environments and the backtest API.

### Gap 1: ADX Implementation is a Placeholder

File: tradeready_gym/spaces/observation_builders.py lines 181-186.

The adx feature is computed as abs(close[i] - close[i-1]) / close[i-1] -- this is a simple
return magnitude, not the Average Directional Index. The real ADX requires Wilder smoothed
DM+/DM-/TR calculations over 14+ periods. Agents requesting adx receive price change magnitude
but their code may assume it is in the 0-100 ADX scale.

Fix: implement proper ADX in ObservationBuilder._compute_adx() or call IndicatorEngine (server-side).

### Gap 2: reward_sum Always Null in Episode Reports

File: tradeready_gym/utils/training_tracker.py line 90.

tracker.report_episode() calls metrics.get("reward_sum") but BaseTradingEnv never includes
reward_sum in the metrics dict passed to report_episode(). The field is always null in the DB.

Fix: accumulate episode reward in BaseTradingEnv._episode_reward, pass it to report_episode().

### Gap 3: volume Feature Duplicates ohlcv[4]

File: tradeready_gym/spaces/observation_builders.py _FEATURE_DIMS dict.

The volume feature (1 dim) returns raw volume -- identical to ohlcv[4] when both are requested.
This silently inflates observation size without adding information.

Fix: document the overlap, or remove volume from the default observation_features list.

### Gap 4: RSI/MACD Divergence Between Gym and Server

Files: tradeready_gym/spaces/observation_builders.py vs src/strategies/indicators.py.

The ObservationBuilder computes RSI and MACD client-side from raw candle data fetched from the API.
The IndicatorEngine in src/strategies/indicators.py computes the same indicators server-side.
These are separate implementations. If they use different epsilon values, warmup handling,
or EMA initialization, RSI and MACD values in observations will differ from strategy test results.

Fix: expose indicator computation as a backtest API endpoint; gym fetches pre-computed values.

### Gap 5: FeatureEngineeringWrapper Hardcodes Close Price Index

File: tradeready_gym/wrappers/feature_engineering.py

The wrapper reads observation[3] as the close price. This is correct only when ohlcv is the
first feature in the observation array (OHLCV order: open[0], high[1], low[2], close[3]).
If ohlcv is not first or observation layout changes, the wrapper silently uses the wrong value
for all SMA and momentum calculations -- no error is raised.

Fix: pass close_index as a constructor parameter, or read from ObservationBuilder.get_close_index().

### Gap 6: MACD Lookback vs Lookback Window

Files: tradeready_gym/envs/base_trading_env.py, tradeready_gym/spaces/observation_builders.py.

MACD slow EMA requires 26 candles. The lookback_window parameter controls how many candles are
fetched per step. If lookback_window < 26, the MACD computation silently returns 0 for early
candles. The default of 30 is safe but only barely (4-candle margin). No validation prevents
setting lookback_window=10 with macd in observation_features.

Fix: validate in __init__ that lookback_window >= max required indicator window when macd or rsi_14
is in observation_features.

### Gap 7: No agent_id in Backtest Sessions Created by Gym

File: tradeready_gym/envs/base_trading_env.py _create_session() lines 145-159.

The BacktestConfig sent to /api/v1/backtest/create does not include agent_id. Sessions are created
under the account context only. This means gym-created sessions are not associated with any
specific agent in the multi-agent system, and per-agent analytics will not reflect gym training.

Fix: add optional agent_id parameter to BaseTradingEnv and forward it to the backtest create request.

### Gap 8: MultiAssetTradingEnv Partial Weight Normalization

File: tradeready_gym/envs/multi_asset_env.py _execute_action() lines 46-98.

Weights are only normalized (divided by sum) when sum > 1.0. When the sum is between 0 and 1,
the weights are used as-is. This means an agent can output weights [0.1, 0.1, 0.1] (sum=0.3)
and only 30% of equity is allocated -- the rest stays in cash without explicit intent. The
behavior is documented in the CLAUDE.md gotcha but may surprise RL researchers expecting
full allocation semantics.

Fix: always normalize, or explicitly document the cash-retention behavior in the env docstring.

### Gap 9: Timeframe String Not Validated for API Compatibility

File: tradeready_gym/envs/base_trading_env.py

The timeframe constructor parameter (default "1m") is passed directly to the backtest API.
The gym CLAUDE.md documents valid values as ["1m","5m","15m","1h","4h","1d"] but there is no
validation in BaseTradingEnv.__init__(). An invalid timeframe (e.g. "2h") will cause the
backtest create request to fail at runtime, not at env construction time.

Fix: validate timeframe in __init__ against the allowed set; raise ValueError with a clear message.

---

## 8. Backtest Engine Interface Summary

Source: src/backtesting/engine.py

### StepResult Fields

Returned by BacktestEngine.step() and step_batch().

| Field | Type | Description |
|-------|------|-------------|
| virtual_time | datetime | Current simulated UTC timestamp |
| step | int | Current step number (1-indexed) |
| total_steps | int | Total steps in the backtest session |
| progress_pct | float | Completion percentage (0.0-100.0) |
| prices | dict[str, Decimal] | Current prices per symbol |
| orders_filled | list | Orders filled this step |
| portfolio | PortfolioSummary | total_equity, available_balance, unrealized_pnl |
| is_complete | bool | True on the last step |
| remaining_steps | int | Steps remaining (0 on last step) |

### Endpoint Map Used by Gym

| Gym Method | Endpoint | Engine Method |
|------------|----------|---------------|
| reset() create | POST /api/v1/backtest/create | BacktestEngine.create_session() |
| reset() start | POST /api/v1/backtest/{id}/start | BacktestEngine.start() |
| step() advance | POST /api/v1/backtest/{id}/step | BacktestEngine.step() |
| step() batch | POST /api/v1/backtest/{id}/step/batch | BacktestEngine.step_batch() |
| step() order | POST /api/v1/backtest/{id}/trade/order | BacktestEngine.execute_order() |
| _get_observation() | GET /api/v1/backtest/{id}/market/candles/{symbol} | BacktestEngine.get_candles() |
| _get_episode_results() | GET /api/v1/backtest/{id}/results | BacktestEngine.complete() result |

### Key Engine Behaviors

- **Bulk preload on start:** BacktestEngine.start() calls DataReplayer.preload_range() which
  executes one SQL query (UNION of candles_1m and candles_backfill) and loads all price data
  for the session time range into memory. Subsequent step() calls have zero DB round-trips
  for price lookups (O(log n) bisect).

- **Auto-complete on last step:** When TimeSimulator.is_complete is True, step() automatically
  calls complete(), which closes all positions, computes metrics, persists results, and removes
  the session from _active. Any subsequent call with that session_id raises BacktestNotFoundError.
  The gym handles this via is_complete check before returning from step().

- **Singleton engine:** BacktestEngine is instantiated once at module level in src/dependencies.py
  and shared across all requests. All active sessions live in its _active dict.

- **Snapshot frequency:** Equity snapshots are captured every 60 steps, on every fill, and on
  the last step. Reducing this modulo increases memory usage per session.

- **DB write frequency:** Progress is written to the DB every 500 steps. Between writes, only
  in-memory state is authoritative. If the server crashes, in-progress sessions become orphans
  and are marked failed on next startup.

- **No Redis:** All price serving during a backtest comes from the in-memory cache, not Redis.
  This is intentional for performance isolation from live trading traffic.

---

## 9. IndicatorEngine Available Indicators

Source: src/strategies/indicators.py

The IndicatorEngine computes server-side indicators for strategy evaluation. It is NOT used
by the gym ObservationBuilder (see Gap 4). It is used by the StrategyExecutor in
src/strategies/executor.py.

| Method | Period/Params | Min Data Points | Return Type |
|--------|--------------|-----------------|-------------|
| compute_rsi | period=14 | 15 | float or None |
| compute_macd | fast=12, slow=26, signal=9 | 27 | tuple(float,float,float) or None |
| compute_sma | period=20 | 20 | float or None |
| compute_sma_50 | period=50 | 50 | float or None |
| compute_ema | period=12 | 12 | float or None |
| compute_ema_26 | period=26 | 26 | float or None |
| compute_bollinger | period=20, std=2 | 20 | tuple(float,float,float) or None |
| compute_adx | period=14 | 29 | float or None |
| compute_atr | period=14 | 15 | float or None |
| compute_volume_ma | period=20 | 20 | float or None |

All methods return None when there is insufficient data (fewer than min_data_points candles).
All computations use pure numpy -- no external indicator library dependency.

The ADX implementation in IndicatorEngine is the real Wilder ADX (DM+/DM-/TR smoothed over 14
periods, requiring 2*period-1 = 27 data points minimum). This is distinct from the placeholder
in the gym ObservationBuilder (Gap 1).

---

*Research complete. All findings based on direct code inspection, not documentation.*