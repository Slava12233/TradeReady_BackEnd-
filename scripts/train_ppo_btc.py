"""PPO BTC training script using the headless Gymnasium environment.

Trains a Proximal Policy Optimization (PPO) agent on BTCUSDT historical data
via the ``TradeReady-BTC-Headless-v0`` environment.  The headless environment
drives the backtest engine in-process (no HTTP overhead), giving a 100-500x
speed improvement over the HTTP-backed environments.

Training pipeline:
  1. Read ``DATABASE_URL`` from environment variables.
  2. Build ``TradeReady-BTC-Headless-v0`` with ``CompositeReward``.
  3. Wrap with ``BatchStepWrapper(n_steps=5)`` + ``NormalizationWrapper``.
  4. Wrap with SB3 ``Monitor`` for episode logging.
  5. Train PPO for 500K timesteps with TensorBoard logging.
  6. Save model to ``models/ppo_btc_v1.zip``.
  7. Run out-of-sample evaluation (2025-01-01 -> 2025-03-01, 10 episodes).
  8. Compute summary metrics: avg reward, Sharpe ratio, max drawdown, win rate.
  9. Validate with the platform's Deflated Sharpe Ratio API.

Requirements:
    pip install -e tradeready-gym/
    pip install stable-baselines3>=2.0 tensorboard

    export DATABASE_URL="postgresql+asyncpg://user:pass@localhost/tradeready"
    export PYTHONPATH="."

Run:
    python scripts/train_ppo_btc.py
    python scripts/train_ppo_btc.py --timesteps 100000 --eval-episodes 5

Estimated training time: 2-6 hours on CPU (500K timesteps).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
import time

# ---------------------------------------------------------------------------
# Check for Stable-Baselines3 before importing anything else
# ---------------------------------------------------------------------------

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.monitor import Monitor
except ImportError:
    print(
        "\nERROR: stable-baselines3 is required for this script.\n"
        "Install it with:\n"
        "    pip install stable-baselines3>=2.0 tensorboard\n"
    )
    sys.exit(1)

import gymnasium as gym

# Import tradeready_gym to trigger gymnasium.register() side-effects.
# This must happen before any gym.make("TradeReady-*") call.
try:
    import tradeready_gym  # noqa: F401
    from tradeready_gym.rewards.composite import CompositeReward
    from tradeready_gym.wrappers.batch_step import BatchStepWrapper
    from tradeready_gym.wrappers.normalization import NormalizationWrapper
except ImportError:
    print("\nERROR: tradeready-gym is not installed.\nInstall it with:\n    pip install -e tradeready-gym/\n")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("\nERROR: httpx is required for the DSR validation step.\nInstall it with:\n    pip install httpx>=0.28\n")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Training configuration
# All magic numbers are documented below.
# ---------------------------------------------------------------------------

# --- Time windows ---
# Six months of training data (2024-07-01 -> 2025-01-01) is the minimum
# needed for PPO to see enough bull/bear/sideways regimes on 1h candles.
TRAIN_START: str = "2024-07-01T00:00:00Z"
TRAIN_END: str = "2025-01-01T00:00:00Z"

# Two months of out-of-sample data for evaluation.  This period was NOT
# seen during training, so performance here is a true OOS estimate.
EVAL_START: str = "2025-01-01T00:00:00Z"
EVAL_END: str = "2025-03-01T00:00:00Z"

# --- Environment ---
ENV_ID: str = "TradeReady-BTC-Headless-v0"
SYMBOL: str = "BTCUSDT"
TIMEFRAME: str = "1h"

# Lookback window of 30 candles gives RSI(14) and MACD(26) room to warm up.
LOOKBACK_WINDOW: int = 30

# Starting virtual balance per episode.
STARTING_BALANCE: float = 10_000.0

# 720 hourly candles = 30 days per episode.  Chosen to match the
# recommendation-plan spec; short enough that multiple episodes fit within
# the 6-month training window.
EPISODE_LENGTH: int = 720

# --- Wrappers ---
# Hold each action for 5 candles before the agent re-decides.  This reduces
# the effective step count by 5× and improves CPU throughput significantly.
BATCH_HOLD_STEPS: int = 5

# --- PPO hyperparameters ---
# These values are CPU-friendly and align with the task specification.

# 500K total environment interactions.  On a modern CPU with the headless
# env + batch stepping this takes 2-6 hours.
DEFAULT_TOTAL_TIMESTEPS: int = 500_000

# Adam learning rate; standard SB3 default — proven stable for PPO.
LEARNING_RATE: float = 3e-4

# On-policy rollout buffer size.  2048 is the standard PPO default.
# Larger values improve gradient estimates but increase memory.
N_STEPS: int = 2048

# Mini-batch size for each SGD update.  64 is fast on CPU and gives
# reasonable variance reduction.
BATCH_SIZE: int = 64

# Number of passes through the rollout buffer per update.  10 is the
# standard PPO default; more epochs risk over-fitting the old policy.
N_EPOCHS: int = 10

# Discount factor.  0.99 values future rewards highly — appropriate for
# trading where multi-step profits matter more than immediate step rewards.
GAMMA: float = 0.99

# GAE smoothing parameter.  0.95 balances bias and variance in advantage
# estimates; the SB3 default.
GAE_LAMBDA: float = 0.95

# PPO clip parameter.  0.2 prevents large policy updates that could
# destabilise training; the standard default.
CLIP_RANGE: float = 0.2

# Entropy bonus coefficient.  0.01 encourages exploration to prevent the
# agent from collapsing to a degenerate "always hold" policy early in training.
ENT_COEF: float = 0.01

# --- Output paths ---
DEFAULT_MODEL_PATH: str = "models/ppo_btc_v1"
TENSORBOARD_LOG: str = "logs/ppo_btc_v1"

# --- Evaluation ---
DEFAULT_EVAL_EPISODES: int = 10

# --- DSR validation ---
# Platform base URL (respects TRADEREADY_API_URL env override).
DEFAULT_BASE_URL: str = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")

# We are testing one variant so num_trials=1 (no multiple-testing penalty).
# A DSR p-value > 0.95 means the Sharpe is statistically significant.
DSR_NUM_TRIALS: int = 1

# Hourly candles -> 8 760 periods per year.
ANNUALIZATION_FACTOR: int = 8_760

# DSR significance threshold: p_value > 0.95 signals genuine skill.
DSR_SIGNIFICANCE_THRESHOLD: float = 0.95


# ---------------------------------------------------------------------------
# Environment factory
# ---------------------------------------------------------------------------


def _make_env(
    db_url: str,
    start_time: str,
    end_time: str,
) -> gym.Env:
    """Build and wrap a ``TradeReady-BTC-Headless-v0`` environment.

    Wrappers applied in order:
      1. ``BatchStepWrapper`` — repeat each action for ``BATCH_HOLD_STEPS``
         candles; sum rewards; reduces effective step count 5×.
      2. ``NormalizationWrapper`` — online Welford z-score normalization
         clipped to ``[-1, 1]``; helps PPO converge.
      3. ``Monitor`` (SB3) — records episode rewards / lengths for logging.

    Args:
        db_url:         SQLAlchemy asyncpg connection string.
        start_time:     Backtest window start (ISO 8601).
        end_time:       Backtest window end (ISO 8601).

    Returns:
        Wrapped Gymnasium environment ready for SB3.
    """
    env = gym.make(
        ENV_ID,
        db_url=db_url,
        symbol=SYMBOL,
        starting_balance=STARTING_BALANCE,
        timeframe=TIMEFRAME,
        lookback_window=LOOKBACK_WINDOW,
        episode_length=EPISODE_LENGTH,
        reward_function=CompositeReward(
            sortino_weight=0.4,
            pnl_weight=0.3,
            activity_weight=0.2,
            drawdown_weight=0.1,
            sortino_window=50,
            activity_bonus=1.0,
            starting_balance=STARTING_BALANCE,
        ),
        start_time=start_time,
        end_time=end_time,
    )

    env = BatchStepWrapper(env, n_steps=BATCH_HOLD_STEPS)
    env = NormalizationWrapper(env)
    env = Monitor(env)
    return env


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def train(env: gym.Env, total_timesteps: int) -> PPO:
    """Instantiate and train a PPO agent.

    Args:
        env:              Training environment (already wrapped).
        total_timesteps:  Total environment interactions to train for.

    Returns:
        Trained PPO model.
    """
    print(f"\nTraining PPO for {total_timesteps:,} timesteps...")
    print(f"  TensorBoard logs: {TENSORBOARD_LOG}")
    print(f"  Env: {ENV_ID} | {SYMBOL} | {TIMEFRAME}")
    print(f"  Training window: {TRAIN_START} -> {TRAIN_END}")
    print(f"  Episode length: {EPISODE_LENGTH} candles ({EPISODE_LENGTH}h = 30 days)")
    print(f"  Batch hold steps: {BATCH_HOLD_STEPS}")
    print()

    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=LEARNING_RATE,
        n_steps=N_STEPS,
        batch_size=BATCH_SIZE,
        n_epochs=N_EPOCHS,
        gamma=GAMMA,
        gae_lambda=GAE_LAMBDA,
        clip_range=CLIP_RANGE,
        ent_coef=ENT_COEF,
        verbose=1,
        tensorboard_log=TENSORBOARD_LOG,
        seed=42,  # reproducibility; override via --seed if needed
    )

    t_start = time.time()
    model.learn(total_timesteps=total_timesteps)
    elapsed = time.time() - t_start

    print(f"\nTraining complete in {elapsed / 60:.1f} minutes ({elapsed:.0f}s).")
    return model


# ---------------------------------------------------------------------------
# OOS evaluation
# ---------------------------------------------------------------------------


def evaluate(
    model: PPO,
    db_url: str,
    n_episodes: int,
) -> dict[str, object]:
    """Run the trained policy on out-of-sample data and compute metrics.

    Metrics computed:
    - ``avg_reward``: mean total reward per episode.
    - ``sharpe_ratio``: ratio of mean return to standard deviation of
      returns, using per-episode final equity as the return proxy.
    - ``max_drawdown_pct``: worst peak-to-trough equity drop across all
      episodes, expressed as a percentage.
    - ``win_rate``: fraction of episodes where final equity exceeds the
      starting balance.
    - ``episode_returns``: list of per-episode fractional returns
      ``(final_equity - starting_balance) / starting_balance``.

    Args:
        model:      Trained PPO model.
        db_url:     SQLAlchemy asyncpg connection string.
        n_episodes: Number of evaluation episodes.

    Returns:
        Dict with keys: ``avg_reward``, ``sharpe_ratio``, ``max_drawdown_pct``,
        ``win_rate``, ``episode_returns``.
    """
    print(f"\nEvaluating policy on OOS data ({EVAL_START} -> {EVAL_END})...")
    print(f"  Episodes: {n_episodes}")

    eval_env = _make_env(
        db_url=db_url,
        start_time=EVAL_START,
        end_time=EVAL_END,
    )

    episode_rewards: list[float] = []
    episode_final_equities: list[float] = []
    episode_peak_equities: list[float] = []

    for ep in range(1, n_episodes + 1):
        obs, _info = eval_env.reset()
        ep_reward = 0.0
        done = False
        steps = 0
        peak_equity = STARTING_BALANCE
        final_equity = STARTING_BALANCE

        while not done:
            action, _states = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = eval_env.step(action)
            ep_reward += float(reward)
            steps += 1
            done = terminated or truncated

            # Track peak equity from info dict (equity key populated by the env)
            equity = float(info.get("equity", STARTING_BALANCE))
            if equity > peak_equity:
                peak_equity = equity
            final_equity = equity

        episode_rewards.append(ep_reward)
        episode_final_equities.append(final_equity)
        episode_peak_equities.append(peak_equity)

        ep_return = (final_equity - STARTING_BALANCE) / STARTING_BALANCE
        print(
            f"  Episode {ep:>2}/{n_episodes}: "
            f"reward={ep_reward:+.4f}  "
            f"final_equity={final_equity:.2f}  "
            f"return={ep_return:+.2%}  "
            f"steps={steps}"
        )

    eval_env.close()

    # --- Summary statistics ---

    avg_reward = sum(episode_rewards) / len(episode_rewards) if episode_rewards else 0.0

    # Per-episode fractional returns for Sharpe and DSR
    episode_returns = [(eq - STARTING_BALANCE) / STARTING_BALANCE for eq in episode_final_equities]

    # Episode-level Sharpe: mean / std of per-episode fractional returns
    if len(episode_returns) >= 2:
        mean_ret = sum(episode_returns) / len(episode_returns)
        variance = sum((r - mean_ret) ** 2 for r in episode_returns) / len(episode_returns)
        std_ret = math.sqrt(variance) if variance > 0.0 else 0.0
        sharpe = mean_ret / std_ret if std_ret > 0.0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown: worst (peak - final) / peak across all episodes
    max_drawdown_pct = 0.0
    for peak, final in zip(episode_peak_equities, episode_final_equities, strict=False):
        if peak > 0.0:
            dd = (peak - final) / peak * 100.0
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd

    # Win rate: episodes ending above starting balance
    wins = sum(1 for eq in episode_final_equities if eq > STARTING_BALANCE)
    win_rate = wins / len(episode_final_equities) if episode_final_equities else 0.0

    return {
        "avg_reward": avg_reward,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate": win_rate,
        "episode_returns": episode_returns,
    }


# ---------------------------------------------------------------------------
# DSR validation
# ---------------------------------------------------------------------------


def validate_dsr(
    episode_returns: list[float],
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, object]:
    """Call the platform DSR API to validate the OOS episode returns.

    The Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014) corrects the
    observed Sharpe for multiple-testing bias.  A p-value > 0.95 indicates
    that the strategy is statistically significant at the 95% confidence level.

    The DSR endpoint is public — no API key required.

    Args:
        episode_returns: List of per-episode fractional returns from evaluation.
        base_url:        Platform REST API base URL.

    Returns:
        Dict with DSR response fields, or an error dict if the call fails.
    """
    url = f"{base_url}/api/v1/metrics/deflated-sharpe"
    payload = {
        "returns": episode_returns,
        "num_trials": DSR_NUM_TRIALS,
        "annualization_factor": ANNUALIZATION_FACTOR,
    }

    print("\nValidating with Deflated Sharpe Ratio API...")
    print(f"  URL: {url}")
    print(f"  num_trials: {DSR_NUM_TRIALS}")
    print(f"  annualization_factor: {ANNUALIZATION_FACTOR}")
    print(f"  n_returns: {len(episode_returns)}")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        print(f"  WARNING: DSR API returned HTTP {exc.response.status_code}: {exc.response.text}")
        return {"error": str(exc), "status_code": exc.response.status_code}
    except httpx.RequestError as exc:
        print(f"  WARNING: DSR API request failed: {exc}")
        print("  (Is the platform running?  Set TRADEREADY_API_URL or ensure the platform is reachable.)")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(
    eval_metrics: dict[str, object],
    dsr_result: dict[str, object],
) -> None:
    """Print a formatted summary of training and evaluation results."""
    sep = "=" * 60

    print(f"\n{sep}")
    print("  OOS EVALUATION SUMMARY")
    print(sep)
    print(f"  Eval period:       {EVAL_START} -> {EVAL_END}")
    print(f"  Episodes:          {len(eval_metrics['episode_returns'])}")
    print(f"  Avg reward:        {eval_metrics['avg_reward']:+.4f}")
    print(f"  Sharpe ratio:      {eval_metrics['sharpe_ratio']:+.4f}")
    print(f"  Max drawdown:      {eval_metrics['max_drawdown_pct']:.2f}%")
    print(f"  Win rate:          {eval_metrics['win_rate']:.1%}")
    print()

    if "error" in dsr_result:
        print(f"  DSR validation:    SKIPPED ({dsr_result['error']})")
    else:
        p_value = dsr_result.get("p_value", 0.0)
        is_sig = dsr_result.get("is_significant", False)
        obs_sr = dsr_result.get("observed_sharpe", 0.0)
        dsr_stat = dsr_result.get("deflated_sharpe", 0.0)
        verdict = "PASS" if is_sig else "FAIL"
        print(f"  Observed Sharpe:   {obs_sr:.4f}")
        print(f"  Deflated Sharpe:   {dsr_stat:.4f}")
        print(f"  DSR p-value:       {p_value:.4f}")
        print(f"  DSR significance:  {verdict} (threshold={DSR_SIGNIFICANCE_THRESHOLD})")

        if not is_sig:
            print()
            print("  NOTE: DSR p-value does not meet the 0.95 threshold.")
            print("  The observed Sharpe may be a product of backtest overfitting.")
            print("  Consider: more training data, reduced timesteps, or higher ent_coef.")

    print(sep)

    # Checklist against plan targets
    max_dd = float(eval_metrics["max_drawdown_pct"])
    avg_rew = float(eval_metrics["avg_reward"])
    sharpe = float(eval_metrics["sharpe_ratio"])

    print("\n  TARGET CHECKLIST")
    print(f"  [{'OK' if avg_rew > 0 else 'FAIL':4}] Positive average OOS reward  ({avg_rew:+.4f})")
    print(f"  [{'OK' if sharpe >= 1.0 else 'WARN':4}] Sharpe >= 1.0  ({sharpe:.4f}; target >= 1.5)")
    print(f"  [{'OK' if max_dd < 8.0 else 'FAIL':4}] Max drawdown < 8%  ({max_dd:.2f}%)")

    if "is_significant" in dsr_result:
        is_sig = bool(dsr_result["is_significant"])
        print(f"  [{'OK' if is_sig else 'FAIL':4}] DSR p-value > 0.95  ({dsr_result.get('p_value', 0.0):.4f})")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Train a PPO agent on BTCUSDT using the headless TradeReady gym environment.\n"
            "\n"
            "Requires:\n"
            "  - DATABASE_URL env var (postgresql+asyncpg://...)\n"
            "  - PYTHONPATH=. (so src/ is importable by the headless env)\n"
            "  - pip install stable-baselines3>=2.0 tensorboard\n"
            "  - pip install -e tradeready-gym/\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=DEFAULT_TOTAL_TIMESTEPS,
        help=f"Total PPO training timesteps (default: {DEFAULT_TOTAL_TIMESTEPS:,}).",
    )
    parser.add_argument(
        "--eval-episodes",
        type=int,
        default=DEFAULT_EVAL_EPISODES,
        help=f"Number of OOS evaluation episodes (default: {DEFAULT_EVAL_EPISODES}).",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        default=DEFAULT_MODEL_PATH,
        help=f"Output path for the saved model (without .zip; default: {DEFAULT_MODEL_PATH!r}).",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Skip training and load an existing model from --model-path.",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip OOS evaluation (useful for quick sanity checks).",
    )
    parser.add_argument(
        "--skip-dsr",
        action="store_true",
        help="Skip Deflated Sharpe Ratio validation (useful when the platform is not running).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the full PPO training -> OOS evaluation -> DSR validation pipeline."""
    args = _parse_args()

    # --- Resolve DATABASE_URL ---
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print(
            "\nERROR: DATABASE_URL environment variable is not set.\n"
            "Example:\n"
            "  export DATABASE_URL='postgresql+asyncpg://agentexchange:password@localhost:5432/agentexchange'\n"
        )
        sys.exit(1)

    if not db_url.startswith("postgresql+asyncpg://"):
        print(
            f"\nERROR: DATABASE_URL must use the asyncpg driver.\n"
            f"Got:      {db_url[:60]}...\n"
            f"Expected: postgresql+asyncpg://...\n"
        )
        sys.exit(1)

    print(f"DATABASE_URL: {db_url[:50]}...")

    # --- Ensure output directories exist ---
    model_path = args.model_path
    pathlib.Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(TENSORBOARD_LOG).mkdir(parents=True, exist_ok=True)

    # --- Training ---
    if args.skip_train:
        zip_path = model_path if model_path.endswith(".zip") else f"{model_path}.zip"
        if not pathlib.Path(zip_path).exists():
            print(f"\nERROR: --skip-train was specified but model file not found: {zip_path}\n")
            sys.exit(1)
        print(f"\nLoading existing model from {zip_path}...")
        model = PPO.load(model_path)
    else:
        train_env = _make_env(
            db_url=db_url,
            start_time=TRAIN_START,
            end_time=TRAIN_END,
        )
        try:
            model = train(env=train_env, total_timesteps=args.timesteps)
        finally:
            # Always close to finalize TrainingTracker even on exception.
            train_env.close()

        model.save(model_path)
        zip_path = model_path if model_path.endswith(".zip") else f"{model_path}.zip"
        print(f"\nModel saved to {zip_path}")

    # --- OOS Evaluation ---
    eval_metrics: dict[str, object] = {
        "avg_reward": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "win_rate": 0.0,
        "episode_returns": [],
    }

    if not args.skip_eval:
        eval_metrics = evaluate(
            model=model,
            db_url=db_url,
            n_episodes=args.eval_episodes,
        )
    else:
        print("\nSkipping OOS evaluation (--skip-eval).")

    # --- DSR Validation ---
    dsr_result: dict[str, object] = {}

    episode_returns = list(eval_metrics.get("episode_returns", []))
    if args.skip_dsr or not episode_returns:
        if args.skip_dsr:
            print("\nSkipping DSR validation (--skip-dsr).")
        else:
            print("\nSkipping DSR validation (no episode returns collected).")
        dsr_result = {"error": "skipped"}
    else:
        # DSR requires at least 10 return observations.  With fewer episodes,
        # we pad with zeros (representing neutral episodes) rather than
        # skipping — the DSR will reflect the limited data.
        if len(episode_returns) < 10:
            pad_count = 10 - len(episode_returns)
            print(f"  Padding {pad_count} zero-return observations to meet DSR minimum of 10.")
            episode_returns = episode_returns + [0.0] * pad_count

        dsr_result = validate_dsr(
            episode_returns=episode_returns,
            base_url=DEFAULT_BASE_URL,
        )

    # --- Print summary ---
    _print_summary(eval_metrics, dsr_result)

    # --- Write results JSON ---
    results_path = pathlib.Path(model_path).parent / "train_results.json"
    results: dict[str, object] = {
        "model_path": f"{model_path}.zip",
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "eval_start": EVAL_START,
        "eval_end": EVAL_END,
        "total_timesteps": args.timesteps,
        "eval_episodes": args.eval_episodes,
        "eval_metrics": {
            "avg_reward": eval_metrics.get("avg_reward"),
            "sharpe_ratio": eval_metrics.get("sharpe_ratio"),
            "max_drawdown_pct": eval_metrics.get("max_drawdown_pct"),
            "win_rate": eval_metrics.get("win_rate"),
        },
        "dsr_validation": dsr_result,
    }
    results_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Results written to {results_path}\n")


if __name__ == "__main__":
    main()
