---
task_id: 3
title: "Run mypy and fix type errors"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[deployment-v002/README]]"
files: ["src/"]
tags:
  - task
  - types
  - deployment
---

# Task 03: Run mypy and fix type errors

## Assigned Agent: `backend-developer`

## Objective
Run `mypy src/ --ignore-missing-imports` and fix any type errors that would fail the CI pipeline.

## Context
The CI pipeline (`.github/workflows/test.yml`) runs `mypy src/ --ignore-missing-imports`. Any type errors will fail the deploy.

## Acceptance Criteria
- [ ] `mypy src/ --ignore-missing-imports` passes with zero errors
- [ ] No changes break existing functionality

## Agent Instructions
1. Run `mypy src/ --ignore-missing-imports`
2. For each error, fix the type annotation or add a targeted `# type: ignore[code]` comment
3. Do NOT add `# type: ignore` without a specific error code
4. Common patterns in this project: `Decimal` fields, async generator returns, pydantic v2 computed fields

## Estimated Complexity
Medium — depends on how many errors mypy reports
