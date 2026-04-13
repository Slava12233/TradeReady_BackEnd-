---
task_id: A-01
title: "Verify Docker services running"
type: task
agent: "deploy-checker"
track: A
depends_on: []
status: "blocked"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/validate_phase1.py", "docker-compose.yml"]
tags:
  - task
  - infrastructure
  - docker
---

# Task A-01: Verify Docker services running

## Assigned Agent: `deploy-checker`

## Objective
Ensure TimescaleDB, Redis, and the API server are all healthy and accessible before starting the data backfill pipeline.

## Context
Track A (Historical Data Loading) requires all infrastructure services to be running. This is the gate for the entire execution plan.

## Files to Check
- `docker-compose.yml` — service definitions
- `scripts/validate_phase1.py` — existing health check script

## Acceptance Criteria
- [ ] TimescaleDB is running and accepting connections on port 5432
- [ ] Redis is running and responding on port 6379
- [ ] API server is accessible on port 8000
- [ ] `validate_phase1.py` passes all checks (or equivalent manual verification)
- [ ] `candles_backfill` hypertable exists in TimescaleDB

## Dependencies
None — this is the first task.

## Agent Instructions
Run `docker compose ps` to check service status. If services are down, run `docker compose up -d`. Then run `scripts/validate_phase1.py` or manually verify each service. Check that the `candles_backfill` table exists by querying the database.

## Estimated Complexity
Low — infrastructure verification only.
