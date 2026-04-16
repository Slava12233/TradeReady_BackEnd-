---
task_id: 01
title: "Pull latest code from main"
type: task
agent: "deploy-checker"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - deployment
  - pre-deploy
---

# Task 01: Pull latest code from main

## Assigned Agent: `deploy-checker`

## Objective
On the production server, pull the latest code from `main` branch containing all 37 customer launch fixes.

## Context
This is the first step of production deployment. All subsequent deployment tasks depend on the code being present.

## Files to Modify/Create
None — this is a git operation on the server.

## Acceptance Criteria
- [ ] SSH into production server
- [ ] `git status` shows clean working tree on `main`
- [ ] `git pull origin main` succeeds
- [ ] HEAD commit matches expected deploy SHA from CI/CD pipeline
- [ ] No merge conflicts

## Dependencies
None — this is the first task.

## Agent Instructions
1. SSH into the production server (use the configured SSH key from GitHub Actions deploy workflow)
2. Navigate to the project directory
3. Run `git fetch origin` then `git status` to verify clean state
4. Run `git pull origin main`
5. Confirm the HEAD commit includes the migration 024 and all customer launch fixes
6. If there are any local changes, investigate BEFORE pulling (never discard without understanding)

## Estimated Complexity
Low — standard git operation
