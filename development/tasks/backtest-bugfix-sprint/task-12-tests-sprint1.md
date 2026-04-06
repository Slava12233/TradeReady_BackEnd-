---
task_id: 12
title: "Write unit tests: Sprint 1 fixes (BT-01, BT-02, BT-17)"
type: task
agent: "test-runner"
phase: 1
depends_on: [2, 3]
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "tests/unit/test_backtesting/test_engine.py"
  - "tests/unit/test_backtesting/test_sandbox.py"
tags:
  - task
  - backtesting
  - testing
---

# Task 12: Write Unit Tests — Sprint 1 (BT-01, BT-02, BT-17)

## Assigned Agent: `test-runner`

## Objective
Write regression tests for the P0 fixes:
1. **BT-01:** Sequential backtest creation — verify 3+ backtests can be created and completed
2. **BT-02:** Stop-loss trigger — verify stop-loss fires when price crosses level
3. **BT-17:** stop_price persistence — verify the field is preserved through order lifecycle

## Tests to Write

### `test_engine.py`:
- `test_create_multiple_sequential_backtests` — create, step, complete 3 backtests sequentially; all succeed
- `test_engine_uses_flush_not_commit` — verify `_persist_results` calls `flush()` not `commit()`

### `test_sandbox.py`:
- `test_stop_loss_sell_triggers_on_price_drop` — place stop-loss sell @ $85K, step to $84K, verify fill
- `test_stop_loss_buy_triggers_on_price_rise` — place stop-loss buy @ $100K, step to $101K, verify fill
- `test_take_profit_triggers` — place take-profit, verify trigger
- `test_stop_price_preserved_on_fill` — place stop-loss, fill it, verify `stop_price` field is not None
- `test_filled_order_has_execution_price` — after fill, `price` = actual execution price (not None)

## Acceptance Criteria
- [ ] All new tests pass
- [ ] Existing backtest tests still pass
- [ ] Tests follow `tests/CLAUDE.md` patterns (async, proper fixtures)

## Dependencies
Tasks 02 and 03 must be completed first.

## Agent Instructions
Read `tests/CLAUDE.md` for test patterns. Read `tests/unit/test_backtesting/` to see existing test structure and fixtures. Use `pytest.mark.asyncio` for async tests. Mock the database session where needed.

## Estimated Complexity
Medium — need to set up proper sandbox state for stop-loss trigger testing.
