---
task_id: 08
title: "Rate-limit auth endpoints"
type: task
agent: "backend-developer"
phase: 2
depends_on: [1]
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/middleware/rate_limit.py", "src/api/routes/auth.py"]
tags:
  - task
  - security
  - rate-limiting
  - P1
---

# Task 08: Rate-limit auth endpoints

## Assigned Agent: `backend-developer`

## Objective
Auth endpoints (login, register) are currently exempt from rate limiting. This allows brute-force password attacks and CPU DoS via bcrypt hashing. Add stricter rate limits to auth routes.

## Context
Security audit (SR-06) flagged this as MEDIUM severity. bcrypt is intentionally slow — an attacker can exhaust CPU by sending thousands of login attempts. Auth endpoints need tighter limits than normal API routes.

## Files to Modify
- `src/api/middleware/rate_limit.py` — Add auth-specific rate limit tier
- `src/api/routes/auth.py` — Apply auth rate limits to login/register endpoints

## Acceptance Criteria
- [ ] Login endpoint: max 5 attempts per minute per IP
- [ ] Register endpoint: max 3 attempts per minute per IP
- [ ] Rate limit returns 429 Too Many Requests with Retry-After header
- [ ] Normal API endpoints remain at their current rate limits
- [ ] Existing rate limit tests pass + new auth rate limit tests added

## Dependencies
Task 01 (JWT fix) should complete first — auth middleware changes should be coordinated.

## Agent Instructions
1. Read `src/api/middleware/CLAUDE.md` for rate limiting patterns
2. The existing rate limiter uses Redis — add a new tier for auth routes
3. Use IP-based limiting (not account-based, since the user isn't authenticated yet)
4. Return standard 429 response with `Retry-After` header

## Estimated Complexity
Medium — new rate limit tier + endpoint decoration
