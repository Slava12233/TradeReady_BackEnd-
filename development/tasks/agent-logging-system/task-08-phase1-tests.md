---
task_id: 08
title: "Phase 1 tests — logging module and config migration"
type: task
agent: "test-runner"
phase: 1
depends_on: [1, 2, 3, 4, 5, 6, 7]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tests/test_logging.py"]
tags:
  - task
  - agent
  - logging
---

# Task 08: Phase 1 Tests

## Assigned Agent: `test-runner`

## Objective
Write and run tests for the new `agent/logging.py` module and verify all config migrations work correctly.

## Tests to Write

### `agent/tests/test_logging.py`

1. **test_configure_agent_logging** — verify structlog is configured with JSON output
2. **test_set_get_trace_id** — set a trace ID, verify get returns it
3. **test_auto_generate_trace_id** — call `set_trace_id(None)`, verify a hex string is returned
4. **test_set_get_agent_id** — set and retrieve agent ID
5. **test_new_span_id** — verify unique span IDs generated
6. **test_correlation_context_processor** — verify trace/span/agent IDs injected into log event dict
7. **test_correlation_context_empty** — verify no extra keys when context vars are unset
8. **test_async_context_isolation** — verify context vars don't leak between concurrent async tasks

## Tests to Run
- All existing agent tests (`pytest agent/tests/ -x`)
- Verify no regressions from config migration

## Acceptance Criteria
- [ ] `agent/tests/test_logging.py` created with 8+ tests
- [ ] All new tests pass
- [ ] All existing agent tests still pass (no regressions)
- [ ] `ruff check agent/tests/test_logging.py` passes

## Agent Instructions
- Follow `tests/CLAUDE.md` patterns for test structure
- Use `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio`
- For async context isolation test, use `asyncio.gather` with two tasks setting different trace IDs
- Mock structlog configuration in tests to avoid side effects

## Estimated Complexity
Medium — need to test async context var behavior
