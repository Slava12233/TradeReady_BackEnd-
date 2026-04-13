---
task_id: E-03
title: "Add agent test job"
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
  - agent
---

# Task E-03: Add agent test job

## Assigned Agent: `backend-developer`

## Objective
Add a new CI job that runs `pytest agent/tests -v --tb=short` — the 2,304 agent tests.

## Files to Modify
- `.github/workflows/test.yml`

## Acceptance Criteria
- [ ] New `agent-tests` job added
- [ ] Installs agent dependencies (`pip install -e agent/[all]`)
- [ ] Runs `pytest agent/tests -v --tb=short`
- [ ] Services: Redis + TimescaleDB (some agent tests need DB)
- [ ] Runs in parallel with other test jobs

## Dependencies
- **E-01**: TimescaleDB service (some agent tests need it)

## Agent Instructions
Read `agent/CLAUDE.md` for the agent package structure. The agent has its own `pyproject.toml` with extras. Install with `pip install -e agent/[all]` to get all dependencies including ML packages.

## Estimated Complexity
Medium — agent package has many dependencies.
