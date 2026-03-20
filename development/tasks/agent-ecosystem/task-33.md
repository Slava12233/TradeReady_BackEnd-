---
task_id: 33
title: "Phase 2 integration test"
agent: "test-runner"
phase: 2
depends_on: [25, 31, 32]
status: "pending"
priority: "high"
files: ["tests/integration/test_agent_ecosystem_phase2.py"]
---

# Task 33: Phase 2 integration test

## Assigned Agent: `test-runner`

## Objective
Write integration tests verifying the full Phase 2 stack: permission-gated trading loop, journal recording, strategy monitoring, and budget enforcement.

## Files to Create
- `tests/integration/test_agent_ecosystem_phase2.py`

## Test Scenarios
1. **Permission-gated trade**: set agent role → attempt trade → verify permission check → verify execution
2. **Budget enforcement**: set budget → trade until exhausted → verify denial
3. **Trading loop full cycle**: start loop → generate signals → execute trade → record journal → verify DB
4. **Strategy degradation**: feed losing trades → verify degradation alert fires
5. **A/B test lifecycle**: create test → feed results → evaluate → verify winner
6. **Journal reflection**: execute trade → record outcome → generate reflection → verify learning created

## Acceptance Criteria
- [ ] At least 6 integration tests
- [ ] Tests verify actual DB state across multiple tables
- [ ] Permission enforcement tested end-to-end
- [ ] Budget exhaustion tested with real atomic counters
- [ ] All tests pass with Docker services running

## Dependencies
- All Phase 2 component tests (Tasks 25, 31, 32)

## Agent Instructions
1. Build on Phase 1 integration test fixtures
2. These tests need DB + Redis
3. Create test agents with specific roles and budgets
4. Verify cross-table consistency (decision → journal → learnings)

## Estimated Complexity
High — complex integration scenarios spanning multiple subsystems.
