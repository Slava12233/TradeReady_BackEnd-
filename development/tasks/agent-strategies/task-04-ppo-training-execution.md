---
task_id: 04
title: "PPO training execution & convergence"
agent: "ml-engineer"
phase: A
depends_on: [2, 3]
status: "completed"
priority: "high"
files: ["agent/strategies/rl/train.py", "agent/strategies/rl/models/"]
---

# Task 04: PPO training execution & convergence

## Assigned Agent: `ml-engineer`

## Objective
Execute the full PPO training run (500K timesteps), monitor convergence via TrainingTracker, and tune hyperparameters if validation Sharpe < 1.0. Train 3 agents with different seeds for ensemble robustness.

## Context
This is the actual training — the longest-running task in Phase A. Expected wall-clock: 1-2 hours with 4 parallel envs. The TrainingTracker will report to `/api/v1/training/runs/{id}/learning-curve` so progress is visible in the dashboard.

## Steps
1. Run data_prep.py to confirm data readiness
2. Start training with seed=42: `python -m agent.strategies.rl.train --seed 42 --timesteps 500000`
3. Monitor learning curve (reward should trend upward, stabilize by ~300K steps)
4. If validation Sharpe < 1.0 after full training:
   - Increase entropy coefficient (more exploration)
   - Reduce learning rate (more stable updates)
   - Try longer training (750K steps)
5. Once seed=42 converges, train seeds 123 and 456
6. Save all 3 models to `agent/strategies/rl/models/`

## Acceptance Criteria
- [ ] At least 1 model achieves validation Sharpe > 1.0
- [ ] All 3 seeds complete training without crashes
- [ ] Learning curves show clear improvement (not flat or diverging)
- [ ] TrainingTracker data is visible in platform dashboard
- [ ] Models saved to disk and loadable: `PPO.load("agent/strategies/rl/models/ppo_seed42")`
- [ ] Training log includes: final Sharpe, ROI, max drawdown, win rate per seed

## Dependencies
- Task 02: training pipeline working
- Task 03: data validated, splits defined
- Platform running with backtest API accessible
- `stable-baselines3` and `torch` installed

## Agent Instructions
If training takes longer than expected, reduce to 2 parallel envs to lower API load. Watch for `429 Too Many Requests` from the API — if that happens, reduce `n_envs` or add `time.sleep(0.01)` between steps. Log GPU/CPU utilization if possible.

## Estimated Complexity
High — long-running, may require hyperparameter tuning iterations.
