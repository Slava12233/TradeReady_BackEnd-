---
task_id: 13
title: "Update context.md + module CLAUDE.md files + root CLAUDE.md"
type: task
agent: "context-manager"
phase: 3
depends_on: [6]
status: "pending"
priority: "medium"
board: "[[v003-next-steps/README]]"
files:
  - "development/context.md"
  - "src/backtesting/CLAUDE.md"
  - "src/metrics/CLAUDE.md"
  - "src/api/routes/CLAUDE.md"
  - "src/api/schemas/CLAUDE.md"
  - "src/webhooks/CLAUDE.md"
  - "src/tasks/CLAUDE.md"
  - "tests/unit/CLAUDE.md"
  - "tests/integration/CLAUDE.md"
  - "CLAUDE.md"
tags:
  - task
  - documentation
  - context
  - claude-md
---

# Task 13: Update context.md + module CLAUDE.md files

## Assigned Agent: `context-manager`

## Objective
Add V.0.0.3 milestone to context.md and sync all affected module CLAUDE.md files with the new code.

## Context
V.0.0.3 added 7 improvements, 30+ new files, 397+ tests, and a new `src/webhooks/` package. All CLAUDE.md files for affected modules need updating.

## Files to Modify/Create
- `development/context.md` — Add V.0.0.3 milestone entry
- `src/backtesting/CLAUDE.md` — Add `step_batch_fast()`, `BatchStepResult`, `fee_rate` config
- `src/metrics/CLAUDE.md` — Add `deflated_sharpe.py`
- `src/api/routes/CLAUDE.md` — Add 10+ new endpoints
- `src/api/schemas/CLAUDE.md` — Add 6 new schema files
- `src/webhooks/CLAUDE.md` — CREATE new CLAUDE.md for new package
- `src/tasks/CLAUDE.md` — Add `webhook_tasks.py`
- `tests/unit/CLAUDE.md` — Add 6 new test files
- `tests/integration/CLAUDE.md` — Add 4 new test files
- `CLAUDE.md` — Add `src/webhooks/CLAUDE.md` to module index table

## Acceptance Criteria
- [ ] `development/context.md` has V.0.0.3 milestone with all 7 improvements listed
- [ ] All module CLAUDE.md files reflect new files and APIs
- [ ] `src/webhooks/CLAUDE.md` created with package overview
- [ ] Root CLAUDE.md index includes `src/webhooks/CLAUDE.md`
- [ ] `<!-- last-updated -->` timestamps updated

## Dependencies
- **Task 6** (security fixes verified) — ensures we document the final state

## Agent Instructions
1. Read each CLAUDE.md file before updating
2. Add file inventories, new endpoints, test counts
3. Follow existing CLAUDE.md format exactly
4. The V.0.0.3 context.md entry should cover: 7 improvements, 64 files changed, 14K+ lines, 397+ new tests, security audit CONDITIONAL PASS → PASS after fixes

## Estimated Complexity
Medium — many files to update, but following established patterns.
