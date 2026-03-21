---
task_id: 02
title: "Verify platform services & prerequisites"
type: task
agent: "deploy-checker"
phase: 2
depends_on: [1]
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: []
tags:
  - task
  - deployment
  - training
---

# Task 02: Verify platform services & prerequisites

## Assigned Agent: `deploy-checker`

## Objective
Verify that all platform services are running and healthy: TimescaleDB, Redis, API, Celery, ingestion. Run migrations, seed pairs, and confirm API responds.

## Steps
1. `docker compose up -d` — start all services
2. `docker compose ps` — verify all containers show "healthy"
3. `alembic upgrade head` — run any pending migrations
4. `python scripts/seed_pairs.py` — seed exchange pairs
5. `curl http://localhost:8000/api/v1/health` — confirm API health
6. Verify Redis connectivity: `redis-cli ping`
7. Verify a test account exists or create one via API

## Acceptance Criteria
- [ ] All Docker services running and healthy
- [ ] Database migrations applied
- [ ] Exchange pairs seeded (600+ USDT pairs)
- [ ] API health endpoint returns `{"status": "healthy"}`
- [ ] A platform account exists with `api_key` and `api_secret`
- [ ] `agent/.env` created from `.env.example` with valid credentials

## Dependencies
- Task 01: packages installed

## Agent Instructions
Check `docker-compose.yml` for service definitions. The platform needs ~8 CPU cores and ~10 GB RAM. If services fail to start, check Docker resource limits. If migrations fail, check `DATABASE_URL` in `.env`.

## Estimated Complexity
Low — running standard deployment commands.
