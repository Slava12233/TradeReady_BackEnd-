---
task_id: 11
title: "Train PPO RL agent multi-seed with Sortino/composite reward"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [10]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/rl/runner.py", "agent/strategies/rl/train.py"]
tags:
  - task
  - ml
  - training
  - rl
---

# Task 11: Train PPO RL multi-seed

## Assigned Agent: `ml-engineer`

## Objective
Run multi-seed PPO training on `TradeReady-Portfolio-v0` environment using the composite reward function. Evaluate and select the best model.

## Steps
1. `python -m agent.strategies.rl.runner --seeds 42,123,456 --timesteps 500000 --reward composite`
2. Training takes ~12h per seed on CPU (run sequentially or parallelize if possible)
3. `python -m agent.strategies.rl.evaluate --model-dir agent/strategies/rl/models/`
4. Verify best model achieves Sharpe > 0.5 on test split (note: lower threshold for aggressive strategy)
5. Generate checksums for all model files

## Acceptance Criteria
- [ ] 3 trained PPO models (one per seed) saved as `.zip` files
- [ ] SHA-256 checksums generated for each model
- [ ] Evaluation report generated in `agent/reports/`
- [ ] Best model outperforms equal-weight and buy-and-hold benchmarks
- [ ] Ensemble of 3 seeds evaluated

## Estimated Complexity
High — long compute time (~36h total for 3 seeds on CPU). May need to reduce timesteps for initial run.
