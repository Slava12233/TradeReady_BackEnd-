---
task_id: 5
title: "Fix BT-04: by_pair results always empty"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/backtesting/results.py"
  - "src/backtesting/engine.py"
  - "src/api/routes/backtest.py"
tags:
  - task
  - backtesting
  - p1
---

# Task 05: Fix BT-04 — `by_pair` Always Returns Empty Array

## Assigned Agent: `backend-developer`

## Objective
Per-pair breakdown in backtest results is always `[]`. The stats are computed in `_persist_results()` but never stored in the database. The results route hardcodes `by_pair=[]`.

## Files to Modify

### `src/backtesting/results.py`:
- `BacktestMetrics.to_dict()`: Include a `"by_pair"` key in the serialized output

### `src/backtesting/engine.py`:
- `_persist_results()`: Compute per-pair stats and include them in the `metrics` JSONB before persisting. The function `calculate_per_pair_stats()` already exists — just make sure its output is included in `metrics.to_dict()`

### `src/api/routes/backtest.py`:
- `get_backtest_results()`: Read `raw_metrics.get("by_pair", [])` instead of hardcoded `[]`

## Acceptance Criteria
- [ ] Running a backtest with 2+ pairs produces non-empty `by_pair` in results
- [ ] Each pair entry includes: symbol, trades, win_rate, net_pnl (at minimum)
- [ ] Old completed backtests without by_pair in metrics gracefully return `[]`
- [ ] Results for single-pair backtests also work correctly

## Dependencies
None — independent of other fixes.

## Agent Instructions
Read `src/backtesting/CLAUDE.md` first. Look at how `calculate_per_pair_stats()` works in `results.py` — it likely returns a list of dicts. The `metrics` column is JSONB, so the per-pair data serializes naturally. Make sure Decimal values are converted to strings before storing in JSONB.

## Estimated Complexity
Medium — requires understanding the metrics persistence flow across 3 files.
