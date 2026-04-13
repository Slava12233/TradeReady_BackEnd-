---
task_id: D-12
title: "Add test script to CI"
type: task
agent: "frontend-developer"
track: D
depends_on: ["D-11", "E-05"]
status: "completed"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - frontend
  - ci
  - testing
---

# Task D-12: Add test script to CI

## Assigned Agent: `frontend-developer`

## Objective
Ensure `npm run test` is included in the GitHub Actions pipeline as part of the frontend job (connects to Track E).

## Context
This bridges Track D (frontend tests) and Track E (CI/CD pipeline). The frontend test job from E-06 should run the tests created in Track D.

## Files to Modify
- `.github/workflows/test.yml` — add frontend test step to the frontend job

## Acceptance Criteria
- [ ] Frontend test step added to CI workflow
- [ ] Step runs after `npm ci` and `npm run build`
- [ ] Test failures block the pipeline (exit code propagated)
- [ ] Coordinate with E-06 to avoid duplicate jobs

## Dependencies
- **D-11**: All frontend tests must pass locally
- **E-05**: Frontend build job must exist in CI

## Agent Instructions
This task may overlap with E-06. Check if E-06 has already added a test step. If so, just verify it works. If not, add `npm run test` as a step in the frontend CI job. Use `working-directory: Frontend` for the step.

## Estimated Complexity
Low — adding one CI step.
