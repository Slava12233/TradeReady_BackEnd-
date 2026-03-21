---
type: moc
title: Code Reviews
tags:
  - moc
  - review
---

# Code Review History

## Dataview: All Reviews

```dataview
TABLE date, reviewer, verdict, scope
FROM ""
WHERE type = "code-review"
SORT date DESC
```

## By Verdict

### Needs Fixes

```dataview
LIST
FROM ""
WHERE type = "code-review" AND verdict = "NEEDS FIXES"
SORT date DESC
```

### Passed

```dataview
LIST
FROM ""
WHERE type = "code-review" AND (verdict = "PASS" OR verdict = "PASS WITH WARNINGS")
SORT date DESC
```

## Recent Reviews

- [[review_2026-03-20_16-24_frontend-perf-fixes|Frontend Perf Fixes]]
- [[review_2026-03-20_11-29_agent-package|Agent Package]]
- [[security-review-permissions|Security: Permissions]]
- [[security-review-agent-strategies|Security: Agent Strategies]]
- [[perf-check-agent-strategies|Perf: Agent Strategies]]
- [[frontend-performance-review|Frontend Performance]]
