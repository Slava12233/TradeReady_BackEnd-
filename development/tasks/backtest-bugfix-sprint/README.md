---
type: task-board
tags:
  - backtesting
  - bugfix
  - sprint
date: 2026-04-06
status: pending
---

# Task Board: Backtest Bugfix Sprint

**Plan source:** `development/backtest-bugfix-plan.md`
**Test report:** `development/reports/tester-report-backtesting.md`
**Generated:** 2026-04-06
**Total tasks:** 18
**Agents involved:** backend-developer (10), test-runner (4), code-reviewer (1), e2e-tester (1), context-manager (1), codebase-researcher (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status | Bugs |
|---|------|-------|-------|------------|--------|------|
| 01 | Research: verify BT-01 root cause | codebase-researcher | 1 | — | pending | BT-01 |
| 02 | Fix db.commit() in engine + orphan detection | backend-developer | 1 | 01 | pending | BT-01 |
| 03 | Fix stop-loss: add stop_price field + trigger logic | backend-developer | 1 | — | pending | BT-02, BT-17 |
| 04 | Schema validation: date range, intervals, balance cap | backend-developer | 2 | — | pending | BT-03, BT-06, BT-12 |
| 05 | Fix by_pair results: persist + serve per-pair stats | backend-developer | 2 | — | pending | BT-04 |
| 06 | Fix agent_id validation: proper error for fake agent | backend-developer | 2 | — | pending | BT-05 |
| 07 | Schema validation: pairs symbol format | backend-developer | 3 | — | pending | BT-07 |
| 08 | Fix compare: missing sessions + minimum 2 | backend-developer | 3 | — | pending | BT-08, BT-09 |
| 09 | Fix best endpoint: metric whitelist + JSONB lookup | backend-developer | 3 | — | pending | BT-10, BT-11 |
| 10 | Fix cancelled/failed session defaults | backend-developer | 4 | — | pending | BT-13, BT-14 |
| 11 | Fix step error message + agent_id fallback docs | backend-developer | 4 | — | pending | BT-15, BT-16 |
| 12 | Write unit tests: Sprint 1 fixes (BT-01, BT-02, BT-17) | test-runner | 1 | 02, 03 | pending | — |
| 13 | Write unit tests: Sprint 2 fixes (BT-03-06) | test-runner | 2 | 04, 05, 06 | pending | — |
| 14 | Write unit tests: Sprint 3 fixes (BT-07-12) | test-runner | 3 | 07, 08, 09 | pending | — |
| 15 | Write unit tests: Sprint 4 fixes (BT-13-16) | test-runner | 4 | 10, 11 | pending | — |
| 16 | Code review: all changes | code-reviewer | 4 | 02-11 | pending | — |
| 17 | E2E validation: run full backtest A-Z | e2e-tester | 4 | 12-15 | pending | — |
| 18 | Update context + CLAUDE.md files | context-manager | 4 | 16, 17 | pending | — |

## Execution Order

### Phase 1: P0 Critical (must fix first)
```
Task 01 (research BT-01) → Task 02 (fix BT-01)  ─┐
Task 03 (fix BT-02/BT-17)                         ├→ Task 12 (tests)
                                                   ─┘
```

### Phase 2: P1 High (parallel batch)
```
Task 04 (schema validation) ─┐
Task 05 (by_pair results)    ├→ Task 13 (tests)
Task 06 (agent_id error)    ─┘
```

### Phase 3: P2 Medium (parallel batch)
```
Task 07 (pairs validation)  ─┐
Task 08 (compare fixes)     ├→ Task 14 (tests)
Task 09 (best endpoint)    ─┘
```

### Phase 4: P3 Low + Quality Gate
```
Task 10 (cancelled/failed defaults)  ─┐
Task 11 (error messages)              ├→ Task 15 (tests)
                                      ─┘
Task 16 (code review) → Task 17 (E2E) → Task 18 (context)
```

## New Agents Created
None — all tasks covered by existing agents.
