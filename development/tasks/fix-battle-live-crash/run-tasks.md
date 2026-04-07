---
type: task-board
tags:
  - battles
  - execution-guide
---

# Execution Guide: Fix Battle Live UI Crash

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` -> `"in_progress"` -> `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Parallel Execution Group 1 (Phase 1 — Hotfixes)
Run simultaneously:
- **Task 01** (`frontend-developer`) — Fix remaining_minutes crash
- **Task 02** (`frontend-developer`) — Defensive null guards
- **Task 03** (`backend-developer`) — Schema update

### Sequential Chain 1 (Phase 2 — Backend)
After Task 03 completes:
- **Task 04** (`backend-developer`) — Time fields in route handler
- **Task 05** (`backend-developer`) — Enrich live snapshot

Tasks 04 and 05 can run in parallel (both depend only on Task 03).

### Sequential Chain 2 (Phase 3 — Frontend Sync)
After Tasks 03, 04, 05 complete:
- **Task 06** (`frontend-developer`) — Type sync & cleanup
- **Task 07** (`frontend-developer`) — Elapsed time display (after Task 06)

### Final Validation (Phase 4)
After all tasks complete:
- **Task 08** (`test-runner`) — Run tests & validate

## Post-Task Checklist

After ALL tasks complete:
- [ ] `code-reviewer` agent validates all changes
- [ ] `test-runner` agent runs relevant tests (Task 08)
- [ ] `api-sync-checker` verifies Pydantic/TypeScript alignment
- [ ] `context-manager` agent logs what changed

## Quick Start

To begin, run these three tasks in parallel:
```
Task 01: frontend-developer — Hotfix remaining_minutes (1 line change)
Task 02: frontend-developer — Defensive null guards (2 files)
Task 03: backend-developer — Schema update (1 file)
```
