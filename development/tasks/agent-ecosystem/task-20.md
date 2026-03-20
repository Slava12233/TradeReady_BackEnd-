---
task_id: 20
title: "Phase 1 integration test"
agent: "test-runner"
phase: 1
depends_on: [4, 8, 12, 15, 18]
status: "pending"
priority: "high"
files: ["tests/integration/test_agent_ecosystem_phase1.py"]
---

# Task 20: Phase 1 integration test

## Assigned Agent: `test-runner`

## Objective
Write integration tests that verify the full Phase 1 stack works end-to-end: session creation, message flow, memory persistence, context building, and tool execution.

## Files to Create
- `tests/integration/test_agent_ecosystem_phase1.py`

## Test Scenarios
1. **Full session lifecycle**: create session → add messages → build context → end session → verify DB state
2. **Memory round-trip**: save learning → retrieve via search → verify caching → reinforce → verify counter
3. **Context assembly**: mock portfolio data → build context → verify all sections present
4. **Tool execution**: call `reflect_on_trade` → verify journal entry + learning created
5. **CLI session persistence**: create session → simulate CLI restart → resume session → verify messages

## Acceptance Criteria
- [ ] At least 5 integration tests
- [ ] Tests use the app factory pattern from `tests/CLAUDE.md`
- [ ] Tests verify actual DB state (not just mocked responses)
- [ ] Tests cover the conversation → memory → context pipeline
- [ ] All tests pass with Docker services running

## Dependencies
- All Phase 1 component tests (Tasks 04, 08, 12, 18)

## Agent Instructions
1. Read `tests/integration/CLAUDE.md` for integration test setup
2. Use fixtures that create test agents and clean up after
3. These tests require DB and Redis — mark appropriately
4. Test the full data flow, not individual components

## Estimated Complexity
Medium — integration testing requires proper setup/teardown.
