---
task_id: 05
title: "Verify DATABASE_URL production credentials"
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
  - database
  - deployment
---

# Task 05: Verify DATABASE_URL production credentials

## Objective
Confirm `DATABASE_URL` uses production database credentials — not the default `postgres:postgres` or the `.env.example` placeholder `change_me`.

## Context
The startup assertion from Task 32 blocks boot in production if `DATABASE_URL` contains `postgres:postgres` or `change_me`.

## Files to Check
- `.env` on production server (read DATABASE_URL value)

## Acceptance Criteria
- [ ] `DATABASE_URL` does NOT contain `postgres:postgres`
- [ ] `DATABASE_URL` does NOT contain `change_me`
- [ ] DB user is a dedicated app user (not the superuser)
- [ ] Password is strong (32+ chars, random)
- [ ] URL uses `postgresql+asyncpg://` scheme (required by the ORM)
- [ ] Database is reachable from the app container: `psql $DATABASE_URL -c 'SELECT 1'` succeeds

## Dependencies
Task 03 — ENVIRONMENT must be set to trigger validation.

## Agent Instructions
1. Read current `DATABASE_URL` from `.env` (do not log it)
2. Verify scheme is `postgresql+asyncpg://`
3. Verify user is not `postgres` (use a dedicated app user like `tradeready_app`)
4. Test connectivity: `docker compose exec api python -c "import asyncio; from src.database.session import get_engine; asyncio.run(get_engine().connect())"` — should succeed
5. If using `postgres:postgres`, create a dedicated user with minimal privileges and update `.env`

## Estimated Complexity
Low — validation; user creation is medium if needed
