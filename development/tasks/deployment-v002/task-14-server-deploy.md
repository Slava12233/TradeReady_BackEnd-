---
task_id: 14
title: "Server-side deploy execution"
type: task
agent: "deploy-checker"
phase: 9
depends_on: [13]
status: "pending"
priority: "high"
board: "[[deployment-v002/README]]"
files: []
tags:
  - task
  - deploy
  - server
---

# Task 14: Server-side deploy execution

## Assigned Agent: `deploy-checker`

## Objective
Monitor the CI/CD pipeline and verify the server-side deployment completes successfully. If auto-deploy fails, guide manual deployment.

## Acceptance Criteria
- [ ] GitHub Actions test job passes (lint + type check + unit tests)
- [ ] GitHub Actions deploy job passes (backup + pull + build + migrate + restart + health check)
- [ ] All 9 Docker services running and healthy on server
- [ ] `alembic current` shows 020 on server
- [ ] API responds at `:8000/health`

## Agent Instructions
1. Check GitHub Actions for pipeline status
2. If pipeline fails at test stage — go back and fix the failing check
3. If pipeline fails at deploy stage — SSH to server and check logs
4. If auto-deploy not available — follow manual deploy steps in `development/deployment-plan-v002.md` Phase 6.2
5. Verify `docker compose ps` shows all services healthy

## Estimated Complexity
Medium — depends on CI/CD pipeline behavior
