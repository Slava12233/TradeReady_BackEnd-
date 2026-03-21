---
task_id: 10
title: "Add wikilinks to task board READMEs"
type: task
agent: backend-developer
phase: 3
depends_on: [5, 9]
status: pending
priority: medium
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
  - wikilinks
  - task-board
---

# Add wikilinks to task board READMEs

## Assigned Agent: `backend-developer`

## Objective

Add `[[wikilinks]]` to cross-references within task board README files to create graph connections between plans and their task boards.

## Context

Creates graph connections between plans and their task boards. Additive text changes in non-agent-parsed sections of READMEs.

## Link Targets to Add

- Plan source references: `development/agent-memory-strategy-report.md` becomes `[[agent-memory-strategy-report]]`
- Agent references in task tables: `context-manager` stays as plain text (agents are outside vault)
- Inter-board references where they exist
- Link to `[[context]]` where the boards reference `development/context.md`

## Example Transformation

```markdown
# Before
**Plan source:** `development/agent-memory-strategy-report.md`

# After
**Plan source:** [[agent-memory-strategy-report]]
```

## Acceptance Criteria

- [ ] All 6 task board READMEs have wikilinks for plan source references
- [ ] Cross-references to other `development/` files use `[[wikilinks]]`
- [ ] Agent names remain plain text (not linked)
- [ ] Source code paths remain inline code (not linked)

## Estimated Complexity

Low (6 files)
