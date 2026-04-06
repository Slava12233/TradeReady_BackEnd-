---
task_id: 13
title: "Write unit tests: Sprint 2 fixes (BT-03, BT-04, BT-05, BT-06)"
type: task
agent: "test-runner"
phase: 2
depends_on: [4, 5, 6]
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "tests/unit/test_schemas/test_backtest_schema.py"
  - "tests/unit/test_backtesting/test_engine.py"
  - "tests/unit/test_backtesting/test_results.py"
tags:
  - task
  - backtesting
  - testing
---

# Task 13: Write Unit Tests — Sprint 2 (BT-03, BT-04, BT-05, BT-06)

## Assigned Agent: `test-runner`

## Objective
Write tests for P1 fixes:
1. **BT-03:** Date range validation rejects end < start
2. **BT-04:** `by_pair` populated in results
3. **BT-05:** Fake agent_id returns proper error
4. **BT-06:** Invalid candle intervals rejected

## Tests to Write

### Schema tests:
- `test_reject_end_before_start` — `end_time < start_time` → ValidationError
- `test_reject_equal_dates` — `end_time == start_time` → ValidationError
- `test_valid_date_range_accepted` — normal range passes
- `test_reject_invalid_candle_interval` — 999 → ValidationError
- `test_valid_candle_intervals` — 60, 300, 3600, 86400 all pass

### Engine tests:
- `test_create_with_fake_agent_id` — non-existent UUID → domain error (not IntegrityError)
- `test_results_by_pair_populated` — run backtest with 2 pairs, verify per-pair stats in results

## Acceptance Criteria
- [ ] All new tests pass
- [ ] Schema validation tests don't require DB connection
- [ ] Engine tests properly mock DB where needed

## Dependencies
Tasks 04, 05, 06 must be completed first.

## Estimated Complexity
Low-Medium — schema tests are simple; engine tests need proper mocking.
