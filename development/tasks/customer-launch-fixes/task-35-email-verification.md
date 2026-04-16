---
task_id: 35
title: "Add email verification at registration"
type: task
agent: "backend-developer"
phase: 3
depends_on: [12]
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/routes/auth.py", "src/accounts/service.py", "src/database/models/account.py"]
tags:
  - task
  - auth
  - backend
  - P2
---

# Task 35: Add email verification at registration

## Assigned Agent: `backend-developer`

## Objective
No email verification at registration. Accounts can be created with any email address (or none). Add email collection and verification.

## Context
Marketing readiness audit (SR-11) flagged this. Email verification prevents fake accounts and enables communication with users (password reset, announcements).

## Files to Modify
- `src/api/routes/auth.py` — Add email field to registration, send verification email
- `src/accounts/service.py` — Email verification logic
- `src/database/models/account.py` — Add `email` and `email_verified` fields if not present

## Acceptance Criteria
- [ ] Registration accepts optional `email` field
- [ ] If email provided, send verification link (or log for MVP)
- [ ] `email_verified` boolean field on account model
- [ ] Verification endpoint confirms email
- [ ] Unverified users can still use the platform (email not blocking)
- [ ] Migration for new fields

## Dependencies
Task 12 (password reset) should complete first — shares email infrastructure.

## Agent Instructions
1. Read `src/accounts/CLAUDE.md` for account model
2. For MVP: log verification links instead of sending real emails
3. Make email optional — don't block existing registration flow
4. Email verification should be a soft requirement, not a hard gate

## Estimated Complexity
High — new fields + verification flow + migration
