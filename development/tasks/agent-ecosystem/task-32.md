---
task_id: 32
title: "Tests for strategy management and A/B testing"
type: task
agent: "test-runner"
phase: 2
depends_on: [29, 30]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["tests/unit/test_strategy_manager.py", "tests/unit/test_ab_testing.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 32: Tests for strategy management and A/B testing

## Assigned Agent: `test-runner`

## Objective
Write unit tests for strategy performance monitoring, degradation detection, and A/B testing.

## Files to Create
- `tests/unit/test_strategy_manager.py` — test performance tracking, degradation, suggestions
- `tests/unit/test_ab_testing.py` — test A/B test creation, recording, evaluation, promotion

## Acceptance Criteria
- [ ] At least 8 tests for strategy manager (performance recording, degradation thresholds, comparison)
- [ ] At least 6 tests for A/B testing (create, record, evaluate winner, statistical significance)
- [ ] 14+ tests total
- [ ] Test degradation detection fires at correct thresholds
- [ ] Test that winner is not declared before min_trades
- [ ] Test promotion updates strategy parameters
- [ ] Test statistical significance check

## Dependencies
- Tasks 29, 30 (strategy management and A/B testing)

## Agent Instructions
1. Create mock trade result data with known outcomes for deterministic testing
2. Test degradation with a series of losing trades
3. Test A/B evaluation with two datasets of known different means
4. Verify promotion writes to strategy config

## Estimated Complexity
Medium — statistical testing requires carefully crafted test data.
