# Task Board: Frontend Performance Fixes

**Plan source:** `development/code-reviews/frontend-performance-review.md`
**Generated:** 2026-03-20
**Total tasks:** 23
**Agents involved:** frontend-developer (18), perf-checker (1), test-runner (2), code-reviewer (1), context-manager (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 1 | Add React.memo to PriceFlashCell | frontend-developer | 1 | — | pending |
| 2 | Code-split Three.js DottedSurface | frontend-developer | 1 | — | pending |
| 3 | Add missing /battles loading.tsx | frontend-developer | 1 | — | pending |
| 4 | Add useShallow to portfolio selector | frontend-developer | 1 | — | pending |
| 5 | Memoize chart context provider value | frontend-developer | 1 | — | pending |
| 6 | Install bundle analyzer | frontend-developer | 1 | — | pending |
| 7 | Restructure dashboard layout (islands) | frontend-developer | 2 | — | pending |
| 8 | Code-split dashboard components | frontend-developer | 2 | Task 6 | pending |
| 9 | Add API client request deduplication | frontend-developer | 2 | — | pending |
| 10 | Reduce coin page polling frequency | frontend-developer | 2 | — | pending |
| 11 | Batch useDailyCandlesBatch (50/group) | frontend-developer | 2 | — | pending |
| 12 | Extract landing CSS from globals | frontend-developer | 2 | — | pending |
| 13 | Add Suspense boundaries to layout | frontend-developer | 2 | Task 7 | pending |
| 14 | Add error boundaries to dashboard | frontend-developer | 3 | Task 8 | pending |
| 15 | Add route prefetching on link hover | frontend-developer | 3 | Task 9 | pending |
| 16 | Switch WS flush to rAF | frontend-developer | 3 | — | pending |
| 17 | Lazy-load tsparticles Sparkles | frontend-developer | 3 | — | pending |
| 18 | Add keepPreviousData to paginated hooks | frontend-developer | 3 | — | pending |
| 19 | Performance validation (Phase 1) | perf-checker | 1 | Tasks 1-6 | pending |
| 20 | Run tests (Phase 1) | test-runner | 1 | Tasks 1-6 | pending |
| 21 | Run tests (Phase 2) | test-runner | 2 | Tasks 7-13 | pending |
| 22 | Code review all changes | code-reviewer | 3 | Tasks 20, 21 | pending |
| 23 | Update context and CLAUDE.md files | context-manager | 3 | Task 22 | pending |

## Execution Order

### Phase 1: Quick Wins (1-2 days)

All Phase 1 tasks are independent — run in parallel:
```
Tasks 1, 2, 3, 4, 5, 6  (all parallel, no dependencies)
    ↓
Task 19 (perf-checker validates Phase 1)
    ↓
Task 20 (test-runner verifies Phase 1)
```

### Phase 2: Architecture Fixes (3-5 days)

Most Phase 2 tasks are independent, with two chains:
```
Parallel group A:  Tasks 9, 10, 11, 12  (independent)
Parallel group B:  Task 7 → Task 13     (layout → suspense boundaries)
Parallel group C:  Task 6 → Task 8      (analyzer → code-split dashboard)
    ↓
Task 21 (test-runner verifies Phase 2)
```

### Phase 3: Polish & Validation (ongoing)

```
Parallel:  Tasks 14, 15, 16, 17, 18  (all independent)
    ↓
Task 22 (code-reviewer reviews everything)
    ↓
Task 23 (context-manager updates docs)
```

## Agent Assignment Summary

| Agent | Tasks | Count |
|-------|-------|-------|
| `frontend-developer` | 1-18 | 18 |
| `perf-checker` | 19 | 1 |
| `test-runner` | 20, 21 | 2 |
| `code-reviewer` | 22 | 1 |
| `context-manager` | 23 | 1 |

## New Agents Created

None — all tasks are covered by existing agents.
