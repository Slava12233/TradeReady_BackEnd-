---
task_id: 14
title: "Unit tests for tools & models"
type: task
agent: "test-runner"
phase: 6
depends_on: [4, 5, 6, 7]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "medium"
files:
  - "agent/tests/__init__.py"
  - "agent/tests/test_models.py"
  - "agent/tests/test_sdk_tools.py"
  - "agent/tests/test_rest_tools.py"
  - "agent/tests/test_config.py"
tags:
  - task
  - testing-agent
---

# Task 14: Unit tests for tools & models

## Assigned Agent: `test-runner`

## Objective
Write unit tests for the agent's output models, configuration, and tool modules. Mock external dependencies (SDK client, httpx, OpenRouter).

## Files to Create

### `agent/tests/test_models.py`
- Test all Pydantic models serialize/deserialize correctly
- Test enum values (SignalType)
- Test validation (confidence 0-1, quantity_pct bounds)

### `agent/tests/test_config.py`
- Test `AgentConfig` loads from env vars
- Test defaults are applied correctly
- Test missing required fields raise errors

### `agent/tests/test_sdk_tools.py`
- Mock `AsyncAgentExchangeClient` methods
- Test each SDK tool function returns correct dict structure
- Test error handling (SDK exceptions → error dicts)

### `agent/tests/test_rest_tools.py`
- Mock `httpx.AsyncClient` responses
- Test `PlatformRESTClient` methods with sample responses
- Test error handling (HTTP errors → descriptive messages)

## Acceptance Criteria
- [ ] All models have serialization tests
- [ ] Config loading tested with mocked env vars
- [ ] SDK tools tested with mocked client
- [ ] REST tools tested with mocked httpx
- [ ] All tests pass with `pytest agent/tests/`
- [ ] No external dependencies needed to run tests

## Dependencies
- Tasks 4, 5, 6, 7 (code to test must exist)

## Agent Instructions
- Use `pytest-asyncio` for async tests
- Mock SDK client with `unittest.mock.AsyncMock`
- Mock httpx with `httpx.MockTransport` or `unittest.mock`
- Follow `tests/CLAUDE.md` patterns from the main project
- Keep tests focused — unit tests only, no integration

## Estimated Complexity
Medium — multiple test files covering different modules
