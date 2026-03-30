---
type: plan
tags:
  - implementation
  - strategy
  - roadmap
  - intern-guide
  - a-to-z
date: 2026-03-23
status: active
audience: intern + CTO
---

# Full Implementation Plan A-Z — Module by Module

> **What this is:** The exact step-by-step build plan for our strategy search system. Every module, what it does, what files to create, what it depends on, and the order to build it.
>
> **The goal:** Find the ONE best trading strategy using automated search (autoresearch + genetic evolution + backtesting + battles + walk-forward validation).

---

## What We Have vs What We Need

### Already Built (green light — working in production)

| # | Module | Status | Location |
|---|--------|--------|----------|
| 1 | PPO RL strategy + training | DONE | `agent/strategies/rl/` |
| 2 | Genetic algorithm + evolution | DONE | `agent/strategies/evolutionary/` |
| 3 | Regime classifier + switcher | DONE | `agent/strategies/regime/` |
| 4 | Risk overlay (veto + sizing) | DONE | `agent/strategies/risk/` |
| 5 | Ensemble combiner + meta-learner | DONE | `agent/strategies/ensemble/` |
| 6 | Drift detection (Page-Hinkley) | DONE | `agent/strategies/drift.py` |
| 7 | Walk-forward (RL + evo + regime) | DONE | `agent/strategies/walk_forward.py` |
| 8 | Retrain orchestrator (4 schedules) | DONE | `agent/strategies/retrain.py` |
| 9 | Backtesting engine + sandbox | DONE | `src/backtesting/` |
| 10 | Battle system (live + historical) | DONE | `src/battles/` |
| 11 | Trading loop + signal generator | DONE | `agent/trading/` |
| 12 | 600+ pair real-time data | DONE | `src/price_ingestion/` |
| 13 | Celery ML training tasks | DONE | `src/tasks/retrain_tasks.py` |
| 14 | 7 Gymnasium environments | DONE | `tradeready-gym/` |
| 15 | Monitoring (7 dashboards, 11 alerts) | DONE | `monitoring/` |

### Needs To Be Built (the plan below)

| # | Module | Priority | Depends On |
|---|--------|----------|-----------|
| A | Unified Feature Pipeline | FIRST | Nothing (foundation) |
| B | Pluggable Signal Interface | FIRST | Nothing (foundation) |
| C | Deflated Sharpe Ratio | FIRST | Nothing (safety gate) |
| D | Volume Spike Detector | HIGH | Module A |
| E | Cross-Sectional Momentum | HIGH | Modules A, B |
| F | Mean Reversion Strategy | HIGH | Modules A, B |
| G | Autoresearch Harness | HIGH | Module C |
| H | Autoresearch Strategy Template | HIGH | Module G |
| I | Pairs Trading / Stat-Arb | HIGH | Module A |
| J | Walk-Forward for Ensemble | MEDIUM | Nothing (extends existing) |
| K | LLM Sentiment Signal | MEDIUM | Module B |
| L | Funding Rate Monitor | MEDIUM | Nothing |
| M | External Data Connectors | MEDIUM | Modules K, L |
| N | Transformer Price Prediction | LOWER | Module A, B |
| O | Synthetic Data Generator | LOWER | Module A |
| P | Order Flow Analysis | LOWER | Module A, B |

---

## Build Order (The Dependency Chain)

```
PHASE 1 — Foundation (Week 1-2)
  Module A: Unified Feature Pipeline ─────────┐
  Module B: Pluggable Signal Interface ────────┤
  Module C: Deflated Sharpe Ratio ─────────────┤
                                               │
PHASE 2 — First New Strategies (Week 3-4) ◄────┘
  Module D: Volume Spike Detector
  Module E: Cross-Sectional Momentum
  Module F: Mean Reversion Strategy

PHASE 3 — Autoresearch (Week 5-6)
  Module G: Autoresearch Harness
  Module H: Autoresearch Strategy Template

PHASE 4 — Statistical Arbitrage (Week 7-8)
  Module I: Pairs Trading / Stat-Arb
  Module J: Walk-Forward for Ensemble

PHASE 5 — Data & Sentiment (Week 9-10)
  Module K: LLM Sentiment Signal
  Module L: Funding Rate Monitor
  Module M: External Data Connectors

PHASE 6 — Advanced ML (Week 11+)
  Module N: Transformer Price Prediction
  Module O: Synthetic Data Generator
  Module P: Order Flow Analysis
```

---

## PHASE 1 — Foundation (Week 1-2)

These three modules are infrastructure. Every future module depends on them.

---

### Module A: Unified Feature Pipeline

**What it does:** Right now, features (RSI, MACD, Bollinger, etc.) are computed in 3 separate places with no sharing. This module creates ONE feature engine that all strategies use.

