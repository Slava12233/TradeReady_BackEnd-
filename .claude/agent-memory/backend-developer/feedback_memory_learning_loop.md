---
name: feedback_memory_learning_loop
description: Patterns from implementing the memory-driven learning loop in TradingJournal and ContextBuilder (Task 32)
type: feedback
---

## Key patterns for journal memory integration

**MemoryStore.save() takes a full Memory object**, not keyword args. The correct call is:
```python
await self._memory_store.save(Memory(id="", agent_id=agent_id, memory_type=MemoryType.EPISODIC, ...))
```
NOT `await store.save(agent_id=..., memory_type=..., content=...)`. The ABC signature is `save(memory: Memory) -> str`.

**Why:** The CLAUDE.md stated keyword args but the actual ABC in store.py uses a positional Memory object.

**How to apply:** Always check `store.py` for the actual method signature before calling `MemoryStore` methods.

## Dedup-reinforce pattern for procedural memories

When saving a procedural memory, first `search()` for overlapping existing memories and `reinforce()` the match instead of creating duplicates. Match criteria used: regime substring + symbol substring + ≥ 2 shared token overlap between pattern and existing content. This prevents memory bloat while increasing `times_reinforced` for confirmed patterns.

**Why:** High-value learnings should surface higher in retrieval scoring via `reinforcement_score = min(1.0, times_reinforced / 10.0)`.

## Test ordering failures in full suite vs isolated

Two tests fail when run in the full suite (`agent/tests/`) but pass in isolation. The root cause is `sys.modules` pollution from earlier test files (pre-existing issue: 546 failures existed before this task). Tests that do lazy `from agent.memory.store import Memory, MemoryType` inside `save_episodic_memory()` may hit a stale import from an earlier test's `patch.dict("sys.modules", ...)` call.

**How to apply:** Verify that ordering-sensitive tests pass in isolation with `-k` selector; document pre-existing failures baseline (546 failing before, 548 with 2 ordering-sensitive new tests).

## ContextBuilder learnings section — dedup pattern

When adding a "past experience" block via `search()` before the general `get_recent()` block, track memory IDs shown in the past-experience block in an `added_ids: set[str]` and filter them out from `get_recent()` results. Return empty string if `len(lines) == 1` (header only, nothing added).
