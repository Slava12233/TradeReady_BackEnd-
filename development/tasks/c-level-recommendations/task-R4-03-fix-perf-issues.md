---
task_id: R4-03
title: "Fix 5 MEDIUM perf issues"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/strategies/regime/switcher.py", "agent/strategies/ensemble/run.py", "agent/strategies/evolutionary/evolve.py"]
tags:
  - task
  - performance
  - optimization
---

# Task R4-03: Fix 5 MEDIUM Performance Issues

## Assigned Agent: `backend-developer`

## Objective
Address the 5 MEDIUM performance findings from perf-checker memory (2026-03-20 audit).

## Context
These were identified during the agent strategies perf audit. 8 HIGH issues were already fixed; 5 MEDIUM remain.

## Files to Modify/Create
1. `agent/strategies/regime/switcher.py:194` — cache indicator recomputation on last candle timestamp
2. `agent/strategies/ensemble/run.py:1172` — replace sequential candle fetch with `asyncio.gather`
3. `agent/strategies/ensemble/run.py:384` — replace `_step_history` list with `deque(maxlen=500)`
4. `agent/strategies/regime/switcher.py:153` — replace `regime_history` list with `deque(maxlen=500)`
5. `agent/strategies/evolutionary/evolve.py:231` — fix mutable function attribute (cross-run state contamination)

## Acceptance Criteria
- [x] Indicator cache prevents redundant recomputation (check last candle timestamp) — was already implemented
- [x] Sequential candle fetches replaced with `asyncio.gather` + `Semaphore(5)` — was already implemented
- [x] Both `_step_history` and `regime_history` use `deque(maxlen=500)` — were already implemented
- [x] Mutable function attribute replaced with instance variable or local state — `_champion_strategy_id` global removed; now threaded as local `_run_champion_strategy_id` in `run_evolution`
- [x] All existing tests pass

## Dependencies
None — pure code optimization

## Agent Instructions
1. Read `.claude/agent-memory/perf-checker/MEMORY.md` for details on each finding
2. Use `asyncio.gather` with `Semaphore(5)` pattern for API calls
3. `from collections import deque` for bounded lists
4. For mutable function attr: move to `__init__` or use local variable

## Estimated Complexity
Medium — 5 independent fixes across 3 files
