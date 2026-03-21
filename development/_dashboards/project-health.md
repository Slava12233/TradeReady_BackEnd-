---
type: dashboard
title: Project Health
tags:
  - dashboard
  - moc
---

# Project Health Dashboard

## Recent Code Reviews (Last 5)

```dataview
TABLE date, verdict, scope, reviewer
FROM ""
WHERE type = "code-review"
SORT date DESC
LIMIT 5
```

## Task Completion by Board

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

## Open Tasks by Priority

```dataview
TABLE WITHOUT ID
  file.link as "Task",
  agent,
  board,
  priority
FROM ""
WHERE type = "task" AND (status = "pending" OR status = "in-progress")
SORT priority DESC
```

## Recent Daily Notes

```dataview
TABLE date
FROM ""
WHERE type = "daily-note"
SORT date DESC
LIMIT 7
```

## Plans by Status

```dataview
TABLE status, created
FROM ""
WHERE type = "plan"
SORT status ASC, created DESC
```

## Code Review Verdicts

```dataview
TABLE WITHOUT ID
  verdict as "Verdict",
  length(rows) as "Count"
FROM ""
WHERE type = "code-review"
GROUP BY verdict
```
