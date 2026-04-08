---
task_id: 22
title: "Final security audit of all new endpoints and webhook system"
type: task
agent: "security-auditor"
phase: 3
depends_on: [1, 4, 7, 10, 15, 16, 17]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/api/routes/metrics.py"
  - "src/api/routes/indicators.py"
  - "src/api/routes/webhooks.py"
  - "src/api/routes/backtest.py"
  - "src/api/routes/strategies.py"
  - "src/webhooks/dispatcher.py"
  - "src/tasks/webhook_tasks.py"
tags:
  - task
  - security
  - audit
  - phase-3
---

# Task 22: Final security audit of all new endpoints and webhook system

## Assigned Agent: `security-auditor`

## Objective
Audit all new code for security vulnerabilities: auth bypasses, injection risks, secret exposure, SSRF in webhook URLs, HMAC implementation correctness.

## Context
This plan adds 10+ new API endpoints and a webhook system that makes outbound HTTP calls. The webhook system is especially security-sensitive (SSRF, secret handling, HMAC correctness).

## Files to Modify/Create
- All new route files, webhook dispatcher, and Celery task — read-only audit

## Acceptance Criteria
- [ ] No auth bypasses on protected endpoints
- [ ] Webhook URLs validated (no internal/private IPs — SSRF prevention)
- [ ] HMAC implementation uses constant-time comparison (`hmac.compare_digest`)
- [ ] Webhook secrets not logged or exposed in responses (except create)
- [ ] No SQL injection risks in new queries
- [ ] No path traversal in symbol validation
- [ ] Rate limiting on webhook creation (prevent abuse)
- [ ] Audit report generated in `development/code-reviews/`

## Dependencies
- All implementation tasks (1, 4, 7, 10, 15-17) must complete first

## Agent Instructions
1. This is a read-only audit — generate a report, do not modify code
2. Focus areas: SSRF in webhook URLs, HMAC correctness, auth on all new endpoints, secret handling
3. Check that webhook URL validation blocks: localhost, 127.0.0.1, 10.x.x.x, 172.16-31.x.x, 192.168.x.x, [::1]
4. Verify `hmac.compare_digest()` is used (not `==`) for signature verification
5. Save report to `development/code-reviews/`

## Estimated Complexity
Medium — security review of well-scoped new code.
