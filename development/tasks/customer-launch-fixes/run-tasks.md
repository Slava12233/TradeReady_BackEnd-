---
type: task-board
title: "Execution Guide — Customer Launch Fixes"
tags:
  - execution
  - guide
---

# Execution Guide: Customer Launch Fixes

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1: P0 Critical Blockers (~19 hours, 2-3 days)

**All 7 tasks are independent — run in parallel:**

| Task | Agent | Est. |
|------|-------|------|
| Task 01: JWT agent scope bypass | backend-developer | 1h |
| Task 02: Terms of Service | planner → frontend-developer | 4h |
| Task 03: Privacy Policy | planner → frontend-developer | 4h |
| Task 04: Support channel | frontend-developer | 2h |
| Task 05: Alertmanager | deploy-checker | 4h |
| Task 06: Database backups | backend-developer | 2h |
| Task 07: Search bar | frontend-developer | 2h |

**Parallel groups:**
- Group A (backend): Tasks 01, 06
- Group B (frontend): Tasks 02, 03, 04, 07
- Group C (infra): Task 05

### Phase 2: P1 High Priority (~40 hours, ~1 week)

**Independent tasks (can run in parallel):**
- Tasks 09, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22

**Sequential chains:**
- Task 01 → Task 08 (JWT fix before rate limiting)
- Task 09 → Task 10 (branding before root route)
- Task 13 → Task 18 (PnL fix before PnL optimization)

**Parallel groups:**
- Group A (backend): Tasks 08, 12, 13, 14, 15, 16, 17, 18, 20, 21
- Group B (frontend): Tasks 09, 10, 19, 20
- Group C (docs): Tasks 11, 22

### Phase 3: P2 Medium Priority (~40 hours, ~1 week)

**All tasks are independent — run in parallel:**

**Parallel groups:**
- Group A (backend): Tasks 24, 25, 26, 27, 28, 32, 35
- Group B (frontend): Tasks 34
- Group C (testing): Tasks 23, 33
- Group D (infra): Tasks 29, 30, 31, 37
- Group E (docs): Tasks 36

**Sequential chain:**
- Task 12 → Task 35 (password reset before email verification — shared email infra)

## Post-Task Checklist

After each task completes:
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed
- [ ] If API changed: api-sync-checker + doc-updater
- [ ] If security-sensitive: security-auditor
- [ ] If DB changed: migration-helper

## Agent Task Counts

| Agent | Tasks | IDs |
|-------|-------|-----|
| backend-developer | 17 | 01, 06, 08, 12, 13, 14, 15, 16, 17, 18, 20, 21, 24, 25, 26, 27, 28, 32, 35 |
| frontend-developer | 10 | 02, 03, 04, 07, 09, 10, 12, 19, 20, 34, 35 |
| deploy-checker | 5 | 05, 29, 30, 31, 37 |
| doc-updater | 3 | 11, 22, 36 |
| test-runner | 2 | 23, 33 |
| planner | 2 | 02, 03 |
| perf-checker | 1 | 15 |

## Timeline

| Milestone | Target | Effort |
|-----------|--------|--------|
| Phase 1 complete (P0 blockers fixed) | Apr 22 | ~19h |
| Phase 2 complete (P1 items fixed) | May 2 | ~40h |
| Phase 3 complete (P2 items fixed) | May 16 | ~40h |
| Soft launch (5-10 users) | Apr 25 | P0 done |
| Public beta (Product Hunt) | May 9 | P0+P1 done |
