---
type: code-review
date: 2026-03-22
reviewer: code-reviewer
verdict: NEEDS FIXES
scope: phase0-group-a
tags:
  - review
  - agent
  - memory
  - permissions
  - server-handlers
  - redis
---

# Code Review Report

- **Date:** 2026-03-22 01:53
- **Reviewer:** code-reviewer agent
- **Verdict:** NEEDS FIXES

## Files Reviewed

- `agent/memory/redis_cache.py`
- `agent/logging_middleware.py`
- `agent/server.py`
- `agent/server_handlers.py`
- `agent/permissions/enforcement.py`
- `src/utils/exceptions.py`
- `agent/tests/test_redis_memory_cache.py`
- `agent/tests/test_server_writer_wiring.py`
- `agent/tests/test_server_handlers.py`
- `tests/unit/test_exceptions.py`
- `tests/unit/test_permission_enforcement.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root)
- `agent/CLAUDE.md`
- `agent/memory/CLAUDE.md`
- `agent/permissions/CLAUDE.md`
- `tests/CLAUDE.md`
- `tests/unit/CLAUDE.md`
- `src/utils/CLAUDE.md`
- `.claude/agent-memory/code-reviewer/MEMORY.md`

---

## Critical Issues (must fix)

### 1. `get_cached()` uses a glob pattern in Redis `GET` — always returns `None`

- **File:** `agent/memory/redis_cache.py:238`
- **Rule violated:** Correctness / Redis API contract
- **Issue:** `redis.get(f"agent:memory:*:{memory_id}")` — Redis `GET` performs an exact key match. The `*` wildcard in the key is treated as the literal string `*`, not a glob. This means the call will always return `None` unless a key literally named `agent:memory:*:<memory_id>` exists, which it never will. The method is permanently broken.

  The task description says "`get_cached()` now requires `agent_id` and delegates to `get_cached_for_agent()`". The implementation contradicts the description — `get_cached()` still accepts only `memory_id` and attempts a pattern lookup rather than delegating.

- **Fix:** Either change `get_cached()` to require `agent_id` and call `get_cached_for_agent(agent_id, memory_id)`, or use `KEYS` / `SCAN` for the pattern search (though `SCAN` is preferred over `KEYS` in production). The simplest and documented fix is delegation:

  ```python
  async def get_cached(self, memory_id: str, agent_id: str) -> Memory | None:
      return await self.get_cached_for_agent(agent_id, memory_id)
  ```

  Note: changing the signature is a breaking API change — all callers of `get_cached()` must be updated.

---

### 2. Task 05 wiring is incomplete — `log_api_call()` has no `writer` parameter

- **File:** `agent/logging_middleware.py:51-56`
- **Rule violated:** Completeness — tests reference behaviour that does not exist in production code
- **Issue:** `agent/tests/test_server_writer_wiring.py` (61 tests) invokes `log_api_call(..., writer=writer)` and asserts that `writer.add_api_call()` is called on success and failure. However, the actual `log_api_call()` signature is:

  ```python
  async def log_api_call(
      channel: str, endpoint: str, method: str = "", **extra_context: Any
  ) -> AsyncGenerator[dict[str, Any], None]:
  ```

  The `writer` argument passes into `**extra_context` and is placed in the `ctx` dict. It is never extracted and no call to `writer.add_api_call()` is made. All 61 tests in `TestLogApiCallWriterSuccess` and `TestLogApiCallWriterFailure` will fail or give false positives because `writer.add_api_call` is never invoked.

- **Fix:** Add the `writer` parameter explicitly and wire it:

  ```python
  @asynccontextmanager
  async def log_api_call(
      channel: str,
      endpoint: str,
      method: str = "",
      *,
      writer: "LogBatchWriter | None" = None,
      **extra_context: Any,
  ) -> AsyncGenerator[dict[str, Any], None]:
      ...
      # In the else clause (success path):
      if writer is not None:
          try:
              await writer.add_api_call({
                  "channel": channel,
                  "endpoint": endpoint,
                  "method": method,
                  "latency_ms": latency,
                  **{k: v for k, v in ctx.items() if v is not None},
              })
          except Exception:  # noqa: BLE001
              pass
  ```

---

### 3. Task 07 `set_working()` TTL not implemented — working memory silently leaks

- **File:** `agent/memory/redis_cache.py:432-456`
- **Rule violated:** Correctness — stated behaviour not implemented; CLAUDE.md documents that working memory has no TTL (intentional) but the task spec requires adding EXPIRE 86400
- **Issue:** The task description for Task 07 states "`set_working()` uses pipeline with EXPIRE 86400". The actual implementation still performs a bare `redis.hset(...)` with no TTL:

  ```python
  await redis.hset(_working_key(agent_id), key, value)
  ```

  No pipeline, no EXPIRE. Additionally, the task notes "4 new TTL tests" for `test_redis_memory_cache.py`, but no TTL tests exist in that file (the `TestWorkingMemory` class has no TTL assertions). This creates a discrepancy: the task was marked complete but the implementation was not delivered.

  Note: the existing `agent/memory/CLAUDE.md` explicitly states "Working memory has no TTL". If the intent is to preserve that design, the task description is wrong. If the intent is to add TTL, both the code and CLAUDE.md need updating. Either way, the code and task spec must agree.

- **Fix (if TTL is desired):**

  ```python
  async def set_working(self, agent_id: str, key: str, value: str) -> None:
      try:
          redis = await self._get_redis()
          working_key = _working_key(agent_id)
          async with redis.pipeline(transaction=False) as pipe:
              pipe.hset(working_key, key, value)
              pipe.expire(working_key, 86400)
              await pipe.execute()
          logger.debug("agent.memory.working_set", key=key)
      except RedisError as exc:
          ...
  ```

  Then update `agent/memory/CLAUDE.md` to reflect the new TTL behaviour.

---

### 4. `server_handlers.py` uses `float` for monetary price calculations

- **File:** `agent/server_handlers.py:209-232`
- **Rule violated:** Code Standards — `Decimal` required for ALL monetary values; never `float`
- **Issue:** `handle_analyze()` casts candle close prices to `float` before computing indicators:

  ```python
  closes = [float(c.close) for c in candles]   # line 209
  sma_20 = sum(closes[-20:]) / min(20, len(closes))  # float arithmetic on prices
  latest_close = closes[-1]
  ```

  Additionally, volume is cast to float at line 232:
  ```python
  vol_24h = sum(float(c.volume) for c in candles[-24:])
  ```

  These are monetary/financial values. Project standards require `Decimal` throughout. While these are display-only indicators, the pattern establishes a precedent against project rules and the precision loss on close prices could produce misleading SMA values.

- **Fix:** Use `Decimal` arithmetic:

  ```python
  from decimal import Decimal
  closes = [c.close if isinstance(c.close, Decimal) else Decimal(str(c.close)) for c in candles]
  sma_20 = sum(closes[-20:], Decimal("0")) / min(20, len(closes))
  ```

---

### 5. `server_handlers.py` uses `float` for balance and PnL formatting

- **File:** `agent/server_handlers.py:312, 321, 326`
- **Rule violated:** Code Standards — `Decimal` required for ALL monetary values; never `float`
- **Issue:** `handle_portfolio()` casts financial values to `float` in multiple places:

  ```python
  if float(b.total) > 0:          # line 312 — balance comparison using float
  unrealised_pct = float(p.unrealized_pnl_pct) * 100  # line 321 — PnL using float
  total_unrealised += float(p.unrealized_pnl)          # line 326 — accumulation using float
  ```

  Balances and PnL are monetary values. The `float()` cast introduces precision loss.

- **Fix:** Use `Decimal` comparisons and arithmetic throughout:

  ```python
  if b.total > Decimal("0"):
  unrealised_pct = p.unrealized_pnl_pct * Decimal("100")
  total_unrealised += p.unrealized_pnl
  ```

---

## Warnings (should fix)

### W1. `PermissionDenied` in `enforcement.py` is a local class, not imported from `src/utils/exceptions`

- **File:** `agent/permissions/enforcement.py:164`
- **Issue:** Task 07 description says `enforcement.py` imports `PermissionDenied` from `src/utils/exceptions`. The actual file defines `PermissionDenied` as a local class that intentionally does NOT inherit from `TradingPlatformError`. Furthermore, `src/utils/exceptions.py` only has `PermissionDeniedError` (the platform HTTP exception), not `PermissionDenied` (the agent layer exception). The task description appears to be inaccurate about what was changed here.

  The `agent/permissions/CLAUDE.md` correctly documents that `PermissionDenied` is NOT a `TradingPlatformError` subclass, so the current local definition is architecturally correct. No code change is needed, but the task tracking is misleading.

- **Recommendation:** Update the task description to clarify that Task 07 added `PermissionDenied` as a **local class** in `enforcement.py` (not an import), and that the `src/utils/exceptions.py` change is a separate unrelated addition of a new exception (if any was actually added).

  Reviewing `src/utils/exceptions.py` — `PermissionDeniedError` at line 134 is the existing platform exception. No new class named `PermissionDenied` (without the `Error` suffix) was added. The `__all__` list does not contain `PermissionDenied`. This means the task description referring to adding `PermissionDenied` to `src/utils/exceptions` was not executed.

---

### W2. `get_cached()` has no tests for its glob-based fallback path

- **File:** `agent/tests/test_redis_memory_cache.py`
- **Issue:** The `TestGetCachedForAgent` class tests `get_cached_for_agent()` correctly. However, there is no `TestGetCached` class testing `get_cached()` — which is the broken method identified in Critical Issue #1. The tests were written for the correct method (`get_cached_for_agent`) rather than testing the broken legacy path.

- **Recommendation:** Either add tests for `get_cached()` that demonstrate the glob-based lookup (and make them fail to confirm the bug), or remove/deprecate `get_cached()` entirely in favour of `get_cached_for_agent()`.

---

### W3. `server.py` accesses private method `_get_redis()` from outside the class

- **File:** `agent/server.py:832`
- **Issue:** `_ping_redis()` calls `await self._redis_cache._get_redis()` to obtain the raw Redis client. Accessing a private method on another class is an encapsulation violation. This is exactly the anti-pattern called out in the code reviewer memory.

  ```python
  redis = await self._redis_cache._get_redis()
  await asyncio.wait_for(redis.ping(), timeout=2.0)
  ```

- **Recommendation:** Add a public `ping()` method to `RedisMemoryCache`:

  ```python
  async def ping(self) -> bool:
      try:
          redis = await self._get_redis()
          await redis.ping()
          return True
      except (RedisError, Exception):
          return False
  ```

  Then `AgentServer._ping_redis()` calls `await self._redis_cache.ping()`.

---

### W4. `test_server_writer_wiring.py` tests will produce false positives

- **File:** `agent/tests/test_server_writer_wiring.py:52-61`
- **Issue:** As described in Critical Issue #2, `log_api_call()` does not accept or use a `writer` parameter. The `writer` kwarg flows into `extra_context` and is placed in `ctx["writer"] = writer`. The test `writer.add_api_call.assert_awaited_once()` will fail with `AssertionError: Expected 'add_api_call' to have been awaited once. Awaited 0 times.` The entire `TestLogApiCallWriterSuccess` and `TestLogApiCallWriterFailure` class groups (estimated 30+ tests) will fail.

  This should be caught before merge by running `pytest agent/tests/test_server_writer_wiring.py`.

---

### W5. `handle_status()` catches `Exception` broadly for an HTTP call

- **File:** `agent/server_handlers.py:415`
- **Rule violated:** Exception handling — `except Exception` on HTTP calls should be narrowed
- **Issue:**

  ```python
  except Exception as exc:  # noqa: BLE001
      platform_status = f"offline ({exc.__class__.__name__})"
  ```

  For an `httpx.AsyncClient.get()` call, the catch should be narrowed to `(httpx.HTTPStatusError, httpx.RequestError, asyncio.TimeoutError)`. Swallowing all exceptions here could mask programming errors. The `# noqa: BLE001` suppression is used, but that suppression is only justified for LLM/pydantic-ai calls per the memory conventions.

