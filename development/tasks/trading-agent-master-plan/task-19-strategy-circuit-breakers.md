---
task_id: 19
title: "Implement strategy-level circuit breakers"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/ensemble/meta_learner.py", "agent/strategies/ensemble/run.py"]
tags:
  - task
  - risk
  - strategy
---

# Task 19: Strategy-level circuit breakers

## Assigned Agent: `backend-developer`

## Objective
Add per-strategy circuit breakers that auto-pause underperforming strategies.

## Rules
- 3 consecutive losses from a strategy → pause for 24h
- Strategy drawdown > 5% in a week → pause for 48h
- Ensemble wrong on > 60% of recent 20 signals → reduce all sizes to 25%

## Implementation
- Track in Redis: `strategy:circuit:{strategy_name}:{agent_id}` with TTL
- Add `StrategyCircuitBreaker` class
- Wire into `EnsembleRunner` — skip paused strategies in signal generation

## Acceptance Criteria
- [ ] `StrategyCircuitBreaker` tracks consecutive losses and weekly PnL per strategy
- [ ] Paused strategies excluded from ensemble signal combination
- [ ] Redis keys auto-expire (24h/48h TTL)
- [ ] Ensemble-wide size reduction when consensus accuracy drops
- [ ] Tests for each trigger condition

## Estimated Complexity
Medium — new class with Redis state management.
