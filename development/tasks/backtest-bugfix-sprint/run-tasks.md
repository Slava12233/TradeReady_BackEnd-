---
type: task
tags:
  - execution-guide
  - backtesting
---

# Execution Guide: Backtest Bugfix Sprint

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1: P0 Critical
```
Sequential: Task 01 (research) → Task 02 (fix BT-01)
Parallel:   Task 03 (fix BT-02/BT-17)  ← can start immediately
After both: Task 12 (tests for Sprint 1)
```

### Phase 2: P1 High
```
Parallel: Task 04 (schema), Task 05 (by_pair), Task 06 (agent_id)
After all: Task 13 (tests for Sprint 2)
```

### Phase 3: P2 Medium
```
Parallel: Task 07 (pairs), Task 08 (compare), Task 09 (best)
After all: Task 14 (tests for Sprint 3)
```

### Phase 4: P3 Low + Quality Gate
```
Parallel: Task 10 (defaults), Task 11 (messages)
After both: Task 15 (tests for Sprint 4)
Sequential: Task 16 (code review) → Task 17 (E2E) → Task 18 (context)
```

## Post-Task Checklist

After each development task (02-11) completes:
- [ ] `ruff check` passes on changed files
- [ ] `mypy` passes on changed files
- [ ] Existing tests still pass

After all tasks complete:
- [ ] code-reviewer agent validates all changes (Task 16)
- [ ] test-runner agent runs full backtest test suite
- [ ] e2e-tester validates live (Task 17)
- [ ] context-manager logs everything (Task 18)
- [ ] If API response shapes changed: api-sync-checker + doc-updater

## Quick Reference

| Phase | Tasks | Can Parallelize |
|-------|-------|-----------------|
| 1 | 01→02, 03 | 02 and 03 in parallel after 01 |
| 2 | 04, 05, 06 | All 3 in parallel |
| 3 | 07, 08, 09 | All 3 in parallel |
| 4 | 10, 11, 16→17→18 | 10 and 11 in parallel |
