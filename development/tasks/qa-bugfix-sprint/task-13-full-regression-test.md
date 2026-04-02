---
task_id: 13
title: "Full regression test & E2E validation"
type: task
agent: "e2e-tester"
phase: 3
depends_on: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: []
tags:
  - task
  - testing
  - e2e
  - regression
---

# Task 13: Full regression test & E2E validation

## Assigned Agent: `e2e-tester`

## Objective
After all 12 bug fixes are deployed, re-run the complete QA test suite (all 53 tests from `development/test-results/test1.md`) and verify every bug is fixed.

## Context
The original QA sweep found 17 bugs across 9 domains. After all fixes are applied, we need to verify:
1. All 17 bugs are resolved
2. No new regressions were introduced
3. The platform passes a full end-to-end flow

## Files to Modify/Create
- `development/test-results/test2.md` — new test results file
- `development/reports/tester-report-2.md` — updated QA report

## Acceptance Criteria
- [ ] All 53 original tests re-run
- [ ] All 17 bugs verified fixed (PASS where previously FAIL)
- [ ] No new failures introduced
- [ ] Full E2E flow works: register → create agent → buy → sell → check portfolio → reset → battle → strategy
- [ ] Test results documented in `development/test-results/test2.md`
- [ ] Updated report in `development/reports/tester-report-2.md`

## Dependencies
ALL tasks 01-12 must be completed first.

## Agent Instructions
1. Read `development/test-results/test1.md` for the original test matrix
2. Run the same test sequence against the production API
3. For each of the 17 bugs, test the specific reproduction steps from `development/reports/tester-report-1.md`
4. Document results in the same format as `test1.md`
5. If any bugs are NOT fixed, create a follow-up bug report with details
6. Test the full happy-path E2E flow:
   - Register new account
   - Check balance (should be non-zero — BUG-001)
   - Create additional agents
   - Place market trades
   - Check win rate (should be correct — BUG-011)
   - Create a strategy (should work — BUG-005)
   - Create a battle (should work — BUG-003)
   - Create a backtest with historical data (should work — BUG-006)
   - Reset account (should work — BUG-002)
   - Delete an agent (should work — BUG-004)

## Estimated Complexity
Medium — executing the tests is mechanical, but documenting and verifying all 17 bugs takes time.
