---
type: task-board
title: "C-Level Report Recommendations Implementation"
source: "[[recommendations-plan]]"
created: 2026-03-23
total_tasks: 39
status: completed
tags:
  - task-board
  - recommendations
  - infrastructure
  - security
  - training
  - retraining
---

# Task Board: C-Level Report Recommendations Implementation

**Plan source:** `development/recommendations-plan.md`
**Report source:** `development/C-level_reports/report-2026-03-23.md`
**Generated:** 2026-03-23
**Total tasks:** 39 (36 implementation + 3 quality gate)
**Agents involved:** backend-developer (10), security-reviewer (7), ml-engineer (6), deploy-checker (3), test-runner (5), e2e-tester (2), migration-helper (1), code-reviewer (2), security-auditor (1), context-manager (1), perf-checker (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| R1-01 | Create `.env` from `.env.example` | backend-developer | 1 | — | completed |
| R1-02 | Start Docker Compose services | deploy-checker | 1 | R1-01 | completed |
| R1-03 | Apply Alembic migrations (head = 019) | migration-helper | 1 | R1-02 | completed |
| R1-04 | Seed exchange pairs | backend-developer | 1 | R1-03 | completed |
| R1-05 | Verify all services healthy | deploy-checker | 1 | R1-04 | completed |
| R1-06 | Import Grafana dashboards / verify Prometheus | deploy-checker | 1 | R1-05 | completed |
| R1-07 | Backfill historical candle data (12+ months) | backend-developer | 1 | R1-05 | completed |
| R1-08 | Provision 5 agent accounts | e2e-tester | 1 | R1-04 | completed |
| R1-09 | Run smoke test (10-step validation) | e2e-tester | 1 | R1-08 | completed |
| R2-01 | Add ADMIN role check to grant_capability/set_role | security-reviewer | 2 | R1-03 | completed |
| R2-02 | Track and await ensure_future in BudgetManager | security-reviewer | 2 | — | completed |
| R2-03 | Enable Redis requirepass + Docker internal bind | security-reviewer | 2 | R1-02 | completed |
| R2-04 | Persist "allow" audit events to agent_audit_log | security-reviewer | 2 | R1-03 | completed |
| R2-05 | SHA-256 checksum verification before PPO.load() | security-reviewer | 2 | — | completed |
| R2-06 | Checksum verification before joblib.load() | security-reviewer | 2 | — | completed |
| R2-07 | Audit remaining --api-key CLI arg exposure | security-reviewer | 2 | — | completed |
| R2-08 | Fix remaining float(Decimal) casts in agent | backend-developer | 2 | — | completed |
| R2-09 | Security audit of all fixes | security-auditor | 2 | R2-01..R2-08 | completed |
| R2-10 | Write regression tests for all security fixes | test-runner | 2 | R2-01..R2-08 | completed |
| R3-01 | Train regime classifier on 12mo BTC 1h data | ml-engineer | 3 | R1-07 | completed |
| R3-02 | Validate classifier accuracy >= 70% | ml-engineer | 3 | R3-01 | completed |
| R3-03 | Run regime switcher demo | ml-engineer | 3 | R3-01 | completed |
| R3-04 | Run 3-month walk-forward validation | ml-engineer | 3 | R3-01 | completed |
| R3-05 | Run backtest comparison (regime vs MACD vs B&H) | ml-engineer | 3 | R3-01 | completed |
| R3-06 | Record baseline performance metrics | ml-engineer | 3 | R3-04, R3-05 | completed |
| R4-01 | Fix float(c.close) in server_handlers.py | backend-developer | 2 | — | completed |
| R4-02 | Audit all float(Decimal) casts across agent pkg | code-reviewer | 2 | — | completed |
| R4-03 | Fix 5 MEDIUM perf issues | backend-developer | 2 | — | completed |
| R4-04 | Verify Redis glob bug fix (run tests) | test-runner | 2 | — | completed |
| R4-05 | Verify writer wiring tests pass | test-runner | 2 | — | completed |
| R5-01 | Create Celery task wrapping RetrainOrchestrator | backend-developer | 4 | R3-01 | completed |
| R5-02 | Add 4 Celery beat schedule entries | backend-developer | 4 | R5-01 | completed |
| R5-03 | Wire DriftDetector into live TradingLoop | backend-developer | 4 | R5-01 | completed |
| R5-04 | Add Prometheus metrics for retrain events | backend-developer | 4 | R5-01 | completed |
| R5-05 | Add Grafana dashboard panel for retraining | backend-developer | 4 | R5-04 | completed |
| R5-06 | Write integration tests for retrain Celery tasks | test-runner | 4 | R5-01 | completed |
| QG-01 | Full code review of all changes | code-reviewer | 5 | all | completed |
| QG-02 | Run full test suite and fix regressions | test-runner | 5 | QG-01 | completed |
| QG-03 | Update context.md and all CLAUDE.md files | context-manager | 5 | QG-02 | completed |

## Execution Order

### Phase 1: Docker Infrastructure (R1-01 to R1-09)
Sequential chain with parallel branches:
1. R1-01 (env) → R1-02 (docker up) → R1-03 (migrations) → R1-04 (seed) → R1-05 (health)
2. After R1-05: R1-06 (Grafana) + R1-07 (backfill) in parallel
3. After R1-04: R1-08 (provision agents) → R1-09 (smoke test)

### Phase 2: Security + Quality (parallel with Phase 1 where possible)
Independent tasks (start immediately):
- R2-02, R2-05, R2-06, R2-07, R2-08, R4-01, R4-02, R4-03, R4-04, R4-05

Infrastructure-dependent:
- R2-01, R2-04 (need R1-03), R2-03 (needs R1-02)

Gate tasks (after all fixes):
- R2-09 → R2-10

### Phase 3: Training Pipeline (after R1-07)
- R3-01 → {R3-02, R3-03, R3-04, R3-05} → R3-06

### Phase 4: Continuous Retraining (after R3-01)
- R5-01 → {R5-02, R5-03, R5-04, R5-06} + R5-04 → R5-05

### Phase 5: Quality Gate (after all tasks)
- QG-01 → QG-02 → QG-03

## Parallel Execution Groups

| Group | Tasks | Can Start |
|-------|-------|-----------|
| A (immediate) | R1-01, R2-02, R2-05, R2-06, R2-07, R2-08, R4-01, R4-02, R4-03, R4-04, R4-05 | Now |
| B (Docker running) | R1-03, R2-03 | After R1-02 |
| C (DB ready) | R1-04, R2-01, R2-04 | After R1-03 |
| D (platform healthy) | R1-06, R1-07, R1-08, R1-09 | After R1-05 |
| E (security fixes done) | R2-09, R2-10 | After R2-01..R2-08 |
| F (data loaded) | R3-01..R3-06 | After R1-07 |
| G (model trained) | R5-01..R5-06 | After R3-01 |
| H (all complete) | QG-01, QG-02, QG-03 | After all |

## Agent Assignment Summary

| Agent | Tasks | Count |
|-------|-------|-------|
| `backend-developer` | R1-01, R1-04, R1-07, R2-08, R4-01, R4-03, R5-01, R5-02, R5-03, R5-04, R5-05 | 11 |
| `security-reviewer` | R2-01, R2-02, R2-03, R2-04, R2-05, R2-06, R2-07 | 7 |
| `ml-engineer` | R3-01, R3-02, R3-03, R3-04, R3-05, R3-06 | 6 |
| `test-runner` | R2-10, R4-04, R4-05, R5-06, QG-02 | 5 |
| `deploy-checker` | R1-02, R1-05, R1-06 | 3 |
| `e2e-tester` | R1-08, R1-09 | 2 |
| `code-reviewer` | R4-02, QG-01 | 2 |
| `migration-helper` | R1-03 | 1 |
| `security-auditor` | R2-09 | 1 |
| `context-manager` | QG-03 | 1 |
| `perf-checker` | (R4-03 verification) | 0 |

## New Agents Created

None required. All 16 existing agents cover the needed capabilities.
