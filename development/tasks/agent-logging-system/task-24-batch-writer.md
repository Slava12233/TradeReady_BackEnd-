---
task_id: 24
title: "Create LogBatchWriter for async DB persistence"
type: task
agent: "backend-developer"
phase: 3
depends_on: [22]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/logging_writer.py"]
tags:
  - task
  - agent
  - logging
---

# Task 24: Create LogBatchWriter

## Assigned Agent: `backend-developer`

## Objective
Create `agent/logging_writer.py` — a batched async writer that buffers API call and strategy signal log events, flushing them to the database in bulk to avoid per-call DB overhead.

## Files to Create
- `agent/logging_writer.py` — `LogBatchWriter` class

## Implementation Details

```python
class LogBatchWriter:
    """Buffers log events and flushes to DB in batches.

    Flush triggers:
    - Buffer reaches max_batch_size (default: 50)
    - Flush interval elapsed (default: 10 seconds)
    - Manual flush() call (on shutdown)
    """
```

Required methods:
- `__init__(session_factory, max_batch_size=50, flush_interval=10.0)`
- `async start()` — starts the periodic flush background task
- `async add_api_call(record: dict)` — add API call to buffer
- `async add_signal(record: dict)` — add strategy signal to buffer
- `async flush()` — drain buffers into DB via `bulk_create()`
- `async stop()` — cancel periodic task + final flush

Key design decisions:
- Two separate deques: one for API calls, one for signals
- Periodic flush via `asyncio.create_task` with `asyncio.sleep` loop
- `flush()` must handle partial failures (log errors, don't lose remaining buffer)
- Use `session_factory` to create short-lived DB sessions per flush
- Thread-safe: use `asyncio.Lock` to prevent concurrent flushes

## Acceptance Criteria
- [ ] Buffers events and flushes at configurable batch size
- [ ] Periodic flush at configurable interval
- [ ] `stop()` drains all remaining events before returning
- [ ] Flush failures logged but don't crash the agent
- [ ] No events lost on normal shutdown
- [ ] `ruff check agent/logging_writer.py` passes
- [ ] Type annotations on all methods

## Agent Instructions
- Use `collections.deque` for the buffer (thread-safe append)
- Import repositories lazily inside `flush()` to avoid circular imports
- The `session_factory` is the same `async_sessionmaker` used by the rest of the agent
- Follow the batch writer pattern from `agent/permissions/enforcement.py` (audit log buffer)

## Estimated Complexity
Medium — async background task management, batch DB writes, error handling