**Why it's first:** Every new strategy needs features. Without this, each strategy re-implements the same indicators — wasteful and bug-prone.

**Files to create:**

```
agent/strategies/features/
  __init__.py          — exports FeatureEngine, FeatureSet
  engine.py            — FeatureEngine class: computes all indicators from candles
  registry.py          — feature registry: name → compute function mapping
  indicators.py        — individual indicator functions (RSI, MACD, Bollinger, ADX, ATR, etc.)
  cache.py             — Redis-backed feature cache (avoid recomputing)
```

**FeatureEngine interface:**

```python
class FeatureEngine:
    """Computes trading features from raw candle data."""

    def compute(self, candles: list[dict], features: list[str]) -> dict[str, list[float]]:
        """
        Input: list of OHLCV candle dicts + list of feature names
        Output: dict mapping feature name → list of float values

        Example:
          engine.compute(candles, ["rsi_14", "macd_hist", "bb_width", "volume_zscore"])
          → {"rsi_14": [45.2, 48.1, ...], "macd_hist": [0.003, -0.001, ...], ...}
        """

    def compute_all(self, candles: list[dict]) -> dict[str, list[float]]:
        """Compute all registered features."""
```

**Feature registry (start with these, add more later):**

| Feature Name | What It Computes | Already Exists In |
|---|---|---|
| `rsi_14` | Relative Strength Index (14-period) | regime labeler, gym obs builder, signal gen |
| `macd_hist` | MACD histogram | regime labeler, gym obs builder |
| `macd_line` | MACD line | gym obs builder |
| `macd_signal` | MACD signal line | gym obs builder |
| `bb_width` | Bollinger Band width | regime labeler |
| `bb_upper` | Bollinger upper band | gym obs builder |
| `bb_lower` | Bollinger lower band | gym obs builder |
| `adx` | Average Directional Index | regime labeler |
| `atr` | Average True Range | regime labeler |
| `atr_ratio` | ATR / close price | regime labeler |
| `volume_ratio` | Current vol / 20-period SMA | regime labeler, signal gen |
| `volume_zscore` | Z-score of volume (NEW) | — |
| `sma_ratio_5` | Close / SMA(5) | gym wrapper |
| `sma_ratio_10` | Close / SMA(10) | gym wrapper |
| `sma_ratio_20` | Close / SMA(20) | gym wrapper |
| `momentum_5` | 5-period momentum | gym wrapper |
| `returns_1h` | 1-hour log return (NEW) | — |
| `returns_24h` | 24-hour log return (NEW) | — |
| `returns_7d` | 7-day log return (NEW) | — |

**Refactor plan:** After building FeatureEngine, update these three files to USE it instead of inline computation:
1. `agent/strategies/regime/labeler.py` → `engine.compute(candles, ["adx", "atr_ratio", "bb_width", "rsi_14", "macd_hist", "volume_ratio"])`
2. `tradeready_gym/spaces/observation_builders.py` → `engine.compute_all(candles)`
3. `agent/trading/signal_generator.py` → `engine.compute(candles, [...])`

**Tests:** ~30 tests in `agent/tests/test_features.py`

**Time:** 2-3 days
**Cost:** $0
**Dependencies:** None

---

### Module B: Pluggable Signal Interface

**What it does:** Right now, `SignalGenerator` is hardwired to `EnsembleRunner` which only accepts 3 sources (RL, evolved, regime). This module creates a plugin system so we can add new signal sources (momentum, mean reversion, sentiment, etc.) without modifying the ensemble core.

**Why it's first:** Every new strategy needs to plug into the trading system. Without this, each new strategy requires hacking the ensemble code.

**Files to create/modify:**

```
agent/strategies/signals/
  __init__.py          — exports SignalSource protocol, SignalRegistry
  protocol.py          — SignalSource protocol (abstract interface)
  registry.py          — SignalRegistry: register/discover signal sources
  base.py              — BaseSignalSource with common logic
```

**SignalSource protocol:**

```python
from typing import Protocol

class SignalSourceProtocol(Protocol):
    """Any strategy that can produce trading signals."""

    name: str                    # e.g., "momentum", "mean_reversion", "sentiment"

    async def generate(
        self,
        symbol: str,
        candles: list[dict],
        features: dict[str, list[float]]
    ) -> TradingSignal | None:
        """
        Input: symbol, candles, pre-computed features
        Output: a TradingSignal (BUY/SELL/HOLD + confidence) or None
        """
        ...
```

**SignalRegistry:**

```python
class SignalRegistry:
    """Register and discover signal sources."""

    def register(self, source: SignalSourceProtocol, weight: float = 0.1) -> None: ...
    def get_all(self) -> list[tuple[SignalSourceProtocol, float]]: ...
    def get(self, name: str) -> SignalSourceProtocol | None: ...
```

