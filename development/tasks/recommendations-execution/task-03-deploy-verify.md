---
task_id: 3
title: "Post-deploy verification of all new endpoints"
type: task
agent: "e2e-tester"
phase: 1
depends_on: [2]
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files: []
tags:
  - task
  - deployment
  - verification
  - e2e
---

# Task 03: Post-Deploy Verification

## Assigned Agent: `e2e-tester`

## Objective
Verify all V.0.0.3 endpoints are live and working after deployment.

## Context
CI/CD deploy completed. Need to verify migration 023 applied, all new endpoints respond, and Swagger UI shows them.

## Acceptance Criteria
- [ ] `/health` returns `{"status": "ok"}`
- [ ] `alembic current` shows 023 (via Docker exec)
- [ ] `webhook_subscriptions` table exists and is queryable
- [ ] `GET /api/v1/market/indicators/available` returns indicator list
- [ ] `GET /api/v1/market/indicators/BTCUSDT` returns indicator values
- [ ] `POST /api/v1/metrics/deflated-sharpe` returns DSR result (with auth)
- [ ] `GET /api/v1/webhooks` returns empty list (with auth)
- [ ] `POST /api/v1/strategies/compare` returns validation error for empty list (with auth)
- [ ] Swagger UI at `/docs` shows all new endpoint groups

## Agent Instructions
1. Use curl commands from the plan (Section R1, Step 4)
2. Test each endpoint group
3. Report pass/fail for each

## Estimated Complexity
Low — curl commands against live endpoints.
