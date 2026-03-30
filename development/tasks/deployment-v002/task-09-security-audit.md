---
task_id: 9
title: "Security audit of deployment changes"
type: task
agent: "security-auditor"
phase: 5
depends_on: [6]
status: "pending"
priority: "medium"
board: "[[deployment-v002/README]]"
files: ["src/config.py", "src/main.py", ".github/workflows/deploy.yml", ".env.example"]
tags:
  - task
  - security
  - deployment
---

# Task 09: Security audit of deployment changes

## Assigned Agent: `security-auditor`

## Objective
Audit the CORS configuration change and CI/CD pipeline changes for security issues.

## Acceptance Criteria
- [ ] CORS_ORIGINS cannot be set to "*" (wildcard) when allow_credentials=True
- [ ] No secrets leaked in CI/CD scripts (deploy.yml uses GitHub secrets properly)
- [ ] Database backup in deploy.yml doesn't expose credentials
- [ ] `.env` is in `.gitignore` and not committed
- [ ] No SSRF risk from configurable CORS origins

## Agent Instructions
1. Read `.claude/agent-memory/security-reviewer/MEMORY.md` for project security context
2. Check that `CORS_ORIGINS` parsing in `src/main.py` handles edge cases (empty string, trailing commas)
3. Verify deploy.yml doesn't echo secrets to logs
4. Check that `pg_dump` credentials come from env vars, not hardcoded

## Estimated Complexity
Low — focused audit of 4 files