**Modify existing files:**
1. `agent/strategies/ensemble/run.py` — `EnsembleRunner` gains a `registry: SignalRegistry` parameter. In `step()`, it collects signals from all registered sources (not just the 3 hardcoded ones).
2. `agent/strategies/ensemble/meta_learner.py` — `MetaLearner` supports dynamic weight keys (not just `rl`/`evolved`/`regime`).
3. `agent/trading/signal_generator.py` — no longer hardwired to `EnsembleRunner` directly; uses the registry.

**Tests:** ~25 tests in `agent/tests/test_signal_registry.py`

**Time:** 2-3 days
**Cost:** $0
**Dependencies:** None

---

### Module C: Deflated Sharpe Ratio

**What it does:** A math formula that answers: "Given that we tested N strategies, is this result actually impressive or just luck?" This is our most important safety gate when mass-testing strategies.

**Why it's first:** Without this, every strategy we find through autoresearch or mass testing might be a statistical fluke.

**Files to create:**

```
agent/strategies/validation/
  __init__.py              — exports deflated_sharpe, validate_strategy
  deflated_sharpe.py       — deflated Sharpe ratio implementation
  strategy_validator.py    — combined validation gate (WFE + DSR + min trades + cost sensitivity)
```

**deflated_sharpe.py:**

```python
from scipy import stats
import math

def deflated_sharpe_ratio(
    observed_sharpe: float,
    num_trials: int,           # how many strategies we tested
    track_record_length: float, # in years
    skewness: float = 0.0,
    kurtosis: float = 3.0,     # normal = 3.0
) -> float:
    """
    Bailey & López de Prado (2014) Deflated Sharpe Ratio.

    Returns p-value (0 to 1). Only deploy if p-value > 0.95 (95% confident
    the result is not just luck from testing many strategies).

    Example:
      - Observed Sharpe: 2.0, tested 100 strategies, 1 year of data
      - DSR p-value: 0.72 → NOT significant (probably luck)

      - Observed Sharpe: 3.5, tested 100 strategies, 2 years of data
      - DSR p-value: 0.97 → Significant (probably real)
    """
    expected_max_sharpe = math.sqrt(2 * math.log(num_trials))
    se = math.sqrt(
        (1 - skewness * observed_sharpe + (kurtosis - 1) / 4 * observed_sharpe**2)
        / track_record_length
    )
    if se == 0:
        return 0.0
    test_stat = (observed_sharpe - expected_max_sharpe) / se
    return float(stats.norm.cdf(test_stat))
```

**strategy_validator.py — combined validation gate:**

```python
class StrategyValidator:
    """All-in-one validation gate. A strategy must pass ALL checks."""

    def validate(self, result: BacktestResult, num_trials: int) -> ValidationVerdict:
        checks = [
            self._check_min_trades(result),           # ≥ 50 trades
            self._check_max_drawdown(result),          # ≤ 30%
            self._check_positive_sharpe(result),       # > 0
            self._check_deflated_sharpe(result, num_trials),  # p > 0.95
            self._check_wfe(result),                   # ≥ 0.50 (if WF data available)
            self._check_cost_sensitivity(result),      # still profitable at 2x fees
            self._check_regime_diversity(result),       # works in ≥ 2 regimes
        ]
        return ValidationVerdict(
            passed=all(c.passed for c in checks),
            checks=checks,
        )
```

**Tests:** ~20 tests in `agent/tests/test_deflated_sharpe.py`

**Time:** 1-2 days
**Cost:** $0
**Dependencies:** `scipy` (already available)

---

## PHASE 2 — First New Strategies (Week 3-4)

Now that the foundation is laid, build the first batch of new strategy candidates.

---

### Module D: Volume Spike Detector

**What it does:** Scans all 600+ coins for abnormal volume. When a coin's volume spikes 3-5x above normal, it generates a signal.

**Why it matters:** Volume spikes often precede big price moves. This is the easiest new signal to build and helps ALL other strategies.

**Files to create:**

```
agent/strategies/signals/
  volume_spike.py      — VolumeSpikeDetector (implements SignalSourceProtocol)
```

**How it works:**

```python
class VolumeSpikeDetector:
    """Detects abnormal volume spikes across all symbols."""

    name = "volume_spike"

    async def generate(self, symbol, candles, features) -> TradingSignal | None:
        volume_zscore = features["volume_zscore"][-1]  # latest z-score

        if volume_zscore > 3.0:  # 3 standard deviations above normal
            # Volume spike detected! Check price direction for signal
            returns = features["returns_1h"][-1]
            if returns > 0:
                return TradingSignal(symbol=symbol, action="BUY", confidence=min(volume_zscore / 5.0, 0.95))
            else:
                return TradingSignal(symbol=symbol, action="SELL", confidence=min(volume_zscore / 5.0, 0.95))

        return None  # no spike, no signal
```

