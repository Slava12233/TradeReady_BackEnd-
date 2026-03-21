---
type: dashboard
title: Agent Activity
tags:
  - dashboard
  - moc
  - agent
---

# Agent Activity Dashboard

## Tasks per Agent

```dataview
TABLE WITHOUT ID
  agent as "Agent",
  length(rows) as "Total Tasks",
  length(filter(rows, (r) => r.status = "completed" OR r.status = "done")) as "Completed",
  length(filter(rows, (r) => r.status = "pending")) as "Pending"
FROM ""
WHERE type = "task"
GROUP BY agent
SORT length(rows) DESC
```

## Reviews by Reviewer

```dataview
TABLE WITHOUT ID
  reviewer as "Reviewer",
  length(rows) as "Reviews",
  length(filter(rows, (r) => r.verdict = "PASS" OR r.verdict = "PASS WITH WARNINGS")) as "Passed"
FROM ""
WHERE type = "code-review"
GROUP BY reviewer
```

## Activity Log

For detailed agent activity beyond what Dataview can query, use the JSONL activity log:

- **Log file:** `development/agent-activity-log.jsonl`
- **Summary script:** `bash scripts/agent-run-summary.sh`
- **Metrics script:** `bash scripts/analyze-agent-metrics.sh`
- **Analysis skill:** `/analyze-agents`

## Daily Notes Mentioning Agents

```dataview
LIST
FROM ""
WHERE type = "daily-note"
SORT date DESC
LIMIT 7
```
