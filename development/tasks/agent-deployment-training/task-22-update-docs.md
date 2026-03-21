---
task_id: 22
title: "Update documentation for deployment"
type: task
agent: "doc-updater"
phase: 12
depends_on: [20, 21]
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "medium"
files: ["agent/CLAUDE.md", "agent/strategies/CLAUDE.md", "CLAUDE.md", "docs/skill.md"]
tags:
  - task
  - deployment
  - training
---

# Task 22: Update documentation for deployment

## Assigned Agent: `doc-updater`

## Objective
Update all documentation to reflect the deployment changes: Docker setup, dependency groups, training commands, and security/perf fixes applied.

## Files to Update
1. `agent/CLAUDE.md` — add Docker section, update dependency table with `[ml]` group
2. `agent/strategies/CLAUDE.md` — note perf/security fixes applied
3. Root `CLAUDE.md` — add agent Docker service to platform section
4. `docs/skill.md` — add deployment instructions

## Acceptance Criteria
- [ ] Docker setup documented in agent/CLAUDE.md
- [ ] `pip install -e "agent/[ml]"` documented
- [ ] Training pipeline commands listed
- [ ] Security/perf fixes noted in changelog

## Dependencies
- Tasks 20-21: Docker and test fixes complete

## Estimated Complexity
Low — documentation updates only.
