---
task_id: 15
title: "Regime strategy validation backtests"
type: task
agent: "e2e-tester"
phase: C
depends_on: [14]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: []
tags:
  - task
  - ml
  - strategies
---

# Task 15: Regime strategy validation backtests

## Assigned Agent: `e2e-tester`

## Objective
Run 12 one-month backtests (one per month of available data) using the regime-adaptive strategy. Compare against static momentum and buy-and-hold benchmarks. Target: positive alpha in 8/12 months.

## Steps
1. For each of 12 months:
   a. Create backtest session via REST API
   b. For each step: run regime switcher → get active strategy → execute trades
   c. Complete backtest, fetch results
2. Create static momentum benchmark (same 12 months, fixed MACD strategy)
3. Create buy-and-hold BTC benchmark
4. Compare: regime-adaptive vs static vs buy-and-hold
5. Report: per-month ROI, Sharpe, max drawdown for all 3 strategies

## Acceptance Criteria
- [ ] 12 backtests complete without errors
- [ ] Regime-adaptive shows positive alpha in >= 8/12 months vs static
- [ ] Results saved to `agent/reports/regime-validation-{timestamp}.json`
- [ ] Comparison table: regime vs static vs buy-and-hold (ROI, Sharpe, max DD)
- [ ] Regime switch events logged per month (how often did it switch?)

## Dependencies
- Task 14: regime switcher working
- Platform running with 12+ months of historical candle data

## Agent Instructions
Use the backtest REST API (same pattern as `agent/workflows/backtest_workflow.py`). Run backtests sequentially (not in parallel) to avoid overwhelming the API. Each backtest is ~744 steps (1h candles, 1 month).

## Estimated Complexity
Medium — 12 backtests + benchmark creation + comparison.
