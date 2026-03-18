"""Example 10: Live paper trading with a trained model.

Requires: pip install stable-baselines3
WARNING: This trades on a live account (virtual funds, real prices).
"""

import gymnasium as gym

import tradeready_gym  # noqa: F401

try:
    from stable_baselines3 import PPO
except ImportError:
    print("Install stable-baselines3: pip install stable-baselines3")
    raise

# Load your trained model
model = PPO.load("ppo_btc_trader")

# Create a live environment (real-time prices, 1-minute steps)
env = gym.make(
    "TradeReady-Live-v0",
    api_key="ak_live_YOUR_KEY",
    step_interval_sec=60,  # wait 60s between decisions
)

obs, info = env.reset()
print("Starting live paper trading... (Ctrl+C to stop)")

try:
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        equity = info.get("equity", "?")
        print(f"Step {info.get('step', 0)} | Equity: {equity} | Reward: {reward:.4f}")
except KeyboardInterrupt:
    print("\nStopping live trading.")
finally:
    env.close()
