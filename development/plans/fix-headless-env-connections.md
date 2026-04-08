---
type: plan
title: "Fix HeadlessTradingEnv DB Connection Management for SB3 PPO Training"
status: pending
priority: high
created: 2026-04-07
tags:
  - plan
  - database
  - connection-pool
  - gymnasium
  - rl-training
  - headless-env
---

# Fix HeadlessTradingEnv DB Connection Management for SB3 PPO Training

## Overview

The `HeadlessTradingEnv` suffers from connection pool exhaustion (`QueuePool limit of size 2 overflow 0 reached`) during SB3 PPO training. Root cause: the `DataReplayer` inside `BacktestEngine` captures a reference to the DB session passed to `start()`, but the headless env wraps that session in a short-lived `async with` scope that closes it immediately after `start()` returns. This leaves the replayer holding a stale/closed session, and `load_candles()` called every step tries to use it, causing cascading connection issues. Additionally, the pool is undersized (2 connections, 0 overflow) for the multi-session-per-episode pattern.

## CLAUDE.md Files Consulted

- Root `CLAUDE.md` -- architecture overview, dependency direction, DB rules
- `src/backtesting/CLAUDE.md` -- engine session lifecycle, DataReplayer session persistence, _active dict
- `tradeready-gym/CLAUDE.md` -- headless env gotchas, per-instance event loop pattern

## Root Cause Analysis (Detailed)

### How connections are used today

The headless env's `_async_reset()` performs 3 separate `async with self._session_factory() as db:` blocks:

1. **Block 1 (lines 323-346):** Creates synthetic Account + Agent rows, commits, session auto-closes.
2. **Block 2 (lines 358-365):** Calls `engine.create_session(db=db)`. Inside, `create_session()` creates a temporary `DataReplayer(db, ...)` just to call `get_data_range()` for validation. This replayer is discarded. The `BacktestSessionModel` is added to `db` and flushed. Session auto-closes after the block.
3. **Block 3 (lines 367-369):** Calls `engine.start(session_id, db)`. Inside `start()`:
   - Line 296: `replayer = DataReplayer(db, config.pairs, ...)` -- **captures `db` as `self._session`**
   - Line 300: `await replayer.preload_range(...)` -- uses `db` to bulk-load all price data (this works)
   - Line 311-322: Stores `replayer` inside `_ActiveSession` in `self._active[session_id]`
   - Line 328: `await db.flush()` -- updates session status
   - Block exits, **session auto-closes** via `async with`

**Problem:** After block 3 exits, the `DataReplayer` stored in `_active[session_id].replayer` still holds `self._session` = the now-closed `db` session. The underlying connection has been returned to the pool (or closed).

### Why `load_candles()` causes pool exhaustion

Every step calls `_advance_step()` which calls `_refresh_candles()` (line 398-412). `_refresh_candles()` calls `active.replayer.load_candles(...)` at line 406-412. `load_candles()` (data_replayer.py line 282) executes `await self._session.execute(query, ...)` on the **stale session**.

SQLAlchemy's behavior when you execute on a closed session: it attempts to checkout a new connection from the pool. But the session was created from a scoped `async with` block, so its state is inconsistent. The connection may not be properly returned after the query, leading to pool exhaustion.

Additionally, each `_async_step()` call opens yet another `async with self._session_factory() as db:` block for `engine.step()` (line 389-391), which needs its own connection. Combined with the stale replayer session trying to grab connections, the pool_size=2 is immediately overwhelmed.

### Why the pool size (2) is too small

