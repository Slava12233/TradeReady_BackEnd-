"""Example 08: Vectorized training with multiple environments.

Requires: pip install stable-baselines3
"""

import gymnasium as gym

import tradeready_gym  # noqa: F401

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import make_vec_env
except ImportError:
    print("Install stable-baselines3: pip install stable-baselines3")
    raise


def make_env():
    """Factory function for creating a single environment."""
    return gym.make(
        "TradeReady-BTC-Continuous-v0",
        api_key="ak_live_YOUR_KEY",
        start_time="2025-01-01T00:00:00Z",
        end_time="2025-02-01T00:00:00Z",
    )


# Create 4 parallel environments
vec_env = make_vec_env(make_env, n_envs=4)

model = PPO("MlpPolicy", vec_env, verbose=1, n_steps=128, batch_size=128)
model.learn(total_timesteps=20_000)
model.save("ppo_btc_vectorized")
print("Vectorized training complete.")
vec_env.close()
