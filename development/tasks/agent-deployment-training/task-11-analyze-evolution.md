---
task_id: 11
title: "Analyze evolution results"
type: task
agent: "ml-engineer"
phase: 6
depends_on: [10]
status: "pending"
board: "[[agent-deployment-training/README]]"
priority: "medium"
files: ["agent/reports/"]
tags:
  - task
  - deployment
  - training
---

# Task 11: Analyze evolution results

## Assigned Agent: `ml-engineer`

## Objective
Analyze the evolution results: fitness curves, parameter convergence, champion behavior.

## Steps
```bash
python -m agent.strategies.evolutionary.analyze \
  --log-path agent/strategies/evolutionary/results/evolution_log.json
```

## Acceptance Criteria
- [ ] Fitness curve data exported (best/avg/worst per gen)
- [ ] Parameter convergence analysis shows which params stabilized
- [ ] Champion description in human-readable terms
- [ ] Report saved to `agent/reports/evolution-report-*.json`

## Dependencies
- Task 10: evolution complete with champion genome

## Estimated Complexity
Low — running existing analysis script.
