---
task_id: 21
title: "Implement drawdown recovery protocol"
type: task
agent: "backend-developer"
phase: 2
depends_on: [17]
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/risk/recovery.py"]
tags:
  - task
  - risk
  - recovery
---

# Task 21: Drawdown recovery protocol

## Assigned Agent: `backend-developer`

## Objective
Create `RecoveryManager` class that manages the transition from reduced trading back to full size after a drawdown event.

## Recovery Sequence
1. After size reduction triggers: wait for ATR to return to < 1.5x median
2. Resume at 25% position sizes
3. Scale up 25% per day over 4 days if no further losses
4. Full size only after recovering 50% of the drawdown

## Files to Create
- `agent/strategies/risk/recovery.py` — `RecoveryManager` class

## Acceptance Criteria
- [ ] `RecoveryManager` tracks recovery state (RECOVERING, SCALING_UP, FULL)
- [ ] ATR normalization check before resuming
- [ ] Graduated position size increase over 4 days
- [ ] 50% drawdown recovery required for full size
- [ ] State persisted in Redis for crash recovery
- [ ] Tests for full recovery sequence

## Estimated Complexity
Medium — new class with state machine logic.
