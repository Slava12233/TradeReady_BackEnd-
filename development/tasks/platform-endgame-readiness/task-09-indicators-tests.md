---
task_id: 9
title: "Write tests for Indicators API (unit + integration)"
type: task
agent: "test-runner"
phase: 1
depends_on: [7, 8]
status: "pending"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tests/unit/test_indicators_api.py"
  - "tests/integration/test_indicators_endpoint.py"
tags:
  - task
  - testing
  - indicators
  - phase-1
---

# Task 09: Write tests for Indicators API (unit + integration)

## Assigned Agent: `test-runner`

## Objective
Write unit and integration tests for the indicators API endpoints.

## Context
Tasks 07-08 implement the indicators API and SDK methods. This task validates correctness.

## Files to Modify/Create
- `tests/unit/test_indicators_api.py` — Unit tests for route logic, caching, validation
- `tests/integration/test_indicators_endpoint.py` — Integration tests for full endpoint

## Acceptance Criteria
- [ ] Unit tests cover: symbol validation, indicator filtering, cache hit/miss, lookback range validation
- [ ] Integration tests cover: full response shape, available indicators endpoint, invalid symbol returns 422
- [ ] All tests pass
- [ ] Tests follow project conventions

## Dependencies
- **Tasks 07 and 08** must complete first

## Agent Instructions
1. Read `tests/CLAUDE.md` for patterns
2. Mock Redis for unit tests; integration tests use real Redis if available
3. Mock candle data for unit tests (create a fixture with known candle values)

## Estimated Complexity
Medium — need to set up candle data fixtures for indicator computation.
