---
task_id: 07
title: "Fix win rate calculation (BUG-011)"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
priority: "medium"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/portfolio/tracker.py", "src/accounts/balance_manager.py", "src/metrics/"]
tags:
  - task
  - analytics
  - metrics
  - P2
---

# Task 07: Fix win rate calculation (BUG-011)

## Assigned Agent: `backend-developer`

## Objective
Fix the win rate calculation which reports 0% win rate and classifies profitable trades as losses. After executing 2 sell trades (both at profit), the analytics endpoint shows `win_rate: 0.0` and `winning_trades: 0`.

## Context
The QA report shows: sold ETH and DOGE at prices above entry, but `winning_trades: 0`, `losing_trades: 2`, `best_trade: -$0.04855`. The PnL is negative which means fees are being subtracted but the entry cost basis may be wrong, OR `realized_pnl` on the `Trade` model is NULL causing misclassification.

## Files to Modify/Create
- `src/portfolio/tracker.py` — find `PerformanceMetrics.calculate()` or equivalent win rate logic
- `src/accounts/balance_manager.py` — check how `realized_pnl` is computed during trade execution
- `src/metrics/` — if the unified metrics calculator is used for analytics

## Acceptance Criteria
- [ ] Trades with positive net PnL (after fees) are classified as wins
- [ ] Trades with negative net PnL are classified as losses
- [ ] `win_rate = winning_trades / total_closed_trades`
- [ ] `realized_pnl` on Trade records is correctly computed as `(exit_price - entry_price) * quantity - fees`
- [ ] Trades with NULL `realized_pnl` are excluded from win/loss stats (not counted as losses)
- [ ] Regression test: buy at X, sell at X+delta, verify `win_rate > 0`

## Dependencies
None — independent investigation.

## Agent Instructions
1. Read `src/portfolio/CLAUDE.md` and `src/metrics/CLAUDE.md`
2. **Step 1 — Find the win rate calculation:**
   - Search for `win_rate` in `src/portfolio/tracker.py` and `src/metrics/`
   - Find the `calculate()` or equivalent method
   - Understand how it classifies trades as wins/losses
3. **Step 2 — Check realized_pnl population:**
   - Search for `realized_pnl` in `src/accounts/balance_manager.py`
   - Verify it's set when a sell trade is executed
   - Check if fees are included in the calculation
4. **Step 3 — Check the data flow:**
   - `GET /analytics/performance` → calls what service? → uses what trade data?
   - Is it using `Trade.realized_pnl` or computing PnL from price difference?
5. Common issues:
   - `realized_pnl` may be NULL if the balance manager doesn't set it
   - PnL may use `filled_price - price` instead of `filled_price - avg_entry_price`
   - Fees may be double-counted
6. Fix the root cause and add regression tests

## Estimated Complexity
Medium — requires tracing the data flow through multiple files to find where PnL goes wrong.
