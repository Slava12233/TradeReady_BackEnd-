---
task_id: 27
title: "Phase 3 tests — correlation, repositories, batch writer"
type: task
agent: "test-runner"
phase: 3
depends_on: [16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tests/test_logging_writer.py", "tests/unit/test_agent_api_call_repo.py", "tests/unit/test_agent_strategy_signal_repo.py"]
tags:
  - task
  - agent
  - logging
---

# Task 27: Phase 3 Tests

## Assigned Agent: `test-runner`

## Objective
Write and run tests for cross-system correlation, new repositories, batch writer, and audit log middleware.

## Tests to Write

### `agent/tests/test_logging_writer.py`
1. **test_batch_writer_flush_on_size** — buffer fills to max_batch_size → auto-flush
2. **test_batch_writer_periodic_flush** — events flushed after interval
3. **test_batch_writer_stop_drains** — stop() flushes remaining events
4. **test_batch_writer_flush_failure** — DB error doesn't crash, events logged
5. **test_batch_writer_concurrent_adds** — concurrent `add()` calls don't corrupt buffer

### `tests/unit/test_agent_api_call_repo.py`
6. **test_create_api_call** — single insert
7. **test_bulk_create** — batch insert
8. **test_get_by_trace** — filter by trace_id
9. **test_get_stats** — aggregated endpoint stats

### `tests/unit/test_agent_strategy_signal_repo.py`
10. **test_create_signal** — single insert
11. **test_get_by_trace** — filter by trace_id
12. **test_get_attribution** — grouped strategy stats

### Integration test
13. **test_trace_id_propagation** — agent sets trace_id → SDK sends X-Trace-Id → platform logs include it

## Tests to Run
- All existing agent + platform tests
- New test files

## Acceptance Criteria
- [ ] 13+ new tests written and passing
- [ ] All existing tests still pass
- [ ] `ruff check` passes on all test files

## Estimated Complexity
Medium — batch writer tests need async task management, repo tests need DB fixtures