Even if sessions were managed correctly, a single `step()` call requires:
- 1 connection for the `engine.step()` DB writes (progress updates every 500 steps, auto-complete on last step)
- 1 connection potentially for `load_candles()` via the replayer (if cache doesn't cover the request)

And `_async_reset()` uses up to 3 sequential sessions. With pool_size=2 and max_overflow=0, there is zero headroom for any overlap or stale references.

### The multi-episode lifecycle problem

SB3's Monitor wrapper calls: `reset() -> step() x N -> close() -> reset() -> step() x N -> ...`

The current `close()` calls `self._db_engine.dispose()` and sets `self._db_engine = None`. This means `reset()` must recreate the entire engine, session factory, and BacktestEngine from scratch. But the old BacktestEngine's `_active` dict may still hold references to the old session factory's connections. Setting `self._backtest_engine = None` in `close()` drops the reference but does not clean up the `_active` dict entries (the session auto-completes only if all steps are exhausted).

## Requirements

- SB3 PPO training runs for 2048+ timesteps across multiple episodes without `QueuePool` errors
- No `Event loop is closed` errors (already partially fixed)
- Clean connection pool state between episodes
- No changes to `BacktestEngine` or `DataReplayer` public API (platform code)

## Architecture Changes

All changes are in ONE file: `tradeready-gym/tradeready_gym/envs/headless_env.py`

No changes to `src/backtesting/engine.py` or `src/backtesting/data_replayer.py`. The fix is entirely in how the headless env manages session lifecycle.

## Implementation Steps

### Phase 1: Fix Pool Configuration

**Step 1.1: Increase pool_size and max_overflow** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`, line 292-298)

Replace:
```python
        self._db_engine = create_async_engine(
            self.db_url,
            # Keep pool small — each env instance has its own engine.
            pool_size=2,
            max_overflow=0,
            pool_pre_ping=True,
        )
```

With:
```python
        self._db_engine = create_async_engine(
            self.db_url,
            # Each env instance has its own engine.  We need enough
            # connections for:  1 long-lived episode session (held by
            # DataReplayer inside BacktestEngine._active) + 1 for
            # per-call operations (create_session, start, step, etc.)
            # + headroom for auto-complete / webhook overlap.
            pool_size=5,
            max_overflow=3,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
```

**Why:** pool_size=5 provides enough connections for the replayer's held session + concurrent engine operations. max_overflow=3 provides burst capacity for episode transitions. pool_recycle=3600 prevents stale connections during long training runs.

**Risk:** Low. More connections per env instance, but each env is a separate process in SubprocVecEnv.

---

### Phase 2: Fix Session Lifecycle (Critical)

The core fix: use a single long-lived session per episode that is shared across all engine calls, rather than creating a new session per call. This session stays open for the replayer to use, and is explicitly closed at episode end.

**Step 2.1: Add an `_episode_session` attribute** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`, line 169)

After line 175 (`self._is_done: bool = False`), add:
```python
        # Long-lived DB session for the current episode.  Kept open so
        # that the DataReplayer inside BacktestEngine._active can query
        # through it.  Closed explicitly in _cleanup_episode().
        self._episode_session: Any | None = None
```

**Step 2.2: Create `_cleanup_episode()` helper** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`)

Add a new method after `_ensure_engine()` (after line 304):

```python
    async def _cleanup_episode(self) -> None:
        """Clean up the previous episode's engine state and DB session.

        Must be called at the start of each reset() to release connections
        held by the previous episode's DataReplayer and BacktestEngine._active
        entry.
        """
        # Cancel the active backtest session in the engine so it releases
        # its _active dict entry (which holds the DataReplayer with its
        # session reference).
        if (
            self._session_id is not None
            and self._backtest_engine is not None
            and self._backtest_engine.is_active(self._session_id)
        ):
            try:
                # We need a live session to call cancel() since it persists
                # partial results to the DB.
                if self._episode_session is not None:
                    await self._backtest_engine.cancel(self._session_id, self._episode_session)
                    await self._episode_session.commit()
            except Exception:  # noqa: BLE001
                logger.debug("headless_env: error cancelling previous session", exc_info=True)

        # Close the episode-scoped DB session to return its connection
        # to the pool.
        if self._episode_session is not None:
            try:
                await self._episode_session.close()
            except Exception:  # noqa: BLE001
                logger.debug("headless_env: error closing episode session", exc_info=True)
            self._episode_session = None

        self._session_id = None
```

**Why:** The engine's `_active` dict entry holds the `DataReplayer` which holds the session. We must either let the backtest auto-complete (which pops from `_active`) or explicitly cancel it. After that, we close the session to return the connection.

**Risk:** Medium. If `cancel()` fails, the session reference may leak. Mitigated by the explicit `session.close()` in the `finally`-like structure.

**Step 2.3: Rewrite `_async_reset()` to use a single episode session** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`, lines 306-381)

