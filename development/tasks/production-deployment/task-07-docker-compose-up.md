---
task_id: 07
title: "Start all services (docker compose up)"
type: task
agent: "deploy-checker"
phase: 2
depends_on: [2, 4, 5, 6]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: ["docker-compose.yml"]
tags:
  - task
  - deployment
  - docker
---

# Task 07: Start all services (docker compose up)

## Objective
Bring up all services including the new Alertmanager container and `db-backup` sidecar.

## Context
Phase 2 deployment trigger. All pre-deploy configuration must be complete before this task runs.

## Files Used
- `docker-compose.yml` — service definitions
- `.env` — environment variables (must be configured from Tasks 03-05)
- `monitoring/alertmanager.yml` — must be configured from Task 06

## Acceptance Criteria
- [ ] `docker compose up -d` succeeds without errors
- [ ] All services report `healthy` status: `docker compose ps`
- [ ] Expected services are running:
  - `api` (FastAPI backend)
  - `timescaledb` (database)
  - `redis`
  - `celery-worker`
  - `celery-beat`
  - `prometheus`
  - `alertmanager` (NEW)
  - `grafana`
  - `db-backup` (NEW)
  - `price-ingestion`
- [ ] Services NOT running (dev profile): `pgadmin` should be absent (moved to dev profile in Task 31)
- [ ] API startup log shows no "weak credential" assertion errors (Task 32)

## Dependencies
- Task 02: Migration applied
- Task 04: JWT_SECRET verified
- Task 05: DATABASE_URL verified
- Task 06: Alertmanager SMTP configured

## Agent Instructions
1. Run `docker compose up -d` (no profile flag — pgAdmin stays off)
2. Wait ~30 seconds for services to initialize
3. Run `docker compose ps` and verify all show `Up (healthy)` or `Up`
4. Check API logs: `docker compose logs api | tail -50` — look for "weak credential" errors
5. If any service shows `unhealthy` or `Restarting`, inspect logs: `docker compose logs <service>`

## Estimated Complexity
Low (if pre-deploy tasks done correctly) — Medium if troubleshooting needed
