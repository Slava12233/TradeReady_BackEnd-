---
task_id: 33
title: "Add backtest comparison and decision analysis tools"
type: task
agent: "backend-developer"
phase: 5
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/tools/rest_tools.py"]
tags:
  - task
  - tools
  - platform
---

# Task 33: Backtest comparison + decision analysis tools

## Assigned Agent: `backend-developer`

## Objective
Wire 5 unused platform endpoints into agent REST tools:
1. `GET /backtest/compare` — compare multiple backtest sessions
2. `GET /backtest/best` — auto-select best by metric
3. `GET /backtest/{id}/results/equity-curve` — time-series equity
4. `GET /agents/{id}/decisions/analyze` — decision quality analysis
5. `PUT /account/risk-profile` — agent self-tuning risk limits

## Acceptance Criteria
- [ ] 5 new REST tools registered
- [ ] Tools follow existing `PlatformRESTClient` pattern
- [ ] Agent can compare backtests and analyze its own decisions
- [ ] Tests for each new tool

## Estimated Complexity
Low — following existing pattern for 5 endpoints.
