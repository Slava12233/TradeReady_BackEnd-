---
task_id: 6
title: "Write tests for Deflated Sharpe (unit + integration)"
type: task
agent: "test-runner"
phase: 1
depends_on: [4, 5]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tests/unit/test_deflated_sharpe.py"
  - "tests/integration/test_metrics_api.py"
tags:
  - task
  - testing
  - metrics
  - phase-1
---

# Task 06: Write tests for Deflated Sharpe (unit + integration)

## Assigned Agent: `test-runner`

## Objective
Write unit tests validating the DSR math against known reference values, and integration tests for the API endpoint.

## Context
Tasks 04-05 implement DSR core + integration. This task validates correctness with reference values.

## Files to Modify/Create
- `tests/unit/test_deflated_sharpe.py` — Unit tests with reference values for the Bailey & Lopez de Prado formula
- `tests/integration/test_metrics_api.py` — API endpoint integration tests

## Acceptance Criteria
- [ ] Unit tests validate: normal CDF accuracy (compare to known values), DSR with known inputs produces expected output, edge cases (num_trials=1, very short returns), skewness/kurtosis computation
- [ ] Integration tests: endpoint returns correct schema, validates min returns length, validates num_trials >= 1, returns is_significant correctly
- [ ] All tests pass
- [ ] Tests follow project conventions

## Dependencies
- **Tasks 04 and 05** must complete first

## Agent Instructions
1. Reference values for validation:
   - Φ(0) = 0.5, Φ(1.96) ≈ 0.975, Φ(-1.96) ≈ 0.025
   - For a known returns series with known N, verify DSR matches hand-computed value
2. Test edge cases: all-positive returns, all-negative returns, constant returns (zero variance)
3. Read `tests/CLAUDE.md` for test conventions

## Estimated Complexity
Medium — requires computing reference values by hand to validate against.
