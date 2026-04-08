---
task_id: 1
title: "SSRF protection on webhook URLs"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[v003-next-steps/README]]"
files:
  - "src/api/schemas/webhooks.py"
  - "src/tasks/webhook_tasks.py"
tags:
  - task
  - security
  - webhooks
  - ssrf
  - critical
---

# Task 01: SSRF Protection on Webhook URLs

## Assigned Agent: `backend-developer`

## Objective
Add URL validation to webhook create/update schemas and defence-in-depth in the Celery task to prevent Server-Side Request Forgery (SSRF) attacks via webhook URLs.

## Context
Security audit finding [CRITICAL]: `WebhookCreateRequest.url` and `WebhookUpdateRequest.url` accept any string. An authenticated user can register internal URLs (`http://localhost:6379`, `http://169.254.169.254/latest/meta-data/`) and the Celery worker will POST to them. Full details in `development/code-reviews/security-audit-endgame-readiness.md`.

## Files to Modify/Create
- `src/api/schemas/webhooks.py` — Add `@field_validator("url")` to both `WebhookCreateRequest` and `WebhookUpdateRequest`
- `src/tasks/webhook_tasks.py` — Add defence-in-depth URL validation in `_async_dispatch` before `httpx.post()`

## Acceptance Criteria
- [ ] Only `https://` scheme accepted (reject `http://`, `ftp://`, etc.)
- [ ] Hostname resolved via `socket.getaddrinfo()` and blocked if IP is in:
  - Loopback: `127.0.0.0/8`, `::1`
  - Link-local: `169.254.0.0/16`, `fe80::/10`
  - Private RFC-1918: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  - Docker bridge: `172.17.0.0/16`
  - Cloud metadata: `169.254.169.254`
- [ ] Bare IP addresses rejected (no hostname)
- [ ] Defence-in-depth: `_async_dispatch` also validates URL before POST
- [ ] Clear error messages for rejected URLs
- [ ] `ruff check` passes
- [ ] Existing webhook tests still pass

## Dependencies
None — highest priority, start immediately.

## Agent Instructions
1. Read `src/api/schemas/webhooks.py` for the current url field definition
2. Read `src/tasks/webhook_tasks.py` for the `_async_dispatch` function
3. Create a shared `_validate_webhook_url(url: str) -> str` helper that both the validator and task can use
4. Use `urllib.parse.urlparse()` for scheme check, `socket.getaddrinfo()` for hostname resolution
5. Use `ipaddress` module (`ip_address()`, `ip_network()`) for range checks
6. The validator should raise `ValueError` (Pydantic catches it); the task helper should raise a custom error
7. Consider: DNS rebinding is not fully mitigated by this — note in code comment

## Estimated Complexity
Medium — URL parsing and IP range validation are well-defined, but edge cases (IPv6, encoded hostnames) need care.
