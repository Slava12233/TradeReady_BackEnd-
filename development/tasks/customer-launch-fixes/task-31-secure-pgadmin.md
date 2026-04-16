---
task_id: 31
title: "Secure pgAdmin default password"
type: task
agent: "deploy-checker"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["docker-compose.yml"]
tags:
  - task
  - security
  - infrastructure
  - P2
---

# Task 31: Secure pgAdmin default password

## Assigned Agent: `deploy-checker`

## Objective
pgAdmin is exposed with a default password in docker-compose.yml. Anyone who can reach the port has full database access.

## Context
Infrastructure audit (SR-07) flagged this. pgAdmin should either use strong credentials from environment variables or be removed from production compose.

## Files to Modify
- `docker-compose.yml` — pgAdmin service credentials

## Acceptance Criteria
- [ ] pgAdmin credentials come from environment variables, not hardcoded defaults
- [ ] pgAdmin is only available in development profile (not production)
- [ ] Or: pgAdmin is removed from production compose entirely
- [ ] Default password is not in the repository

## Agent Instructions
1. Find the pgAdmin service in docker-compose.yml
2. Move credentials to environment variables: `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD`
3. Add pgAdmin to a `dev` profile so it's not started in production
4. Add a comment that production should NOT use pgAdmin

## Estimated Complexity
Low — Docker compose config change
