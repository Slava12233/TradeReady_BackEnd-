---
type: task-board
tags:
  - battles
  - bugfix
  - frontend
  - backend
---

# Task Board: Fix Battle Live UI Crash

**Plan source:** `development/plans/fix-battle-live-crash.md`
**Generated:** 2026-04-07
**Total tasks:** 8
**Agents involved:** `frontend-developer`, `backend-developer`, `api-sync-checker`, `test-runner`, `code-reviewer`, `context-manager`

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Hotfix: BattleDetail remaining_minutes crash | `frontend-developer` | 1 | — | done |
| 02 | Defensive null guards in AgentPerformanceCard & BattleList | `frontend-developer` | 1 | — | done |
| 03 | Update BattleLiveResponse Pydantic schema | `backend-developer` | 2 | — | done |
| 04 | Add time fields to battle live route handler | `backend-developer` | 2 | Task 03 | done |
| 05 | Enrich get_live_snapshot() with all participant fields | `backend-developer` | 2 | Task 03 | done |
| 06 | Sync frontend types & hook field mapping | `frontend-developer` | 3 | Tasks 03-05 | done |
| 07 | Add elapsed time display in BattleDetail | `frontend-developer` | 3 | Task 06 | done |
| 08 | Run tests & validate API sync | `test-runner` | 4 | Tasks 01-07 | done |

## Execution Order

### Phase 1: Immediate Frontend Hotfixes (parallel)
Tasks 01 and 02 can run in parallel — they touch different files.

### Phase 2: Backend Enrichment (sequential)
Task 03 first (schema), then Tasks 04 and 05 in parallel (both depend on schema only).

### Phase 3: Frontend Sync (sequential)
Task 06 (type sync) → Task 07 (elapsed time display).

### Phase 4: Validation
Task 08: test-runner validates all changes.

### Post-Pipeline (mandatory)
After all tasks: `code-reviewer` → `context-manager`

## New Agents Created
None — all tasks covered by existing agents.
