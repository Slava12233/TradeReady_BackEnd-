# agent/strategies/regime/ — Market Regime Detection Strategy

<!-- last-updated: 2026-03-23 -->

> Labels market candles into four regime types, trains a classifier to predict the current regime, and activates the matching pre-built trading strategy at each decision step.

## What This Module Does

The `regime/` sub-package implements a market regime detection system. It uses ADX and ATR-to-close-ratio rules to label historical candles into one of four regime types (`TRENDING`, `HIGH_VOLATILITY`, `LOW_VOLATILITY`, `MEAN_REVERTING`), then trains a supervised classifier (XGBoost preferred, sklearn RandomForest fallback) on 6 technical features to predict the regime from live candles. The `RegimeSwitcher` enforces a confidence threshold and cooldown before switching strategies, preventing thrashing in boundary regimes.

Four pre-built strategy definitions (one per regime) are included and can be deployed to the platform as-is.

189 unit tests cover all components. The classifier has been trained and validated on 12 months of BTC 1h data: 99.92% accuracy, Walk-Forward Efficiency (WFE) 97.46%, Sharpe 1.14 vs MACD 0.74 baseline.

## Key Files

| File | Purpose |
|------|---------|
| `labeler.py` | `RegimeType` enum, `label_candles(candles)`, `generate_training_data(candles)` — rule-based regime labelling. |
| `classifier.py` | `RegimeClassifier` — train, predict, evaluate, save, load. XGBoost preferred; sklearn fallback. |
| `switcher.py` | `RegimeSwitcher`, `SwitchEvent` — stateful regime tracking with cooldown and confidence gating. |
| `strategy_definitions.py` | `TRENDING_STRATEGY`, `MEAN_REVERTING_STRATEGY`, `HIGH_VOLATILITY_STRATEGY`, `LOW_VOLATILITY_STRATEGY`, `STRATEGY_BY_REGIME`, `create_regime_strategies()` — pre-built strategy dicts. |
| `validate.py` | CLI script — 12-month sequential backtests: regime-adaptive vs static MACD vs buy-and-hold. |
| `models/` | Output directory for trained `.joblib` classifier files. |

## Public API

```python
from agent.strategies.regime.labeler import RegimeType, label_candles, generate_training_data
from agent.strategies.regime.classifier import RegimeClassifier
from agent.strategies.regime.switcher import RegimeSwitcher, SwitchEvent
from agent.strategies.regime.strategy_definitions import (
    TRENDING_STRATEGY,
    MEAN_REVERTING_STRATEGY,
    HIGH_VOLATILITY_STRATEGY,
    LOW_VOLATILITY_STRATEGY,
    STRATEGY_BY_REGIME,
    create_regime_strategies,
)
```

### Regime Taxonomy (`labeler.py`)

| `RegimeType` | Detection Rule |
|-------------|----------------|
| `TRENDING` | ADX > 25 |
| `HIGH_VOLATILITY` | ATR/close > 2× median ATR/close |
| `LOW_VOLATILITY` | ATR/close < 0.5× median ATR/close |
| `MEAN_REVERTING` | All remaining candles (default case) |

### `RegimeClassifier` (`classifier.py`)

6-feature input vector per candle: ADX, ATR/close, Bollinger Band width, RSI-14, MACD histogram, volume_ratio (current volume / 20-period SMA of volume).

XGBoost is used when available; automatically falls back to `RandomForestClassifier` if xgboost is not installed. Both produce a `.joblib` file.

| Method | Description |
|--------|-------------|
| `train(features: pd.DataFrame, labels: list[RegimeType])` | Fit the classifier on labelled training data |
| `predict(row_df: pd.DataFrame)` | Return `(RegimeType, confidence: float)` for a single observation |
| `evaluate(test_features, test_labels)` | Return accuracy, per-class precision/recall/F1 |
| `save(path: Path)` | Persist model to `.joblib` |
| `load(path: Path)` | Load a previously saved model |

### `RegimeSwitcher` (`switcher.py`)

Stateful — the cooldown counter and last-regime state are instance variables. Create a fresh instance per trading session.

| Method | Returns | Description |
|--------|---------|-------------|
| `step(candles: list[dict])` | `(RegimeType, strategy_id: str, switched: bool)` | Classify current regime; fire a switch if conditions are met |
| `history` | `list[SwitchEvent]` | Log of all regime transitions |

