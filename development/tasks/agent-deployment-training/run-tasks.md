# Execution Guide: Agent Deployment & Training

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Prerequisites

```bash
# Docker must be installed and running
docker --version

# Python 3.12+ required
python --version

# Platform repo cloned
cd /path/to/AiTradingAgent
```

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1 — Setup (sequential, ~1 hour total)
```
01 (fix deps) → 02 (verify platform) → 03 (backfill data) → 04 (V1 validation)
```
These MUST run in order. Each depends on the previous.

### Phase 2 — Training (parallel, ~6-12 hours total)

After Task 03 completes, these 3 chains can run in parallel:

**Chain A — PPO:**
```
06 (train PPO) → 07 (evaluate PPO)
```

**Chain B — Regime:**
```
05 (train regime classifier)
```

**Chain C — Evolution:**
```
08 (investigate battle bug) → 09 (fix if needed) → 10 (run evolution) → 11 (analyze)
```

### Phase 3 — Validation (after training completes)
```
[05 + 07] → 12 (validate strategies)
[05 + 07 + 11] → 13 (ensemble weights) → 14 (ensemble validation)
```

### Phase 4 — Fixes (parallel, no training dependency)

These can start anytime — they don't depend on training results:
```
15 (N+1 API)     ──┐
16 (async fixes)  ─┤
17 (growth caps)  ─┤→ 21 (run tests)
18 (checksums)    ─┤
19 (CLI keys)     ─┘
```

### Phase 5 — Docker (parallel with Phase 4)
```
20 (Dockerfile) — only needs Task 01
```

### Phase 6 — Final (after all above)
```
21 (tests) → 22 (docs) → 23 (context)
```

## Parallel Execution Groups

**Group 1 — No dependencies (start immediately):**
- Task 15: Fix N+1 API calls → `backend-developer`
- Task 16: Fix blocking sync → `backend-developer`
- Task 17: Fix unbounded growth → `backend-developer`
- Task 18: Add checksums → `security-reviewer`
- Task 19: Remove CLI keys → `security-reviewer`

**Group 2 — After Task 01:**
- Task 20: Dockerize agent → `backend-developer`

**Group 3 — After Task 03 (data loaded):**
- Task 05: Train regime → `ml-engineer`
- Task 06: Train PPO → `ml-engineer`
- Task 08: Investigate battle bug → `codebase-researcher`

**Group 4 — After training completes:**
- Task 12: Validate strategies → `e2e-tester`
- Task 13: Ensemble optimization → `e2e-tester`

## Stop-Early Rules

- **After Task 07:** If PPO Sharpe > 1.0 and ROI > 10% → PPO alone may be sufficient
- **After Task 11:** If evolved champion beats PPO → two strategies may be enough
- **After Task 12:** If regime adds alpha → proceed to ensemble
- **Always do Tasks 15-19:** Fixes are needed regardless of training outcomes

## Post-Task Checklist

After each CODE CHANGE task (15-20) completes:
- [ ] `test-runner` agent runs relevant tests
- [ ] `code-reviewer` agent validates the changes
- [ ] `context-manager` agent logs what changed

After TRAINING tasks (05-14):
- [ ] Verify output files exist (models, reports, logs)
- [ ] Check metrics against acceptance criteria
- [ ] Save results for ensemble comparison

## Agent Assignment Summary

| Agent | Tasks | Total |
|-------|-------|-------|
| `backend-developer` | 01, 09, 15, 16, 17, 20 | 6 |
| `ml-engineer` | 05, 06, 07, 10, 11 | 5 |
| `e2e-tester` | 03, 04, 12, 13, 14 | 5 |
| `security-reviewer` | 18, 19 | 2 |
| `codebase-researcher` | 08 | 1 |
| `deploy-checker` | 02 | 1 |
| `test-runner` | 21 | 1 |
| `doc-updater` | 22 | 1 |
| `context-manager` | 23 | 1 |

## Quick Start

To begin execution right now:
```
1. Task 01: delegate to backend-developer → "Add ML deps to pyproject.toml"
2. Tasks 15-19: delegate in parallel → Fix perf + security issues (no deps)
3. Task 20: delegate to backend-developer → "Create agent Dockerfile"
```
These 7 tasks have zero or only Task 01 as dependency and can start simultaneously.
