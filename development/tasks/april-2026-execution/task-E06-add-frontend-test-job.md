---
task_id: E-06
title: "Add frontend test job"
type: task
agent: "frontend-developer"
track: E
depends_on: ["D-11"]
status: "completed"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - ci
  - frontend
  - testing
---

# Task E-06: Add frontend test job

## Assigned Agent: `frontend-developer`

## Objective
Add `npm run test` as a step in the frontend CI job (or as a separate job).

## Context
Depends on Track D delivering tests. Without tests, this step would just pass with 0 tests.

## Files to Modify
- `.github/workflows/test.yml`

## Acceptance Criteria
- [ ] Frontend test step added to CI
- [ ] Runs `npm run test` in Frontend directory
- [ ] Test failures block the pipeline
- [ ] Coordinates with E-05 (can be same job or separate)
- [ ] Runs after `npm ci` (dependencies installed)

## Dependencies
- **D-11**: Frontend tests must exist and pass locally

## Agent Instructions
Add `npm run test` as a step after build/lint in the frontend job from E-05. Or create a separate `frontend-tests` job if you want parallel execution. Either way, ensure test failures propagate as job failures.

## Estimated Complexity
Low — adding one step to existing job.
