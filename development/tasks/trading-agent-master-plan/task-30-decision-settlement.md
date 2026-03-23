---
task_id: 30
title: "Create decision outcome settlement Celery task"
type: task
agent: "backend-developer"
phase: 4
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["src/tasks/celery_app.py", "src/tasks/agent_analytics.py"]
tags:
  - task
  - celery
  - feedback-loop
---

# Task 30: Decision outcome settlement

## Assigned Agent: `backend-developer`

## Objective
Create Celery beat task `settle_agent_decisions` (every 5 minutes) that closes the feedback loop from trade outcome to agent learning system.

## Implementation
1. `AgentDecisionRepository.find_unresolved()` — get decisions with no `outcome_pnl`
2. For each: check if the linked order has been filled via `OrderRepository`
3. Compute realized PnL from trade data
4. `AgentDecisionRepository.update_outcome(decision_id, outcome_pnl)`
5. `TradingJournal` consumes settled decisions to reinforce/weaken memories

## Files to Modify
- `src/tasks/agent_analytics.py` — add `settle_agent_decisions` task
- `src/tasks/celery_app.py` — register in beat schedule (every 5 minutes)

## Acceptance Criteria
- [ ] Task runs every 5 minutes via Celery beat
- [ ] Unresolved decisions matched to filled orders
- [ ] `outcome_pnl` populated with realized PnL
- [ ] Memory reinforcement triggered on settlement
- [ ] Tests for settlement logic

## Estimated Complexity
Medium — querying across decision and order tables, computing PnL.
