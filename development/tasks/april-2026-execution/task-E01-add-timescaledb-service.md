---
task_id: E-01
title: "Add TimescaleDB service"
type: task
agent: "backend-developer"
track: E
depends_on: []
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - ci
  - infrastructure
  - database
---

# Task E-01: Add TimescaleDB service

## Assigned Agent: `backend-developer`

## Objective
Add a TimescaleDB/PostgreSQL service container to `.github/workflows/test.yml` for integration tests.

## Context
Currently CI only has Redis as a service container. Integration tests need TimescaleDB to run. Without it, we can only run unit tests in CI.

## Files to Modify
- `.github/workflows/test.yml` — add TimescaleDB service

## Acceptance Criteria
- [ ] TimescaleDB service container added to test.yml
- [ ] Uses `timescale/timescaledb:latest-pg16` or appropriate version
- [ ] Health check configured with `--health-cmd pg_isready`
- [ ] Generous startup timeout (30+ seconds)
- [ ] Environment variables set: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
- [ ] Service ports mapped (5432)
- [ ] Test jobs can connect to the database

## Dependencies
None — can start immediately.

## Agent Instructions
Read the existing `.github/workflows/test.yml` to understand the current service configuration (Redis is already there). Add TimescaleDB following the same pattern:

```yaml
services:
  timescaledb:
    image: timescale/timescaledb:latest-pg16
    env:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: tradeready_test
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
      --health-start-period 30s
```

Ensure the DATABASE_URL environment variable is set for test jobs.

## Estimated Complexity
Low — adding a service container to an existing workflow.
