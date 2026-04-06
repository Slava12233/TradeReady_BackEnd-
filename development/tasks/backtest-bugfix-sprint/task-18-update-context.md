---
task_id: 18
title: "Update context + CLAUDE.md files"
type: task
agent: "context-manager"
phase: 4
depends_on: [16, 17]
status: "pending"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "development/context.md"
  - "src/backtesting/CLAUDE.md"
  - "src/api/routes/CLAUDE.md"
  - "src/api/schemas/CLAUDE.md"
  - "development/CLAUDE.md"
tags:
  - task
  - context
  - documentation
---

# Task 18: Update Context + CLAUDE.md Files

## Assigned Agent: `context-manager`

## Objective
Update all development tracking files to reflect the completed backtest bugfix sprint.

## Updates Required

1. **`development/context.md`** — Add milestone entry for backtest bugfix sprint (17 bugs fixed, files changed, test counts)
2. **`src/backtesting/CLAUDE.md`** — Update with new `stop_price` field, flush-not-commit pattern, by_pair persistence
3. **`src/api/routes/CLAUDE.md`** — Note new validation guards in backtest routes
4. **`src/api/schemas/CLAUDE.md`** — Note new validators (date range, intervals, pairs, balance cap)
5. **`development/CLAUDE.md`** — Add `backtest-bugfix-sprint/` to task boards listing
6. **Daily note** — Append to today's daily note

## Acceptance Criteria
- [ ] context.md updated with sprint summary
- [ ] All affected CLAUDE.md files reflect the changes
- [ ] Daily note has entry
- [ ] Task board README updated to show completed status

## Dependencies
Code review and E2E validation must pass first.

## Estimated Complexity
Low — documentation updates only.
