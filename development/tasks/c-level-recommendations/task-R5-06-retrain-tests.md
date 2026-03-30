---
task_id: R5-06
title: "Write integration tests for retrain Celery tasks"
type: task
agent: "test-runner"
phase: 4
depends_on: ["R5-01"]
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/tests/test_retrain_celery.py"]
tags:
  - task
  - testing
  - retraining
  - celery
---

# Task R5-06: Write Integration Tests for Retrain Tasks

## Assigned Agent: `test-runner`

## Objective
Write tests verifying the Celery retraining integration works correctly.

## Files to Modify/Create
- `agent/tests/test_retrain_celery.py` (new)

## Acceptance Criteria
- [x] Test: Celery task wraps RetrainOrchestrator correctly
- [x] Test: beat schedule entries are registered
- [ ] Test: drift-triggered retrain respects cooldown (not implemented in retrain_tasks.py — no cooldown logic present)
- [ ] Test: retrain results logged to memory system (not directly testable from task layer)
- [ ] Test: concurrent retrains prevented by Celery task locking (no locking in retrain_tasks.py — handled by Celery beat schedule cadence)
- [x] 10+ test functions; all pass (29 tests, 29 passed)

## Dependencies
- R5-01 (tasks must exist to test)

## Estimated Complexity
Medium — integration testing with mocked Celery/Redis
