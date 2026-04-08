---
task_id: 6
title: "Fix headless gym env DB connection management for SB3 training"
type: task
agent: "ml-engineer"
phase: 2
depends_on: []
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files:
  - "tradeready-gym/tradeready_gym/envs/headless_env.py"
tags:
  - task
  - ml
  - gymnasium
  - database
  - connection-pool
---

# Task 06: Fix Headless Gym Env DB Connection Management

## Assigned Agent: `ml-engineer`

## Objective
Fix the `HeadlessTradingEnv` so it works with SB3 PPO training without connection pool exhaustion or event loop errors.

## Issues Found During Training Smoke Test

1. **Connection pool exhaustion** — `QueuePool limit of size 2 overflow 0 reached, timeout 30s`. The env creates sessions in `reset()`, `step()`, and `_advance_step()` but connections are not returned to the pool fast enough. The pool_size=2 is too small, and sessions may be leaked.

2. **Event loop closed** — SB3's `Monitor` wrapper calls `close()` then `reset()` between episodes. The original `close()` closed the event loop, making subsequent `reset()` crash. PARTIALLY FIXED (event loop no longer closed in `close()`).

3. **Synthetic Account/Agent** — The engine validates `agent_id` exists in the agents table. FIXED (now creates synthetic rows).

## Root Cause Analysis

The headless env creates a **new session** for every async operation (create_session, start, step, refresh_candles) via `async with self._session_factory() as db:`. With pool_size=2 and the engine potentially holding sessions open internally (the `BacktestEngine._active` dict keeps references), the pool fills up.

## Proposed Fix

1. **Increase pool size** — `create_async_engine(pool_size=5, max_overflow=5)` instead of default 2/0
2. **Use a single long-lived session per episode** — Instead of `async with` per call, create one session in `reset()` and close it in `close()`. Pass it to all engine calls.
3. **Or**: Have the engine return control of the session — currently `BacktestEngine.step()` opens its own session internally
4. **Ensure `db.commit()` releases connections** — Add explicit `await db.close()` after commits in `reset()`

## Files to Modify
- `tradeready-gym/tradeready_gym/envs/headless_env.py` — Fix connection management

## Verification
- `python scripts/train_ppo_btc.py --timesteps 2048 --eval-episodes 1 --skip-dsr` completes without errors inside Docker
- No `QueuePool limit reached` errors
- No `Event loop is closed` errors
- Model saved to `models/ppo_btc_v1.zip`
