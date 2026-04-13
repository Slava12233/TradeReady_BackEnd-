---
task_id: B-05
title: "Run full PPO training (500K steps)"
type: task
agent: "ml-engineer"
track: B
depends_on: ["B-04"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/train_ppo_btc.py", "models/"]
tags:
  - task
  - ml
  - training
  - ppo
  - critical-path
---

# Task B-05: Run full PPO training (500K steps)

## Assigned Agent: `ml-engineer`

## Objective
Run the full 500K-step PPO training with default hyperparameters. This produces the first trained model for the platform.

## Command
```bash
python scripts/train_ppo_btc.py
```

## Acceptance Criteria
- [ ] 500K timesteps complete (est. 2-6 hours on CPU)
- [ ] Model saved to `models/ppo_btc_v1.zip`
- [ ] TensorBoard curves show learning (reward increasing over timesteps)
- [ ] OOS evaluation completes (10 episodes by default)
- [ ] No crashes or memory issues during long run

## Dependencies
- **B-04**: TensorBoard from 100K run must show learning signal (if flat, tune hyperparams first)

## Agent Instructions
This is the main training run. Run with defaults (the script uses 500K timesteps). Monitor periodically for crashes. The script handles checkpointing and TensorBoard logging. If it crashes mid-way, check for memory issues (CPU training can be memory-intensive with large replay buffers). The model will be saved automatically at completion.

**Fallback**: If training diverges (reward goes to -inf or NaN), stop and adjust:
1. Reduce learning rate (3e-4 → 1e-4)
2. Increase batch size
3. Clip reward values

## Estimated Complexity
Medium — long-running but automated. Risk: divergence, memory issues.
