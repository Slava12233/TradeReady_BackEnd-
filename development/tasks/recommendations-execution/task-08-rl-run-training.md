---
task_id: 8
title: "Run PPO training and evaluate results"
type: task
agent: "ml-engineer"
phase: 2
depends_on: [7]
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files:
  - "models/ppo_btc_v1.zip"
tags:
  - task
  - ml
  - rl-training
  - evaluation
---

# Task 08: Run PPO Training and Evaluate Results

## Assigned Agent: `ml-engineer`

## Objective
Execute the training script, monitor convergence, evaluate on OOS data, and validate with DSR.

## Context
Task 7 creates the script. This task runs it and evaluates the output.

## Acceptance Criteria
- [ ] Training completes without errors (500K timesteps)
- [ ] Model saved to `models/ppo_btc_v1.zip`
- [ ] TensorBoard shows converging reward curve
- [ ] OOS evaluation: positive average reward across 10 episodes
- [ ] OOS Sharpe Ratio >= 1.0 (target: >= 1.5)
- [ ] Deflated Sharpe p-value < 0.05 (statistically significant)
- [ ] Max drawdown < 8% on OOS data
- [ ] Training report saved to `development/reports/rl-training-report.md`

## Dependencies
- **Task 7** (training script created)

## Agent Instructions
1. Set `DATABASE_URL` and `PYTHONPATH=.`
2. Run `python scripts/train_ppo_btc.py`
3. Monitor TensorBoard for convergence
4. If training fails to converge after 100K steps, try reducing lookback_window to 20 or increasing batch_hold_steps to 10
5. Save results report with metrics

## Estimated Complexity
High — training takes 2-6 hours on CPU; evaluation requires analysis.
