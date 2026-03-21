---
type: task-board
title: Agent Trading Strategies (5 Strategies for 10% Portfolio Improvement)
created: 2026-03-20
status: done
total_tasks: 29
plan_source: "[[agent-strategies-report]]"
tags:
  - task-board
  - ml
  - strategies
  - agent
---

# Task Board: Agent Trading Strategies (5 Strategies for 10% Portfolio Improvement)

**Plan source:** `development/agent-development/agent-strategies-report.md`
**CTO brief:** `development/agent-development/agent-strategies-cto-brief.md`
**Task detail:** `development/tasks/agent-strategies-tasks.md`
**Generated:** 2026-03-20
**Total tasks:** 29
**Agents involved:** ml-engineer (12), backend-developer (3), test-runner (5), codebase-researcher (2), e2e-tester (2), code-reviewer (1), security-reviewer (1), perf-checker (1), doc-updater (1), context-manager (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Research gym envs & backtest API surface | codebase-researcher | A | — | pending |
| 02 | PPO training pipeline setup | ml-engineer | A | 01 | pending |
| 03 | Data preparation & validation script | ml-engineer | A | 01 | pending |
| 04 | PPO training execution & convergence | ml-engineer | A | 02, 03 | pending |
| 05 | PPO evaluation & deployment bridge | ml-engineer | A | 04 | pending |
| 06 | PPO unit & integration tests | test-runner | A | 02, 05 | pending |
| 07 | Genetic algorithm core (genome, operators) | ml-engineer | B | — | pending |
| 08 | Battle integration runner | backend-developer | B | 07 | pending |
| 09 | Evolution loop orchestrator | ml-engineer | B | 07, 08 | pending |
| 10 | Evolution analysis & reporting | ml-engineer | B | 09 | pending |
| 11 | Evolutionary system tests | test-runner | B | 07, 08 | pending |
| 12 | Regime classifier training | ml-engineer | C | — | pending |
| 13 | Strategy version creation (4 regimes) | backend-developer | C | 12 | pending |
| 14 | Regime switching logic | ml-engineer | C | 12, 13 | pending |
| 15 | Regime strategy validation backtests | e2e-tester | C | 14 | pending |
| 16 | Regime system tests | test-runner | C | 12, 14 | pending |
| 17 | Risk agent core | backend-developer | D | — | pending |
| 18 | Veto logic & position sizing | ml-engineer | D | 17 | pending |
| 19 | Risk agent integration with signal strategies | ml-engineer | D | 05, 18 | pending |
| 20 | Risk agent tests | test-runner | D | 17, 18 | pending |
| 21 | Meta-learner signal combiner | ml-engineer | E | 05, 10, 14 | pending |
| 22 | Meta-learner weight optimization via battles | ml-engineer | E | 21 | pending |
| 23 | Full ensemble pipeline | ml-engineer | E | 21, 22, 19 | pending |
| 24 | Ensemble validation & final battle | e2e-tester | E | 23 | pending |
| 25 | Ensemble tests | test-runner | E | 21, 23 | pending |
| 26 | Security review (all strategies) | security-reviewer | Post | 06, 11, 16, 20, 25 | pending |
| 27 | Performance check (training & inference) | perf-checker | Post | 06, 11, 16, 20, 25 | pending |
| 28 | Documentation update (CLAUDE.md, skill.md) | doc-updater | Post | 26, 27 | pending |
| 29 | Context log update | context-manager | Post | 28 | pending |

## Execution Order

### Phase A: PPO Reinforcement Learning (Week 1)
```
Task 01 (research) ──┬──→ Task 02 (pipeline) ──┐
                     └──→ Task 03 (data)  ──────┤
                                                 ├──→ Task 04 (train) → Task 05 (deploy) → Task 06 (tests)
```

### Phase B: Evolutionary Battle-Driven (Week 2)
```
Task 07 (genome) ──┬──→ Task 08 (battles) ──→ Task 09 (evolution) → Task 10 (analysis)
                   └──→ Task 11 (tests)
```

### Phase C: Regime-Adaptive (Week 3)
```
Task 12 (classifier) ──→ Task 13 (strategies) ──→ Task 14 (switcher) ──→ Task 15 (validation)
                    └──→ Task 16 (tests)
```

### Phase D: Risk Agent (Week 3, parallel with C)
```
Task 17 (core) → Task 18 (veto) → Task 19 (integration) → Task 20 (tests)
```

### Phase E: Hybrid Ensemble (Week 4)
```
Task 21 (meta-learner) → Task 22 (weights) → Task 23 (pipeline) → Task 24 (validation) → Task 25 (tests)
```

### Post-Phase: Quality Gates
```
Task 26 (security) ──┐
Task 27 (perf)    ───┤──→ Task 28 (docs) → Task 29 (context)
```

## Parallel Execution Groups

These tasks have no mutual dependencies and CAN run simultaneously:

- **Group 1:** Task 01, Task 07, Task 12, Task 17 (all phase starts)
- **Group 2:** Task 02 + Task 03 (both depend on 01 only)
- **Group 3:** Task 08 + Task 11 (both depend on 07 only)
- **Group 4:** Task 13 + Task 16 (both depend on 12)
- **Group 5:** Task 26 + Task 27 (both post-phase, independent)

## New Agents Created

- **`ml-engineer`** — No existing agent covered RL training, genetic algorithms, or ML classifier implementation. The `backend-developer` handles generic Python services but lacks ML domain expertise (reward engineering, hyperparameter tuning, train/val/test splits, model serialization).

## Stop-Early Criteria

**If any single phase achieves +10% ROI on out-of-sample data, skip remaining phases and focus on production deployment of that strategy.**
