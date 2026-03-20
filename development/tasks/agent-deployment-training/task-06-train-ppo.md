---
task_id: 06
title: "Train PPO agent (3 seeds)"
agent: "ml-engineer"
phase: 5
depends_on: [3]
status: "validated"
priority: "high"
files: ["agent/strategies/rl/models/"]
---

# Task 06: Train PPO agent (3 seeds)

## Assigned Agent: `ml-engineer`

## Objective
Run PPO training with 3 seeds (42, 123, 456) for 500K timesteps each. Enable auto-tuning if Sharpe < 1.0.

## Steps
1. Start with seed 42:
   ```bash
   python -m agent.strategies.rl.runner \
     --seeds 42 \
     --timesteps 500000 \
     --target-sharpe 1.0 \
     --tune \
     --max-tune-attempts 3
   ```
2. If seed 42 converges, train seeds 123 and 456:
   ```bash
   python -m agent.strategies.rl.runner \
     --seeds 42,123,456 \
     --timesteps 500000
   ```
3. Check training logs in `agent/strategies/rl/results/training_log.json`

## Acceptance Criteria
- [ ] At least 1 model achieves validation Sharpe > 1.0
- [ ] All 3 seeds complete without crashes
- [ ] Models saved to `agent/strategies/rl/models/ppo_seed{N}.zip`
- [ ] Training log saved to `agent/strategies/rl/results/training_log.json`
- [ ] Learning curves show improvement (not flat or diverging)

## Dependencies
- Task 03: historical data covering train/val/test splits (2024-01-01 through 2025-01-01)

## Agent Instructions
Read `agent/strategies/rl/CLAUDE.md` for training pipeline details. PPO training uses the `TradeReady-Portfolio-v0` gym environment with 4 parallel SubprocVecEnv workers. If API rate-limited (429), reduce `--n-envs` to 2. Expected wall-clock: 1-2 hours per seed on CPU, faster with GPU.

## Estimated Complexity
High — long-running training, may require hyperparameter tuning.
