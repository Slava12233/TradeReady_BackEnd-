---
task_id: 12
title: "Improve position limit error message (BUG-016)"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "pending"
priority: "low"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/risk/manager.py"]
tags:
  - task
  - risk
  - ux
  - P3
---

# Task 12: Improve position limit error message (BUG-016)

## Assigned Agent: `backend-developer`

## Objective
Improve the `position_limit_exceeded` error message to include the calculation details so users understand WHY their order was rejected.

## Context
The position limit check works correctly (rejects orders that would make a single position exceed 25% of equity). But the error message just says `ORDER_REJECTED: position_limit_exceeded` with no explanation of current position size, requested addition, or the limit. Users can't tell if it's a bug or expected behavior.

## Files to Modify/Create
- `src/risk/manager.py` — improve error message in `_check_position_limit()` (lines ~780-803)

## Acceptance Criteria
- [ ] Error message includes: symbol, current position %, requested addition %, limit %, equity amount
- [ ] Example: `"position_limit_exceeded: BTCUSDT position would be 32.5% of equity (limit: 25%). Current: $2,000, Requested: $1,250, Equity: $10,000"`
- [ ] Existing position limit logic unchanged (no behavioral change)
- [ ] Unit test verifies the error message format

## Dependencies
None.

## Agent Instructions
1. Read `src/risk/CLAUDE.md`
2. Read `src/risk/manager.py` — find `_check_position_limit()` around line 780
3. The `OrderRejectedError` raise should include:
   - `symbol`
   - `new_position_pct` (computed in the method)
   - `max_position_pct` (the limit)
   - `existing_value` (current position USDT value)
   - `order_value` (requested order USDT value)
   - `total_equity`
4. Format as a human-readable string
5. Do NOT change the rejection logic — only the message

## Estimated Complexity
Low — single string format change.
