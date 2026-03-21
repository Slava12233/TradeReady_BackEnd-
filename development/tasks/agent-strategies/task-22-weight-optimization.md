---
task_id: 22
title: "Meta-learner weight optimization via battles"
type: task
agent: "ml-engineer"
phase: E
depends_on: [21]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "low"
files: ["agent/strategies/ensemble/optimize_weights.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 22: Meta-learner weight optimization via battles

## Assigned Agent: `ml-engineer`

## Objective
Find optimal weights for the meta-learner by running historical battles with different weight configurations.

## Files to Create
- `agent/strategies/ensemble/optimize_weights.py`:
  - Generate 12 weight configurations:
    - Equal weights: [0.33, 0.33, 0.33]
    - RL-heavy: [0.5, 0.25, 0.25]
    - Evolved-heavy: [0.25, 0.5, 0.25]
    - Regime-heavy: [0.25, 0.25, 0.5]
    - 8 random combinations
  - For each config: create agent, run through backtest with the ensemble using those weights
  - Rank by Sharpe ratio
  - Output: optimal weights and comparison table
  - CLI: `python -m agent.strategies.ensemble.optimize_weights`

## Acceptance Criteria
- [ ] 12 configurations tested on same historical period
- [ ] Results ranked by Sharpe ratio
- [ ] Optimal weights saved to config file
- [ ] Out-of-sample validation: optimal weights tested on different period
- [ ] Comparison table shows all configs with Sharpe, ROI, max drawdown

## Dependencies
- Task 21: meta-learner with configurable weights

## Agent Instructions
Use the backtest API (not full battle system) for faster iteration. Each config can be a separate backtest session. This is essentially a grid search over the weight space.

## Estimated Complexity
Medium — grid search + backtest orchestration.