Replace the entire `_async_reset()` method:

```python
    async def _async_reset(self) -> None:
        """Async implementation of reset() -- creates and starts a new session."""
        await self._ensure_engine()

        # Clean up previous episode (cancel engine session, close DB session)
        await self._cleanup_episode()

        # Imports deferred to match _ensure_engine() pattern
        from src.backtesting.engine import BacktestConfig  # noqa: PLC0415
        from src.database.models import Account, Agent  # noqa: PLC0415

        # Parse ISO-8601 strings to timezone-aware datetimes
        start_dt = datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))

        # Open ONE session for the entire episode.  This session will be
        # captured by the DataReplayer inside BacktestEngine.start() and
        # kept alive until _cleanup_episode() closes it at the start of
        # the next reset() or in close().
        self._episode_session = self._session_factory()

        # Create synthetic Account + Agent rows
        synthetic_account_id = uuid4()
        synthetic_agent_id = uuid4()

        account = Account(
            id=synthetic_account_id,
            display_name="headless_gym",
            email=f"headless-{synthetic_account_id.hex[:8]}@gym.local",
            password_hash="not-a-real-hash",
            api_key=f"ak_headless_{synthetic_account_id.hex[:16]}",
            api_key_hash="not-a-real-hash",
            api_secret_hash="not-a-real-hash",
            starting_balance=Decimal(str(self.starting_balance)),
        )
        self._episode_session.add(account)
        await self._episode_session.flush()

        agent = Agent(
            id=synthetic_agent_id,
            account_id=synthetic_account_id,
            display_name="headless_gym_agent",
            api_key=f"ak_agent_headless_{synthetic_agent_id.hex[:16]}",
            api_key_hash="not-a-real-hash",
            starting_balance=Decimal(str(self.starting_balance)),
        )
        self._episode_session.add(agent)
        await self._episode_session.commit()

        config = BacktestConfig(
            start_time=start_dt,
            end_time=end_dt,
            starting_balance=Decimal(str(self.starting_balance)),
            candle_interval=self._candle_interval,
            pairs=[self.symbol],
            strategy_label="headless_gym",
            agent_id=synthetic_agent_id,
        )

        session_model = await self._backtest_engine.create_session(
            account_id=synthetic_account_id,
            config=config,
            db=self._episode_session,
        )
        session_id = str(session_model.id)
        await self._episode_session.commit()

        await self._backtest_engine.start(session_id, self._episode_session)
        await self._episode_session.commit()

        self._session_id = session_id
        self._prev_equity = self.starting_balance
        self._step_count = 0
        self._episode_count += 1
        self._is_done = False
        self._last_portfolio = {}
        self._last_candles = []
        self.reward_fn.reset()

        # Take the first step to populate prices and portfolio state
        await self._advance_step()
```

**Key changes:**
1. Calls `_cleanup_episode()` first to release previous episode resources.
2. Creates `self._episode_session = self._session_factory()` (without `async with`) -- this is a long-lived session that stays open.
3. Uses `self._episode_session` for ALL calls: Account/Agent creation, `create_session()`, `start()`.
4. The `DataReplayer` created inside `engine.start()` at line 296 captures `self._episode_session` as its `self._session`. Since we keep it open, `load_candles()` will work correctly.
5. No more separate `async with` blocks that close sessions prematurely.

**Risk:** Medium. The session stays open for the entire episode. If the episode is long (thousands of steps), the transaction context must handle it. Mitigated by calling `commit()` at appropriate points (after inserts, after start) to release row locks.

