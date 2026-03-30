---
task_id: R2-03
title: "Enable Redis requirepass and bind to Docker internal network"
type: task
agent: "security-reviewer"
phase: 2
depends_on: ["R1-02"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["docker-compose.yml", ".env.example", ".env"]
tags:
  - task
  - security
  - redis
  - docker
---

# Task R2-03: Enable Redis `requirepass` and Docker Internal Bind

## Assigned Agent: `security-reviewer`

## Objective
Add password authentication to Redis to prevent unauthenticated writes to the permissions cache (which could allow temporary capability elevation for up to 300s TTL).

## Context
HIGH-3 from security review: Redis cache at `agent:permissions:{agent_id}` has no auth. Write access allows temporary capability elevation.

## Files to Modify/Create
- `docker-compose.yml` — add `--requirepass` to Redis command
- `.env.example` — add `REDIS_PASSWORD` variable
- `.env` — populate with generated password
- Verify `REDIS_URL` format: `redis://:${REDIS_PASSWORD}@redis:6379/0`

## Acceptance Criteria
- [x] Redis rejects unauthenticated commands — `NOAUTH Authentication required.` confirmed
- [x] `REDIS_URL` includes password in connection string — `redis://:JtClC...@redis:6379/0`
- [x] All services (API, Celery, price ingestion) reconnect with authenticated URL — all healthy
- [x] `CELERY_BROKER_URL` defaults to `REDIS_URL` and picks up the password — confirmed `redis://:**@redis:6379/0`
- [x] Redis port binding restricted — host port removed entirely; Redis only reachable on Docker internal network (stronger than 127.0.0.1 binding; Memurai was already occupying 6379 locally)

## Completion Notes (2026-03-23)
- `REDIS_PASSWORD` generated with `secrets.token_urlsafe(32)` and stored in `.env`
- `.env.example` updated with `REDIS_PASSWORD` placeholder and generation command
- `docker-compose.yml` Redis service: added `--requirepass ${REDIS_PASSWORD}`, `env_file: .env`, updated healthcheck to use `-a ${REDIS_PASSWORD}`, removed host port binding entirely
- Host port binding removed (not restricted to 127.0.0.1) because Windows Memurai service already occupies port 6379. No host exposure is actually more secure.
- All 5 consumer services (api, celery, celery-beat, ingestion, + healthcheck) verified healthy post-restart
- API `/health` returns `redis_connected: true`; Celery logs show `Connected to redis://:**@redis:6379/0`

## Dependencies
- R1-02 (Docker must be running to test)

## Agent Instructions
1. Add `REDIS_PASSWORD` to `.env.example` and `.env`
2. Update Redis service command in `docker-compose.yml`:
   ```yaml
   command: redis-server --requirepass ${REDIS_PASSWORD} --appendonly yes
   ```
3. Update `REDIS_URL` format in `.env`
4. Restrict Redis port binding: `"127.0.0.1:6379:6379"`
5. Restart services and verify all reconnect successfully

## Estimated Complexity
Medium — must verify all consumers reconnect; risk of breaking existing connections
