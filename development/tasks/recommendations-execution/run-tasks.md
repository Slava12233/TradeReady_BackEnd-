---
type: task
tags:
  - execution-guide
  - recommendations
date: 2026-04-08
---

# Execution Guide: Recommendations

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute:

1. Read the task file
2. Delegate to the specified agent
3. Update task `status`: pending → in_progress → completed/failed
4. Run post-change pipeline as needed

## Execution Order

### Phase 1 — Deploy + Backup (Day 0-1)

**Group 1A** (start immediately, parallel):
- Task 1: Pre-flight → `deploy-checker`
- Task 4: Backup script → `backend-developer`

**Group 1B** (after Group 1A):
- Task 2: Merge + deploy → `deploy-checker`
- Task 5: Backup docs → `doc-updater`

**Group 1C** (after Task 2):
- Task 3: Post-deploy verify → `e2e-tester`

### Phase 2 — RL + Frontend + Docs (Day 1-7)

**Track A: RL Training** (sequential):
6 → 7 → 8

**Track B: Frontend** (9 first, then 10-13 parallel, then 14):
9 → {10, 11, 12, 13} → 14

**Track C: Docs** (sequential):
15 → 16

### Phase 3 — Validation (Day 7-10)

17 (API sync) and 18 (context sync) — after all work done.

### Sequential Chains

```
Deploy:   1 → 2 → 3
Backup:   4 → 5
RL:       3 → 6 → 7 → 8
Frontend: 3 → 9 → {10,11,12,13} → 14
Docs:     3 → 15 → 16
Sync:     {9,14} → 17, {3,8,14,15} → 18
```

## Post-Task Checklist

After code tasks:
- [ ] `code-reviewer` validates changes
- [ ] `test-runner` runs tests
- [ ] `context-manager` logs changes

After frontend tasks:
- [ ] `api-sync-checker` verifies types
- [ ] `pnpm build` passes

After ML tasks:
- [ ] Training report saved
- [ ] Model file committed (if small) or documented

## Quick Start

Begin with Phase 1 Group 1A (no dependencies):
- Task 1: Pre-flight validation → `deploy-checker`
- Task 4: Backup script → `backend-developer`
