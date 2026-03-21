---
task_id: 07
title: "Evaluate PPO models vs benchmarks"
type: task
agent: "ml-engineer"
phase: 5
depends_on: [6]
status: "pending"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["agent/reports/"]
tags:
  - task
  - deployment
  - training
---

# Task 07: Evaluate PPO models vs benchmarks

## Assigned Agent: `ml-engineer`

## Objective
Run trained PPO models on held-out test data and compare against 3 benchmarks.

## Steps
1. Run evaluation:
   ```bash
   python -m agent.strategies.rl.evaluate \
     --model-dir agent/strategies/rl/models/
   ```
2. Review comparison: PPO vs equal-weight vs BTC-hold vs ETH-hold
3. Check if ensemble (mean of 3 seeds) outperforms individuals

## Acceptance Criteria
- [ ] Evaluation completes on held-out test period
- [ ] PPO outperforms at least 2/3 benchmarks
- [ ] Report saved to `agent/reports/ppo-evaluation-*.json`
- [ ] Per-seed metrics: Sharpe, ROI, max drawdown, win rate
- [ ] Ensemble (3 seeds) metric included if all 3 seeds trained

## Dependencies
- Task 06: at least 1 trained PPO model

## Agent Instructions
The evaluation script loads all `ppo_seed*.zip` files from the model directory. It creates a test-period gym environment and runs deterministic episodes. Benchmarks are computed analytically from candle data.

## Estimated Complexity
Low — running evaluation script, analyzing output.
