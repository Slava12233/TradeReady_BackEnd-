---
task_id: 16
title: "Code review: all backtest bugfix changes"
type: task
agent: "code-reviewer"
phase: 4
depends_on: [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
status: "pending"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/backtesting/engine.py"
  - "src/backtesting/sandbox.py"
  - "src/backtesting/results.py"
  - "src/api/routes/backtest.py"
  - "src/api/schemas/backtest.py"
  - "src/database/repositories/backtest_repo.py"
tags:
  - task
  - backtesting
  - quality
---

# Task 16: Code Review — All Backtest Bugfix Changes

## Assigned Agent: `code-reviewer`

## Objective
Review all changes from Tasks 02-11 for compliance with project standards, architecture rules, and conventions.

## Review Scope
- `src/backtesting/engine.py` — flush vs commit pattern, error handling
- `src/backtesting/sandbox.py` — stop_price field, frozen dataclass changes
- `src/backtesting/results.py` — by_pair persistence
- `src/api/routes/backtest.py` — validation guards, error messages, serialization
- `src/api/schemas/backtest.py` — validators, field constraints
- `src/database/repositories/backtest_repo.py` — JSONB sorting SQL

## Review Checklist
- [ ] No `db.commit()` inside engine methods (flush only)
- [ ] All new validators follow Pydantic v2 patterns
- [ ] Error messages are user-friendly and specific
- [ ] No security regressions (SQL injection in JSONB queries, etc.)
- [ ] API response shapes backwards-compatible where possible
- [ ] Existing tests not broken

## Dependencies
All development tasks (02-11) must be completed.

## Estimated Complexity
Medium — reviewing 6 files across multiple bug fixes.