**Step 2.4: Update `_advance_step()` to use the episode session** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`, lines 383-399)

Replace:
```python
    async def _advance_step(self) -> None:
        """Call engine.step() and cache the result for observation building."""
        from src.backtesting.engine import StepResult  # noqa: PLC0415

        assert self._session_id is not None  # noqa: S101

        async with self._session_factory() as db:
            step_result: StepResult = await self._backtest_engine.step(self._session_id, db)
            await db.commit()

        self._current_prices = dict(step_result.prices)
        self._is_done = step_result.is_complete
        self._last_portfolio = self._portfolio_to_dict(step_result.portfolio)

        # Fetch candles for observation (no DB hit -- served from in-memory cache)
        await self._refresh_candles()
```

With:
```python
    async def _advance_step(self) -> None:
        """Call engine.step() and cache the result for observation building."""
        from src.backtesting.engine import StepResult  # noqa: PLC0415

        assert self._session_id is not None  # noqa: S101
        assert self._episode_session is not None  # noqa: S101

        step_result: StepResult = await self._backtest_engine.step(
            self._session_id, self._episode_session
        )
        # Commit periodically to release any row-level locks from
        # engine.step()'s DB progress writes (every 500 steps) and to
        # ensure auto-complete results are persisted.
        await self._episode_session.commit()

        self._current_prices = dict(step_result.prices)
        self._is_done = step_result.is_complete
        self._last_portfolio = self._portfolio_to_dict(step_result.portfolio)

        # Fetch candles for observation -- uses the replayer's load_candles()
        # which queries through self._episode_session (the same session the
        # DataReplayer captured during start()).
        await self._refresh_candles()
```

**Key change:** No more `async with self._session_factory() as db:` wrapper. Uses `self._episode_session` directly. This is the SAME session object the DataReplayer holds, so `load_candles()` queries work on a live connection.

---

### Phase 3: Fix `close()` for Proper Cleanup

**Step 3.1: Update `close()` to clean up episode state** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`, lines 236-254)

Replace:
```python
    def close(self) -> None:
        """Release the database connection pool.

        The event loop is intentionally NOT closed here because SB3's
        ``Monitor`` wrapper may call ``reset()`` after ``close()`` during
        episode transitions.  The loop is only closed in ``__del__`` when
        the env instance is garbage-collected.
        """
        if self._db_engine is not None:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._db_engine.dispose())
            except Exception:  # noqa: BLE001
                logger.debug("headless_env.close: error disposing DB engine", exc_info=True)
            self._db_engine = None
            self._session_factory = None
            self._backtest_engine = None

        super().close()
```

With:
```python
    def close(self) -> None:
        """Release the current episode session and the database connection pool.

        The event loop is intentionally NOT closed here because SB3's
        ``Monitor`` wrapper may call ``reset()`` after ``close()`` during
        episode transitions.  The loop is only closed in ``__del__`` when
        the env instance is garbage-collected.
        """
        if self._loop.is_closed():
            super().close()
            return

        # Clean up the current episode (cancel engine session, close DB session)
        try:
            self._loop.run_until_complete(self._cleanup_episode())
        except Exception:  # noqa: BLE001
            logger.debug("headless_env.close: error in episode cleanup", exc_info=True)

        # Dispose the connection pool.  After this, reset() will recreate
        # the engine via _ensure_engine().
        if self._db_engine is not None:
            try:
                self._loop.run_until_complete(self._db_engine.dispose())
            except Exception:  # noqa: BLE001
                logger.debug("headless_env.close: error disposing DB engine", exc_info=True)
            self._db_engine = None
            self._session_factory = None
            self._backtest_engine = None

        super().close()
```

**Key change:** Calls `_cleanup_episode()` before disposing the engine pool. This ensures the active backtest session is cancelled (removed from `_active` dict) and the episode session is closed (connection returned to pool) before we dispose the pool itself.

**Risk:** Low. Adds proper cleanup ordering.

---

### Phase 4: Harden `__del__` for GC Safety

**Step 4.1: Update `__del__` to handle lingering sessions** (File: `tradeready-gym/tradeready_gym/envs/headless_env.py`, lines 256-262)

Replace:
```python
    def __del__(self) -> None:
        """Ensure the event loop is cleaned up on garbage collection."""
        try:
            if hasattr(self, "_loop") and not self._loop.is_closed():
                self._loop.close()
        except Exception:  # noqa: BLE001
            pass
```

