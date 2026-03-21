---
task_id: 20
title: "Risk agent tests"
type: task
agent: "test-runner"
phase: D
depends_on: [17, 18]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: ["agent/tests/test_risk_agent.py", "agent/tests/test_veto.py", "agent/tests/test_sizing.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 20: Risk agent tests

## Assigned Agent: `test-runner`

## Objective
Write tests for risk assessment, veto pipeline, dynamic sizing, and middleware integration.

## Files to Create
- `agent/tests/test_risk_agent.py`:
  - Exposure calculation correct (positions / equity)
  - Drawdown triggers REDUCE at 5%
  - Daily loss triggers HALT at 3%
  - Clean portfolio gets OK verdict

- `agent/tests/test_veto.py`:
  - HALT risk → signal VETOED
  - Low confidence signal → VETOED
  - Over-exposure → RESIZED to remaining capacity
  - All checks pass → APPROVED
  - Short-circuit: first failing check stops pipeline

- `agent/tests/test_sizing.py`:
  - High volatility → smaller size
  - High drawdown → smaller size
  - Low volatility → larger size (up to cap)
  - Result always within [min, max] bounds

## Acceptance Criteria
- [ ] All tests pass
- [ ] Each veto check has at least 2 tests (trigger and no-trigger)
- [ ] Sizing tests verify numerical correctness
- [ ] All financial values use Decimal in tests

## Dependencies
- Task 17, 18: risk agent and veto code

## Estimated Complexity
Low-Medium — focused unit tests.
