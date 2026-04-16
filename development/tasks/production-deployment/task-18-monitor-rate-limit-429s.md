---
task_id: 18
title: "Monitor auth rate-limiting 429s"
type: task
agent: "deploy-checker"
phase: 3
depends_on: [7]
status: "pending"
priority: "medium"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - monitoring
  - security
  - post-deploy
---

# Task 18: Monitor auth rate-limiting 429s

## Objective
Watch production logs for auth endpoint 429 responses. Expected: some 429s from brute-force attempts or aggressive clients; concerning: legitimate users getting rate-limited.

## Context
Task 08 (customer launch fixes) wired up IP-based auth rate limiting: login 5/min, register 3/min per IP.

## Acceptance Criteria
- [ ] Auth 429 logs appear in structured logs: `rate_limit.auth_exceeded`
- [ ] 429s are from scanning IPs or abusive clients, NOT from legitimate users
- [ ] If a legitimate user reports being locked out: investigate and consider adjusting limits
- [ ] No false positives from shared IPs (corporate NAT, mobile carrier NAT)
- [ ] Prometheus metric `platform_api_errors_total{status="429"}` is visible

## Dependencies
Task 07 — API must be running.

## Agent Instructions
1. Tail API logs filtering for auth rate-limiting:
   ```bash
   docker compose logs -f api | grep -E 'rate_limit\.auth_exceeded|/auth/'
   ```
2. Over first 24 hours, note:
   - Count of 429s per hour
   - Which endpoints (`auth_login` vs `auth_register`)
   - Distribution of client IPs
3. If any support ticket mentions "I can't login" or "429 error":
   - Check if their IP hit the limit
   - Verify it wasn't a brute-force attempt
   - Consider raising limit if legitimate (e.g., shared corporate IP)
4. Add a Prometheus query to the Grafana dashboard:
   - `rate(platform_api_errors_total{endpoint=~"/api/v1/auth/.*",status="429"}[5m])`

## Estimated Complexity
Low — log review over time
