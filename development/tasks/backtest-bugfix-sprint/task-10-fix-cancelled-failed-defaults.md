---
task_id: 10
title: "Fix cancelled/failed session defaults"
type: task
agent: "backend-developer"
phase: 4
depends_on: []
status: "completed"
priority: "low"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/api/routes/backtest.py"
tags:
  - task
  - backtesting
  - p3
---

# Task 10: Fix BT-13 + BT-14 — Cancelled/Failed Session Metric Defaults

## Assigned Agent: `backend-developer`

## Objective
Fix misleading defaults for incomplete sessions:
1. **BT-13:** Cancelled sessions show `max_drawdown: 100%` and `sharpe: 0` in comparisons
2. **BT-14:** Failed sessions show `final_equity: 0` instead of `starting_balance`

## Files to Modify

### `src/api/routes/backtest.py`:

**BT-13 — `compare_backtests()` (~lines 780-781):**
Use `None` for metrics of non-completed sessions instead of misleading defaults:
```python
if s.metrics and s.status == "completed":
    sharpe = Decimal(s.metrics.get("sharpe_ratio", "0"))
    dd = Decimal(s.metrics.get("max_drawdown_pct", "0"))
else:
    sharpe = None
    dd = None
```
Exclude non-completed sessions from best-of rankings.

**BT-14 — `get_backtest_results()` (~line 612):**
Fallback to `starting_balance` instead of `"0"`:
```python
"final_equity": str(session.final_equity or session.starting_balance)
```

**BT-14 — Orphan detection UPDATE (~lines 529, 718):**
Set `final_equity` when marking as failed:
```python
.values(status="failed", completed_at=now, final_equity=BacktestSessionModel.starting_balance)
```

## Acceptance Criteria
- [ ] Cancelled session in compare shows `null` metrics, not 100%/0
- [ ] Failed session results show `final_equity` = `starting_balance`
- [ ] Completed sessions unaffected
- [ ] Compare ranking excludes non-completed sessions

## Dependencies
None.

## Estimated Complexity
Low — default value changes in serialization logic.
