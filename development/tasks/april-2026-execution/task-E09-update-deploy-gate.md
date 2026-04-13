---
task_id: E-09
title: "Update deploy.yml gate"
type: task
agent: "backend-developer"
track: E
depends_on: ["E-02", "E-03", "E-04", "E-05", "E-06"]
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/deploy.yml"]
tags:
  - task
  - ci
  - deployment
  - gate
---

# Task E-09: Update deploy.yml gate

## Assigned Agent: `backend-developer`

## Objective
Ensure `deploy.yml` waits for ALL test jobs (not just lint + unit) before deploying to production.

## Context
Currently deploy triggers after `test.yml` passes, but `test.yml` only runs lint, format check, and unit tests. After adding integration, agent, gym, and frontend jobs, deploy must wait for all of them.

## Files to Modify
- `.github/workflows/deploy.yml` — update the `needs` field

## Acceptance Criteria
- [ ] Deploy job requires ALL test jobs to pass: unit, integration, agent, gym, frontend
- [ ] If any test job fails, deploy is blocked
- [ ] Deploy workflow syntax is valid
- [ ] Existing deploy behavior preserved (SSH deploy to production)

## Dependencies
- **E-02..E-06**: All test jobs must be defined first

## Agent Instructions
Read `.github/workflows/deploy.yml` to understand the current gate. Update the `needs` field to include all new jobs. If deploy.yml uses `workflow_run` to trigger after test.yml, the new jobs in test.yml should automatically be included. If it uses `needs`, list all job names explicitly.

## Estimated Complexity
Low — updating a dependency list.
