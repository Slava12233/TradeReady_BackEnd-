---
task_id: 10
title: "Code review all deployment changes"
type: task
agent: "code-reviewer"
phase: 5
depends_on: [1, 2, 5, 6]
status: "pending"
priority: "medium"
board: "[[deployment-v002/README]]"
files: ["src/config.py", "src/main.py", "src/mcp/tools.py", ".github/workflows/deploy.yml", ".github/workflows/test.yml", ".env.example"]
tags:
  - task
  - review
  - deployment
---

# Task 10: Code review all deployment changes

## Assigned Agent: `code-reviewer`

## Objective
Review all code changes made for the V.0.0.2 deployment for compliance with project standards.

## Acceptance Criteria
- [ ] CORS change follows project patterns (lazy import in create_app, Settings class)
- [ ] No Decimal/float violations introduced
- [ ] Import order correct (stdlib → third-party → local)
- [ ] deploy.yml follows bash best practices (set -euo pipefail, proper quoting)
- [ ] MCP tools.py description wrapping doesn't break tool definitions
- [ ] Review report saved to `development/code-reviews/`

## Agent Instructions
1. Read `.claude/agent-memory/code-reviewer/MEMORY.md` for project conventions
2. Review the diff of all changed files (git diff against the pre-change state)
3. Focus on: exception handling, import order, naming, security patterns
4. Save report to `development/code-reviews/review_2026-03-30_deployment-v002.md`

## Estimated Complexity
Low — small number of changed files
