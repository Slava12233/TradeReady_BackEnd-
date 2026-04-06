---
task_id: 1
title: "Research: verify BT-01 root cause (backtest fails after first use)"
type: task
agent: "codebase-researcher"
phase: 1
depends_on: []
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/backtesting/engine.py"
  - "src/database/session.py"
  - "src/api/routes/backtest.py"
  - "src/dependencies.py"
tags:
  - task
  - backtesting
  - p0
---

# Task 01: Research — Verify BT-01 Root Cause

## Assigned Agent: `codebase-researcher`

## Objective
Confirm the exact failure mechanism that causes all backtest creations to fail after the first backtest completes. The hypothesis is that `db.commit()` inside `engine._persist_results()` violates the "repos flush, routes commit" pattern and poisons session state.

## Context
BUG-BT-01 is the #1 blocker — users can only run ONE backtest per agent/account lifetime. After the first backtest completes, all subsequent creates transition from "created" to "failed" within seconds, with no error details.

## Investigation Steps
1. Read `src/backtesting/engine.py` — find all `db.commit()` calls inside engine methods (especially `_persist_results()`, `complete()`, `cancel()`)
2. Read `src/api/routes/backtest.py` — find all `db.commit()` calls in route handlers and orphan detection blocks
3. Read `src/database/session.py` — understand how `get_async_session()` manages session lifecycle
4. Read `src/dependencies.py` — check if `BacktestEngine` is a singleton, how `_active` dict persists
5. Trace the full lifecycle: `create_backtest()` route → `engine.create_session()` → `engine.step()` → auto-complete → `engine.complete()` → `_persist_results()` → session state after commit
6. Determine: does `db.commit()` inside the engine actually poison the session for the NEXT request? Or is it a different mechanism (singleton state, Redis lock, orphan detection re-marking)?

## Acceptance Criteria
- [ ] Identified the exact line(s) causing the failure
- [ ] Confirmed whether it's a session state issue, singleton state issue, or both
- [ ] Documented the fix approach with specific code changes needed
- [ ] Checked if there are any Redis locks or other shared state involved

## Dependencies
None — this is the first task.

## Agent Instructions
Focus on `src/backtesting/engine.py` and `src/api/routes/backtest.py`. The key question: what happens to the DB session AFTER `_persist_results()` calls `await db.commit()`? Does the next request get a fresh session from `get_async_session()`, or does something leak?

Also check if the `BacktestEngine._active` dict cleanup in `complete()` might cause issues when the orphan detection in route handlers runs.

## Estimated Complexity
Medium — requires tracing async session lifecycle across multiple files.