**Register with signal registry:**

```python
registry.register(VolumeSpikeDetector(), weight=0.15)
```

**Tests:** ~15 tests
**Time:** 1 day
**Cost:** $0
**Dependencies:** Module A (FeatureEngine for `volume_zscore`), Module B (SignalSourceProtocol)

---

### Module E: Cross-Sectional Momentum Strategy

**What it does:** Ranks all 600+ coins by recent returns. Buys the top performers, avoids the bottom.

**Files to create:**

```
agent/strategies/signals/
  momentum.py          — MomentumSignalSource (implements SignalSourceProtocol)

agent/strategies/momentum/
  __init__.py
  scanner.py           — MomentumScanner: ranks all symbols by returns
  config.py            — MomentumConfig (lookback periods, top/bottom percentiles)
```

**How it works:**

```python
class MomentumScanner:
    """Ranks all symbols by recent returns."""

    async def scan(self, all_candles: dict[str, list[dict]]) -> list[RankedSymbol]:
        """
        1. For each symbol, compute returns over multiple lookbacks (1h, 4h, 24h, 7d)
        2. Z-score normalize returns within each lookback
        3. Composite momentum score = weighted average of z-scores
        4. Return symbols ranked by composite score
        """

class MomentumSignalSource:
    """Generates BUY signals for top-momentum coins."""

    name = "momentum"

    async def generate(self, symbol, candles, features) -> TradingSignal | None:
        # Uses pre-computed rankings from MomentumScanner
        rank = self.scanner.get_rank(symbol)
        if rank is not None and rank <= self.config.top_percentile:
            return TradingSignal(symbol=symbol, action="BUY", confidence=...)
        return None
```

**Config defaults:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lookback_1h_weight` | 0.1 | Weight for 1-hour return |
| `lookback_4h_weight` | 0.2 | Weight for 4-hour return |
| `lookback_24h_weight` | 0.4 | Weight for 24-hour return |
| `lookback_7d_weight` | 0.3 | Weight for 7-day return |
| `top_percentile` | 10 | Top 10% = buy signal |
| `scan_interval_minutes` | 60 | Re-rank every hour |

**Tests:** ~20 tests
**Time:** 2-3 days
**Cost:** $0
**Dependencies:** Module A (returns features), Module B (signal protocol)

---

### Module F: Mean Reversion Strategy

**What it does:** Buys coins that dropped too far below their average, sells coins that rose too far above. Only active during MEAN_REVERTING regime.

**Files to create:**

```
agent/strategies/signals/
  mean_reversion.py    — MeanReversionSignalSource (implements SignalSourceProtocol)
```

**How it works:**

```python
class MeanReversionSignalSource:
    """Mean reversion signals using Bollinger Bands and RSI."""

    name = "mean_reversion"

    async def generate(self, symbol, candles, features) -> TradingSignal | None:
        # Only active during MEAN_REVERTING regime
        if self.current_regime != RegimeType.MEAN_REVERTING:
            return None

        rsi = features["rsi_14"][-1]
        bb_position = (close - bb_lower) / (bb_upper - bb_lower)  # 0 = at lower band, 1 = at upper

        if rsi < 30 and bb_position < 0.1:
            return TradingSignal(symbol=symbol, action="BUY", confidence=0.7)
        elif rsi > 70 and bb_position > 0.9:
            return TradingSignal(symbol=symbol, action="SELL", confidence=0.7)

        return None
```

**Tests:** ~15 tests
**Time:** 1-2 days
**Cost:** $0
**Dependencies:** Module A (RSI, Bollinger features), Module B (signal protocol), existing regime classifier

---

## PHASE 3 — Autoresearch (Week 5-6)

The automated strategy discovery machine.

---

### Module G: Autoresearch Harness

**What it does:** The LOCKED evaluation system. Takes any strategy, runs it against a fixed historical period, returns a composite score. This file is NEVER modified by the AI agent — it's the "answer key."

**Files to create:**

```
autoresearch/
  __init__.py
  harness.py           — THE LOCKED EVALUATOR (never modified by autoresearch agent)
  config.py            — HarnessConfig (evaluation period, metrics, thresholds)
  runner.py            — orchestrates the loop: modify → backtest → score → keep/revert
  experiments.tsv      — results log (tab-separated)
  README.md            — explanation of the autoresearch system
