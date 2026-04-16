---
task_id: 29
title: "Add Celery worker health check"
type: task
agent: "deploy-checker"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["docker-compose.yml", "scripts/celery_healthcheck.sh"]
tags:
  - task
  - infrastructure
  - celery
  - P2
---

# Task 29: Add Celery worker health check

## Assigned Agent: `deploy-checker`

## Objective
Celery worker has no health check. If it crashes silently, background tasks (analytics, cleanup, settlement) stop running without notification.

## Context
Infrastructure audit (SR-07) flagged this. The worker is critical for scheduled tasks but has no monitoring.

## Files to Create/Modify
- `scripts/celery_healthcheck.sh` — Create health check script using `celery inspect ping`
- `docker-compose.yml` — Add healthcheck to celery worker service

## Acceptance Criteria
- [ ] Celery worker service has a Docker healthcheck
- [ ] Health check uses `celery inspect ping` to verify worker responsiveness
- [ ] Unhealthy worker triggers container restart (restart policy)
- [ ] Health check interval is reasonable (30s check, 10s timeout)

## Agent Instructions
1. Create a simple health check script: `celery -A src.tasks.celery_app inspect ping`
2. Add `healthcheck` section to the celery worker service in docker-compose.yml
3. Set `restart: unless-stopped` on the worker service

## Estimated Complexity
Low — Docker healthcheck configuration
