---
task_id: 11
title: "Write tests for Strategy Comparison API"
type: task
agent: "test-runner"
phase: 2
depends_on: [10]
status: "done"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tests/unit/test_strategy_comparison.py"
tags:
  - task
  - testing
  - strategies
  - phase-2
---

# Task 11: Write tests for Strategy Comparison API

## Assigned Agent: `test-runner`

## Objective
Write unit tests for the strategy comparison endpoint and service method.

## Context
Task 10 implements the comparison API. This task validates correctness.

## Files to Modify/Create
- `tests/unit/test_strategy_comparison.py` — Unit tests for service + endpoint

## Acceptance Criteria
- [x] Tests cover: ranking by sharpe_ratio, ranking by other metrics, 2 strategies, 10 strategies, invalid strategy ID returns 404, < 2 strategies returns 422, DSR included when available, DSR omitted when not available
- [x] Tests validate recommendation text format
- [x] All tests pass

## Dependencies
- **Task 10** must complete first

## Agent Instructions
1. Read `tests/CLAUDE.md` for conventions
2. Mock strategy repository to return known test results with predictable metrics
3. Verify ranking order is correct for multiple metrics

## Estimated Complexity
Low — standard unit test writing with mocked data.
