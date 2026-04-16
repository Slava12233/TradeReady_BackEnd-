---
task_id: 12
title: "Implement password reset flow"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/routes/auth.py", "src/accounts/service.py", "Frontend/src/app/(auth)/forgot-password/page.tsx", "Frontend/src/app/(auth)/reset-password/page.tsx"]
tags:
  - task
  - auth
  - backend
  - frontend
  - P1
---

# Task 12: Implement password reset flow

## Assigned Agent: `backend-developer` (API) + `frontend-developer` (UI)

## Objective
Users who forget their password are permanently locked out. Implement a password reset flow with email-based token verification.

## Context
Marketing readiness audit (SR-11) flagged this as P1 — users locked out permanently is a deal-breaker for retention.

## Backend Files to Create/Modify
- `src/api/routes/auth.py` — Add POST `/auth/forgot-password` and POST `/auth/reset-password` endpoints
- `src/accounts/service.py` — Add password reset token generation and verification logic
- `src/database/models/` — Add password_reset_tokens table or use existing mechanism

## Frontend Files to Create/Modify
- `Frontend/src/app/(auth)/forgot-password/page.tsx` — "Enter your email" form
- `Frontend/src/app/(auth)/reset-password/page.tsx` — "Enter new password" form (with token from URL)

## Acceptance Criteria
- [ ] POST `/auth/forgot-password` accepts email/username, sends reset link (or logs it for now)
- [ ] Reset tokens expire after 1 hour
- [ ] POST `/auth/reset-password` accepts token + new password, updates the password
- [ ] Used tokens cannot be reused
- [ ] Frontend forgot-password page with email input
- [ ] Frontend reset-password page with new password input
- [ ] Rate limited: max 3 reset requests per hour per account

## Agent Instructions
1. Read `src/accounts/CLAUDE.md` for account service patterns
2. For MVP: log the reset link to console/structlog instead of actually sending email (email integration can come later)
3. Use a secure random token (secrets.token_urlsafe) stored with expiry in Redis or DB
4. Frontend pages should follow existing auth page patterns

## Estimated Complexity
High — new endpoints + token management + 2 frontend pages
