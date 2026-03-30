---
task_id: 12
title: "Pre-deploy checklist validation"
type: task
agent: "deploy-checker"
phase: 7
depends_on: [7, 8, 9, 10, 11]
status: "pending"
priority: "high"
board: "[[deployment-v002/README]]"
files: []
tags:
  - task
  - deploy
  - gate
---

# Task 12: Pre-deploy checklist validation

## Assigned Agent: `deploy-checker`

## Objective
Validate ALL pre-deployment requirements are met before pushing to main.

## Acceptance Criteria
- [ ] `ruff check src/ tests/` — zero errors
- [ ] `ruff format --check src/ tests/` — zero reformats needed
- [ ] `mypy src/ --ignore-missing-imports` — zero errors
- [ ] `pytest tests/unit` — zero failures
- [ ] Migration chain 017→020 verified
- [ ] Migration safety verified (no destructive ops)
- [ ] Security audit passed
- [ ] Code review passed
- [ ] `.env` not in git (in .gitignore)
- [ ] `CORS_ORIGINS` field present in `.env.example`
- [ ] All Dockerfiles exist (Dockerfile, Dockerfile.ingestion, Dockerfile.celery, agent/Dockerfile)
- [ ] `prometheus.yml` exists at repo root
- [ ] `pgadmin-servers.json` and `pgpassfile` exist at repo root

## Agent Instructions
1. Run each check command and verify output
2. Read deployment plan Phase 1 checklist for full list
3. If ANY check fails, report which one and stop — do not approve deploy

## Estimated Complexity
Medium — comprehensive checklist verification
