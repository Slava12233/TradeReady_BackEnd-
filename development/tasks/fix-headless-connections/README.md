---
type: task-board
tags:
  - headless-env
  - connection-pool
  - rl-training
  - gymnasium
date: 2026-04-08
status: in-progress
---

# Task Board: Fix HeadlessTradingEnv DB Connections

**Plan source:** `development/plans/fix-headless-env-connections.md`
**Generated:** 2026-04-08
**Total tasks:** 3
**Agents involved:** ml-engineer (2), test-runner (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 1 | Implement connection fix (7 changes) | ml-engineer | 1 | — | pending |
| 2 | Update + add tests | test-runner | 1 | Task 1 | pending |
| 3 | Smoke test PPO training in Docker | ml-engineer | 2 | Tasks 1, 2 | pending |

## Execution Order

### Phase 1: Fix + Test
1 -> 2 (sequential — tests depend on the fix)

### Phase 2: Validation
3 (after Phase 1 — runs real training)

## Root Cause Summary

`DataReplayer` captures the DB session from `engine.start()`, but the headless env closes it via `async with` scope. Fix: keep ONE session open per episode (`self._episode_session`).

## New Agents Created
None.
