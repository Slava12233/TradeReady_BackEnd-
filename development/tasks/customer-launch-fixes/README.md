---
type: task-board
title: "Customer Launch Fixes"
tags:
  - customer-readiness
  - launch
  - fixes
---

# Task Board: Customer Launch Fixes

**Plan source:** `development/tasks/customer-readiness-audit/CUSTOMER-READINESS-REPORT.md`
**Generated:** 2026-04-15
**Total tasks:** 37
**Agents involved:** backend-developer, frontend-developer, planner, deploy-checker, security-auditor, perf-checker, test-runner, doc-updater, context-manager

## Task Overview

| # | Task | Agent | Priority | Phase | Depends On | Status |
|---|------|-------|----------|-------|------------|--------|
| 01 | Fix JWT agent scope bypass | backend-developer | P0 | 1 | — | completed |
| 02 | Create Terms of Service page | planner + frontend-developer | P0 | 1 | — | completed |
| 03 | Create Privacy Policy page | planner + frontend-developer | P0 | 1 | — | completed |
| 04 | Add support/contact channel | frontend-developer | P0 | 1 | — | completed |
| 05 | Set up Alertmanager pipeline | deploy-checker | P0 | 1 | — | completed |
| 06 | Automate database backups | backend-developer | P0 | 1 | — | completed |
| 07 | Fix dashboard search bar | frontend-developer | P0 | 1 | — | completed |
| 08 | Rate-limit auth endpoints | backend-developer | P1 | 2 | 01 | completed |
| 09 | Unify branding to TradeReady | frontend-developer | P1 | 2 | — | completed |
| 10 | Route root URL to product | frontend-developer | P1 | 2 | 09 | completed |
| 11 | Document display_name field | doc-updater | P1 | 2 | — | completed |
| 12 | Implement password reset flow | backend-developer + frontend-developer | P1 | 2 | — | completed |
| 13 | Fix PnL endpoint period filter | backend-developer | P1 | 2 | — | completed |
| 14 | Fix price staleness fail-open | backend-developer | P1 | 2 | — | completed |
| 15 | Cache symbol validation | perf-checker + backend-developer | P1 | 2 | — | completed |
| 16 | Add password max_length validation | backend-developer | P1 | 2 | — | completed |
| 17 | Scope WebSocket channels to agents | backend-developer | P1 | 2 | — | completed |
| 18 | Optimize PnL endpoint SQL | backend-developer | P1 | 2 | 13 | completed |
| 19 | Add /landing to sitemap.ts | frontend-developer | P1 | 2 | — | completed |
| 20 | Implement leaderboard ROI | backend-developer + frontend-developer | P1 | 2 | — | completed |
| 21 | Publish SDK to PyPI | backend-developer | P1 | 2 | — | completed |
| 22 | Fix quickstart docs placeholder URLs | doc-updater | P1 | 2 | — | completed |
| 23 | Fix api-client test unhandled rejections | test-runner | P2 | 3 | — | completed |
| 24 | Fix account reset silent exception swallow | backend-developer | P2 | 3 | — | completed |
| 25 | Fix cancel-all-orders TOCTOU | backend-developer | P2 | 3 | — | completed |
| 26 | Pipeline rate limiter Redis calls | perf-checker | P2 | 3 | — | completed |
| 27 | Fix cache._redis private access | backend-developer | P2 | 3 | — | completed |
| 28 | Migrate stdlib logging to structlog | backend-developer | P2 | 3 | — | completed |
| 29 | Add Celery worker health check | deploy-checker | P2 | 3 | — | completed |
| 30 | Fix deploy.yml rollback hardcode | deploy-checker | P2 | 3 | — | completed |
| 31 | Secure pgAdmin default password | deploy-checker | P2 | 3 | — | completed |
| 32 | Add weak credential startup assertion | backend-developer | P2 | 3 | — | completed |
| 33 | Fix 27 integration test failures | test-runner | P2 | 3 | — | completed |
| 34 | Add OG image for social sharing | frontend-developer | P2 | 3 | — | completed |
| 35 | Add email verification at registration | backend-developer + frontend-developer | P2 | 3 | — | completed |
| 36 | Document synthetic order book | doc-updater | P2 | 3 | — | completed |
| 37 | Add platform infrastructure Grafana dashboard | deploy-checker | P2 | 3 | — | completed |

## Execution Order

### Phase 1: P0 Critical Blockers (MUST fix before ANY customer)
Run these tasks in parallel (no dependencies between them):
- Tasks 01, 02, 03, 04, 05, 06, 07 — all independent

### Phase 2: P1 High Priority (fix before marketing push)
Can start after Phase 1 completes:
- Independent: 09, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22
- Sequential: 09 → 10 (branding before root route), 01 → 08 (JWT fix before rate limiting), 13 → 18 (PnL fix before PnL optimization)

### Phase 3: P2 Medium Priority (fix within 2 weeks of launch)
Can start after Phase 2 completes:
- All tasks 23-37 are independent and can run in parallel

## New Agents Created
None — all tasks covered by existing agents.
