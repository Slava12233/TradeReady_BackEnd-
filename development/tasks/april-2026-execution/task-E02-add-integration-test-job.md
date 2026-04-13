---
task_id: E-02
title: "Add integration test job"
type: task
agent: "backend-developer"
track: E
depends_on: ["E-01"]
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - ci
  - testing
  - integration
---

# Task E-02: Add integration test job

## Assigned Agent: `backend-developer`

## Objective
Add a new job in `test.yml` that runs `pytest tests/integration -v --tb=short` with both DB and Redis services.

## Context
Integration tests (24 files, 504 tests) require a real database. Currently they only run locally.

## Files to Modify
- `.github/workflows/test.yml`

## Acceptance Criteria
- [ ] New `integration-tests` job added
- [ ] Job depends on TimescaleDB + Redis services
- [ ] Runs `pytest tests/integration -v --tb=short`
- [ ] DATABASE_URL and REDIS_URL environment variables configured
- [ ] Alembic migrations run before tests (`alembic upgrade head`)
- [ ] Job can run in parallel with existing unit test job

## Dependencies
- **E-01**: TimescaleDB service must be configured

## Agent Instructions
Read `tests/integration/CLAUDE.md` for integration test requirements. The tests use `from src.main import create_app` and need a real database. Add a separate job (not a step in the existing job) so integration tests run in parallel with unit tests. Remember to install Python dependencies and run migrations first.

## Estimated Complexity
Medium — new CI job with database setup.
