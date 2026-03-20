---
task_id: 13
title: "Run ensemble weight optimization"
agent: "e2e-tester"
phase: 8
depends_on: [5, 7, 11]
status: "pending"
priority: "medium"
files: ["agent/reports/"]
---

# Task 13: Run ensemble weight optimization

## Assigned Agent: `e2e-tester`

## Objective
Find optimal weights for combining PPO, evolved, and regime signals.

## Steps
```bash
python -m agent.strategies.ensemble.optimize_weights \
  --base-url http://localhost:8000 \
  --api-key ak_live_KEY
```

## Acceptance Criteria
- [ ] 12 weight configurations tested
- [ ] Results ranked by Sharpe ratio
- [ ] Optimal weights identified and saved
- [ ] Report saved to `agent/reports/weight-optimization-*.json`

## Dependencies
- Task 05: regime classifier trained
- Task 07: PPO models evaluated
- Task 11: evolution results analyzed

## Estimated Complexity
Medium — grid search over weight configurations.
