---
task_id: 1
title: "Implement headless env connection fix (all 4 phases)"
type: task
agent: "ml-engineer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[fix-headless-connections/README]]"
files:
  - "tradeready-gym/tradeready_gym/envs/headless_env.py"
tags:
  - task
  - gymnasium
  - database
  - connection-pool
---

# Task 01: Implement Headless Env Connection Fix

## Assigned Agent: `ml-engineer`

## Objective
Fix the HeadlessTradingEnv so SB3 PPO training works without connection pool exhaustion. All changes in ONE file: `tradeready-gym/tradeready_gym/envs/headless_env.py`.

## Context
The plan at `development/plans/fix-headless-env-connections.md` has the FULL implementation with exact code. The root cause: `DataReplayer` captures the DB session passed to `engine.start()`, but the headless env closes that session immediately via `async with` scope. This leaves the replayer with a dead session, causing pool exhaustion.

## Files to Modify
- `tradeready-gym/tradeready_gym/envs/headless_env.py` — 7 changes total

## Implementation (from the plan)

### Change 1: Add `self._episode_session` attribute
After `self._is_done: bool = False` (line ~175), add:
```python
self._episode_session: Any | None = None
```

### Change 2: Increase pool config
Replace `pool_size=2, max_overflow=0` with:
```python
pool_size=5,
max_overflow=3,
pool_pre_ping=True,
pool_recycle=3600,
```

### Change 3: Add `_cleanup_episode()` method
New async method (after `_ensure_engine()`):
- If `self._session_id` is active in engine: `await self._backtest_engine.cancel(session_id, self._episode_session)` + commit
- Close `self._episode_session` (returns connection to pool)
- Set `self._episode_session = None` and `self._session_id = None`

### Change 4: Rewrite `_async_reset()` 
- Call `_cleanup_episode()` first
- Create ONE `self._episode_session = self._session_factory()` (without `async with`)
- Use this session for ALL calls: Account/Agent creation, `create_session()`, `start()`
- The DataReplayer inside `engine.start()` captures this session and can query through it for the entire episode

### Change 5: Rewrite `_advance_step()`
- Remove `async with self._session_factory() as db:` wrapper
- Use `self._episode_session` directly for `engine.step()` + commit

### Change 6: Rewrite `close()`
- Call `_cleanup_episode()` first (via `self._loop.run_until_complete()`)
- Then dispose engine pool
- Keep event loop alive (closed in `__del__`)

### Change 7: Harden `__del__`
- Close episode_session and dispose engine before closing loop
- All wrapped in try/except (best-effort GC cleanup)

## Acceptance Criteria
- [ ] `_episode_session` attribute exists
- [ ] Pool config: pool_size=5, max_overflow=3, pool_recycle=3600
- [ ] `_cleanup_episode()` method cancels active sessions and closes episode session
- [ ] `_async_reset()` uses single long-lived session for entire episode
- [ ] `_advance_step()` uses `self._episode_session` directly (no `async with`)
- [ ] `close()` calls `_cleanup_episode()` before disposing pool
- [ ] `__del__` handles lingering sessions
- [ ] `ruff check` and `ruff format` pass
- [ ] Existing headless env patterns preserved (per-instance event loop, lazy imports)

## Agent Instructions
1. Read the FULL plan at `development/plans/fix-headless-env-connections.md` — it has exact code for every change
2. Read the current `tradeready-gym/tradeready_gym/envs/headless_env.py`
3. Apply all 7 changes from the plan
4. Run `ruff check` and `ruff format`
5. The key insight: `self._episode_session` stays open so `DataReplayer.load_candles()` has a live connection

## Estimated Complexity
Medium — 7 targeted changes to one file, all specified in the plan.
