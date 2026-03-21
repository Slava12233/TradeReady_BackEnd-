---
task_id: 21
title: "Run full test suite & fix failures"
type: task
agent: "test-runner"
phase: 11
depends_on: [15, 16, 17, 18, 19]
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["agent/tests/"]
tags:
  - task
  - deployment
  - training
---

# Task 21: Run full test suite & fix failures

## Assigned Agent: `test-runner`

## Objective
Run all agent tests after the fix tasks and ensure everything passes. Fix any test failures caused by the changes in Tasks 15-19.

## Steps
1. Run agent tests: `cd agent && pytest tests/ -v --tb=short`
2. Run platform tests: `pytest tests/unit/ -v --tb=short`
3. Run gym tests: `cd tradeready-gym && pytest tests/ -v --tb=short`
4. Fix any failures caused by Tasks 15-19 changes
5. Verify total test count matches expectations (~900+ agent tests)

## Acceptance Criteria
- [ ] All agent tests pass (0 failures)
- [ ] All platform unit tests pass
- [ ] All gym tests pass
- [ ] No import errors from ML dependencies
- [ ] Test count documented

## Dependencies
- Tasks 15-19: all fix tasks complete

## Agent Instructions
The most likely failures are in `test_battle_runner.py` (from Task 15 asyncio.gather changes), `test_rl_deploy.py` (from Task 16 async wrapping), and `test_regime_switcher.py` (from Task 17 deque changes). Update mocks as needed.

## Estimated Complexity
Medium — may need to fix tests that mock the old sequential patterns.
