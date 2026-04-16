---
task_id: 04
title: "Verify JWT_SECRET strength"
type: task
agent: "deploy-checker"
phase: 1
depends_on: [3]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: [".env"]
tags:
  - task
  - security
  - deployment
---

# Task 04: Verify JWT_SECRET strength

## Objective
Confirm `JWT_SECRET` in the production `.env` is a strong secret (32+ chars, not a default value). The startup assertion from Task 32 will block boot otherwise.

## Context
Task 32 added `_validate_production_secrets()` that rejects weak JWT_SECRETs in production. Known-weak values: `change-me`, `secret`, `password`, `changeme`, `test`, `change_me`. Min length: 32 chars.

## Files to Check
- `.env` on production server (read JWT_SECRET value)

## Acceptance Criteria
- [ ] `JWT_SECRET` is at least 32 characters long
- [ ] `JWT_SECRET` is not one of the known-weak values
- [ ] `JWT_SECRET` was generated with a secure RNG (e.g., `python -c "import secrets; print(secrets.token_urlsafe(48))"`)
- [ ] If secret was weak, rotate it and document that existing JWTs will be invalidated on rotation

## Dependencies
Task 03 — ENVIRONMENT must be set to trigger validation.

## Agent Instructions
1. Read current `JWT_SECRET` from `.env` (do not log it)
2. Check length: `echo -n "$JWT_SECRET" | wc -c` — must be >= 32
3. Check against weak list: not in `{change-me, secret, password, changeme, test, change_me}`
4. If weak: generate a new one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and update `.env`
5. If rotated: warn the team that all existing JWTs will be invalidated (users must re-login)

## Estimated Complexity
Low — validation only; rotation if needed is medium
