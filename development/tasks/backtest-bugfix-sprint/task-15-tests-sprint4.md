---
task_id: 15
title: "Write unit tests: Sprint 4 fixes (BT-13, BT-14, BT-15, BT-16)"
type: task
agent: "test-runner"
phase: 4
depends_on: [10, 11]
status: "completed"
priority: "low"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "tests/unit/test_backtesting/test_routes.py"
tags:
  - task
  - backtesting
  - testing
---

# Task 15: Write Unit Tests — Sprint 4 (BT-13 to BT-16)

## Assigned Agent: `test-runner`

## Objective
Write tests for P3 fixes:
1. **BT-13:** Cancelled sessions show null metrics (not 100%/0)
2. **BT-14:** Failed sessions show starting_balance as final_equity
3. **BT-15:** Stepping completed backtest says "already completed"
4. **BT-16:** agent_id fallback behavior documented

## Tests to Write
- `test_cancelled_session_metrics_null_in_compare` — cancelled session metrics are null, not misleading
- `test_failed_session_equity_equals_starting_balance` — final_equity = starting_balance
- `test_step_completed_backtest_error_message` — error says "already completed"
- `test_step_failed_backtest_error_message` — error says "was failed"
- `test_step_cancelled_backtest_error_message` — error says "was cancelled"

## Acceptance Criteria
- [ ] All new tests pass
- [ ] Error message assertions are exact string matches

## Dependencies
Tasks 10 and 11 must be completed first.

## Estimated Complexity
Low — straightforward assertion tests.
