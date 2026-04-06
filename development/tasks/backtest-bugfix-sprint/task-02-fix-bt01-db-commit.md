---
task_id: 2
title: "Fix BT-01: db.commit() in engine + orphan detection"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/backtesting/engine.py"
  - "src/api/routes/backtest.py"
tags:
  - task
  - backtesting
  - p0
---

# Task 02: Fix BT-01 — Backtest System Breaks After Initial Use

## Assigned Agent: `backend-developer`

## Objective
Fix the root cause that prevents creating new backtests after the first one completes. Apply the fix identified by Task 01's research.

## Context
The primary hypothesis: `_persist_results()` in `engine.py` calls `await db.commit()` directly, violating the "repositories flush, routes commit" pattern. This may poison the SQLAlchemy async session state. Orphan detection blocks in `backtest.py` also call `db.commit()` mid-request.

## Files to Modify
- `src/backtesting/engine.py` — `_persist_results()`: Replace `await db.commit()` with `await db.flush()`
- `src/backtesting/engine.py` — `complete()` and `cancel()`: Ensure they use `flush()` not `commit()`
- `src/api/routes/backtest.py` — Orphan detection blocks: Replace `await db.commit()` with `await db.flush()` or move commit to route handler boundary
- `src/api/routes/backtest.py` — Ensure route handlers that mutate state call `await db.commit()` at the END of the handler (after all engine operations complete)

## Acceptance Criteria
- [ ] No `db.commit()` calls inside `src/backtesting/engine.py` — all replaced with `db.flush()`
- [ ] Route handlers in `backtest.py` own the commit boundary
- [ ] Orphan detection uses `flush()` or deferred commit
- [ ] Existing tests still pass (run `pytest tests/unit/test_backtesting/`)
- [ ] Can create 3+ sequential backtests without failure (manual or E2E test)

## Dependencies
Task 01 must confirm the root cause first. If research reveals a different mechanism, adjust the fix accordingly.

## Agent Instructions
Read `src/backtesting/CLAUDE.md` first. Follow the project pattern: "repositories flush, routes commit." The engine is NOT a route — it should never own the transaction boundary. Search for ALL `db.commit()` in `src/backtesting/` and `src/api/routes/backtest.py` to ensure none are missed.

Be careful with the `cancel()` path — it needs to flush partial results, not commit, so the route handler can still roll back if something fails after cancel.

## Estimated Complexity
Medium — straightforward pattern change, but must verify no side effects across all backtest lifecycle paths.
