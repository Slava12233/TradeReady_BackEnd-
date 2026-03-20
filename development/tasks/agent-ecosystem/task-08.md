---
task_id: 08
title: "Tests for conversation system"
agent: "test-runner"
phase: 1
depends_on: [5, 6, 7]
status: "pending"
priority: "medium"
files: ["tests/unit/test_agent_session.py", "tests/unit/test_context_builder.py", "tests/unit/test_intent_router.py"]
---

# Task 08: Tests for conversation system

## Assigned Agent: `test-runner`

## Objective
Write unit tests for the conversation system: session manager, context builder, and intent router.

## Files to Create
- `tests/unit/test_agent_session.py` — test session lifecycle, message persistence, context building
- `tests/unit/test_context_builder.py` — test dynamic prompt assembly, token limits, graceful degradation
- `tests/unit/test_intent_router.py` — test intent classification, slash commands, handler routing

## Acceptance Criteria
- [ ] At least 8 tests for session manager (create, resume, add message, summarize, end)
- [ ] At least 6 tests for context builder (all data sources, token overflow, failure handling)
- [ ] At least 8 tests for intent router (each intent type + slash commands + edge cases)
- [ ] 22+ tests total
- [ ] All tests pass with mocked DB and external dependencies

## Dependencies
- Tasks 05, 06, 07 (all conversation system components)

## Agent Instructions
1. Mock all DB repos and external SDK calls
2. Test context builder with various combinations of available/unavailable data
3. Test router with natural language variants: "buy BTC", "what's my portfolio", "write a journal entry"
4. Test slash command override: `/trade` should always route to TRADE regardless of message body

## Estimated Complexity
Medium — comprehensive coverage of the conversation system.
