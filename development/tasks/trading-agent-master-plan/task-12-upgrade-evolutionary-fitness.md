---
task_id: 12
title: "Upgrade evolutionary fitness function with OOS component"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [2]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/evolutionary/evolve.py", "agent/strategies/evolutionary/battle_runner.py"]
tags:
  - task
  - ml
  - evolutionary
---

# Task 12: Upgrade evolutionary fitness function

## Assigned Agent: `ml-engineer`

## Objective
Replace the simple `sharpe - 0.5 * max_drawdown` fitness with a multi-factor function that includes out-of-sample performance to prevent overfitting.

## New Fitness Function
```python
fitness = (
    0.35 * sharpe_ratio
    + 0.25 * profit_factor
    - 0.20 * max_drawdown_pct
    + 0.10 * win_rate
    + 0.10 * oos_sharpe_ratio  # out-of-sample
)
```

## Steps
1. Modify `evolve.py` to split battle periods into in-sample (70%) and out-of-sample (30%)
2. Compute OOS metrics by running a secondary evaluation on the held-out period
3. Add `profit_factor` and `win_rate` to fitness calculation
4. Update `ConvergenceDetector` to track the new composite metric

## Acceptance Criteria
- [ ] Fitness function uses 5 factors including OOS Sharpe
- [ ] Battle periods split into train/test segments
- [ ] OOS performance tracked and logged per generation
- [ ] Convergence detection works with new fitness metric
- [ ] Tests for new fitness calculation

## Estimated Complexity
Medium — modify existing fitness calculation, add train/test split logic.
