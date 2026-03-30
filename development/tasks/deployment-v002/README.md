---
type: task-board
title: "Deployment V.0.0.2 to Production"
tags:
  - deployment
  - v0.0.2
  - production
---

# Task Board: Deployment V.0.0.2 to Production

**Plan source:** `development/deployment-plan-v002.md`
**Generated:** 2026-03-30
**Total tasks:** 16
**Agents involved:** deploy-checker, backend-developer, test-runner, code-reviewer, migration-helper, security-auditor, e2e-tester, context-manager

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Fix ruff lint errors (auto-fix + manual line-length) | `backend-developer` | 1 | — | completed |
| 02 | Fix ruff format (69 files) | `backend-developer` | 1 | — | completed |
| 03 | Run mypy type check and fix errors | `backend-developer` | 1 | — | pending |
| 04 | Run unit tests and fix failures | `test-runner` | 1 | 01, 02, 03 | pending |
| 05 | CI/CD pipeline fixes (test.yml + deploy.yml) | `backend-developer` | 2 | — | completed |
| 06 | CORS env-driven configuration | `backend-developer` | 3 | — | completed |
| 07 | Verify migration chain integrity (017→020) | `migration-helper` | 4 | — | pending |
| 08 | Verify migration safety (no destructive ops) | `migration-helper` | 4 | 07 | pending |
| 09 | Security audit of deployment changes | `security-auditor` | 5 | 06 | pending |
| 10 | Code review all deployment changes | `code-reviewer` | 5 | 01, 02, 05, 06 | pending |
| 11 | Run full unit test suite | `test-runner` | 6 | 03, 04 | pending |
| 12 | Pre-deploy checklist validation | `deploy-checker` | 7 | 07, 08, 09, 10, 11 | pending |
| 13 | Commit and push all fixes to main | `backend-developer` | 8 | 12 | pending |
| 14 | Server-side deploy execution | `deploy-checker` | 9 | 13 | pending |
| 15 | Post-deployment validation (health, prices, E2E) | `e2e-tester` | 10 | 14 | pending |
| 16 | Update context.md and CLAUDE.md files | `context-manager` | 11 | 15 | pending |

## Execution Order

### Phase 1: Code Quality Fixes (Tasks 01-04)
Fix all lint, format, type, and test failures so CI passes.
- Tasks 01, 02 → DONE (ruff check --fix, ruff format)
- Task 03 → mypy (sequential after lint fixes)
- Task 04 → pytest (after all code fixes)

### Phase 2-3: Code Changes (Tasks 05-06) — DONE
CI/CD pipeline fixes and CORS configuration already applied.

### Phase 4: Migration Validation (Tasks 07-08)
Verify migration chain and safety — can run in parallel.

### Phase 5: Review & Audit (Tasks 09-10)
Security audit + code review of all changes — can run in parallel.

### Phase 6: Full Test Suite (Task 11)
Run all unit tests to confirm zero failures.

### Phase 7: Pre-Deploy Gate (Task 12)
Deploy-checker validates everything is ready.

### Phase 8: Push (Task 13)
Commit remaining fixes and push to main.

### Phase 9: Deploy (Task 14)
Execute deployment on server.

### Phase 10: Validate (Task 15)
E2E validation of the live deployment.

### Phase 11: Context Update (Task 16)
Final context and documentation sync.

## New Agents Created
None — all 16 existing agents cover the required capabilities.
