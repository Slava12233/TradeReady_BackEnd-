---
task_id: 1
title: "Pre-flight validation for V.0.0.3 deploy"
type: task
agent: "deploy-checker"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files: []
tags:
  - task
  - deployment
  - validation
---

# Task 01: Pre-flight Validation for V.0.0.3 Deploy

## Assigned Agent: `deploy-checker`

## Objective
Run the full pre-deploy checklist: verify migration chain, run tests, lint, type check. Confirm the branch is ready to push to `main`.

## Context
R1 from the C-level report. V.0.0.3 has 7 endgame improvements + 9 security fixes. Migration 023 is ready. Security re-audit verdict: PASS.

## Acceptance Criteria
- [ ] `alembic history | head -5` shows 023 as head
- [ ] `pytest tests/unit/ -x -q` passes
- [ ] `ruff check src/ tests/` — zero new errors
- [ ] `mypy src/` passes on modified files
- [ ] Git working tree is clean (all changes committed)
- [ ] Branch is `V.0.0.3` or merged to `main`

## Agent Instructions
1. Run `alembic history | head -5` to verify migration chain
2. Run `pytest tests/unit/ -x -q` for unit tests
3. Run `ruff check src/ tests/ --statistics`
4. Run `mypy src/ --ignore-missing-imports` on changed files
5. Run `git status` to verify clean tree
6. Report pass/fail for each check

## Estimated Complexity
Low — running existing checks, no code changes.
