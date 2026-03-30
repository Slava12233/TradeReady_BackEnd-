---
task_id: 4
title: "Run unit tests and fix failures"
type: task
agent: "test-runner"
phase: 1
depends_on: [1, 2, 3]
status: "pending"
priority: "high"
board: "[[deployment-v002/README]]"
files: ["tests/unit/"]
tags:
  - task
  - tests
  - deployment
---

# Task 04: Run unit tests and fix failures

## Assigned Agent: `test-runner`

## Objective
Run `pytest tests/unit -v --tb=short` and fix any failing tests. The CI runs this exact command.

## Context
CI pipeline runs unit tests with a Redis service container (no password) against `redis://localhost:6379/0`. Tests must pass in that environment.

## Acceptance Criteria
- [ ] `pytest tests/unit -v --tb=short` passes with zero failures
- [ ] No tests are skipped due to import errors
- [ ] Any tests broken by the CORS or CI/CD changes are updated

## Agent Instructions
1. Run `pytest tests/unit -v --tb=short 2>&1 | tail -50` to see failures
2. For each failure, determine if it's a real bug or a test that needs updating
3. The CORS change (`src/main.py`) now calls `get_settings()` inside `create_app()` — tests that create the app may need to mock settings
4. Check `tests/CLAUDE.md` for fixture patterns and gotchas
5. `get_settings()` uses `lru_cache` — patch it BEFORE the cached instance is created

## Estimated Complexity
High — could be many failures; root causes vary
