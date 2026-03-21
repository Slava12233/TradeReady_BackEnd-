---
task_id: 18
title: "Create agent fleet MOC"
type: task
agent: backend-developer
phase: 5
depends_on: [17]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/_moc/agents-moc.md
tags:
  - task
  - obsidian
  - moc
  - agents
---

# Create agent fleet MOC

## Assigned Agent: `backend-developer`

## Objective

Create `development/_moc/agents-moc.md` with the full agent inventory and Dataview queries showing task count per agent across all boards.

## Context

Gives humans visibility into which agents do the most work and what kind of work they do. Complements the `/analyze-agents` skill with a visual, always-up-to-date view.

## Files to Create

- `development/_moc/agents-moc.md`

## Content Requirements

- Frontmatter: `type: moc`, `title: Agent Fleet`, `tags: [moc, agents]`
- Agent inventory table mirroring `.claude/agents/CLAUDE.md` (16 agents with purpose, tools, model)
- Vault-internal links to reviews and tasks where each agent appears
- Dataview query for agent workload:
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

## Acceptance Criteria

- [ ] `development/_moc/agents-moc.md` exists with valid frontmatter
- [ ] All 16 agents are listed with their purpose
- [ ] Dataview query shows task count per agent
- [ ] Links to related reviews and tasks where applicable

## Estimated Complexity

Low
