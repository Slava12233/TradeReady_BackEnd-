---
task_id: 10
title: "Add composite reward function for RL training"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [2]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["tradeready-gym/tradeready_gym/rewards/", "agent/strategies/rl/config.py"]
tags:
  - task
  - ml
  - rl
  - reward
---

# Task 10: Add composite reward function for RL

## Assigned Agent: `ml-engineer`

## Objective
Create a new composite reward function that combines multiple objectives for the aggressive 10% monthly target:
```python
reward = 0.4 * sortino_increment + 0.3 * pnl_normalized + 0.2 * activity_bonus + 0.1 * drawdown_penalty
```

## Context
Current reward types are: `pnl`, `sharpe`, `sortino`, `drawdown`. For 10% monthly, we need a reward that encourages active trading (activity bonus), penalizes inaction, and uses Sortino (penalizes only downside).

## Files to Modify/Create
- `tradeready-gym/tradeready_gym/rewards/composite.py` — new `CompositeReward` class
- `tradeready-gym/tradeready_gym/rewards/__init__.py` — register new reward
- `agent/strategies/rl/config.py` — add `"composite"` to `reward_type` options

## Acceptance Criteria
- [ ] `CompositeReward` class implemented with 4 weighted components
- [ ] Registered in gym rewards and selectable via `--reward composite`
- [ ] `RLConfig.reward_type` accepts `"composite"`
- [ ] Unit tests for reward calculation
- [ ] Activity bonus prevents model from learning to hold cash

## Estimated Complexity
Medium — new reward class following existing pattern.
