# Execution Guide: Frontend Performance Fixes

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1: Quick Wins (Parallel Execution)

All 6 tasks can run simultaneously:

```
┌─────────────────────────────────────────────────┐
│  PARALLEL: All independent                       │
│                                                   │
│  Task 1:  React.memo PriceFlashCell              │
│  Task 2:  Code-split Three.js                    │
│  Task 3:  Add battles loading.tsx                │
│  Task 4:  useShallow portfolio selector          │
│  Task 5:  Memoize chart context                  │
│  Task 6:  Install bundle analyzer                │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
        Task 19: perf-checker (validate Phase 1)
                  │
                  ▼
        Task 20: test-runner (verify Phase 1)
```

**Suggested execution:** Launch Tasks 1-6 as parallel `frontend-developer` agents, then run Tasks 19-20 sequentially.

### Phase 2: Architecture Fixes

```
┌─────────────────────────────────────────────────┐
│  PARALLEL GROUP A: Independent                    │
│                                                   │
│  Task 9:  API client deduplication               │
│  Task 10: Reduce coin page polling               │
│  Task 11: Batch daily candles                    │
│  Task 12: Extract landing CSS                    │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  SEQUENTIAL CHAIN B:                              │
│                                                   │
│  Task 7:  Restructure dashboard layout            │
│       ↓                                           │
│  Task 13: Add Suspense boundaries                │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  SEQUENTIAL CHAIN C:                              │
│                                                   │
│  Task 6:  Install bundle analyzer (Phase 1)      │
│       ↓                                           │
│  Task 8:  Code-split dashboard components        │
└─────────────────────────────────────────────────┘

        After all Phase 2 tasks complete:
                  │
                  ▼
        Task 21: test-runner (verify Phase 2)
```

**Suggested execution:**
1. Launch Group A (Tasks 9, 10, 11, 12) in parallel
2. Launch Chain B (Task 7, then 13) — can overlap with Group A
3. Launch Task 8 after Task 6 from Phase 1 is confirmed done
4. After all complete, run Task 21

### Phase 3: Polish & Final Validation

```
┌─────────────────────────────────────────────────┐
│  PARALLEL: All independent                       │
│                                                   │
│  Task 14: Error boundaries                       │
│  Task 15: Route prefetching                      │
│  Task 16: WS rAF flush                          │
│  Task 17: Lazy-load tsparticles                  │
│  Task 18: keepPreviousData hooks                 │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
        Task 22: code-reviewer (review everything)
                  │
                  ▼
        Task 23: context-manager (update docs)
```

## Post-Task Checklist

After each phase completes:
- [ ] `perf-checker` agent validates performance improvements
- [ ] `test-runner` agent runs `pnpm test` and `pnpm build`
- [ ] `code-reviewer` agent validates against project standards
- [ ] `context-manager` agent logs what changed in `development/context.md`

## Quick Start

To begin execution, run the first phase tasks (all parallel):

```
Task 1: React.memo PriceFlashCell         → delegate to `frontend-developer`
Task 2: Code-split Three.js DottedSurface → delegate to `frontend-developer`
Task 3: Add battles loading.tsx           → delegate to `frontend-developer`
Task 4: useShallow portfolio selector     → delegate to `frontend-developer`
Task 5: Memoize chart context value       → delegate to `frontend-developer`
Task 6: Install bundle analyzer           → delegate to `frontend-developer`
```

All 6 can run in parallel since they touch different files with no dependencies.
