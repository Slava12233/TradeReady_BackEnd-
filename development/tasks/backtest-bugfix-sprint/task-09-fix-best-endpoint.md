---
task_id: 9
title: "Fix best endpoint: metric whitelist + JSONB lookup"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/api/routes/backtest.py"
  - "src/database/repositories/backtest_repo.py"
tags:
  - task
  - backtesting
  - p2
---

# Task 09: Fix BT-10 + BT-11 — Best Endpoint Metric Validation + JSONB Lookup

## Assigned Agent: `backend-developer`

## Objective
Fix two related bugs in the "best backtest" endpoint:
1. **BT-10:** Invalid metrics (e.g., `fake_metric`) silently fall back to `roi_pct`
2. **BT-11:** `sharpe_ratio` returns "N/A" despite valid data — it's stored in JSONB `metrics`, not as a direct column

## Files to Modify

### `src/api/routes/backtest.py` — `get_best_backtest()`:

**Add metric whitelist:**
```python
VALID_METRICS = {"roi_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                 "win_rate", "profit_factor", "total_trades", "total_pnl"}
JSONB_METRICS = {"sharpe_ratio", "sortino_ratio", "max_drawdown_pct", "win_rate", "profit_factor"}

if metric not in VALID_METRICS:
    raise InputValidationError(field="metric", details={"valid": sorted(VALID_METRICS)})
```

**Fix value extraction:**
```python
if metric in JSONB_METRICS:
    value = str(session.metrics.get(metric, "N/A")) if session.metrics else "N/A"
else:
    value = str(getattr(session, metric, "N/A"))
```

### `src/database/repositories/backtest_repo.py` — `get_best_session()`:

**Fix JSONB sorting:**
```python
from sqlalchemy import func, cast, Numeric

if metric in JSONB_METRICS:
    sort_expr = cast(BacktestSession.metrics[metric].astext, Numeric)
else:
    sort_expr = getattr(BacktestSession, metric, BacktestSession.roi_pct)

stmt = stmt.order_by(sort_expr.desc().nullslast()).limit(1)
```

## Acceptance Criteria
- [ ] `metric=fake_metric` → 422 listing valid metrics
- [ ] `metric=sharpe_ratio` → returns actual sharpe value (e.g., "0.9400")
- [ ] `metric=roi_pct` → still works (direct column)
- [ ] `metric=sortino_ratio` → returns actual value from JSONB
- [ ] Sessions with no metrics (failed/cancelled) don't crash the sort

## Dependencies
None.

## Agent Instructions
The tricky part is the JSONB sort in the repository. SQLAlchemy's `BacktestSession.metrics["sharpe_ratio"].astext` extracts the JSON value as text, then `cast(..., Numeric)` makes it sortable. Test with `nullslast()` to handle sessions where `metrics` is NULL.

Check if the `JSONB_METRICS` set matches what `BacktestMetrics.to_dict()` actually stores — read `src/backtesting/results.py` to confirm field names.

## Estimated Complexity
Medium — JSONB column sorting in SQLAlchemy requires careful SQL expression construction.
