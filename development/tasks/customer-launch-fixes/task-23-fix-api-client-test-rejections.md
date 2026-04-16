---
task_id: 23
title: "Fix api-client test unhandled rejections"
type: task
agent: "test-runner"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/tests/unit/api-client.test.ts"]
tags:
  - task
  - testing
  - frontend
  - P2
---

# Task 23: Fix api-client test unhandled rejections

## Assigned Agent: `test-runner`

## Objective
6 unhandled rejections in `api-client.test.ts` pollute test output. The tests pass but the error noise makes it hard to spot real failures.

## Context
Code quality audit (SR-03) flagged this. All 735 tests pass, but 6 unhandled rejection errors fire from error-handling tests in the api-client suite.

## Files to Modify
- `Frontend/tests/unit/api-client.test.ts` — Properly catch expected errors in tests

## Acceptance Criteria
- [ ] Zero unhandled rejection errors in test output
- [ ] All 735 tests still pass
- [ ] Error-handling tests use proper `expect(...).rejects.toThrow()` patterns
- [ ] Test output is clean with no noise

## Agent Instructions
1. Read the test file and identify the 6 tests that cause unhandled rejections
2. These tests test error scenarios (503, 401, 404, timeout, network error)
3. Ensure all promise rejections are properly caught with `await expect(promise).rejects.toThrow()`
4. The issue is likely that the test creates a promise that rejects but doesn't await the rejection

## Estimated Complexity
Low — test pattern fix
