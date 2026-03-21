---
type: moc
title: Task Boards
tags:
  - moc
  - tasks
---

# Task Boards

## Completed

- [[tradeready-test-agent/README|TradeReady Test Agent]] (18 tasks)
- [[agent-strategies/README|Agent Strategies]] (29 tasks)
- [[frontend-performance-fixes/README|Frontend Performance]] (23 tasks)
- [[agent-deployment-training/README|Agent Deployment]] (23 tasks)
- [[agent-ecosystem/README|Agent Ecosystem]] (36 tasks)
- [[agent-memory-system/README|Agent Memory System]] (14 tasks)

## In Progress

- [[obsidian-integration/README|Obsidian Integration]] (32 tasks)

## Pending

- [[agent-logging-system/README|Agent Logging System]] (34 tasks)

## Dataview: All Task Boards

```dataview
TABLE status, total_tasks as "Tasks", created
FROM ""
WHERE type = "task-board"
SORT created DESC
```

## Dataview: Tasks by Status

```dataview
TABLE WITHOUT ID
  file.link as "Task",
  agent,
  status,
  priority
FROM ""
WHERE type = "task"
SORT status ASC, priority DESC
```
