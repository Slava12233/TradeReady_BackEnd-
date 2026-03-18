"""Example 09: Evaluate a trained model.

Requires: pip install stable-baselines3
"""

import gymnasium as gym

import tradeready_gym  # noqa: F401

try:
    from stable_baselines3 import PPO
except ImportError:
    print("Install stable-baselines3: pip install stable-baselines3")
    raise

# Load trained model
model = PPO.load("ppo_btc_trader")

# Evaluate on a different date range (out-of-sample)
env = gym.make(
    "TradeReady-BTC-Continuous-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-03-01T00:00:00Z",
    end_time="2025-03-15T00:00:00Z",
    track_training=False,  # don't report evaluation as training
)

obs, info = env.reset()
total_reward = 0.0
steps = 0

while True:
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, info = env.step(action)
    total_reward += reward
    steps += 1
    if terminated or truncated:
        break

print(f"Evaluation: {steps} steps | Total reward: {total_reward:.2f} | Final equity: {info.get('equity', '?')}")
env.close()