With:
```python
    def __del__(self) -> None:
        """Ensure the event loop and connections are cleaned up on GC."""
        try:
            if hasattr(self, "_loop") and not self._loop.is_closed():
                # Best-effort cleanup of episode session and pool
                if hasattr(self, "_episode_session") and self._episode_session is not None:
                    try:
                        self._loop.run_until_complete(self._episode_session.close())
                    except Exception:  # noqa: BLE001
                        pass
                    self._episode_session = None
                if hasattr(self, "_db_engine") and self._db_engine is not None:
                    try:
                        self._loop.run_until_complete(self._db_engine.dispose())
                    except Exception:  # noqa: BLE001
                        pass
                    self._db_engine = None
                self._loop.close()
        except Exception:  # noqa: BLE001
            pass
```

**Why:** If `close()` was never called (e.g., exception during training), `__del__` should still attempt to clean up DB connections. Without this, connections leak on GC.

**Risk:** Low. GC cleanup is best-effort.

---

## Summary of All Changes (Single File)

**File:** `tradeready-gym/tradeready_gym/envs/headless_env.py`

| Change | Lines (approx) | Description |
|--------|----------------|-------------|
| Add `self._episode_session` attribute | After line 175 | New instance var for long-lived session |
| Increase pool config | Lines 292-298 | `pool_size=5, max_overflow=3, pool_recycle=3600` |
| Add `_cleanup_episode()` method | After line 304 | Cancels engine session, closes DB session |
| Rewrite `_async_reset()` | Lines 306-381 | Single episode session, no per-call `async with` |
| Rewrite `_advance_step()` | Lines 383-399 | Use `self._episode_session` instead of `async with` |
| Rewrite `close()` | Lines 236-254 | Call `_cleanup_episode()` before pool dispose |
| Harden `__del__` | Lines 256-262 | Clean up lingering sessions on GC |

**No changes to platform source files.** All fixes are in the gym package.

## Connection Flow After Fix

### Episode 1: reset()

1. `_ensure_engine()` creates pool (pool_size=5, max_overflow=3)
2. `_cleanup_episode()` -- no-op (first episode)
3. `self._episode_session = self._session_factory()` -- checks out connection #1
4. Create Account + Agent rows via `self._episode_session`, commit
5. `engine.create_session(db=self._episode_session)` -- uses connection #1
   - Creates temporary `DataReplayer(self._episode_session)` for validation, discarded after
   - Inserts `BacktestSessionModel`, flushes
6. Commit
7. `engine.start(session_id, self._episode_session)` -- uses connection #1
   - Creates `DataReplayer(self._episode_session)` -- stores **connection #1** reference
   - `preload_range()` -- bulk query on connection #1 (returns all data)
   - Stores replayer in `_active[session_id]`
8. Commit
9. `_advance_step()` -- calls `engine.step(session_id, self._episode_session)` -- connection #1
   - `replayer.load_prices()` -- from cache (no DB hit)
   - `_refresh_candles()` -> `replayer.load_candles()` -- queries on connection #1 (WORKS because session is still open)

### Episode 1: step() x N

