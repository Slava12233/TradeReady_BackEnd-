"""Pydantic-settings configuration for the PPO RL training pipeline.

All hyperparameters are typed fields with docstrings explaining the rationale
behind each default value.  Values can be overridden via environment variables
or a ``agent/.env`` file using the ``RL_`` prefix.

Example::

    config = RLConfig()                      # load from env / defaults
    config = RLConfig(total_timesteps=1000)  # override for a quick smoke test
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the .env file relative to the agent/ package root (two levels up from this file)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"

# Directory where trained model artifacts are stored (gitignored)
_MODELS_DIR = Path(__file__).parent / "models"


class RLConfig(BaseSettings):
    """Complete hyperparameter configuration for the PPO trading agent.

    Fields are grouped into four sections:
    - PPO algorithm hyperparameters
    - Environment / data configuration
    - Reward shaping
    - Training run meta-configuration

    All financial date/time values are stored as plain strings in ISO-8601
    format to avoid any float or precision issues when forwarding them to the
    backtest REST API.

    Example::

        config = RLConfig()
        print(config.learning_rate)   # 0.0003
        print(config.train_start)     # "2024-01-01T00:00:00Z"
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        env_prefix="RL_",
        case_sensitive=False,
        extra="ignore",
    )

    # ── PPO algorithm hyperparameters ──────────────────────────────────────────

    learning_rate: float = Field(
        default=3e-4,
        description=(
            "Adam optimiser learning rate.  3e-4 is the SB3/PPO recommended default; "
            "lower values (~1e-4) may help in noisy financial environments."
        ),
    )
    clip_range: float = Field(
        default=0.2,
        description=(
            "PPO policy clipping coefficient epsilon.  0.2 is the standard value from "
            "the original PPO paper (Schulman et al. 2017); restricts how far the "
            "updated policy can deviate from the old policy per gradient step."
        ),
    )
    n_steps: int = Field(
        default=2048,
        description=(
            "Number of environment steps collected per environment per update.  "
            "Higher values reduce variance in gradient estimates at the cost of "
            "sample efficiency.  2048 is the SB3 default for continuous control."
        ),
    )
    batch_size: int = Field(
        default=64,
        description=(
            "Mini-batch size for each PPO optimisation epoch.  Must divide evenly "
            "into (n_steps * n_envs).  64 balances throughput and gradient noise."
        ),
    )
    n_epochs: int = Field(
        default=10,
        description=(
            "Number of gradient update passes over the rollout buffer per PPO "
            "iteration.  10 is the standard value; more epochs risk over-fitting "
            "to a single rollout."
        ),
    )
    gamma: float = Field(
        default=0.99,
        description=(
            "Discount factor for future rewards.  0.99 values future returns highly, "
            "which is appropriate for multi-step trading strategies where end-of-episode "
            "portfolio value matters."
        ),
    )
    gae_lambda: float = Field(
        default=0.95,
        description=(
            "GAE (Generalised Advantage Estimation) lambda.  Controls the bias-variance "
            "trade-off in advantage estimates.  0.95 is the PPO paper default."
        ),
    )
    ent_coef: float = Field(
        default=0.01,
        description=(
            "Entropy bonus coefficient.  Encourages policy exploration by penalising "
            "premature convergence to a deterministic policy.  0.01 is a light touch; "
            "increase to 0.05 if the agent is collapsing to always-HOLD early."
        ),
    )
    vf_coef: float = Field(
        default=0.5,
        description=(
            "Value function loss coefficient.  Scales the critic loss relative to the "
            "policy loss.  0.5 is the standard PPO default."
        ),
    )
    max_grad_norm: float = Field(
        default=0.5,
        description=(
            "Maximum gradient norm for clipping.  Prevents exploding gradients from "
            "destabilising training on volatile price sequences."
        ),
    )

    # ── Neural network architecture ────────────────────────────────────────────

    net_arch_pi: list[int] = Field(
        default=[256, 256],
        description=(
            "Hidden layer sizes for the policy (actor) network.  "
            "Two layers of 256 units is a standard starting point for "
            "moderate-dimensional observations (~279 dims after wrappers)."
        ),
    )
    net_arch_vf: list[int] = Field(
        default=[256, 256],
        description=(
            "Hidden layer sizes for the value function (critic) network.  "
            "Matches the policy network depth so the critic does not become "
            "a bottleneck for advantage estimation quality."
        ),
    )

    # ── Environment / data configuration ──────────────────────────────────────

    asset_universe: list[str] = Field(
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
        description=(
            "Full set of trading pairs available for portfolio allocation.  "
            "TradeReady-Portfolio-v0 uses BTCUSDT+ETHUSDT+SOLUSDT (3 assets) by default; "
            "this list is the superset from which the env draws its pairs."
        ),
    )
    env_symbols: list[str] = Field(
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        description=(
            "Symbols actually passed to the TradeReady-Portfolio-v0 environment.  "
            "Must be a subset of asset_universe.  Kept at 3 by default to stay "
            "within the registered env's action space shape (3,)."
        ),
    )
    timeframe: str = Field(
        default="1h",
        description=(
            "Candle interval forwarded to the backtest API.  "
            "Valid values: 1m, 5m, 15m, 1h, 4h, 1d.  "
            "1h gives a reasonable trade frequency without excessive HTTP call volume."
        ),
    )
    lookback_window: int = Field(
        default=30,
        description=(
            "Number of historical candles in each observation.  30 provides just enough "
            "history for MACD (needs 26 candles) while keeping observation size manageable.  "
            "Minimum safe value when using macd feature is 26."
        ),
    )
    starting_balance: float = Field(
        default=10_000.0,
        description=(
            "Virtual USDT balance at the start of each episode.  "
            "Stored as float because the gym and SB3 both require numpy floats; "
            "the env converts to Decimal before sending to the API."
        ),
    )

    # ── Date splits (stored as ISO-8601 strings, never float) ─────────────────

    train_start: str = Field(
        default="2024-01-01T00:00:00Z",
        description="Start of the training data window (ISO-8601 UTC).",
    )
    train_end: str = Field(
        default="2024-10-01T00:00:00Z",
        description="End of the training data window (ISO-8601 UTC).",
    )
    val_start: str = Field(
        default="2024-10-01T00:00:00Z",
        description="Start of the validation window used by EvalCallback (ISO-8601 UTC).",
    )
    val_end: str = Field(
        default="2024-12-01T00:00:00Z",
        description="End of the validation window (ISO-8601 UTC).",
    )
    test_start: str = Field(
        default="2024-12-01T00:00:00Z",
        description="Start of the held-out test window — never used during training (ISO-8601 UTC).",
    )
    test_end: str = Field(
        default="2025-01-01T00:00:00Z",
        description="End of the held-out test window (ISO-8601 UTC).",
    )

    # ── Reward shaping ─────────────────────────────────────────────────────────

    reward_type: str = Field(
        default="sharpe",
        description=(
            "Reward function variant.  Choices: 'pnl', 'sharpe', 'sortino', 'drawdown'. "
            "'sharpe' is the default because raw PnL rewards encourage excessive risk-taking "
            "while Sharpe incentivises risk-adjusted returns."
        ),
    )
    drawdown_penalty_coeff: float = Field(
        default=0.5,
        description=(
            "Penalty weight on drawdown when reward_type='drawdown'.  "
            "0.5 balances PnL incentive against drawdown avoidance; "
            "increase toward 1.0 for more conservative agents."
        ),
    )
    sharpe_window: int = Field(
        default=50,
        description=(
            "Rolling window length (in steps) for the SharpeReward and SortinoReward "
            "calculations.  50 steps at 1h timeframe covers ~2 trading days."
        ),
    )

    # ── Training run meta-configuration ───────────────────────────────────────

    total_timesteps: int = Field(
        default=500_000,
        description=(
            "Total environment steps for the training run.  500k is a reasonable "
            "starting budget for the portfolio env at 1h candles (~2 years of data "
            "per episode gives ~17k steps/episode, so ~29 episodes total)."
        ),
    )
    n_envs: int = Field(
        default=4,
        description=(
            "Number of parallel environments in the VecEnv.  4 is a good default "
            "for a single workstation; increase to 8+ on multi-core servers.  "
            "Note: SubprocVecEnv uses one process per env."
        ),
    )
    seed: int = Field(
        default=42,
        description=(
            "Master random seed.  Applied to Python random, numpy, and the SB3 model "
            "to ensure reproducible initial weights and env sampling order."
        ),
    )
    save_freq: int = Field(
        default=10_000,
        description=(
            "Number of timesteps between checkpoint saves.  10k steps = roughly "
            "one full episode in the portfolio env.  Checkpoints go to models_dir."
        ),
    )
    eval_freq: int = Field(
        default=20_000,
        description=(
            "Number of timesteps between EvalCallback evaluations on the validation "
            "environment.  Should be a multiple of (n_steps * n_envs) for alignment."
        ),
    )
    n_eval_episodes: int = Field(
        default=3,
        description=(
            "Number of evaluation episodes run by EvalCallback at each eval_freq.  "
            "3 episodes gives a low-variance reward estimate without slowing training."
        ),
    )
    models_dir: Path = Field(
        default=_MODELS_DIR,
        description=(
            "Directory for saving checkpoints and the final trained model.  "
            "Defaults to agent/strategies/rl/models/ which is gitignored."
        ),
    )
    log_dir: Path = Field(
        default=_MODELS_DIR / "logs",
        description=(
            "TensorBoard log directory.  Pass to SB3 PPO as tensorboard_log.  "
            "Defaults to agent/strategies/rl/models/logs/."
        ),
    )

    # ── Platform connectivity ──────────────────────────────────────────────────

    platform_api_key: str = Field(
        default="",
        description=(
            "TradeReady ak_live_... API key.  Required for env.reset() to create "
            "backtest sessions.  Reads from RL_PLATFORM_API_KEY env var or agent/.env."
        ),
    )
    platform_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the TradeReady REST API.  Used by every gym env.",
    )
    track_training: bool = Field(
        default=True,
        description=(
            "When True, each gym env instance reports episode metrics to the "
            "platform training API via TrainingTracker.  Disable with False "
            "to skip the training run registration HTTP calls during quick tests."
        ),
    )

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        """Reject timeframe values the backtest API does not support."""
        allowed = {"1m", "5m", "15m", "1h", "4h", "1d"}
        if v not in allowed:
            raise ValueError(f"timeframe must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("reward_type")
    @classmethod
    def validate_reward_type(cls, v: str) -> str:
        """Reject unknown reward type names before they reach the gym factory."""
        allowed = {"pnl", "sharpe", "sortino", "drawdown"}
        if v not in allowed:
            raise ValueError(f"reward_type must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("lookback_window")
    @classmethod
    def validate_lookback_window(cls, v: int) -> int:
        """Require at least 26 candles so MACD can be computed without NaN."""
        if v < 26:
            raise ValueError(
                f"lookback_window must be >= 26 to support MACD (slow EMA period=26), got {v}"
            )
        return v
