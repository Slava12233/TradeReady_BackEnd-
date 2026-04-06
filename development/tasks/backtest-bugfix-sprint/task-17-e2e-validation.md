---
task_id: 17
title: "E2E validation: run full backtest A-Z"
type: task
agent: "e2e-tester"
phase: 4
depends_on: [12, 13, 14, 15]
status: "pending"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files: []
tags:
  - task
  - backtesting
  - e2e
---

# Task 17: E2E Validation — Full Backtest A-Z

## Assigned Agent: `e2e-tester`

## Objective
Run a comprehensive live E2E test against the running platform to verify all 17 bugs are fixed. Reproduce the exact scenarios from `development/reports/tester-report-backtesting.md`.

## Test Scenarios

### P0 Verifications:
1. Create backtest #1 → complete it → create backtest #2 → complete it → create backtest #3 (BT-01)
2. Place stop-loss sell @ $85K → step through Feb 2025 → verify trigger (BT-02)
3. Verify stop_price appears in order list (BT-17)

### P1 Verifications:
4. `end_time < start_time` → expect 422 (BT-03)
5. Complete a 2-pair backtest → verify `by_pair` populated (BT-04)
6. `agent_id="00000000-..."` → expect 404 (BT-05)
7. `candle_interval=999` → expect 422 (BT-06)

### P2 Verifications:
8. `pairs=["FAKECOINUSDT"]` → expect 422 (BT-07)
9. Compare with non-existent ID → expect error (BT-08)
10. Compare with single ID → expect 422 (BT-09)
11. `best?metric=fake` → expect 422 (BT-10)
12. `best?metric=sharpe_ratio` → expect actual value (BT-11)
13. `starting_balance=1000000000` → expect 422 (BT-12)

### P3 Verifications:
14. Compare including cancelled session → metrics null (BT-13)
15. Failed session results → final_equity = starting_balance (BT-14)
16. Step completed backtest → "already completed" message (BT-15)

## Acceptance Criteria
- [ ] All 16 scenarios pass
- [ ] No 500 errors
- [ ] Return user credentials for UI verification

## Dependencies
All test-writing tasks must be completed (unit tests pass first).

## Estimated Complexity
High — full platform E2E covering all 17 bugs.