```

**harness.py — the locked evaluator:**

```python
class BacktestHarness:
    """
    LOCKED evaluation harness for autoresearch.

    DO NOT MODIFY THIS FILE DURING AUTORESEARCH RUNS.
    Changes to this file invalidate all experiment comparisons.
    """

    def __init__(self, config: HarnessConfig):
        self.config = config

    async def evaluate(self, strategy_func: Callable) -> HarnessResult:
        """
        1. Load fixed historical candles (config.eval_start → config.eval_end)
        2. Run strategy_func on candles (walk-forward: 70% train, 30% OOS)
        3. Compute metrics on OOS period ONLY
        4. Apply hard rejects (drawdown > 30%, Sharpe < 0, trades < 50)
        5. Compute composite score
        6. Return HarnessResult
        """

    def composite_score(self, metrics: dict) -> float:
        """
        score = sharpe_ratio * (1 - max_drawdown / 0.50)

        Hard rejects:
          max_drawdown > 0.30 → score = -999
          sharpe_ratio < 0    → score = -999
          num_trades < 50     → score = -999
        """
```

**HarnessConfig:**

| Field | Default | Description |
|-------|---------|-------------|
| `eval_start` | `"2024-01-01"` | Start of evaluation data |
| `eval_end` | `"2025-01-01"` | End of evaluation data |
| `oos_ratio` | `0.30` | 30% held for out-of-sample |
| `symbols` | `["BTCUSDT","ETHUSDT","SOLUSDT"]` | Coins to test on |
| `timeframe` | `"1h"` | Candle timeframe |
| `fee_pct` | `0.001` | 0.1% trading fee |
| `slippage_pct` | `0.0005` | 0.05% slippage |
| `max_drawdown_reject` | `0.30` | Reject if DD > 30% |
| `min_trades` | `50` | Reject if < 50 trades |

**runner.py — the loop orchestrator:**

```python
class AutoresearchRunner:
    """Orchestrates the autoresearch loop."""

    async def run_loop(self, max_experiments: int = 100):
        for i in range(max_experiments):
            # 1. Git: create experiment branch
            # 2. AI agent modifies strategy template
            # 3. Run BacktestHarness.evaluate()
            # 4. Log result to experiments.tsv
            # 5. If score improved → git commit (keep)
            #    If not → git revert (discard)
            # 6. Continue
```

**experiments.tsv format:**

```
commit	score	sharpe	max_dd	win_rate	num_trades	status	description
a1b2c3d	1.45	1.82	0.12	0.58	87	KEEP	added RSI divergence filter
e4f5g6h	-999	-0.3	0.35	0.41	23	DISCARD	aggressive scalping — too few trades
```

**Tests:** ~20 tests in `agent/tests/test_autoresearch_harness.py`
**Time:** 3-4 days
**Cost:** $0 (the harness itself is just backtesting on our own data)
**Dependencies:** Module C (Deflated Sharpe for validation)

---

### Module H: Autoresearch Strategy Template

**What it does:** The MODIFIABLE strategy file that the AI agent edits during autoresearch runs. This is the "test paper" — the AI fills in answers by changing parameters and logic.

**Files to create:**

```
autoresearch/
  strategy.py          — THE MODIFIABLE STRATEGY (AI edits this)
  research_prompt.md   — instructions for the AI agent
```

**strategy.py — modifiable template:**

```python
"""
AUTORESEARCH STRATEGY TEMPLATE
==============================
This file is modified by the AI agent during autoresearch runs.
The harness.py evaluator is NEVER modified.

To add a new signal: modify the `generate_signals()` function.
To change parameters: modify the PARAMS dict.
To change entry/exit logic: modify `should_enter()` / `should_exit()`.
"""

PARAMS = {
    # --- Indicator periods ---
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2.0,
    "sma_fast": 10,
    "sma_slow": 50,

    # --- Entry/exit ---
    "confidence_threshold": 0.55,
    "stop_loss_pct": 0.05,
    "take_profit_pct": 0.10,
    "trailing_stop_pct": 0.03,
    "max_hold_candles": 48,

    # --- Position sizing ---
    "position_size_pct": 0.05,
    "max_positions": 3,

    # --- Filters ---
    "volume_min_ratio": 0.5,
    "adx_min_trend": 25,
}

def generate_signals(candles: list[dict], features: dict) -> list[Signal]:
    """Generate trading signals. AI modifies this logic."""
    signals = []
    # ... strategy logic here ...
    return signals

def should_enter(signal: Signal, portfolio: dict) -> bool:
    """Entry filter. AI modifies this logic."""
    return signal.confidence >= PARAMS["confidence_threshold"]

def should_exit(position: dict, current_price: float, features: dict) -> bool:
    """Exit logic. AI modifies this logic."""
    # ... exit conditions ...
```

**research_prompt.md — AI agent instructions:**

```markdown
# Autoresearch: Trading Strategy Optimization

