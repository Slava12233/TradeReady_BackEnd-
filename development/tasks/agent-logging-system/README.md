---
type: task-board
title: Agent Logging System
created: 2026-03-21
status: pending
total_tasks: 34
plan_source: "[[agent-logging-plan]]"
tags:
  - task-board
  - agent
  - logging
  - observability
---

# Task Board: Agent Logging System

**Plan source:** `development/agent-logging-plan.md`
**Research source:** `development/agent-logging-research.md`
**Generated:** 2026-03-21
**Total tasks:** 34
**Agents involved:** `backend-developer`, `migration-helper`, `test-runner`, `code-reviewer`, `perf-checker`, `security-auditor`, `doc-updater`, `api-sync-checker`, `context-manager`

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Create centralized logging module | `backend-developer` | 1 | — | pending |
| 02 | Migrate main.py structlog config | `backend-developer` | 1 | 01 | pending |
| 03 | Migrate server.py structlog config | `backend-developer` | 1 | 01 | pending |
| 04 | Migrate strategy CLI configs | `backend-developer` | 1 | 01 | pending |
| 05 | Standardize event names across agent | `backend-developer` | 1 | 01 | pending |
| 06 | Fix Celery task logging | `backend-developer` | 1 | 01 | pending |
| 07 | Eliminate unnecessary print() statements | `backend-developer` | 1 | 01 | pending |
| 08 | Phase 1 tests | `test-runner` | 1 | 01-07 | pending |
| 09 | Create API call logging middleware | `backend-developer` | 2 | 01 | pending |
| 10 | Instrument SDK tools | `backend-developer` | 2 | 09 | pending |
| 11 | Instrument REST tools | `backend-developer` | 2 | 09 | pending |
| 12 | Instrument agent tools (direct DB) | `backend-developer` | 2 | 09 | pending |
| 13 | Add LLM call logging | `backend-developer` | 2 | 01 | pending |
| 14 | Add memory operation logging | `backend-developer` | 2 | 01 | pending |
| 15 | Phase 2 tests | `test-runner` | 2 | 09-14 | pending |
| 16 | Add trace ID propagation to SDK client | `backend-developer` | 3 | 01 | pending |
| 17 | Add trace ID propagation to REST client | `backend-developer` | 3 | 01 | pending |
| 18 | Platform-side trace ID extraction | `backend-developer` | 3 | 16 | pending |
| 19 | Create agent_api_calls DB model | `backend-developer` | 3 | — | pending |
| 20 | Create agent_strategy_signals DB model | `backend-developer` | 3 | — | pending |
| 21 | Generate Alembic migration (new tables + trace_id column) | `migration-helper` | 3 | 19, 20 | pending |
| 22 | Create repositories for new tables | `backend-developer` | 3 | 19, 20 | pending |
| 23 | Activate AuditLog writer middleware | `backend-developer` | 3 | 18 | pending |
| 24 | Create LogBatchWriter for async DB persistence | `backend-developer` | 3 | 22 | pending |
| 25 | Link trace_id in TradingLoop decisions | `backend-developer` | 3 | 21, 24 | pending |
| 26 | Phase 3 security review | `security-auditor` | 3 | 23, 24 | pending |
| 27 | Phase 3 tests | `test-runner` | 3 | 16-25 | pending |
| 28 | Create Prometheus metrics registry | `backend-developer` | 4 | 09 | pending |
| 29 | Expose agent /metrics endpoint + instrument code | `backend-developer` | 4 | 28 | pending |
| 30 | Register platform-side Prometheus metrics | `backend-developer` | 4 | — | pending |
| 31 | Create Grafana dashboards + alert rules | `backend-developer` | 4 | 28, 29 | pending |
| 32 | Build decision replay + analysis API endpoints | `backend-developer` | 5 | 21, 22, 25 | pending |
| 33 | Build analytics Celery tasks (attribution, memory, health) | `backend-developer` | 5 | 22, 25 | pending |
| 34 | Add feedback lifecycle + anomaly detection | `backend-developer` | 5 | 21, 33 | pending |

## Execution Order

### Phase 1: Logging Foundation (Tasks 01-08)
```
Task 01 (logging module) ──┬──► Task 02 (main.py)
                           ├──► Task 03 (server.py)
                           ├──► Task 04 (strategy CLIs)
                           ├──► Task 05 (event names)
                           ├──► Task 06 (celery)
                           └──► Task 07 (print cleanup)
                                        │
                    All Phase 1 ────────► Task 08 (tests)
```

### Phase 2: Agent-Side Logging (Tasks 09-15)
```
Task 09 (middleware) ──┬──► Task 10 (SDK)
                       ├──► Task 11 (REST)
                       └──► Task 12 (DB tools)
Task 01 ──────────────┬──► Task 13 (LLM logging)
                      └──► Task 14 (memory logging)
                                   │
                All Phase 2 ──────► Task 15 (tests)
```

### Phase 3: Cross-System Correlation (Tasks 16-27)
```
Task 01 ──┬──► Task 16 (SDK trace) ──► Task 18 (platform-side)
          └──► Task 17 (REST trace)           │
                                              └──► Task 23 (AuditLog)
Task 19 + 20 (models) ──► Task 21 (migration) ──► Task 25 (loop integration)
                     └──► Task 22 (repos) ──► Task 24 (batch writer) ──► Task 25
                                                       │
                                              Task 26 (security) + Task 27 (tests)
```

### Phase 4: Prometheus Metrics (Tasks 28-31)
```
Task 09 ──► Task 28 (registry) ──► Task 29 (endpoint + instrument) ──► Task 31 (dashboards)
                                   Task 30 (platform metrics) ─────────┘
```

### Phase 5: Intelligence Layer (Tasks 32-34)
```
Task 21 + 22 + 25 ──► Task 32 (decision replay API)
Task 22 + 25 ────────► Task 33 (analytics tasks) ──► Task 34 (feedback + anomaly)
```

## Parallel Execution Groups

Tasks within the same phase that have no interdependencies can run in parallel:

- **Phase 1:** Tasks 02, 03, 04, 05, 06, 07 (all depend only on 01)
- **Phase 2:** Tasks 10, 11, 12 (all depend only on 09); Tasks 13, 14 (depend only on 01)
- **Phase 3:** Tasks 16, 17 (parallel); Tasks 19, 20 (parallel); Task 23 and Task 24 (parallel after deps)
- **Phase 4:** Task 30 (independent of 28/29)
- **Phase 5:** Tasks 32, 33 (parallel after deps)

## Post-Phase Pipeline

After each phase completes:
1. `test-runner` — run all relevant tests (Tasks 08, 15, 27)
2. `code-reviewer` — review all changes
3. `perf-checker` — check for latency regressions (especially Phase 3 batch writer)
4. `context-manager` — update development/context.md
5. If API changed (Phase 5): `api-sync-checker` + `doc-updater`
6. If DB changed (Phase 3, 5): `migration-helper` validates migration
