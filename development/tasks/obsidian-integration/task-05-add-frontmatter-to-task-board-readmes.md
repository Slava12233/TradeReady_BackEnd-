---
task_id: 5
title: "Add frontmatter to task board READMEs"
type: task
agent: backend-developer
phase: 2
depends_on: [1]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/tasks/tradeready-test-agent/README.md
  - development/tasks/agent-strategies/README.md
  - development/tasks/frontend-performance-fixes/README.md
  - development/tasks/agent-deployment-training/README.md
  - development/tasks/agent-ecosystem/README.md
  - development/tasks/agent-memory-system/README.md
tags:
  - task
  - obsidian
  - frontmatter
  - task-board
---

# Add frontmatter to task board READMEs

## Assigned Agent: `backend-developer`

## Objective

Add YAML frontmatter to all 6 task board README.md files so Dataview can list all task boards, filter by status, and count total tasks.

## Context

Enables Dataview to list all task boards, filter by status (done/in-progress), and count total tasks across the project.

## Files to Modify

- `development/tasks/tradeready-test-agent/README.md`
- `development/tasks/agent-strategies/README.md`
- `development/tasks/frontend-performance-fixes/README.md`
- `development/tasks/agent-deployment-training/README.md`
- `development/tasks/agent-ecosystem/README.md`
- `development/tasks/agent-memory-system/README.md`

## Frontmatter Format

```yaml
---
type: task-board
title: Agent Memory & Learning System
created: 2026-03-21
status: done
total_tasks: 14
plan_source: "[[agent-memory-strategy-report]]"
tags:
  - task-board
  - agent-memory
---
```

## Acceptance Criteria

- [ ] All 6 README.md files have valid YAML frontmatter
- [ ] `type: task-board` is present on all
- [ ] `status` correctly reflects board completion state (done/in-progress)
- [ ] `total_tasks` matches actual task count in each board
- [ ] Existing README content is preserved

## Estimated Complexity

Low (6 files, simple metadata)
