---
task_id: 2
title: "Merge V.0.0.3 to main and trigger CI/CD deploy"
type: task
agent: "deploy-checker"
phase: 1
depends_on: [1]
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files: []
tags:
  - task
  - deployment
  - ci-cd
---

# Task 02: Merge V.0.0.3 to Main and Trigger Deploy

## Assigned Agent: `deploy-checker`

## Objective
Merge the V.0.0.3 branch to `main` and push to trigger the GitHub Actions CI/CD deploy workflow.

## Context
Pre-flight (Task 1) passed. CI/CD at `.github/workflows/deploy.yml` automatically: runs lint+test, SSHs into production, takes pg_dump backup, pulls latest, builds Docker images, runs `alembic upgrade head` (applies 023), rolling restarts, health check with auto-rollback.

## Acceptance Criteria
- [ ] V.0.0.3 merged to `main`
- [ ] `git push origin main` triggers GitHub Actions
- [ ] Deploy workflow starts (visible in GitHub Actions UI)

## Dependencies
- **Task 1** (pre-flight passes)

## Agent Instructions
1. `git checkout main && git merge V.0.0.3`
2. `git push origin main`
3. Confirm GitHub Actions workflow triggered
4. NOTE: This requires user confirmation before executing (pushing to main)

## Estimated Complexity
Low — git merge + push.