- **Recommendation:** Narrow to:
  ```python
  except (httpx.HTTPStatusError, httpx.RequestError, TimeoutError, Exception) as exc:
  ```
  Or at minimum remove the `# noqa: BLE001` suppression so ruff flags it for human review.

---

### W6. Missing `PermissionDenied` in `src/utils/exceptions.py` `__all__`

- **File:** `src/utils/exceptions.py:842-888`
- **Issue:** If a new `PermissionDenied` class was intended to be added to `src/utils/exceptions.py` as part of Task 07 (distinct from the existing `PermissionDeniedError`), it was not added and is not in `__all__`. The task description references this but the file does not contain it. This appears to be an unimplemented task deliverable.

  If `PermissionDenied` (without the `Error` suffix) was NOT intended to be in `src/utils/exceptions.py`, then the task description is inaccurate and should be corrected.

---

## Suggestions (consider)

### S1. `server_handlers.py` — `AgentConfig(_env_file=None)` constructed on every handler call

- **File:** `agent/server_handlers.py:87, 183, 282, 403, 493, 650`
- **Suggestion:** Each handler constructs a fresh `AgentConfig(_env_file=None)` on every invocation. For a persistent server this is wasteful — `AgentConfig` reads from environment variables which don't change. The config should be injected from the server or cached at module level. This is a performance observation rather than a correctness issue.