## Your task
You are optimizing a trading strategy. Each experiment:
1. Read strategy.py and past results in experiments.tsv
2. Make ONE change (parameter tweak, new filter, logic change)
3. Commit to git
4. Run: python -m autoresearch.runner
5. Check the composite_score in the output
6. If improved → KEEP. If not → REVERT.
7. Repeat. Never stop.

## Rules
- ONLY modify autoresearch/strategy.py
- NEVER modify autoresearch/harness.py (the evaluator)
- NEVER install new packages
- Make ONE change per experiment (so you know what helped)
- Simpler is better — if you can delete code and maintain score, do it
- The score is: sharpe_ratio * (1 - max_drawdown / 0.50)
- Strategies with >30% drawdown or <50 trades are auto-rejected

## What to try
- Change indicator periods (RSI, MACD, SMA)
- Tighten/loosen entry thresholds
- Add new entry conditions (e.g., volume confirmation)
- Modify exit rules (stop-loss, take-profit, trailing stop)
- Change position sizing
- Add filters (ADX trend filter, regime filter)
- Remove conditions that don't help (simplify)
```

**Tests:** ~10 tests
**Time:** 2 days
**Cost:** $0 for the template; $0.50-$5 per overnight autoresearch run (LLM costs)
**Dependencies:** Module G (harness)

---

## PHASE 4 — Statistical Arbitrage (Week 7-8)

---

### Module I: Pairs Trading / Statistical Arbitrage

**What it does:** Finds pairs of coins that move together (cointegrated), and trades when they temporarily diverge.

**Files to create:**

```
agent/strategies/pairs/
  __init__.py
  scanner.py           — PairScanner: finds cointegrated pairs among 600+ symbols
  spread.py            — SpreadCalculator: computes and tracks pair spreads
  strategy.py          — PairsTradingStrategy (implements SignalSourceProtocol)
  config.py            — PairsConfig
```

**How it works:**

```python
class PairScanner:
    """Scans for cointegrated pairs."""

    async def scan(self, symbols: list[str], lookback_days: int = 90) -> list[CointegratedPair]:
        """
        1. Fetch daily closes for all symbols
        2. For each pair (i, j) where i < j:
           - Run Engle-Granger cointegration test
           - If p-value < 0.05 → cointegrated!
           - Record hedge ratio and half-life
        3. Return sorted by cointegration strength
        """

class PairsTradingStrategy:
    """Trades spread convergence between cointegrated pairs."""

    name = "pairs"

    async def generate(self, symbol, candles, features) -> TradingSignal | None:
        # For each cointegrated pair involving this symbol:
        spread_zscore = self.spread_calc.current_zscore(pair)

        if spread_zscore > 2.0:    # spread too wide → sell the expensive one
            return TradingSignal(symbol=symbol, action="SELL", confidence=0.7)
        elif spread_zscore < -2.0:  # spread too narrow → buy the cheap one
            return TradingSignal(symbol=symbol, action="BUY", confidence=0.7)

        return None
```

**Config:**

| Field | Default | Description |
|-------|---------|-------------|
| `lookback_days` | 90 | Days of data for cointegration test |
| `rescan_interval_hours` | 24 | How often to rescan for new pairs |
| `max_pairs` | 50 | Maximum pairs to track |
| `entry_zscore` | 2.0 | Enter trade when spread exceeds this |
| `exit_zscore` | 0.5 | Exit when spread returns to this |
| `min_half_life` | 5 | Minimum half-life in days (faster mean reversion) |
| `max_half_life` | 60 | Maximum half-life (must revert within 60 days) |

**Tests:** ~25 tests
**Time:** 4-5 days
**Cost:** $0
**Dependencies:** Module A (return features), Module B (signal protocol), `statsmodels` (for cointegration tests — add to dependencies)

---

### Module J: Walk-Forward for Ensemble

**What it does:** Extends the existing walk-forward validation to cover the full ensemble (not just individual components).

**Files to modify:**

```
agent/strategies/walk_forward.py   — add walk_forward_ensemble() function
```

**What to add:**

```python
async def walk_forward_ensemble(config: WalkForwardConfig) -> WalkForwardResult:
    """
    Walk-forward validation for the full ensemble pipeline.

    Each window:
    1. Train RL, regime classifier, genome on IS period
    2. Run the full ensemble (all 3 strategies + risk overlay) on OOS period
    3. Record OOS Sharpe ratio

    This validates the WHOLE system, not just individual parts.
    """
