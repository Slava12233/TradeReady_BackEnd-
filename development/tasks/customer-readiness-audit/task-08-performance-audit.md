---
task_id: 08
title: "Performance Audit — Backend & Frontend"
type: task
agent: "perf-checker"
phase: 1
depends_on: []
status: "pending"
priority: "medium"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/08-performance-audit.md"
tags:
  - task
  - audit
  - performance
  - backend
  - frontend
---

# Task 08: Performance Audit — Backend & Frontend

## Assigned Agent: `perf-checker`

## Objective
Check for performance issues that could degrade user experience under normal load. Focus on: N+1 queries, blocking async calls, missing indexes, unbounded growth patterns, React render issues, and bundle size.

## Context
Performance optimizations already applied (2026-03-20):
- PriceFlashCell memo, 4 header islands, 8 lazy sections
- GET dedup in api-client, 3x exponential retry
- requestAnimationFrame for PriceBatchBuffer
- useDailyCandlesBatch (600→12 queries)

Additional perf fixes (2026-03-20):
- asyncio.gather for parallel operations
- run_in_executor for blocking ML ops
- deque(maxlen=500) for bounded histories
- Regime feature caching

Known from 2026-03-22 perf audit: 2 HIGH, 3 MEDIUM identified.

## Areas to Check

### Backend Hot Paths
1. **`GET /market/prices`** — Called frequently, must be sub-100ms
2. **`POST /trade/order`** — Order execution path (engine → risk → balance → DB)
3. **`GET /account/positions`** — Portfolio display
4. **`GET /market/candles/{symbol}`** — Chart data
5. **Price ingestion pipeline** — Binance WS → Redis → DB

### Database Performance
6. Check for missing indexes on frequently queried columns
7. Check for N+1 query patterns in route handlers
8. Check TimescaleDB continuous aggregate refresh policies

### Frontend Performance
9. **Bundle size** — Check `next build` output for large chunks
10. **React renders** — Any components missing memo/useMemo where needed
11. **Network requests** — Excessive API calls on page load
12. **WebSocket efficiency** — Price update batching

### Scalability Concerns
13. What happens with 10 concurrent users?
14. What happens with 100 agents on one account?
15. What happens with 10,000 orders in history?

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/08-performance-audit.md`:

```markdown
# Sub-Report 08: Performance Audit

**Date:** 2026-04-15
**Agent:** perf-checker
**Overall Status:** PASS / PARTIAL / FAIL

## Backend Performance

| Hot Path | Issue Found | Severity | Fix Effort |
|----------|-----------|----------|------------|
| GET /market/prices | Y/N | — | — |
| POST /trade/order | Y/N | — | — |
| ... | ... | ... | ... |

## Database Performance

| Check | Status | Details |
|-------|--------|---------|
| Missing indexes | PASS/FAIL | |
| N+1 queries | PASS/FAIL | |
| Aggregates | PASS/FAIL | |

## Frontend Performance

| Check | Status | Details |
|-------|--------|---------|
| Bundle size | Xkb | |
| Render efficiency | PASS/FAIL | |
| Network calls | X on load | |

## Scalability Assessment

| Scenario | Expected | Concern Level |
|----------|----------|---------------|
| 10 users | OK/RISK | LOW/MED/HIGH |
| 100 agents | OK/RISK | LOW/MED/HIGH |
| 10K orders | OK/RISK | LOW/MED/HIGH |

## Findings

### HIGH
| # | File | Issue | Impact | Fix |
|---|------|-------|--------|-----|

### MEDIUM
| # | File | Issue | Impact | Fix |
|---|------|-------|--------|-----|

## Recommendations
```

## Acceptance Criteria
- [ ] 5 backend hot paths reviewed
- [ ] Database indexes and query patterns checked
- [ ] Frontend bundle and render efficiency assessed
- [ ] Scalability scenarios evaluated
- [ ] Findings categorized by severity

## Estimated Complexity
Medium — read-only code analysis
