---
type: task-board
tags:
  - platform
  - strategy
  - endgame
  - infrastructure
date: 2026-04-07
status: in-progress
---

# Task Board: Platform Endgame Readiness

**Plan source:** `development/platform-endgame-readiness-plan.md`
**Generated:** 2026-04-08
**Total tasks:** 22
**Agents involved:** backend-developer (11), test-runner (5), ml-engineer (1), migration-helper (1), doc-updater (1), security-auditor (1), context-manager (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 1 | Implement step_batch_fast() engine + API | backend-developer | 1 | — | pending |
| 2 | Batch step SDK + gym batch_size param | backend-developer | 1 | Task 1 | pending |
| 3 | Tests: batch step fast (unit + integration) | test-runner | 1 | Tasks 1, 2 | pending |
| 4 | Deflated Sharpe Ratio service + API | backend-developer | 1 | — | pending |
| 5 | Auto-compute DSR on test completion + SDK | backend-developer | 1 | Task 4 | pending |
| 6 | Tests: Deflated Sharpe (unit + integration) | test-runner | 1 | Tasks 4, 5 | pending |
| 7 | Market Data Indicators API endpoints | backend-developer | 1 | — | pending |
| 8 | Indicators SDK methods | backend-developer | 1 | Task 7 | pending |
| 9 | Tests: Indicators API (unit + integration) | test-runner | 1 | Tasks 7, 8 | pending |
| 10 | Strategy Comparison API + service + SDK | backend-developer | 2 | Task 4 | pending |
| 11 | Tests: Strategy Comparison | test-runner | 2 | Task 10 | pending |
| 12 | Configurable fee_rate + custom portfolio env | backend-developer | 2 | — | pending |
| 13 | Headless Gymnasium environment | ml-engineer | 2 | Task 1 | pending |
| 14 | Tests: enhanced gym environments | test-runner | 2 | Tasks 12, 13 | pending |
| 15 | WebhookSubscription DB model + migration | backend-developer | 2 | — | pending |
| 16 | Webhook dispatcher + Celery task (HMAC) | backend-developer | 2 | Task 15 | pending |
| 17 | Webhook REST endpoints + SDK + wire triggers | backend-developer | 2 | Tasks 15, 16 | pending |
| 18 | Tests: webhook system (unit + integration) | test-runner | 2 | Tasks 15, 16, 17 | pending |
| 19 | Validate webhook migration safety | migration-helper | 2 | Task 15 | pending |
| 20 | SDK example scripts (5 examples) | backend-developer | 3 | Tasks 1, 4, 7, 10, 17 | pending |
| 21 | Update SDK README with examples | doc-updater | 3 | Task 20 | pending |
| 22 | Final security audit | security-auditor | 3 | Tasks 1, 4, 7, 10, 15-17 | pending |

## Execution Order

### Phase 1: Core Agent Infrastructure (Week 1-2)

Three independent improvement tracks — run in parallel:

**Track A: Batch Backtesting**
1. Task 1 → Task 2 → Task 3

**Track B: Deflated Sharpe**
4. Task 4 → Task 5 → Task 6

**Track C: Indicators API**
7. Task 7 → Task 8 → Task 9

### Phase 2: Platform Experience (Week 3-4)

Can start after relevant Phase 1 tasks complete:

**Track D: Strategy Compare** (after Task 4)
10. Task 10 → Task 11

**Track E: Gym Enhancements** (after Task 1 for headless; fee config is independent)
12. Task 12 ─┐
13. Task 13 ─┤→ Task 14
             │
**Track F: Webhooks** (independent)
15. Task 15 → Task 16 → Task 17 → Task 18
         └→ Task 19 (parallel with 16-17)

### Phase 3: Documentation & Security (Week 5)

After all implementation complete:
20. Task 20 → Task 21
22. Task 22 (parallel with 20-21)

## Agent Summary

| Agent | Tasks | Description |
|-------|-------|-------------|
| `backend-developer` | 1, 2, 4, 5, 7, 8, 10, 12, 15, 16, 17, 20 | All backend implementation (12 tasks) |
| `test-runner` | 3, 6, 9, 11, 14, 18 | All test writing (6 tasks) |
| `ml-engineer` | 13 | Headless gym environment (1 task) |
| `migration-helper` | 19 | Migration validation (1 task) |
| `doc-updater` | 21 | SDK docs update (1 task) |
| `security-auditor` | 22 | Final security audit (1 task) |

## New Agents Created
None — all tasks are covered by existing agents.

## Post-Task Pipeline

After **each implementation task** completes, run the standard pipeline:
1. `code-reviewer` — validates changes against standards
2. `test-runner` — runs relevant tests
3. `context-manager` — logs changes to `development/context.md`

Additional pipelines as needed:
- API/schema changes → `api-sync-checker` + `doc-updater` first
- DB migration → `migration-helper` validates before apply
- Security-sensitive (webhooks) → `security-auditor` after
