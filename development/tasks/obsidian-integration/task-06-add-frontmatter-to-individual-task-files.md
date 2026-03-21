---
task_id: 6
title: "Add frontmatter to individual task files"
type: task
agent: backend-developer
phase: 2
depends_on: [5]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files: []
tags:
  - task
  - obsidian
  - frontmatter
  - bulk-update
---

# Add frontmatter to individual task files

## Assigned Agent: `backend-developer`

## Objective

Verify and normalize YAML frontmatter on all ~110 individual task files across 6 task board directories. Add `type: task`, `board`, and `tags` fields to existing frontmatter.

## Context

Most task files already have YAML frontmatter (task_id, title, agent, phase, depends_on, status, priority, files). The `type` and `board` fields enable Dataview to query tasks globally across all boards. The `tags` field enables tag-based navigation.

## Scope

All ~110 task files across 6 task board directories:
- `development/tasks/tradeready-test-agent/`
- `development/tasks/agent-strategies/`
- `development/tasks/frontend-performance-fixes/`
- `development/tasks/agent-deployment-training/`
- `development/tasks/agent-ecosystem/`
- `development/tasks/agent-memory-system/`

## Fields to Add to Existing Frontmatter

```yaml
type: task
board: "[[agent-memory-system/README]]"
tags:
  - task
  - agent-memory
```

## Agent Instructions

- Read each task file's existing frontmatter
- Add `type: task` if missing
- Add `board` field pointing to the parent board README using wikilink format
- Add `tags` field with `task` plus board-relevant tags
- Do NOT modify existing fields (`task_id`, `status`, `depends_on`, etc.)

## Acceptance Criteria

- [ ] All ~110 task files have `type: task` in frontmatter
- [ ] All task files have `board` field with correct wikilink to parent README
- [ ] All task files have `tags` array
- [ ] No existing frontmatter fields are corrupted or removed
- [ ] The `status` field remains unchanged (read by `/plan-to-tasks` skill)

## Estimated Complexity

High (110+ files, but each change is small and mechanical)
