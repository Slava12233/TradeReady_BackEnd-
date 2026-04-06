---
task_id: 3
title: "Fix BT-02 + BT-17: stop-loss trigger + stop_price field"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/backtesting/sandbox.py"
  - "src/api/routes/backtest.py"
tags:
  - task
  - backtesting
  - p0
---

# Task 03: Fix BT-02 + BT-17 — Stop-Loss Orders Never Trigger; stop_price Not Persisted

## Assigned Agent: `backend-developer`

## Objective
Fix two related bugs:
1. **BT-02:** Stop-loss orders never trigger during backtest stepping (limit buys DO work)
2. **BT-17:** `stop_price` shows as `null` in order list after placement/fill

## Context
The `SandboxOrder` dataclass has only a `price` field — no `stop_price`. When `_execute_market_order()` creates the filled order copy, it sets `price=None`, wiping the trigger price. The order list serialization also omits any `stop_price` field.

## Files to Modify

### `src/backtesting/sandbox.py`:
1. **`SandboxOrder` dataclass** (~line 54): Add `stop_price: Decimal | None = None` field
2. **`place_order()`** (~line 244): For `stop_loss` and `take_profit` order types, set `stop_price=price` on the `SandboxOrder`
3. **`check_pending_orders()`** (~line 312): Verify trigger comparison uses the correct price field (`stop_price or price`)
4. **`_execute_market_order()`** (~line 644): When creating the filled order copy, preserve `stop_price` from the original order. Set `price` to the actual execution price (`ref_price`), not `None`

### `src/api/routes/backtest.py`:
5. **Order list serialization** (~lines 257-272): Add `"stop_price": str(o.stop_price) if o.stop_price else None` to the order dict

## Acceptance Criteria
- [ ] `SandboxOrder` has a `stop_price` field
- [ ] Stop-loss sell triggers when price drops below stop_price
- [ ] Stop-loss buy triggers when price rises above stop_price
- [ ] Take-profit orders also use `stop_price` correctly
- [ ] Filled orders preserve `stop_price` and set `price` to actual fill price
- [ ] Order list endpoint returns `stop_price` field
- [ ] Existing limit order tests still pass
- [ ] Existing market order tests still pass

## Dependencies
None — independent of BT-01 fix.

## Agent Instructions
Read `src/backtesting/CLAUDE.md` first. The `SandboxOrder` is a frozen dataclass — you'll need to either make it non-frozen or use `dataclasses.replace()` when creating the filled copy. Check how `check_pending_orders()` handles the trigger for limit orders (which DO work) and ensure stop-loss follows the same pattern.

Key test: stop-loss sell 0.02 BTC @ $85,000 → BTC drops to $84,349 in Feb 2025 → must trigger.

## Estimated Complexity
Medium — requires changes to a frozen dataclass and multiple methods that construct `SandboxOrder` instances.
