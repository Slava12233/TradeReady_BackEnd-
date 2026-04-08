"""RL training example: PPO agent on TradeReady-Portfolio-v0.

Demonstrates how to train a Proximal Policy Optimization (PPO) agent from
Stable-Baselines3 using the TradeReady Gymnasium environment:
  1. Register the TradeReady gym environments by importing tradeready_gym
  2. Wrap TradeReady-Portfolio-v0 with NormalizationWrapper + BatchStepWrapper
  3. Train PPO for a configurable number of timesteps
  4. Evaluate the trained policy over several test episodes
  5. Report average reward and equity

Requirements:
    pip install -e sdk/
    pip install -e tradeready-gym/
    pip install stable-baselines3>=2.0

    export TRADEREADY_API_URL=http://localhost:8000
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY

Run:
    python sdk/examples/rl_training.py
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Check for Stable-Baselines3 before importing anything else
# ---------------------------------------------------------------------------

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.monitor import Monitor
except ImportError:
    print(
        "ERROR: stable-baselines3 is required for this example.\n"
        "Install it with:  pip install stable-baselines3>=2.0"
    )
    sys.exit(1)

import gymnasium as gym

# Import tradeready_gym to trigger gymnasium.register() side-effects
import tradeready_gym  # noqa: F401
from tradeready_gym.rewards.composite import CompositeReward
from tradeready_gym.wrappers.batch_step import BatchStepWrapper
from tradeready_gym.wrappers.normalization import NormalizationWrapper

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("TRADEREADY_API_KEY", "")

TRAIN_TIMESTEPS = int(os.environ.get("TRADEREADY_TRAIN_STEPS", "50000"))
BATCH_HOLD = 5        # hold each action for N candles (reduces HTTP calls)
EVAL_EPISODES = 3     # episodes to evaluate after training


def _require_env() -> None:
    """Verify required environment variables are set before proceeding."""
    if not API_KEY:
        print("ERROR: TRADEREADY_API_KEY environment variable is not set.")
        sys.exit(1)


def make_env(track_training: bool = True) -> gym.Env:
    """Build and wrap a TradeReady-Portfolio-v0 environment.

    The portfolio environment allocates weights across BTC, ETH, and SOL.
    We wrap it with:
      - BatchStepWrapper to hold each action for 5 candles (fewer API calls)
      - NormalizationWrapper to z-score the observation (helps PPO converge)
      - Monitor wrapper from SB3 for episode logging

    Args:
        track_training: When True, episodes are reported to the platform's
                        training API.  Set False for evaluation environments.

    Returns:
        A wrapped Gymnasium environment ready for SB3.
    """
    env = gym.make(
        "TradeReady-Portfolio-v0",
        api_key=API_KEY,
        base_url=BASE_URL,
        # 30-day training window
        start_time="2025-01-01T00:00:00Z",
        end_time="2025-01-31T23:59:00Z",
        starting_balance=10000.0,
        reward_function=CompositeReward(),
        track_training=track_training,
        strategy_label="ppo_example",
    )

    # Repeat each action for 5 consecutive candles (5x fewer HTTP steps)
    env = BatchStepWrapper(env, n_steps=BATCH_HOLD)

    # Online z-score normalization: keeps observations in a stable range
    env = NormalizationWrapper(env)

    # SB3 Monitor wrapper: records episode rewards / lengths for logging
    env = Monitor(env)

    return env


def train(env: gym.Env) -> PPO:
    """Instantiate and train a PPO agent.

    Args:
        env: Training environment (already wrapped).

    Returns:
        Trained PPO model.
    """
    print(f"Training PPO for {TRAIN_TIMESTEPS:,} timesteps...")

    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=3e-4,
        n_steps=512,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        verbose=1,
    )

    model.learn(total_timesteps=TRAIN_TIMESTEPS)
    print("Training complete.")
    return model


def evaluate(model: PPO, n_episodes: int = EVAL_EPISODES) -> None:
    """Run the trained policy for several episodes and print stats.

    Args:
        model:      Trained PPO model.
        n_episodes: Number of evaluation episodes.
    """
    print(f"\nEvaluating policy over {n_episodes} episode(s)...")

    # Build a separate eval env with training tracking disabled
    eval_env = make_env(track_training=False)

    total_rewards: list[float] = []
    for ep in range(n_episodes):
        obs, _info = eval_env.reset()
        ep_reward = 0.0
        done = False
        steps = 0

        while not done:
            action, _states = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, _info = eval_env.step(action)
            ep_reward += float(reward)
            steps += 1
            done = terminated or truncated

        total_rewards.append(ep_reward)
        print(f"  Episode {ep + 1}: reward={ep_reward:.4f}  steps={steps}")

    avg_reward = sum(total_rewards) / len(total_rewards)
    print(f"\nAverage reward over {n_episodes} episode(s): {avg_reward:.4f}")

    eval_env.close()


def main() -> None:
    """Run the full PPO training + evaluation workflow."""
    _require_env()

    # Optional: validate the environment before training (catches API errors early)
    print("Checking environment compatibility...")
    env = make_env(track_training=True)
    check_env(env, warn=True)

    # Train PPO
    model = train(env)
    env.close()

    # Evaluate the trained policy
    evaluate(model)

    # Optionally save the model for later use
    model.save("ppo_portfolio_agent")
    print("\nModel saved to ppo_portfolio_agent.zip")


if __name__ == "__main__":
    main()
