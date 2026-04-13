---
task_id: A-03
title: "Dry-run daily backfill"
type: task
agent: "backend-developer"
track: A
depends_on: ["A-02"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/backfill_history.py"]
tags:
  - task
  - data
  - backfill
---

# Task A-03: Dry-run daily backfill

## Assigned Agent: `backend-developer`

## Objective
Run the daily backfill script in dry-run mode to preview pair count, date ranges, and estimated row counts before committing to the full backfill.

## Context
Before running the potentially multi-hour backfill, we validate the script's behavior with `--dry-run` to catch any issues early.

## Files to Use
- `scripts/backfill_history.py` — supports `--daily`, `--dry-run`, `--resume`, `--exchange`

## Acceptance Criteria
- [ ] Dry-run completes without errors
- [ ] Output shows expected pair count (20 pairs)
- [ ] Output shows expected date ranges (from 2017 or earliest available)
- [ ] No database writes occurred during dry run

## Dependencies
- **A-02**: Trading pairs must be seeded in the database

## Agent Instructions
Run: `python scripts/backfill_history.py --daily --dry-run`
Review the output to confirm it lists the correct pairs and date ranges. If the script doesn't support `--symbols` filtering in dry-run mode, note that for the next task.

## Estimated Complexity
Low — validation step only.
