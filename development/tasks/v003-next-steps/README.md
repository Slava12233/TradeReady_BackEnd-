---
type: task-board
tags:
  - v0.0.3
  - next-steps
  - security
  - frontend
date: 2026-04-08
status: in-progress
---

# Task Board: V.0.0.3 Next Steps

**Plan source:** `development/v0.0.3-next-steps.md`
**Generated:** 2026-04-08
**Total tasks:** 13
**Agents involved:** backend-developer (4), test-runner (2), security-auditor (1), frontend-developer (4), e2e-tester (1), context-manager (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 1 | SSRF protection on webhook URLs | backend-developer | 1 | — | pending |
| 2 | Bound returns array on DSR endpoint | backend-developer | 1 | — | pending |
| 3 | Remove webhook secret from Celery args | backend-developer | 1 | — | pending |
| 4 | Medium/Low security fixes (5 items) | backend-developer | 1 | Tasks 1, 3 | pending |
| 5 | Tests for all security fixes | test-runner | 1 | Tasks 1-4 | pending |
| 6 | Security re-audit (verify fixes) | security-auditor | 1 | Tasks 1-5 | pending |
| 7 | Full test suite + lint + type check | test-runner | 2 | Task 5 | pending |
| 8 | Webhook management UI | frontend-developer | 3 | Task 6 | pending |
| 9 | Indicators dashboard widget | frontend-developer | 3 | Task 6 | pending |
| 10 | Strategy comparison view | frontend-developer | 3 | Task 6 | pending |
| 11 | Batch backtest progress UI | frontend-developer | 3 | Task 6 | pending |
| 12 | Performance benchmarks | e2e-tester | 3 | Task 7 | pending |
| 13 | Context + CLAUDE.md sync | context-manager | 3 | Task 6 | pending |

## Execution Order

### Phase 1: Security Fixes (MUST-DO before production deploy)

**Group 1A** (no dependencies — start in parallel):
- Task 1: SSRF protection → `backend-developer`
- Task 2: Bound returns → `backend-developer`
- Task 3: Remove secret from Celery → `backend-developer`

**Group 1B** (after Tasks 1 + 3 — avoids file conflicts):
- Task 4: Medium/Low fixes → `backend-developer`

**Group 1C** (after all code fixes):
- Task 5: Security fix tests → `test-runner`

**Group 1D** (after tests pass):
- Task 6: Security re-audit → `security-auditor`

### Phase 2: Validation

- Task 7: Full test suite → `test-runner` (after Task 5)

### Phase 3: Frontend + Perf + Docs (can parallelize after Phase 1)

**Frontend** (all independent, run in parallel):
- Task 8: Webhook UI → `frontend-developer`
- Task 9: Indicators widget → `frontend-developer`
- Task 10: Strategy compare view → `frontend-developer`
- Task 11: Batch progress UI → `frontend-developer`

**Perf + Docs** (parallel with frontend):
- Task 12: Benchmarks → `e2e-tester`
- Task 13: Context/docs sync → `context-manager`

## Agent Summary

| Agent | Tasks | Count |
|-------|-------|-------|
| `backend-developer` | 1, 2, 3, 4 | 4 |
| `test-runner` | 5, 7 | 2 |
| `security-auditor` | 6 | 1 |
| `frontend-developer` | 8, 9, 10, 11 | 4 |
| `e2e-tester` | 12 | 1 |
| `context-manager` | 13 | 1 |

## New Agents Created
None — all tasks covered by existing agents.

## Production Deploy Gate

**All of Phase 1 (Tasks 1-6) + Phase 2 (Task 7) must PASS before deploying V.0.0.3 to production.**

After security re-audit passes:
1. Apply migration 023: `alembic upgrade head`
2. Deploy backend
3. Phase 3 tasks can follow incrementally
