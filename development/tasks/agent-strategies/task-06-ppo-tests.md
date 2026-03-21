---
task_id: 06
title: "PPO unit & integration tests"
type: task
agent: "test-runner"
phase: A
depends_on: [2, 5]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: ["agent/tests/test_rl_config.py", "agent/tests/test_rl_pipeline.py", "agent/tests/test_rl_deploy.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 06: PPO unit & integration tests

## Assigned Agent: `test-runner`

## Objective
Write tests for the RL training pipeline: config validation, pipeline smoke test, deployment bridge logic.

## Files to Create
- `agent/tests/test_rl_config.py`:
  - Config loads from env vars
  - Default values are valid
  - Invalid values (negative learning rate, empty asset list) raise ValidationError

- `agent/tests/test_rl_pipeline.py`:
  - Training starts with 100 timesteps and produces a model file (smoke test)
  - Model loads successfully from saved checkpoint
  - Evaluation produces valid EvaluationReport

- `agent/tests/test_rl_deploy.py`:
  - Weight-to-order conversion: [0.5, 0.3, 0.2] with current [0.4, 0.4, 0.2] → buy asset0, sell asset1, hold asset2
  - Minimum order filtering (orders < $1 are skipped)
  - Edge case: all weights = 0 (go to cash)
  - Edge case: single asset = 1.0 (concentrate)

## Acceptance Criteria
- [ ] All tests pass: `pytest agent/tests/test_rl_*.py -v`
- [ ] Config tests cover all validation rules
- [ ] Pipeline smoke test completes in < 60 seconds (100 timesteps only)
- [ ] Deploy bridge tests cover all weight-to-order scenarios
- [ ] No mocking of the actual RL training (mock the platform API, not SB3)

## Dependencies
- Task 02: config and pipeline code exists
- Task 05: evaluation and deploy code exists

## Agent Instructions
Follow the existing test patterns in `agent/tests/`. Use `pytest-asyncio` for async tests. Mock the platform API with `httpx.MockTransport` (same as `test_rest_tools.py`). For the pipeline smoke test, use a tiny environment (10 steps per episode, 100 total timesteps).

## Estimated Complexity
Medium — several test files covering different concerns.
