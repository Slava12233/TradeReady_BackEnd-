---
task_id: 32
title: "Add weak credential startup assertion"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["src/main.py", "src/config.py"]
tags:
  - task
  - security
  - backend
  - P2
---

# Task 32: Add weak credential startup assertion

## Assigned Agent: `backend-developer`

## Objective
The platform has weak default credentials in config (e.g., `JWT_SECRET=change-me`). Add a startup assertion that refuses to start with known-weak defaults in production.

## Context
Security audit (SR-06) flagged this as LOW. Default credentials in development are fine, but production should never start with them.

## Files to Modify
- `src/main.py` — Add startup check
- `src/config.py` — Define which settings must be non-default in production

## Acceptance Criteria
- [ ] App refuses to start if `JWT_SECRET` is a known default value and `ENVIRONMENT=production`
- [ ] Same check for `DATABASE_URL` containing `postgres:postgres` in production
- [ ] Development/test environments are not affected
- [ ] Clear error message explaining which credential needs to be changed
- [ ] Test: verify startup fails with weak creds in production mode

## Agent Instructions
1. Read `src/config.py` (or settings) for environment detection
2. Add a startup validation function that checks critical secrets
3. Call it early in `create_app()` or as a lifespan event
4. Known weak defaults to reject: `change-me`, `secret`, `password`, `postgres:postgres`

## Estimated Complexity
Low — startup validation function
