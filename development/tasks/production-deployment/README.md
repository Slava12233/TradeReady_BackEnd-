---
type: task-board
title: "Production Deployment"
tags:
  - deployment
  - production
  - launch
---

# Task Board: Production Deployment

**Plan source:** `development/tasks/customer-launch-fixes/PRODUCTION-READINESS-REPORT.md`
**Generated:** 2026-04-17
**Total tasks:** 18
**Agents involved:** deploy-checker, migration-helper, backend-developer, e2e-tester, context-manager

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Pull latest code from main | deploy-checker | 1 | — | pending |
| 02 | Apply migration 024 (email_verified) | migration-helper | 1 | 01 | pending |
| 03 | Set ENVIRONMENT=production in .env | deploy-checker | 1 | 01 | pending |
| 04 | Verify JWT_SECRET strength | deploy-checker | 1 | 03 | pending |
| 05 | Verify DATABASE_URL production credentials | deploy-checker | 1 | 03 | pending |
| 06 | Configure Alertmanager SMTP credentials | deploy-checker | 1 | 01 | pending |
| 07 | Start all services (docker compose up) | deploy-checker | 2 | 02,04,05,06 | pending |
| 08 | Verify Alertmanager UI reachable | deploy-checker | 2 | 07 | pending |
| 09 | Verify API health endpoint | deploy-checker | 2 | 07 | pending |
| 10 | Verify root URL serves landing page | e2e-tester | 2 | 07 | pending |
| 11 | Verify legal pages load (/terms, /privacy, /contact) | e2e-tester | 2 | 07 | pending |
| 12 | Test registration with optional display_name | e2e-tester | 2 | 07 | pending |
| 13 | Test Cmd+K search on dashboard | e2e-tester | 2 | 07 | pending |
| 14 | Verify OG image meta tags | deploy-checker | 2 | 07 | pending |
| 15 | Monitor Alertmanager 24h baseline | deploy-checker | 3 | 08 | pending |
| 16 | Verify first backup ran (2AM UTC) | deploy-checker | 3 | 07 | pending |
| 17 | Review Grafana infrastructure dashboard | deploy-checker | 3 | 07 | pending |
| 18 | Monitor auth rate-limiting 429s | deploy-checker | 3 | 07 | pending |

## Execution Order

### Phase 1: Pre-Deploy Configuration (on the server)
Sequential setup before services start:
1. Task 01 — Pull code
2. Tasks 02-06 — Migration, env vars, SMTP credentials (can run in parallel after Task 01)

### Phase 2: Deploy & Smoke Tests
Bring up services and validate basic functionality:
- Task 07 — `docker compose up -d`
- Tasks 08-14 — Parallel smoke tests (Alertmanager UI, API health, pages, registration, search, OG tags)

### Phase 3: Post-Deploy Monitoring (first 24 hours)
Verify operational health:
- Task 15 — Alertmanager tuning
- Task 16 — Backup verification
- Task 17 — Grafana review
- Task 18 — Rate-limit log review

## New Agents Created
None — all tasks covered by existing agents (deploy-checker, migration-helper, e2e-tester).
