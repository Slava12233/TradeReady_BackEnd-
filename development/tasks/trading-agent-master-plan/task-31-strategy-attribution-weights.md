---
task_id: 31
title: "Wire strategy attribution analytics to ensemble weight adjustment"
type: task
agent: "backend-developer"
phase: 4
depends_on: [23]
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["src/tasks/agent_analytics.py", "agent/strategies/ensemble/meta_learner.py"]
tags:
  - task
  - analytics
  - ensemble
---

# Task 31: Attribution → ensemble weights

## Assigned Agent: `backend-developer`

## Objective
Wire the existing `agent_strategy_attribution` Celery task output into the `MetaLearner` weight adjustment system. Strategies with negative 7-day attribution get auto-paused.

## Acceptance Criteria
- [ ] Attribution results read by `MetaLearner.update_weights()` on each trading session start
- [ ] Strategies with negative PnL attribution over 7 days auto-paused
- [ ] Monthly attribution reports saved to `development/agent-analysis/`
- [ ] Tests for attribution-based weight adjustment

## Estimated Complexity
Low — connecting existing analytics to existing weight system.
