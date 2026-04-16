---
task_id: 12
title: "Test registration with optional display_name"
type: task
agent: "e2e-tester"
phase: 2
depends_on: [7]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - smoke-test
  - auth
---

# Task 12: Test registration with optional display_name

## Objective
Verify the fix from Task 11 (customer launch fixes): registration should succeed without `display_name`, defaulting to "Agent".

## Acceptance Criteria
- [ ] `POST https://api.tradeready.io/api/v1/auth/register` with `{"password": "Test1234!"}` only returns 201
- [ ] Response includes `account_id`, `api_key`, `api_secret`, `agent_id`, `agent_api_key`
- [ ] `display_name` in response is `"Agent"` (the default)
- [ ] Account with `display_name` provided works identically
- [ ] Password length < 8 returns 422
- [ ] Password length > 72 returns 422 (Task 16 bcrypt truncation fix)
- [ ] Email address if provided triggers email verification log (look for `email_verify` in API logs)

## Dependencies
Task 07 — API must be running.

## Agent Instructions
1. Run three registration tests with curl:
   ```bash
   # Test A: minimal (no display_name)
   curl -sX POST https://api.tradeready.io/api/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"password":"Test1234!"}'
   
   # Test B: with display_name (backward compat)
   curl -sX POST https://api.tradeready.io/api/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"display_name":"TestBot","password":"Test1234!"}'
   
   # Test C: password too short
   curl -sX POST https://api.tradeready.io/api/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"password":"short"}'
   
   # Test D: password too long (73 chars)
   curl -sX POST https://api.tradeready.io/api/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"password":"'$(python -c "print('a'*73)")'"}' 
   ```
2. Verify Test A returns 201 with `display_name: "Agent"`
3. Verify Test C and D return 422 with validation errors
4. Check API logs for password_reset + email_verify structured logs if email provided

## Estimated Complexity
Low — API smoke test
