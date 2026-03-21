---
task_id: 20
title: "Create project health dashboard"
type: task
agent: backend-developer
phase: 6
depends_on: [4, 5, 6, 7, 8, 19]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/_dashboards/project-health.md
tags:
  - task
  - obsidian
  - dashboard
  - dataview
---

# Create project health dashboard

## Assigned Agent: `backend-developer`

## Objective

Create `development/_dashboards/project-health.md` with Dataview queries that provide a single-page overview of project health.

## Context

Single-page overview of project health. Replaces manually scanning context.md for status. Dataview queries are read-only -- they cannot modify files.

## Files to Create

- `development/_dashboards/project-health.md`

## Dataview Queries to Include

1. **Recent code reviews** (last 5, sorted by date, showing verdict)
2. **Task completion rate** (completed vs total across all boards, grouped by board)
3. **Open tasks by priority** (high/medium/low)
4. **Recent daily notes** (last 7 days, with links)
5. **Plans by status** (draft/active/archived/complete)
6. **Code review verdict distribution** (count of PASS vs NEEDS FIXES)

## Example Queries

```dataview
TABLE date, verdict, scope
FROM ""
WHERE type = "code-review"
SORT date DESC
LIMIT 5
```

```dataview
TABLE WITHOUT ID
  board as "Board",
  length(rows) as "Total",
  length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) as "Done",
  round(length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) / length(rows) * 100) + "%" as "Progress"
FROM ""
WHERE type = "task"
GROUP BY board
```

## Acceptance Criteria

- [ ] Dashboard file exists at `development/_dashboards/project-health.md`
- [ ] Contains all 6 Dataview queries listed above
- [ ] Queries use correct frontmatter field names
- [ ] Dashboard has clear section headings

## Estimated Complexity

Medium