Each step uses `self._episode_session` (connection #1). Only 1 connection held for the entire episode.

### Between episodes: close() or reset()

**If SB3 calls close() then reset():**
1. `close()` -> `_cleanup_episode()`:
   - `engine.cancel(session_id, self._episode_session)` -- persists partial results, pops from `_active`, DataReplayer reference released
   - `self._episode_session.close()` -- returns connection #1 to pool
2. `close()` -> `engine.dispose()` -- closes all pool connections
3. `reset()` -> `_ensure_engine()` recreates pool
4. New episode starts fresh

**If SB3 calls reset() directly (without close()):**
1. `reset()` -> `_cleanup_episode()`:
   - `engine.cancel(session_id, self._episode_session)` -- pops from `_active`
   - `self._episode_session.close()` -- returns connection #1 to pool
2. New episode session opened, uses a fresh/recycled connection from pool

## Connection Count Analysis

| Phase | Connections In Use | Pool Available (of 5+3) |
|-------|-------------------|------------------------|
| Episode running | 1 (episode session) | 7 |
| Episode transition (cleanup + new reset) | 0 during cleanup, then 1 | 7-8 |
| Auto-complete on last step | 1 (same session for complete + persist) | 7 |
| After close() + dispose() | 0 | Pool destroyed |

No scenario exceeds pool_size=5 + max_overflow=3 = 8 connections. The steady-state usage is **1 connection per episode**.

## Testing Strategy

### Manual smoke test (primary verification)
```bash
# Inside Docker (or with PYTHONPATH=. and DB running)
python scripts/train_ppo_btc.py --timesteps 2048 --eval-episodes 1 --skip-dsr
```
- Must complete without `QueuePool limit reached` errors
- Must complete without `Event loop is closed` errors
- Must save model to `models/ppo_btc_v1.zip`

### Unit tests to add/update

1. **Test multi-episode lifecycle:** `reset() -> step(0) x 10 -> reset() -> step(0) x 10 -> close()`
   - Assert no exceptions
   - Assert `env._episode_session is None` after close()

2. **Test close-then-reset:** `reset() -> step(0) x 5 -> close() -> reset() -> step(0) x 5 -> close()`
   - Assert no exceptions (exercises SB3 Monitor pattern)
   - Assert pool is recreated after close()

3. **Test episode cleanup cancels active session:**
   - After first `reset()`, assert `engine.is_active(session_id)` is True
   - After second `reset()`, assert previous `session_id` is no longer in `engine._active`

4. **Test connection pool not exhausted:**
   - Run 5 consecutive `reset() -> step(0) x 50` cycles
   - Assert no `QueuePool` errors (wrap in try/except and fail if caught)

**File:** `tradeready-gym/tests/test_headless_env.py` -- add tests to existing suite

### Integration test

Run a short PPO training (256 timesteps, 1 eval episode) against a test database with backfill data. This is the gold standard verification that all connection issues are resolved.

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Long-lived session accumulates objects in identity map | Medium | `commit()` after every step clears pending state; `expire_on_commit=False` prevents lazy-load issues |
| `cancel()` fails during cleanup leaving `_active` entry | Medium | Explicit `session.close()` after cancel attempt ensures connection is returned regardless; next `_ensure_engine()` creates fresh engine |
| Session disconnects during long training (hours) | Low | `pool_pre_ping=True` detects stale connections; `pool_recycle=3600` rotates connections hourly |
| Multiple SB3 envs in SubprocVecEnv | Low | Each env instance has its own event loop, engine, and pool -- fully isolated by design |
| `auto-complete` inside `engine.step()` pops from `_active` on last step | Low | After auto-complete, `_cleanup_episode()` will see `is_active() == False` and skip the cancel call; just closes the session |

## Project-Specific Considerations

- **Agent scoping:** Synthetic account/agent are created per-episode, correctly scoped with `agent_id`. No changes needed.
- **Decimal precision:** No monetary value changes. All Decimal usage is preserved.
- **Async patterns:** The long-lived session approach is standard for batch/pipeline workloads where session scope matches business scope (episode = session).
- **Migration safety:** No DB schema changes. No migration needed.
- **Frontend sync:** No API changes. No TypeScript type updates needed.

## Success Criteria

- [ ] `python scripts/train_ppo_btc.py --timesteps 2048 --eval-episodes 1 --skip-dsr` completes without errors inside Docker
- [ ] No `QueuePool limit of size N overflow N reached` errors in logs
- [ ] No `Event loop is closed` errors in logs
- [ ] Model saved to `models/ppo_btc_v1.zip`
- [ ] Multi-episode lifecycle works: `reset -> step x N -> reset -> step x N -> close`
- [ ] SB3 Monitor pattern works: `reset -> step x N -> close -> reset -> step x N -> close`
- [ ] Existing 52 headless env tests still pass
- [ ] New connection management tests pass

## Assigned Agent

`ml-engineer` -- this is a Gymnasium/RL training infrastructure fix within the `tradeready-gym` package.

## Estimated Effort

~2 hours implementation + testing. Single file change, well-scoped.
