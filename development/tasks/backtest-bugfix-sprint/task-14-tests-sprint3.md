---
task_id: 14
title: "Write unit tests: Sprint 3 fixes (BT-07, BT-08, BT-09, BT-10, BT-11, BT-12)"
type: task
agent: "test-runner"
phase: 3
depends_on: [7, 8, 9]
status: "completed"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "tests/unit/test_schemas/test_backtest_schema.py"
  - "tests/unit/test_backtesting/test_routes.py"
tags:
  - task
  - backtesting
  - testing
---

# Task 14: Write Unit Tests — Sprint 3 (BT-07 to BT-12)

## Assigned Agent: `test-runner`

## Objective
Write tests for P2 fixes:
1. **BT-07:** Invalid symbol format rejected
2. **BT-08:** Compare detects missing sessions
3. **BT-09:** Compare requires 2+ sessions
4. **BT-10:** Invalid metrics rejected
5. **BT-11:** Best by sharpe returns actual value
6. **BT-12:** Excessive balance rejected

## Tests to Write

### Schema tests:
- `test_reject_invalid_symbol_format` — `FAKECOIN` (no USDT) → error
- `test_reject_lowercase_symbol` — `btcusdt` → error
- `test_valid_symbols_accepted` — `BTCUSDT`, `ETHUSDT` pass
- `test_reject_excessive_balance` — 10B → error
- `test_max_valid_balance` — 10M → accepted

### Route/endpoint tests:
- `test_compare_requires_two_sessions` — single ID → 422
- `test_compare_missing_session_error` — mix of valid + invalid → error with missing list
- `test_best_rejects_invalid_metric` — `banana` → 422 with valid metric list
- `test_best_sharpe_returns_value` — completed backtest → actual sharpe value
- `test_best_sortino_returns_value` — verify other JSONB metrics work too

## Acceptance Criteria
- [ ] All new tests pass
- [ ] Tests properly isolate schema vs route logic

## Dependencies
Tasks 07, 08, 09 must be completed first.

## Estimated Complexity
Low-Medium — mostly schema validation + simple route tests.
