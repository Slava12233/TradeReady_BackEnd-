---
task_id: 25
title: "Ensemble tests"
agent: "test-runner"
phase: E
depends_on: [21, 23]
status: "completed"
priority: "low"
files: ["agent/tests/test_meta_learner.py", "agent/tests/test_ensemble_pipeline.py"]
---

# Task 25: Ensemble tests

## Assigned Agent: `test-runner`

## Objective
Write tests for meta-learner voting logic, disagreement detection, and ensemble pipeline.

## Files to Create
- `agent/tests/test_meta_learner.py`:
  - 3/3 agreement → high confidence consensus
  - 2/3 agreement → medium confidence, correct action
  - 0/3 agreement → HOLD
  - Missing signal (source offline) → treated as HOLD
  - Weights normalization
  - Confidence threshold filtering

- `agent/tests/test_ensemble_pipeline.py`:
  - Pipeline initializes all components (mock models)
  - Step produces valid StepResult
  - Disabled signal source doesn't crash pipeline
  - Risk veto prevents order execution
  - Report generation includes all stats

## Acceptance Criteria
- [ ] All tests pass
- [ ] Meta-learner tests cover all agreement scenarios
- [ ] Pipeline tests verify full step cycle with mocked components

## Dependencies
- Task 21: meta-learner code
- Task 23: ensemble pipeline code

## Estimated Complexity
Medium — mock-heavy tests for orchestration code.
