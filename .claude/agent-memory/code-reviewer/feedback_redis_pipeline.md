---
name: redis_pipeline_context_manager
description: Redis pipeline calls must use async with context manager pattern
type: feedback
---

Redis pipeline usage must always use `async with redis.pipeline() as pipe:` — not plain object assignment.

**Why:** Project standard documented in root CLAUDE.md. The context manager ensures the pipeline is reset/closed on exception paths even if the surrounding try/except block does not cover every failure mode.

**How to apply:** Flag any `pipe = self._redis.pipeline()` followed by `await pipe.execute()` without a context manager. This appeared in `agent/strategies/ensemble/circuit_breaker.py` (Tasks 19) — the pattern is correct functionally but non-conformant.
