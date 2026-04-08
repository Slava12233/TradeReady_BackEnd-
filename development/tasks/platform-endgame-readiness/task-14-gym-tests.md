---
task_id: 14
title: "Write tests for enhanced gym environments"
type: task
agent: "test-runner"
phase: 2
depends_on: [12, 13]
status: "pending"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tradeready-gym/tests/test_headless_env.py"
  - "tradeready-gym/tests/test_configurable_fees.py"
tags:
  - task
  - testing
  - gymnasium
  - phase-2
---

# Task 14: Write tests for enhanced gym environments

## Assigned Agent: `test-runner`

## Objective
Write tests for the configurable fee rate and headless environment.

## Context
Tasks 12-13 implement fee configuration and headless env. This task validates them.

## Files to Modify/Create
- `tradeready-gym/tests/test_configurable_fees.py` — Tests for fee_rate parameter threading
- `tradeready-gym/tests/test_headless_env.py` — Tests for headless env (may need DB fixture)

## Acceptance Criteria
- [ ] Fee tests: default fee is 0.001, custom fee is respected, fee affects trade PnL correctly
- [ ] Headless tests: env creates successfully with DB URL, reset returns valid observation, step returns valid (obs, reward, done, truncated, info), close cleans up resources
- [ ] All tests pass

## Dependencies
- **Tasks 12 and 13** must complete first

## Agent Instructions
1. Read `tradeready-gym/CLAUDE.md` for test patterns
2. Fee tests can mock the API — verify the fee_rate param is passed through
3. Headless tests may need a real DB with candle data — use a test fixture or mark as integration

## Estimated Complexity
Medium — headless env tests require DB setup or careful mocking.
