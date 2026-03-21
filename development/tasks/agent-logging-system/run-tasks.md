# Execution Guide: Agent Logging System

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1: Foundation (Tasks 01-08)

**Sequential start:**
1. Task 01 (logging module) — MUST complete first

**Parallel batch (all depend only on Task 01):**
2. Tasks 02, 03, 04, 05, 06, 07 — run in parallel

**Gate:**
3. Task 08 (Phase 1 tests) — after all above complete

**Post-phase pipeline:** code-reviewer → context-manager

### Phase 2: Agent-Side Logging (Tasks 09-15)

**Sequential start:**
1. Task 09 (middleware) — MUST complete first

**Parallel batch A (depend on Task 09):**
2. Tasks 10, 11, 12 — run in parallel

**Parallel batch B (depend on Task 01):**
3. Tasks 13, 14 — can run in parallel with batch A

**Gate:**
4. Task 15 (Phase 2 tests) — after all above complete

**Post-phase pipeline:** code-reviewer → perf-checker → context-manager

### Phase 3: Cross-System Correlation (Tasks 16-27)

**Parallel start groups:**
- Group A: Tasks 16, 17 (trace ID propagation — parallel)
- Group B: Tasks 19, 20 (DB models — parallel)

**After Group A:**
- Task 18 (platform-side extraction)

**After Group B:**
- Task 21 (migration) and Task 22 (repositories) — parallel

**After Task 18:**
- Task 23 (audit log) — parallel with Task 24

**After Task 22:**
- Task 24 (batch writer)

**After Tasks 21 + 24:**
- Task 25 (loop integration)

**After Tasks 23 + 24:**
- Task 26 (security review)

**Gate:**
- Task 27 (Phase 3 tests) — after all above complete

**Post-phase pipeline:** code-reviewer → security-auditor → perf-checker → context-manager

### Phase 4: Prometheus Metrics (Tasks 28-31)

**Sequential:**
1. Task 28 (registry)
2. Task 29 (endpoint + instrumentation) — depends on 28
3. Task 30 (platform metrics) — independent, can run parallel with 28/29
4. Task 31 (dashboards + alerts) — after 28 + 29

**Post-phase pipeline:** code-reviewer → context-manager

### Phase 5: Intelligence Layer (Tasks 32-34)

**Parallel start:**
- Task 32 (decision replay API) — depends on 21, 22, 25
- Task 33 (analytics tasks) — depends on 22, 25

**After Task 33:**
- Task 34 (feedback + anomaly)

**Post-phase pipeline:** code-reviewer → test-runner → api-sync-checker → doc-updater → context-manager

## Post-Task Checklist

After each task completes:
- [ ] `ruff check` passes on changed files
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed

After each phase completes:
- [ ] All phase tests pass
- [ ] If API changed: api-sync-checker + doc-updater
- [ ] If security-sensitive: security-auditor
- [ ] If DB changed: migration-helper validates
- [ ] If performance-sensitive: perf-checker

## Agent Assignment Summary

| Agent | Tasks | Count |
|-------|-------|-------|
| `backend-developer` | 01-07, 09-14, 16-20, 22-25, 28-34 | 28 |
| `test-runner` | 08, 15, 27 | 3 |
| `migration-helper` | 21 | 1 |
| `security-auditor` | 26 | 1 |
| `code-reviewer` | Post-phase reviews | (per-phase) |
| `perf-checker` | Phase 2+3 reviews | (per-phase) |
| `context-manager` | Final step each phase | (per-phase) |
| `api-sync-checker` | Phase 5 review | (once) |
| `doc-updater` | Phase 5 review | (once) |
