---
task_id: 18
title: "Update context.md + CLAUDE.md files for all recommendations"
type: task
agent: "context-manager"
phase: 3
depends_on: [3, 8, 14, 15]
status: "pending"
priority: "medium"
board: "[[recommendations-execution/README]]"
files:
  - "development/context.md"
  - "src/webhooks/CLAUDE.md"
  - "src/backtesting/CLAUDE.md"
  - "src/metrics/CLAUDE.md"
  - "src/api/routes/CLAUDE.md"
  - "src/api/schemas/CLAUDE.md"
  - "src/tasks/CLAUDE.md"
  - "tests/unit/CLAUDE.md"
  - "tests/integration/CLAUDE.md"
  - "CLAUDE.md"
tags:
  - task
  - context
  - claude-md
  - documentation
---

# Task 18: Context and CLAUDE.md Sync

## Assigned Agent: `context-manager`

## Objective
Add V.0.0.3 milestone to context.md, create `src/webhooks/CLAUDE.md`, update all affected module CLAUDE.md files, and update root CLAUDE.md index.

## Context
This is the final task — syncs all documentation with the final state of V.0.0.3 including endgame improvements, security fixes, frontend components, RL training, backup infrastructure, and onboarding docs.

## Files to Modify/Create
- `development/context.md` — V.0.0.3 milestone entry
- `src/webhooks/CLAUDE.md` — CREATE new package overview
- `src/backtesting/CLAUDE.md` — Add step_batch_fast, BatchStepResult, fee_rate
- `src/metrics/CLAUDE.md` — Add deflated_sharpe.py
- `src/api/routes/CLAUDE.md` — Add 10+ new endpoints
- `src/api/schemas/CLAUDE.md` — Add 6 new schema files
- `src/tasks/CLAUDE.md` — Add webhook_tasks.py
- `tests/unit/CLAUDE.md` — Add 6+ new test files
- `tests/integration/CLAUDE.md` — Add 4+ new test files
- `CLAUDE.md` — Add src/webhooks/CLAUDE.md to module index

## Acceptance Criteria
- [ ] context.md has complete V.0.0.3 milestone (7 improvements, security fixes, test counts)
- [ ] `src/webhooks/CLAUDE.md` created with dispatcher, fire_event, validate_webhook_url
- [ ] All module CLAUDE.md files reflect new files and APIs
- [ ] Root CLAUDE.md includes webhooks in index
- [ ] All timestamps updated

## Dependencies
- All major work tasks (deploy, training, frontend, docs) should be done first

## Estimated Complexity
Medium — many files, established patterns.
