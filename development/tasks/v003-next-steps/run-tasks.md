---
type: task
tags:
  - execution-guide
  - v003-next-steps
date: 2026-04-08
---

# Execution Guide: V.0.0.3 Next Steps

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1 — Security Fixes (Critical Path)

**Group 1A** (start immediately, all parallel):
- Task 1: SSRF protection → `backend-developer`
- Task 2: Bound returns → `backend-developer`
- Task 3: Remove secret from Celery → `backend-developer`

**Group 1B** (after Tasks 1 + 3):
- Task 4: Medium/Low fixes → `backend-developer`

**Group 1C** (after Tasks 1-4):
- Task 5: Security fix tests → `test-runner`

**Group 1D** (after Task 5):
- Task 6: Security re-audit → `security-auditor`

### Phase 2 — Full Validation

**Group 2A** (after Task 5):
- Task 7: Full test suite → `test-runner`

### Phase 3 — Frontend + Perf + Docs (after Phase 1)

**All parallel:**
- Task 8: Webhook UI → `frontend-developer`
- Task 9: Indicators widget → `frontend-developer`
- Task 10: Strategy compare view → `frontend-developer`
- Task 11: Batch progress UI → `frontend-developer`
- Task 12: Perf benchmarks → `e2e-tester`
- Task 13: Context/docs sync → `context-manager`

### Sequential Chains

```
Security:  1 ──┐
           2 ──┤→ 4 → 5 → 6
           3 ──┘
Validation: 5 → 7
Frontend:   6 → 8, 9, 10, 11 (parallel)
Perf:       7 → 12
Docs:       6 → 13
```

## Post-Task Checklist

After each code task completes:
- [ ] `code-reviewer` agent validates the changes
- [ ] `test-runner` agent runs relevant tests
- [ ] `context-manager` agent logs what changed
- [ ] If security-sensitive: `security-auditor` verifies

## Production Deploy Checklist

After Task 6 (security re-audit) passes:
- [ ] All Phase 1 tasks completed
- [ ] Security audit verdict: PASS
- [ ] Full test suite passes (Task 7)
- [ ] Apply migration: `alembic upgrade head`
- [ ] Deploy backend
- [ ] Smoke test: hit new endpoints via Swagger UI
- [ ] Monitor Grafana for errors
