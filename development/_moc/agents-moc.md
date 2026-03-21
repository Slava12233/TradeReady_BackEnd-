---
type: moc
title: Agent Fleet
tags:
  - moc
  - agent
---

# Agent Fleet

> 16 specialized Claude Code agents organized by role category.

## Quality Gate Agents (every change)

| Agent | Purpose |
|-------|---------|
| `code-reviewer` | Reviews code against project standards |
| `test-runner` | Maps changes to tests, runs them, writes missing tests |
| `context-manager` | Maintains context.md and CLAUDE.md files |

## Security Agents

| Agent | Purpose |
|-------|---------|
| `security-auditor` | Read-only audit for vulnerabilities |
| `security-reviewer` | Vulnerability detection + remediation |

## Infrastructure Agents

| Agent | Purpose |
|-------|---------|
| `migration-helper` | Alembic migration validation |
| `api-sync-checker` | Frontend/backend API sync |
| `deploy-checker` | Deployment readiness |
| `doc-updater` | Documentation sync |
| `perf-checker` | Performance regression detection |

## Development Agents

| Agent | Purpose |
|-------|---------|
| `backend-developer` | Python async modules and services |
| `frontend-developer` | Next.js/React components and pages |
| `ml-engineer` | RL, genetic algorithms, ML models |
| `e2e-tester` | Live E2E scenarios |

## Research & Planning Agents

| Agent | Purpose |
|-------|---------|
| `planner` | Implementation plans (uses Opus) |
| `codebase-researcher` | Code investigation and analysis |

## Dataview: Agent Workload

```dataview
TABLE WITHOUT ID
  agent as "Agent",
  length(rows) as "Total Tasks",
  length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) as "Completed"
FROM ""
WHERE type = "task"
GROUP BY agent
SORT length(rows) DESC
```
