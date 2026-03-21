---
task_id: 15
title: "Phase 2 tests — API call middleware, LLM logging, memory logging"
type: task
agent: "test-runner"
phase: 2
depends_on: [9, 10, 11, 12, 13, 14]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tests/test_logging_middleware.py"]
tags:
  - task
  - agent
  - logging
---

# Task 15: Phase 2 Tests

## Assigned Agent: `test-runner`

## Objective
Write and run tests for the API call logging middleware, LLM call logging, and memory operation logging.

## Tests to Write

### `agent/tests/test_logging_middleware.py`
1. **test_log_api_call_success** — verify INFO log emitted with correct fields on success
2. **test_log_api_call_failure** — verify ERROR log emitted and exception re-raised
3. **test_log_api_call_timing** — verify latency_ms is reasonable (>0, not wildly large)
4. **test_log_api_call_context_enrichment** — verify caller can set ctx["response_status"]
5. **test_log_api_call_span_id_unique** — verify different span_ids across calls
6. **test_log_api_call_extra_context** — verify extra kwargs appear in log

### Memory logging tests (can be in existing memory test files)
7. **test_memory_save_logs** — verify save produces INFO log
8. **test_memory_retrieval_logs** — verify retrieval logs cache hits and DB hits
9. **test_memory_cache_hit_log** — verify cache hit logged at DEBUG
10. **test_memory_cache_miss_log** — verify cache miss logged at DEBUG

## Tests to Run
- All existing agent tests
- New test files

## Acceptance Criteria
- [ ] 10+ new tests written and passing
- [ ] All existing agent tests still pass
- [ ] `ruff check` passes on test files

## Agent Instructions
- Use `caplog` or `structlog.testing.capture_logs` to capture and assert log output
- For timing tests, use `time.sleep(0.01)` to ensure measurable latency
- Mock external dependencies (SDK client, Redis, DB) to isolate logging behavior

## Estimated Complexity
Medium — need to test async context manager behavior and log capture
