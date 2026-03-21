---
task_id: 02
title: "PPO training pipeline setup"
type: task
agent: "ml-engineer"
phase: A
depends_on: [1]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "high"
files: ["agent/strategies/rl/__init__.py", "agent/strategies/rl/config.py", "agent/strategies/rl/train.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 02: PPO training pipeline setup

## Assigned Agent: `ml-engineer`

## Objective
Create the RL training pipeline scaffolding: config, training script, and environment wiring. The agent should be able to run `python -m agent.strategies.rl.train` and begin PPO training against the platform's Gymnasium environments.

## Context
Strategy 4 from the plan. The `tradeready-gym` package already provides environments, rewards, and wrappers. This task wires them together with Stable-Baselines3 PPO.

## Files to Create
- `agent/strategies/__init__.py` — package init
- `agent/strategies/rl/__init__.py` — package init
- `agent/strategies/rl/config.py` — Pydantic config for all hyperparameters:
  - PPO: learning_rate (3e-4), clip_range (0.2), n_steps (2048), batch_size (64), n_epochs (10), gamma (0.99), gae_lambda (0.95), ent_coef (0.01), vf_coef (0.5), max_grad_norm (0.5)
  - Environment: asset_universe (["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]), timeframe ("1h"), lookback_window (30), train_start/end, val_start/end, test_start/end
  - Reward: reward_type ("sharpe"), drawdown_penalty_coeff (0.5)
  - Training: total_timesteps (500_000), n_envs (4), seed (42), save_freq (10_000), log_dir
- `agent/strategies/rl/train.py` — training script:
  - Load config from env/CLI args
  - Create `TradeReady-Portfolio-v0` env with proper kwargs
  - Apply wrappers: FeatureEngineering → Normalization
  - Create SB3 `SubprocVecEnv` for parallel envs (or `DummyVecEnv` fallback)
  - Initialize PPO with MlpPolicy (2 layers × 256 units)
  - Add SB3 callbacks: CheckpointCallback (save every N steps), EvalCallback (validate periodically)
  - Call `model.learn(total_timesteps=config.total_timesteps)`
  - Save final model to `agent/strategies/rl/models/`

## Acceptance Criteria
- [ ] `agent/strategies/rl/config.py` exists with all hyperparameters as typed Pydantic fields
- [ ] `agent/strategies/rl/train.py` is runnable: `python -m agent.strategies.rl.train --help` shows all options
- [ ] Training starts and completes at least 1 episode without errors (test with 1000 timesteps)
- [ ] Model checkpoint is saved to disk
- [ ] `--seed` flag ensures reproducible results (same seed = same initial weights)
- [ ] `structlog` logging shows episode rewards, learning rate, and training progress
- [ ] No `float` for financial values anywhere in the code

## Dependencies
- Task 01 output: gym API research doc (observation dimensions, API call counts)
- `tradeready-gym` package installed: `pip install -e tradeready-gym/`
- `stable-baselines3[extra]` and `torch` installed

## Agent Instructions
Read `tradeready-gym/examples/` for reference implementations. Use `pydantic-settings` for config (same pattern as `agent/config.py`). Keep the training script under 200 lines — configuration belongs in the config class, not hardcoded.

## Estimated Complexity
Medium — mostly wiring existing components together.
