---
task_id: E-04
title: "Add gym test job"
type: task
agent: "backend-developer"
track: E
depends_on: ["E-01"]
status: "completed"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - ci
  - testing
  - gym
---

# Task E-04: Add gym test job

## Assigned Agent: `backend-developer`

## Objective
Add a new CI job that runs `pytest tradeready-gym/tests -v --tb=short` — the 159 gym tests.

## Files to Modify
- `.github/workflows/test.yml`

## Acceptance Criteria
- [ ] New `gym-tests` job added
- [ ] Installs gym package: `pip install -e tradeready-gym/`
- [ ] Installs SB3: `pip install "stable-baselines3>=2.0"`
- [ ] Runs `pytest tradeready-gym/tests -v --tb=short`
- [ ] Services: TimescaleDB (headless env needs DB)
- [ ] Runs in parallel with other test jobs

## Dependencies
- **E-01**: TimescaleDB service

## Agent Instructions
Read `tradeready-gym/CLAUDE.md` for the package structure. The gym has its own dependencies in `pyproject.toml`. Some tests (headless env) need a database connection. Ensure DATABASE_URL is set.

## Estimated Complexity
Low-Medium — similar pattern to E-03.
