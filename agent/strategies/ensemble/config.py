"""Pydantic-settings configuration for the ensemble runner.

All fields are overridable via environment variables using the ``ENSEMBLE_``
prefix, or via the ``agent/.env`` file.

Example::

    config = EnsembleConfig()                                  # load from env / defaults
    config = EnsembleConfig(confidence_threshold=0.7)          # override in code
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env file relative to the agent/ package root (three levels up from this file)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class EnsembleConfig(BaseSettings):
    """Complete configuration for the EnsembleRunner.

    Fields are grouped into four sections:
    - Signal source weights (loaded from weight-optimization results or defaulting to equal)
    - Ensemble gate parameters
    - Source enable/disable flags
    - Platform connectivity

    All weight values are raw (not normalised).  The MetaLearner normalises
    them to sum to 1.0 at combine-time.

    Example::

        config = EnsembleConfig()
        print(config.weights)             # {"rl": 0.333, "evolved": 0.333, "regime": 0.334}
        print(config.confidence_threshold) # 0.6
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_prefix="ENSEMBLE_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Signal source weights ──────────────────────────────────────────────────

    weights: dict[str, float] = Field(
        default={
            "rl": 0.333,
            "evolved": 0.333,
            "regime": 0.334,
        },
        description=(
            "Per-source weight mapping.  Keys must match SignalSource values: "
            "'rl', 'evolved', 'regime'.  Raw weights — MetaLearner normalises "
            "them to sum to 1.0 at combine-time.  Defaults to equal weighting.  "
            "Optimal weights can be obtained by running optimize_weights.py and "
            "copying the 'optimal_weights' field from the JSON report."
        ),
    )

    # ── Ensemble gate parameters ───────────────────────────────────────────────

    confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum combined weighted confidence required to emit a BUY or SELL "
            "action.  Signals below this threshold are overridden to HOLD.  "
            "0.6 provides a balance between acting on moderate agreement and "
            "filtering out noisy or split signals."
        ),
    )
    min_agreement_rate: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum fraction of active (non-zero confidence) sources that must "
            "agree with the winning action.  0.5 means at least half must agree; "
            "below this the MetaLearner falls back to HOLD regardless of confidence."
        ),
    )

    # ── Source enable/disable flags ────────────────────────────────────────────

    enable_risk_overlay: bool = Field(
        default=True,
        description=(
            "When True, route every approved order through the RiskMiddleware "
            "(RiskAgent + VetoPipeline + DynamicSizer) before execution.  "
            "Disable only for dry-run testing where no SDK connection is available."
        ),
    )
    enable_rl_signal: bool = Field(
        default=True,
        description=(
            "When True, the PPO deploy bridge is loaded and its portfolio-weight "
            "output is included as a WeightedSignal in each step.  Disable to "
            "run the ensemble without the RL component (e.g. when no trained "
            "model exists yet)."
        ),
    )
    enable_evolved_signal: bool = Field(
        default=True,
        description=(
            "When True, the evolved champion genome is loaded and its RSI/MACD "
            "state is converted to a WeightedSignal at each step.  Disable to "
            "run without the genetic-algorithm component."
        ),
    )
    enable_regime_signal: bool = Field(
        default=True,
        description=(
            "When True, the regime classifier and switcher are loaded and the "
            "current market regime is converted to a WeightedSignal at each "
            "step.  Disable to run without the regime-detection component."
        ),
    )

    # ── Symbols and mode ──────────────────────────────────────────────────────

    symbols: list[str] = Field(
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        description=(
            "Trading pairs the ensemble operates on.  Must match the pairs "
            "supported by the platform backtest / live API.  The PPO model, "
            "evolved genome, and regime classifier each generate one signal per "
            "symbol per step."
        ),
    )
    mode: Literal["backtest", "live"] = Field(
        default="backtest",
        description=(
            "Execution mode.  'backtest' drives an existing backtest session "
            "step-by-step and never places real orders.  'live' queries live "
            "market data and places orders via the SDK."
        ),
    )

    # ── Backtest loop parameters ───────────────────────────────────────────────

    backtest_days: int = Field(
        default=7,
        ge=1,
        description=(
            "Length of the backtest window in calendar days when running "
            "run_backtest().  A longer window improves statistical significance "
            "but increases wall-clock runtime."
        ),
    )
    batch_size: int = Field(
        default=5,
        ge=1,
        description=(
            "Number of candle steps to advance per loop iteration in run_backtest(). "
            "5 steps at 1-minute candles = 5 minutes of simulated time per iteration.  "
            "Increase to reduce total HTTP calls at the cost of decision resolution."
        ),
    )
    max_iterations: int = Field(
        default=50,
        ge=1,
        description=(
            "Maximum number of iterations in the run_backtest() trading loop before "
            "halting even if the backtest session has not terminated.  Acts as a "
            "safety limit to prevent runaway loops."
        ),
    )

    # ── Model artifact paths ───────────────────────────────────────────────────

    rl_model_path: str = Field(
        default="",
        description=(
            "Absolute or relative path to the trained PPO model .zip file "
            "(e.g. 'agent/strategies/rl/models/ppo_seed42.zip').  "
            "When empty, the runner auto-discovers the first ppo_seed*.zip file "
            "in agent/strategies/rl/models/."
        ),
    )
    evolved_genome_path: str = Field(
        default="",
        description=(
            "Absolute or relative path to the evolved champion genome JSON file "
            "(e.g. 'agent/strategies/evolutionary/models/champion.json').  "
            "When empty, the runner uses a fresh random genome with seed=42 as "
            "a fallback — useful for smoke-testing without a full GA run."
        ),
    )
    regime_model_path: str = Field(
        default="",
        description=(
            "Absolute or relative path to the trained regime classifier .joblib "
            "file (e.g. 'agent/strategies/regime/models/regime_classifier.joblib').  "
            "When empty, the runner trains a lightweight RandomForest on synthetic "
            "candles as a fallback — useful for smoke-testing."
        ),
    )

    # ── Platform connectivity ─────────────────────────────────────────────────

    platform_api_key: str = Field(
        default="",
        description=(
            "TradeReady ak_live_... API key.  Required to create and drive backtest "
            "sessions and to place live orders via the SDK.  Reads from "
            "ENSEMBLE_PLATFORM_API_KEY env var or agent/.env."
        ),
    )
    platform_base_url: str = Field(
        default="http://localhost:8000",
        description=(
            "Base URL of the TradeReady REST API.  Used for backtest session "
            "management (create, start, step, results) and market data endpoints."
        ),
    )

    # ── Candle window ─────────────────────────────────────────────────────────

    candle_window: int = Field(
        default=100,
        ge=50,
        description=(
            "Number of recent candles fetched on each step for the regime "
            "switcher and evolved-signal feature extraction.  Must be >= 50 "
            "(RegimeSwitcher MIN_CANDLES_REQUIRED) to guarantee a valid "
            "classifier prediction on every step."
        ),
    )

    # ── Risk overlay parameters ────────────────────────────────────────────────

    risk_base_size_pct: float = Field(
        default=0.05,
        ge=0.001,
        le=1.0,
        description=(
            "Base position size fraction forwarded to the RiskMiddleware as the "
            "initial size_pct for every trade signal.  0.05 = 5 % of equity.  "
            "The DynamicSizer may reduce this further based on volatility and "
            "drawdown.  Kept well below 10 % to stay within platform risk limits."
        ),
    )
