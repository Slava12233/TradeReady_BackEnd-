---
type: code-review
date: <% tp.date.now("YYYY-MM-DD") %>
reviewer: code-reviewer
verdict:
scope: <% tp.file.title.replace(/review_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}_/, '') %>
tags:
  - review
---

# Code Review Report

- **Date:** <% tp.date.now("YYYY-MM-DD HH:mm") %>
- **Reviewer:** code-reviewer agent
- **Verdict:**

## Files Reviewed

-

## CLAUDE.md Files Consulted

-

---

## Critical Issues (must fix)

### 1.

- **File:**
- **Rule violated:**
- **Issue:**
- **Fix:**

---

## Warnings (should fix)

## Suggestions (optional improvements)

## Passed Checks

- [ ] Naming conventions
- [ ] Dependency direction
- [ ] Error handling
- [ ] Type safety (Decimal, not float)
- [ ] Agent scoping (agent_id)
- [ ] Async patterns
- [ ] Test coverage adequate
