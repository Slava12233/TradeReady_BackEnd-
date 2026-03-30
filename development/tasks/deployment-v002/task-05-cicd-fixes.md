---
task_id: 5
title: "CI/CD pipeline fixes"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[deployment-v002/README]]"
files: [".github/workflows/test.yml", ".github/workflows/deploy.yml"]
tags:
  - task
  - cicd
  - deployment
---

# Task 05: CI/CD pipeline fixes

## Assigned Agent: `backend-developer`

## Status: COMPLETED
- `test.yml`: Removed stale `V0.0.1` branch trigger, now only `main`
- `deploy.yml`: Complete rewrite — pulls `main` (was V0.0.1), adds DB backup, rolling restart, auto-rollback on health check failure
