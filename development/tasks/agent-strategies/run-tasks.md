# Execution Guide: Agent Trading Strategies

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Prerequisites

Before starting any tasks:
```bash
# Platform must be running
docker compose up -d
# OR: uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Historical data must be loaded
python scripts/backfill_history.py

# Agent package installed
pip install -e agent/
pip install -e sdk/
pip install -e tradeready-gym/
```

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Parallel Execution Groups

**Group 1 — All phase starts (no dependencies):**
- Task 01 (research gym API) — `codebase-researcher`
- Task 07 (genetic algorithm core) — `ml-engineer`
- Task 12 (regime classifier) — `ml-engineer`
- Task 17 (risk agent core) — `backend-developer`

**Group 2 — After Task 01:**
- Task 02 (PPO pipeline) + Task 03 (data prep) — both `ml-engineer`, can run in parallel

**Group 3 — After Task 07:**
- Task 08 (battle integration) + Task 11 (evolutionary tests) — parallel

**Group 4 — After Task 12:**
- Task 13 (strategy versions) + Task 16 (regime tests) — parallel

### Sequential Chains

**Phase A (PPO):**
```
01 → [02 + 03] → 04 → 05 → 06
```

**Phase B (Evolution):**
```
07 → [08 + 11] → 09 → 10
```

**Phase C (Regime):**
```
12 → [13 + 16] → 14 → 15
```

**Phase D (Risk):**
```
17 → 18 → 19 → 20
```

**Phase E (Ensemble):**
```
[05 + 10 + 14] → 21 → 22 → 23 → 24 → 25
```

**Post-phase:**
```
[26 + 27] → 28 → 29
```

## Stop-Early Rule

**After each phase completes, check the results:**
- Phase A: If PPO Sharpe > 1.0 and ROI > 10% on out-of-sample → STOP. Deploy this.
- Phase B: If evolved champion beats PPO → consider stopping. Two strategies may be enough.
- Phase C: If regime-adaptive adds alpha → you now have 3 uncorrelated signals. Proceed to Phase E.
- Phase D: Always build the risk agent — it protects against drawdowns.
- Phase E: Only build if individual strategies are promising but not sufficient alone.

## Post-Task Checklist

After each task completes:
- [ ] `code-reviewer` agent validates the changes
- [ ] `test-runner` agent runs relevant tests
- [ ] `context-manager` agent logs what changed
- [ ] If API changed: `api-sync-checker` + `doc-updater`
- [ ] If security-sensitive: `security-auditor`
- [ ] If DB changed: `migration-helper`

## Agent Assignment Summary

| Agent | Tasks | Total |
|-------|-------|-------|
| `ml-engineer` | 02, 03, 04, 05, 07, 09, 10, 12, 14, 18, 19, 21, 22, 23 | 14 |
| `backend-developer` | 08, 13, 17 | 3 |
| `test-runner` | 06, 11, 16, 20, 25 | 5 |
| `codebase-researcher` | 01 | 1 |
| `e2e-tester` | 15, 24 | 2 |
| `security-reviewer` | 26 | 1 |
| `perf-checker` | 27 | 1 |
| `doc-updater` | 28 | 1 |
| `context-manager` | 29 | 1 |

## New Dependencies to Install

```bash
# Phase A (PPO)
pip install "stable-baselines3[extra]" torch

# Phase C (Regime classifier)
pip install xgboost joblib

# Add to agent/pyproject.toml:
# [project.optional-dependencies]
# ml = ["stable-baselines3[extra]", "torch", "xgboost", "joblib"]
```

## Quick Start

To begin execution right now:
```
1. Task 01: delegate to codebase-researcher → "Research gym envs & backtest API surface"
2. Task 07: delegate to ml-engineer → "Genetic algorithm core (genome, operators)"
3. Task 12: delegate to ml-engineer → "Regime classifier training"
4. Task 17: delegate to backend-developer → "Risk agent core"
```
These 4 tasks have zero dependencies and can start simultaneously.
