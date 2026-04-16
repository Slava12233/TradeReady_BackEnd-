---
task_id: 09
title: "Verify API health endpoint"
type: task
agent: "deploy-checker"
phase: 2
depends_on: [7]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - smoke-test
  - api
---

# Task 09: Verify API health endpoint

## Objective
Confirm the production API is healthy and reachable externally.

## Acceptance Criteria
- [ ] `curl https://api.tradeready.io/health` returns 200 OK
- [ ] Response JSON: `status` is `"ok"` or `"degraded"` (NOT `"unhealthy"`)
- [ ] `redis_connected: true`
- [ ] `db_connected: true`
- [ ] `ingestion_active: true`
- [ ] Latency: `checks.redis_latency_ms < 10`, `checks.db_latency_ms < 20`
- [ ] Total pairs: `total_pairs > 400` (expected ~448 live Binance pairs)
- [ ] TLS cert valid (no cert warnings)

## Dependencies
Task 07 — API container must be running.

## Agent Instructions
1. Run: `curl -s https://api.tradeready.io/health | jq .`
2. Verify all fields in acceptance criteria
3. If `status: "degraded"`: acceptable if stale pairs ratio < 30% (check `stale_pairs.length / total_pairs`)
4. If `status: "unhealthy"`: block deployment — inspect logs with `docker compose logs api`
5. Verify HTTPS cert: `curl -vI https://api.tradeready.io/health 2>&1 | grep "SSL certificate"`

## Estimated Complexity
Low — smoke test
