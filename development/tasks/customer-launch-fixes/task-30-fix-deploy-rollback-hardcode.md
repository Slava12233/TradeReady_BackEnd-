---
task_id: 30
title: "Fix deploy.yml rollback migration hardcode"
type: task
agent: "deploy-checker"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: [".github/workflows/deploy.yml"]
tags:
  - task
  - infrastructure
  - ci-cd
  - P2
---

# Task 30: Fix deploy.yml rollback hardcode

## Assigned Agent: `deploy-checker`

## Objective
Rollback in `deploy.yml` hardcodes migration 017. As migrations advance, rollback would target the wrong revision.

## Context
Infrastructure audit (SR-07) flagged this. Current head is 023; rolling back to 017 would be destructive.

## Files to Modify
- `.github/workflows/deploy.yml` — Make rollback target dynamic (previous revision)

## Acceptance Criteria
- [ ] Rollback step uses `alembic downgrade -1` (previous revision) instead of hardcoded revision
- [ ] Or: rollback step reads the current head before deploy and stores it for rollback
- [ ] Rollback is tested (dry-run possible)
- [ ] No hardcoded migration revision numbers in CI

## Agent Instructions
1. Read `.github/workflows/deploy.yml` and find the hardcoded migration reference
2. Replace with dynamic approach: capture `alembic current` before upgrade, use it for rollback
3. Consider using `alembic downgrade -1` for single-step rollback

## Estimated Complexity
Low — CI config fix
