---
type: task-board
tags:
  - qa
  - bugfix
  - production
date: 2026-04-01
status: completed
---

# Task Board: QA Bug Fix Sprint

**Plan source:** `development/qa-bugfix-plan.md`
**Generated:** 2026-04-01
**Total tasks:** 13
**Agents involved:** backend-developer, migration-helper, doc-updater, codebase-researcher, test-runner, code-reviewer, context-manager, e2e-tester

## Task Overview

| # | Task | Agent | Sprint | Depends On | Status |
|---|------|-------|--------|------------|--------|
| 01 | Fix zero balance at registration (BUG-001) | backend-developer | 1 | — | **DONE** |
| 02 | Fix account reset DATABASE_ERROR (BUG-002) | backend-developer | 1 | Task 01 | **DONE** |
| 03 | Fix agent deletion CASCADE (BUG-004) | migration-helper | 1 | — | **DONE** |
| 04 | Update docs for correct backtest/analytics URLs (BUG-007/008/009/010) | — | 1 | — | **N/A** (docs already correct) |
| 05 | Investigate & fix battle creation (BUG-003) | backend-developer | 2 | Task 01 | **DONE** |
| 06 | Fix strategy creation ValidationError (BUG-005) | backend-developer | 2 | — | **DONE** |
| 07 | Fix win rate calculation (BUG-011) | backend-developer | 2 | — | **DONE** |
| 08 | Make tickers `symbols` param optional (BUG-012) | backend-developer | 2 | — | **DONE** |
| 09 | Fix position `opened_at` epoch zero (BUG-017) | backend-developer | 2 | — | **DONE** |
| 10 | Backfill historical candle data (BUG-006) | backend-developer | 3 | — | **DONE** (script fixed, needs prod run) |
| 11 | Fix docs & schema for candles/pairs/stop_price (BUG-013/014/015) | backend-developer | 3 | — | **DONE** |
| 12 | Improve position limit error message (BUG-016) | backend-developer | 3 | — | **DONE** |
| 13 | Full regression test + E2E validation | test-runner | 3 | Tasks 01-12 | **DONE** (1734/1734 pass) |

## Execution Order

### Sprint 1: Unblock Users (Day 1-2)
Run these first — critical path for user onboarding:
1. Task 01 (balance) + Task 03 (cascade migration) — **parallel**
2. Task 02 (account reset) — after Task 01
3. Task 04 (docs URLs) — **parallel** with everything

### Sprint 2: Restore Features (Day 3-5)
Can start after Sprint 1 completes:
4. Task 05 (battles) — needs investigation first
5. Task 06 (strategies) + Task 07 (win rate) + Task 08 (tickers) + Task 09 (opened_at) — **all parallel**

### Sprint 3: Data, Docs & Polish (Day 6-7)
6. Task 10 (backfill) + Task 11 (docs/schema) + Task 12 (error msg) — **all parallel**
7. Task 13 (full regression) — after ALL other tasks

## Post-Task Pipeline

After each code-change task:
```
code-reviewer → test-runner → context-manager
```

After API/schema changes (Tasks 08, 09, 11):
```
api-sync-checker → doc-updater → code-reviewer → test-runner → context-manager
```

## New Agents Created
None — all tasks covered by existing agents.
