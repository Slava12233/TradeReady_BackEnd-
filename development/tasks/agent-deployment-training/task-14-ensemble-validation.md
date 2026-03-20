---
task_id: 14
title: "Run ensemble final validation"
agent: "e2e-tester"
phase: 8
depends_on: [13]
status: "pending"
priority: "medium"
files: ["agent/reports/"]
---

# Task 14: Run ensemble final validation

## Assigned Agent: `e2e-tester`

## Objective
Compare ensemble vs each individual strategy across 3 held-out periods.

## Steps
```bash
python -m agent.strategies.ensemble.validate \
  --base-url http://localhost:8000 \
  --api-key ak_live_KEY \
  --periods 3
```

## Acceptance Criteria
- [ ] Ensemble tested against PPO-only, Evolved-only, Regime-only
- [ ] Ensemble outperforms individuals in 2/3 periods
- [ ] Buy-and-hold baseline included
- [ ] Report saved to `agent/reports/ensemble-final-validation-*.json`

## Dependencies
- Task 13: optimized weights available

## Estimated Complexity
Medium — battle orchestration with result collection.
