---
task_id: 14
title: "Optimize ensemble weights across all trained strategies"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [9, 11, 13]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/ensemble/optimize_weights.py", "agent/strategies/ensemble/config.py"]
tags:
  - task
  - ml
  - ensemble
---

# Task 14: Optimize ensemble weights

## Assigned Agent: `ml-engineer`

## Objective
Find optimal weights for combining RL, evolved, and regime signals now that all three strategies are trained. Validate ensemble outperforms each individual strategy.

## Steps
1. `python -m agent.strategies.ensemble.optimize_weights --base-url http://localhost:8000 --seed 42`
2. `python -m agent.strategies.ensemble.validate --base-url http://localhost:8000 --periods 3`
3. Compare ensemble vs each strategy in isolation
4. Save optimal weights to `optimal_weights.json`

## Acceptance Criteria
- [ ] Optimal weights found and saved
- [ ] Ensemble outperforms best individual strategy on Sharpe
- [ ] Validation across 3 periods shows consistent improvement
- [ ] Default `EnsembleConfig` updated with optimized weights

## Estimated Complexity
Medium — optimization is automated, validation takes compute time.
