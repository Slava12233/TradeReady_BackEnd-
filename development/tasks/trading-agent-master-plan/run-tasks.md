---
type: task
title: "Execution Guide — Trading Agent Master Plan"
tags:
  - task
  - execution-guide
---

# Execution Guide: Trading Agent Master Plan

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 0: Foundation (Do First)

**Parallel Group A** (bug fixes — no dependencies):
- Task 04: Fix Redis cache bug → `backend-developer`
- Task 05: Wire LogBatchWriter → `backend-developer`
- Task 06: Register IntentRouter handlers → `backend-developer`
- Task 07: TTL + PermissionDenied fix → `backend-developer`

**Sequential Chain B** (infrastructure):
- Task 01: Apply migrations → `migration-helper`
- Then parallel: Task 02 (data load) + Task 03 (agents) → `e2e-tester`

**Optimal:** Run Group A and Task 01 in parallel. After Task 01, run Tasks 02+03.

### Phase 1: Training Pipeline (After Phase 0)

Three parallel branches that converge:
```
Branch A: Task 08 → Task 09 (regime)
Branch B: Task 10 → Task 11 (RL — longest, ~36h CPU)
Branch C: Task 12 → Task 13 (evolutionary)
```
All three → Task 14 (ensemble weights) → Task 15 (validation)

**Tip:** Start Task 11 (PPO training) first — it takes 36h on CPU. Run branches A and C while PPO trains.

### Phase 2: Risk Hardening (Parallel with Phase 1)

**Parallel Group** (all independent):
- Task 16: Position sizing → `backend-developer`
- Task 17: Drawdown profiles → `backend-developer`
- Task 18: Correlation-aware risk → `backend-developer`
- Task 19: Strategy circuit breakers → `backend-developer`
- Task 20: Advanced order tools → `backend-developer`

**Sequential:**
- Task 17 → Task 21 (recovery protocol)
- All → Task 22 (security review)

### Phase 3: Intelligence (After Phase 1 + 2)

- Task 23: Dynamic ensemble weights (needs Tasks 14 + 16)
- Tasks 24, 25, 26, 27: parallel (enhanced tools, drift, pairs, websocket)

### Phase 4: Continuous Learning (After Phase 3)

- Tasks 28, 29: parallel (retrain pipeline, walk-forward)
- Tasks 30, 31, 32: parallel (settlement, attribution, memory)

### Phase 5: Platform + UI (After Phase 2 + 3)

- Tasks 33, 34, 35: all parallel (tools, battle UI, dashboard)

### Phase 6: Hardening (After Phase 4)

- Tasks 36, 37: parallel (monitoring, performance)

## Post-Task Checklist

After each code change task completes:
- [ ] `code-reviewer` agent validates changes
- [ ] `test-runner` agent runs relevant tests
- [ ] `context-manager` agent logs what changed
- [ ] If API changed: `api-sync-checker` + `doc-updater`
- [ ] If security-sensitive: `security-auditor`
- [ ] If DB changed: `migration-helper`

## LLM Budget Reminder

$5/day limit on OpenRouter. Training tasks (Phase 1) don't use LLM. Most code tasks don't use LLM. Only daily analysis ($0.50) and reflection ($0.30) use LLM in production.
