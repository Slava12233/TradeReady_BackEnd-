---
task_id: 03
title: "Set ENVIRONMENT=production in .env"
type: task
agent: "deploy-checker"
phase: 1
depends_on: [1]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: [".env"]
tags:
  - task
  - deployment
  - configuration
---

# Task 03: Set ENVIRONMENT=production in .env

## Objective
Set `ENVIRONMENT=production` in the server's `.env` file. This activates the startup credential validation added in Task 32 — the app will refuse to start with weak JWT_SECRET or default DB credentials.

## Context
Without `ENVIRONMENT=production`, the validation in `src/main.py._validate_production_secrets()` is skipped. Setting this value enables the safety net that blocks boot with known-weak defaults.

## Files to Modify
- `.env` (on the production server — NOT in git)

## Acceptance Criteria
- [ ] `.env` file exists on server
- [ ] `.env` contains `ENVIRONMENT=production`
- [ ] File is owned by the deploy user, not world-readable (`chmod 600`)
- [ ] `.env` is NOT committed to git (`git status` shows no tracked changes)

## Dependencies
Task 01 — code must be present to reference `.env.example`.

## Agent Instructions
1. SSH into the production server
2. Check if `.env` exists — if not, copy from `.env.example`
3. Add or update the line `ENVIRONMENT=production`
4. Verify file permissions: `ls -l .env` should show `-rw------- ... deployuser`
5. Verify not tracked: `git ls-files .env` should return nothing

## Estimated Complexity
Low — single env var change