A switch fires only when:
1. Classifier confidence ≥ `confidence_threshold` (default 0.7)
2. At least `cooldown_candles` (default 20) candles have elapsed since the last switch

### Pre-built Strategy Definitions (`strategy_definitions.py`)

Each strategy is a JSONB-compatible dict ready for `POST /api/v1/strategies`. Key distinctions:

| Strategy | Entry Logic | Exit Logic |
|----------|-------------|------------|
| `TRENDING_STRATEGY` | MACD crossover + ADX > 25 | Trailing stop + max hold |
| `MEAN_REVERTING_STRATEGY` | RSI oversold/overbought + Bollinger mean-reversion | Take-profit at mean + time stop |
| `HIGH_VOLATILITY_STRATEGY` | Breakout + high ATR confirmation | Tight trailing stop |
| `LOW_VOLATILITY_STRATEGY` | SMA crossover (slow signals) | Fixed take-profit + time stop |

`create_regime_strategies(api_client)` registers all four strategies on the platform and returns a `dict[RegimeType, str]` mapping regime to strategy ID.

## CLI Commands

```bash
# Train the regime classifier on historical BTC 1h data
python -m agent.strategies.regime.classifier \
    --train \
    --data-url http://localhost:8000 \
    --api-key ak_live_... \
    --symbol BTCUSDT \
    --months 12

# Run 12-month validation (regime-adaptive vs static MACD vs buy-and-hold)
python -m agent.strategies.regime.validate \
    --base-url http://localhost:8000 \
    --api-key ak_live_... \
    --months 12

# Demo mode: run switcher on synthetic data (no platform connection)
python -m agent.strategies.regime.switcher --demo --candles 300
```

## Patterns

- **XGBoost with sklearn fallback** — detected at import time; no config flag needed. Both produce identical API.
- **Fitness is always scalar** — `RegimeSwitcher` reduces the regime prediction to a strategy ID; the ensemble combiner treats it as a directional bias signal.
- **`STRATEGY_BY_REGIME` dict** — maps `RegimeType` → pre-built strategy definition. Use `STRATEGY_BY_REGIME[RegimeType.TRENDING]` to get the strategy dict without calling `create_regime_strategies()`.

## Gotchas

- **`RegimeSwitcher` is stateful.** The cooldown counter and `last_regime` are instance variables. Each trading session must create a new `RegimeSwitcher` instance or call `switcher.reset()` between sessions.
- **`xgboost` is optional.** If not installed, `RegimeClassifier` silently uses `RandomForestClassifier`. To force XGBoost, install via `pip install -e "agent/[regime]"`.
- **`joblib.load()` uses pickle internally.** Load classifier models only from trusted, locally-generated paths. Never load from network paths.
- **Cooldown prevents rapid switching.** The switcher will not change strategies more than once per `cooldown_candles` (default 20) regardless of classifier confidence. In fast-moving markets, the active strategy may be suboptimal for up to 20 candles after a regime change.
- **`generate_training_data()` requires at least 26 candles** to compute MACD slow EMA. Short data windows will produce NaN features that must be dropped before training.
- **`volume_ratio` requires a `volume` key** in each candle dict. Candles missing `volume` default to 0; an all-zero volume window produces NaN `volume_ratio`, which causes those rows to be dropped by the NaN filter.

## Recent Changes

- `2026-03-23` — R3-01: Regime classifier trained on 12-month BTC 1h data. Results: 99.92% accuracy, WFE 97.46%, Sharpe 1.14 vs MACD 0.74. Trained model artifact saved to `agent/strategies/regime/models/` with SHA-256 sidecar. R3-04: `walk_forward_regime()` integration added to `walk_forward.py` — enables WFE computation for the regime classifier (passes `WFE >= 50%` gate). Checksum `strict=True` is now the default for `verify_checksum()` — missing `.sha256` sidecars raise `SecurityError` instead of silently skipping.
- `2026-03-22` — Added `volume_ratio` (current_volume / SMA(volume,20)) as feature 6 in `labeler.py:generate_training_data()` and `classifier.py:FEATURE_NAMES`. Added `_volume_ratio_series()` helper in `labeler.py`. Added `_print_evaluation()` to `classifier.py` (was missing; used by tests). Updated test count from 170 → 189 (17 new tests in `test_regime_labeler.py`). CLAUDE.md updated accordingly.
- `2026-03-20` — Initial CLAUDE.md created.
