---
type: task
tags:
  - execution-guide
  - qa-bugfix
---

# Execution Guide: QA Bug Fix Sprint

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Sprint 1: Unblock Users (Day 1-2)

**Parallel Group A:**
- Task 01: Fix zero balance at registration → `backend-developer`
- Task 03: Fix agent delete CASCADE → `migration-helper`
- Task 04: Update docs URLs → `doc-updater`

**Sequential (after Task 01):**
- Task 02: Fix account reset → `backend-developer`

### Sprint 2: Restore Features (Day 3-5)

**Sequential (needs investigation):**
- Task 05: Fix battle creation → `backend-developer` (investigate first)

**Parallel Group B:**
- Task 06: Fix strategy creation → `backend-developer`
- Task 07: Fix win rate → `backend-developer`
- Task 08: Fix tickers optional → `backend-developer`
- Task 09: Fix opened_at → `backend-developer`

### Sprint 3: Data, Docs & Polish (Day 6-7)

**Parallel Group C:**
- Task 10: Backfill historical data → `backend-developer`
- Task 11: Fix docs/schema polish → `doc-updater`
- Task 12: Improve error message → `backend-developer`

**Final (after ALL tasks):**
- Task 13: Full regression test → `e2e-tester`

## Post-Task Checklist

After each code-change task completes:
- [ ] `code-reviewer` agent validates the changes
- [ ] `test-runner` agent runs relevant tests
- [ ] `context-manager` agent logs what changed
- [ ] If API changed: `api-sync-checker` + `doc-updater`
- [ ] If security-sensitive: `security-auditor`
- [ ] If DB changed: `migration-helper` validates migration

## Quick Reference

| Sprint | Tasks | Est. Time | Key Risk |
|--------|-------|-----------|----------|
| 1 | 01, 02, 03, 04 | 1-2 days | Migration safety (Task 03) |
| 2 | 05, 06, 07, 08, 09 | 2-3 days | Battle root cause unknown (Task 05) |
| 3 | 10, 11, 12, 13 | 1-2 days | Backfill rate limits (Task 10) |