---

### S2. `server_handlers.py` — indicator calculations are analysis-only but deserve a comment

- **File:** `agent/server_handlers.py:209-232`
- **Suggestion:** After fixing Critical Issue #4 to use `Decimal`, add a comment clarifying that these are human-facing display indicators only (not used for order placement decisions). This makes the intentional non-precision-critical nature explicit and prevents future reviewers from flagging the calculations as incorrect.

---

### S3. `enforcement.py` `require()` decorator mutates `_action_map` transiently (thread-unsafe)

- **File:** `agent/permissions/enforcement.py:790-797`
- **Suggestion:** The decorator temporarily replaces `self._action_map` with a merged dict, calls `require_action`, then restores it. In a concurrent async environment, two concurrent decorator invocations on different actions could interleave — one invocation would see the other's merged map. Consider using a local variable:

  ```python
  original_map = self._action_map
  self._action_map = {**original_map, action_name: capability}
  try:
      await self.require_action(agent_id, action_name)
  finally:
      self._action_map = original_map
  ```

  This is already the current code, but the race condition remains. A truly safe fix would pass the map as an argument to `require_action` rather than mutating instance state.

---

## Passed Checks

- **Dependency direction:** No upward imports found. The `agent/` package correctly imports from `src/` via lazy imports with `# noqa: PLC0415`. `src/utils/exceptions.py` has no upward imports.
- **Logging:** All modules use `structlog.get_logger(__name__)`. No stdlib `logging` usage found.
- **Async patterns:** All I/O methods are `async/await`. Redis pipelines use `async with redis.pipeline() as pipe:` correctly.
- **Exception hierarchy:** New `PermissionDenied` in `enforcement.py` is intentionally NOT a `TradingPlatformError` subclass — this is architecturally correct per the CLAUDE.md and module documentation.
- **Naming conventions:** All files follow `snake_case.py`. Classes follow `PascalCase`. Functions follow `snake_case`. Constants follow `UPPER_SNAKE_CASE`.
- **Security:** No secrets hardcoded. No raw SQL. No sensitive data logged.
- **Test structure:** Test classes use `class Test<Subject>:` pattern. No `@pytest.mark.asyncio` decorators (correctly absent due to `asyncio_mode = "auto"`). Factory helpers (`_make_cache`, `_make_memory`, `_make_enforcer`) follow the established pattern.
- **`src/utils/exceptions.py` addition:** The existing `PermissionDeniedError` class is well-formed with correct `code`, `http_status`, `to_dict()`, and is present in `__all__`. No regression to the existing hierarchy.
- **`test_exceptions.py`:** 8 new tests follow naming convention `test_{method}_{scenario}`. All monetary values in tests use `Decimal`. Tests cover `.to_dict()`, `http_status`, and `details` contracts correctly.
- **`test_permission_enforcement.py`:** 10 new tests cover `check_action`, `require_action`, `@require` decorator, audit log, and escalation. Mock patterns match project conventions (separate `_make_cap_mgr` / `_make_budget_mgr` helpers, no shared fixtures needed).
- **`server_handlers.py` structure:** All handlers degrade gracefully on error (return `"[error] ..."` strings). All handlers catch specific exceptions where possible. `REASONING_LOOP_SENTINEL` sentinel pattern is clean and well-documented.
- **`server.py` router wiring:** `IntentRouter` registration in `__init__` is correct. Handler imports from `server_handlers.py` are clean top-level imports (not lazy), with the comment explaining they are needed for mockability in tests.