```

**Tests:** ~10 tests (add to existing `test_walk_forward.py`)
**Time:** 1-2 days
**Cost:** $0
**Dependencies:** Existing walk-forward code

---

## PHASE 5 — Data & Sentiment (Week 9-10)

---

### Module K: LLM Sentiment Signal

**What it does:** Uses our existing LLM (Gemini Flash) to score news/events as bullish or bearish.

**Files to create:**

```
agent/strategies/signals/
  sentiment.py         — SentimentSignalSource (implements SignalSourceProtocol)

agent/strategies/sentiment/
  __init__.py
  analyzer.py          — SentimentAnalyzer: calls LLM to score text
  sources.py           — news/event fetchers (Fear & Greed, etc.)
  config.py            — SentimentConfig
```

**How it works:**

```python
class SentimentAnalyzer:
    """Uses cheap LLM to score sentiment."""

    async def analyze(self, text: str) -> SentimentScore:
        prompt = f"""Score this crypto news on a scale of -1.0 (very bearish)
        to +1.0 (very bullish). Return ONLY a number.

        News: {text}"""

        response = await self.llm.complete(prompt)  # uses Gemini Flash (~$0.0002/call)
        return SentimentScore(score=float(response), confidence=0.6)
```

**Initial data sources (free):**

| Source | What | How to Fetch |
|--------|------|-------------|
| **Fear & Greed Index** | Overall market mood (0-100) | `GET https://api.alternative.me/fng/` (free, no API key) |
| **CoinGecko trending** | Currently trending coins | `GET https://api.coingecko.com/api/v3/search/trending` (free) |

**Tests:** ~15 tests
**Time:** 3 days
**Cost:** ~$0.01/day (Gemini Flash for sentiment scoring)
**Dependencies:** Module B (signal protocol), existing OpenRouter integration

---

### Module L: Funding Rate Monitor

**What it does:** Tracks perpetual futures funding rates across exchanges. Identifies arbitrage opportunities.

**Files to create:**

```
agent/strategies/signals/
  funding_rate.py      — FundingRateSignalSource (implements SignalSourceProtocol)

agent/strategies/funding/
  __init__.py
  monitor.py           — FundingRateMonitor: fetches and tracks rates
  config.py            — FundingConfig
```

**How it works:**

```python
class FundingRateMonitor:
    """Tracks funding rates via CCXT."""

    async def fetch_rates(self) -> dict[str, float]:
        """Fetch current funding rates for all perpetual swap symbols."""
        # Uses CCXT: exchange.fetch_funding_rate(symbol)

class FundingRateSignalSource:
    name = "funding_rate"

    async def generate(self, symbol, candles, features) -> TradingSignal | None:
        rate = self.monitor.get_rate(symbol)
        if rate is None:
            return None

        # High positive funding → longs paying shorts → short signal
        if rate > 0.001:  # > 0.1% per 8h (136% annualized)
            return TradingSignal(symbol=symbol, action="SELL", confidence=0.8)
        elif rate < -0.001:  # negative funding → long signal
            return TradingSignal(symbol=symbol, action="BUY", confidence=0.8)

        return None
```

**Tests:** ~15 tests
**Time:** 2 days
**Cost:** $0 (uses existing CCXT connection)
**Dependencies:** Module B (signal protocol), existing `src/exchange/ccxt_adapter.py`

---

### Module M: External Data Connectors

**What it does:** Pluggable connectors for external data sources.

**Files to create:**

```
agent/strategies/data/
  __init__.py
  connector.py         — DataConnector protocol
  fear_greed.py        — Fear & Greed Index connector (free)
  coingecko.py         — CoinGecko connector (free)
```

**Start with free sources only.** Add paid sources (CryptoQuant, LunarCrush) later IF the strategy search shows they'd help.

**Tests:** ~10 tests
**Time:** 1-2 days
**Cost:** $0 (free APIs)
**Dependencies:** None

---

## PHASE 6 — Advanced ML (Week 11+)

These are longer-term additions. Build them after the autoresearch system is running and producing results.

---

### Module N: Transformer Price Prediction

**What it does:** A Temporal Fusion Transformer that reads price history and predicts next-period returns.

**Files to create:**

```
agent/strategies/transformer/
  __init__.py
  model.py             — TFTModel: Temporal Fusion Transformer
  train.py             — training script
  predict.py           — inference: candles → prediction
  signal.py            — TransformerSignalSource (implements SignalSourceProtocol)
  config.py            — TransformerConfig
```

**Time:** 1-2 weeks
**Cost:** $0 (CPU training; GPU optional for speed)
**Dependencies:** Module A (features), Module B (signal protocol), `torch`, `pytorch-forecasting` or custom implementation

---

### Module O: Synthetic Data Generator

**What it does:** Generates realistic fake market data for stress-testing strategies.

**Files to create:**

```
agent/strategies/synthetic/
  __init__.py
  generator.py         — SyntheticDataGenerator
  scenarios.py         — pre-built stress scenarios (crash, flash crash, pump, sideways)
```

