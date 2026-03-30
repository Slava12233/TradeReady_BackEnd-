---
task_id: 11
title: "Run full unit test suite"
type: task
agent: "test-runner"
phase: 6
depends_on: [3, 4]
status: "pending"
priority: "high"
board: "[[deployment-v002/README]]"
files: ["tests/unit/"]
tags:
  - task
  - tests
  - deployment
---

# Task 11: Run full unit test suite

## Assigned Agent: `test-runner`

## Objective
Run the complete unit test suite to confirm zero failures before deployment. This is the final gate.

## Acceptance Criteria
- [ ] `pytest tests/unit -v --tb=short` passes with zero failures
- [ ] No tests skipped due to import errors
- [ ] Test count is consistent with expected (~981+ unit tests)

## Agent Instructions
1. Run `pytest tests/unit -v --tb=short`
2. If any failures, investigate and fix
3. Report total pass/fail/skip counts
4. This is the same command the CI pipeline runs

## Estimated Complexity
Low — if tasks 03 and 04 are done, this should be a clean run
