---
task_id: 15
title: "Post-deployment validation"
type: task
agent: "e2e-tester"
phase: 10
depends_on: [14]
status: "pending"
priority: "high"
board: "[[deployment-v002/README]]"
files: []
tags:
  - task
  - e2e
  - validation
  - deployment
---

# Task 15: Post-deployment validation

## Assigned Agent: `e2e-tester`

## Objective
Validate the live deployment works end-to-end: API, prices, database, Celery, monitoring, and agent connectivity from outside.

## Acceptance Criteria
- [ ] `curl /health` returns 200 with `"status": "ok"`
- [ ] Swagger docs load at `/docs`
- [ ] Redis `HLEN prices` > 0 (price ingestion flowing)
- [ ] `SELECT COUNT(*) FROM trading_pairs` returns 600+
- [ ] Celery worker responds to `inspect ping`
- [ ] Celery beat PID file exists
- [ ] `alembic current` shows 020
- [ ] Prometheus scraping API target (status: "up")
- [ ] Grafana login works, 7 dashboards provisioned
- [ ] 11 alert rules loaded in Prometheus
- [ ] Agent can connect from outside via `http://<server-ip>:8000`
- [ ] CORS allows requests from the frontend domain

## Agent Instructions
1. Follow `development/deployment-plan-v002.md` Phase 8 (Post-Deployment Validation) step by step
2. Follow Phase 9 (Monitoring Setup Verification) step by step
3. Test external agent connectivity by hitting `/health` and `/api/v1/market/prices` from outside Docker
4. Report pass/fail for each check

## Estimated Complexity
Medium — many checks but all are straightforward
