---
type: task
tags:
  - execution-guide
  - platform-endgame
date: 2026-04-08
---

# Execution Guide: Platform Endgame Readiness

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1 — Parallel Execution Groups (Week 1-2)

**Group 1A** (no dependencies — start immediately, all parallel):
- Task 1: Batch backtest engine + API → `backend-developer`
- Task 4: Deflated Sharpe service + API → `backend-developer`
- Task 7: Indicators API endpoints → `backend-developer`

**Group 1B** (after Group 1A completes):
- Task 2: Batch step SDK + gym → `backend-developer` (after Task 1)
- Task 5: DSR auto-compute + SDK → `backend-developer` (after Task 4)
- Task 8: Indicators SDK → `backend-developer` (after Task 7)

**Group 1C** (after Group 1B completes):
- Task 3: Batch step tests → `test-runner` (after Tasks 1, 2)
- Task 6: DSR tests → `test-runner` (after Tasks 4, 5)
- Task 9: Indicators tests → `test-runner` (after Tasks 7, 8)

### Phase 2 — Parallel Execution Groups (Week 3-4)

**Group 2A** (start after relevant Phase 1 tasks):
- Task 10: Strategy compare → `backend-developer` (after Task 4)
- Task 12: Fee config → `backend-developer` (no dependency)
- Task 13: Headless gym → `ml-engineer` (after Task 1)
- Task 15: Webhook model + migration → `backend-developer` (no dependency)

**Group 2B** (after Group 2A):
- Task 11: Strategy compare tests → `test-runner` (after Task 10)
- Task 16: Webhook dispatcher → `backend-developer` (after Task 15)
- Task 19: Migration validation → `migration-helper` (after Task 15)

**Group 2C** (after Group 2B):
- Task 14: Gym tests → `test-runner` (after Tasks 12, 13)
- Task 17: Webhook API + SDK + triggers → `backend-developer` (after Tasks 15, 16)

**Group 2D** (after Group 2C):
- Task 18: Webhook tests → `test-runner` (after Tasks 15, 16, 17)

### Phase 3 — Documentation & Security (Week 5)

**Group 3A** (after all implementation):
- Task 20: SDK examples → `backend-developer` (after Tasks 1, 4, 7, 10, 17)
- Task 22: Security audit → `security-auditor` (after Tasks 1, 4, 7, 10, 15-17)

**Group 3B** (after Group 3A):
- Task 21: SDK docs → `doc-updater` (after Task 20)

### Sequential Chains

```
Batch Backtest:   1 → 2 → 3
Deflated Sharpe:  4 → 5 → 6
Indicators:       7 → 8 → 9
Strategy Compare: 4 → 10 → 11
Gym Enhancements: 1 → 13 → 14, 12 → 14
Webhooks:         15 → 16 → 17 → 18, 15 → 19
SDK Examples:     [1,4,7,10,17] → 20 → 21
Security:         [all impl] → 22
```

## Post-Task Checklist

After each task completes:
- [ ] `code-reviewer` agent validates the changes
- [ ] `test-runner` agent runs relevant tests
- [ ] `context-manager` agent logs what changed
- [ ] If API changed: `api-sync-checker` + `doc-updater`
- [ ] If security-sensitive: `security-auditor`
- [ ] If DB changed: `migration-helper`

## Verification After Each Improvement

```bash
ruff check src/ tests/          # Zero lint errors
mypy src/                       # Type check passes
pytest tests/unit/              # All unit tests pass
pytest tests/integration/       # All integration tests pass
```

## Risk Mitigation

- **No breaking changes**: All improvements are additive with sensible defaults
- **Rollback plan**: Each improvement is independent — can be reverted individually
- **Migration safety**: Task 19 validates migration before apply
- **Security**: Task 22 audits all new code before production deploy
