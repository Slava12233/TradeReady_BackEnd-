---
task_id: 29
title: "Implement walk-forward validation for RL and evolutionary"
type: task
agent: "ml-engineer"
phase: 4
depends_on: [14]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/rl/runner.py", "agent/strategies/evolutionary/evolve.py"]
tags:
  - task
  - ml
  - validation
  - continuous-learning
---

# Task 29: Walk-forward validation

## Assigned Agent: `ml-engineer`

## Objective
Replace single train/test split with rolling window validation. Walk-Forward Efficiency > 50% required to deploy.

## Implementation
- Train on months 1-6, evaluate on month 7
- Train on months 2-7, evaluate on month 8
- Continue rolling through all available data
- Final score = average of all out-of-sample evaluations
- Walk-Forward Efficiency = OOS performance / in-sample performance

## Files to Modify
- `agent/strategies/rl/runner.py` — add `walk_forward_train()` method
- `agent/strategies/evolutionary/evolve.py` — add rolling battle window evaluation

## Acceptance Criteria
- [ ] Rolling window splits implemented for both RL and GA
- [ ] Walk-Forward Efficiency metric computed
- [ ] WFE < 50% triggers warning (likely overfit)
- [ ] Results include per-window breakdown
- [ ] Tests for window splitting logic

## Estimated Complexity
Medium — modifying existing training loops to iterate over windows.
