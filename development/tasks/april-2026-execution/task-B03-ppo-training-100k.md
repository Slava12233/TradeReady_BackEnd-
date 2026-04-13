---
task_id: B-03
title: "Run PPO training (100K steps)"
type: task
agent: "ml-engineer"
track: B
depends_on: ["B-02"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/train_ppo_btc.py"]
tags:
  - task
  - ml
  - training
  - ppo
  - critical-path
---

# Task B-03: Run PPO training (100K steps)

## Assigned Agent: `ml-engineer`

## Objective
Run a quick 100K-step PPO training as a validation run before committing to the full 500K-step training.

## Context
This is a smoke test for the training pipeline. If 100K steps complete without crashes and show some learning signal, the full run is likely to succeed. Estimated runtime: ~30 minutes on CPU.

## Command
```bash
python scripts/train_ppo_btc.py --timesteps 100000 --eval-episodes 3
```

## Acceptance Criteria
- [ ] Training script starts without errors
- [ ] 100K timesteps complete
- [ ] TensorBoard logs are written to `runs/` directory
- [ ] OOS evaluation runs for 3 episodes
- [ ] No OOM errors or connection issues
- [ ] Training shows some learning signal (reward trend, even if noisy)

## Dependencies
- **B-02**: Headless env must work correctly

## Agent Instructions
Read `scripts/train_ppo_btc.py` first to understand the training configuration (BatchStepWrapper, NormalizationWrapper, CompositeReward). Run the command and monitor output. If it crashes, diagnose whether the issue is with the env, the reward function, or SB3 configuration. Key things to watch: observation normalization, reward scaling, episode lengths.

## Estimated Complexity
Medium — first real training run. May need hyperparameter adjustments if diverges.