**Time:** 1 week
**Cost:** $0
**Dependencies:** Module A (feature computation for validation)

---

### Module P: Order Flow Analysis

**What it does:** Analyzes order book depth and flow for trading signals.

**Files to create:**

```
agent/strategies/signals/
  order_flow.py        — OrderFlowSignalSource (implements SignalSourceProtocol)

agent/strategies/orderflow/
  __init__.py
  analyzer.py          — OrderFlowAnalyzer: processes depth data
  imbalance.py         — order book imbalance calculations
```

**Time:** 1-2 weeks
**Cost:** $0
**Dependencies:** Module B (signal protocol), existing order book data from `src/exchange/`

---

## Full Timeline Summary

```
WEEK 1-2:  Foundation
  ├── Module A: Feature Pipeline ........... 3 days
  ├── Module B: Signal Interface ........... 3 days
  └── Module C: Deflated Sharpe ............ 2 days

WEEK 3-4:  First Strategies
  ├── Module D: Volume Spike ............... 1 day
  ├── Module E: Momentum ................... 3 days
  └── Module F: Mean Reversion ............. 2 days

WEEK 5-6:  Autoresearch
  ├── Module G: Harness .................... 4 days
  └── Module H: Strategy Template .......... 2 days
  → First overnight autoresearch run!

WEEK 7-8:  Statistical Arbitrage
  ├── Module I: Pairs Trading .............. 5 days
  └── Module J: Walk-Forward Ensemble ...... 2 days

WEEK 9-10: Data & Sentiment
  ├── Module K: LLM Sentiment .............. 3 days
  ├── Module L: Funding Rate ............... 2 days
  └── Module M: Data Connectors ............ 2 days

WEEK 11+:  Advanced (ongoing)
  ├── Module N: Transformer ................ 2 weeks
  ├── Module O: Synthetic Data ............. 1 week
  └── Module P: Order Flow ................. 2 weeks
```

## Total Cost of Everything

| Item | One-Time | Monthly Ongoing |
|------|----------|----------------|
| **All 16 modules (development)** | $0 (code) | — |
| **ML training loops** | — | $0 (CPU) |
| **LLM calls (trading journal)** | — | ~$0.30 |
| **LLM calls (sentiment, if built)** | — | ~$1-3 |
| **LLM calls (autoresearch runs)** | — | ~$2-20 |
| **External data APIs** | — | $0 (free sources first) |
| **Server (if cloud)** | — | $35-245 |
| | | |
| **TOTAL (own machine)** | **$0** | **~$3-24/month** |
| **TOTAL (cloud)** | **$0** | **~$38-269/month** |

## What Gets Tested During Autoresearch

Once Modules A-H are built, the autoresearch loop can test ALL of these strategy types:

```
AUTORESEARCH SEARCH SPACE:
  ├── Indicator parameters (RSI, MACD, BB, SMA periods)
  ├── Entry conditions (which signals, what thresholds)
  ├── Exit conditions (stop-loss, take-profit, trailing, time-based)
  ├── Position sizing (fixed, volatility-adjusted, Kelly)
  ├── Symbol selection (top N by volume, momentum tier, sector)
  ├── Regime filtering (trade only in specific regimes)
  ├── Signal combinations (momentum + volume, mean reversion + RSI)
  ├── Ensemble weights (how much to trust each signal source)
  └── Risk parameters (max positions, max drawdown tolerance)

  Each overnight run tests ~100 variations.
  Each weekend tests ~500 variations.
  The champion goes through the validation funnel.
```

## After All Modules Are Built — The Daily Flow

```
06:00  Autoresearch overnight run completes
       → 100 experiments tested, 12 improvements kept
       → Best candidate: Sharpe 2.1, DD 11%, 73 trades

07:00  Developer reviews experiments.tsv
       → Picks top 3 candidates for validation

08:00  Walk-forward validation runs on top 3
       → Candidate A: WFE 0.62 ✓ | DSR p=0.97 ✓ → PASSES
       → Candidate B: WFE 0.44 ✗ → FAILS (overfitting)
       → Candidate C: WFE 0.55 ✓ | DSR p=0.89 ✗ → FAILS (luck)

09:00  Battle: Candidate A vs current champion
       → 7-day historical battle
       → Candidate A Sharpe: 1.95 | Champion Sharpe: 1.72
       → A/B gate: +0.23 improvement → DEPLOY Candidate A

10:00  New champion deployed
       → Drift detection starts monitoring
       → Ensemble weights adjusted at next 8h cycle
       → Life goes on. Next weekend: another autoresearch run.
```

---

*Plan compiled 2026-03-23. Build order based on dependency analysis and priority.*
