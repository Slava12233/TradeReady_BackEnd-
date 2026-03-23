---
type: task-board
title: "Trading Agent Master Plan — 10% Monthly Returns"
status: active
plan_source: "development/trading-agent-master-plan.md"
created: 2026-03-22
tags:
  - task-board
  - trading-agent
  - master-plan
---

# Task Board: Trading Agent Master Plan — 10% Monthly Returns

**Plan source:** `development/trading-agent-master-plan.md`
**Generated:** 2026-03-22
**Total tasks:** 37
**Agents involved:** backend-developer (14), ml-engineer (8), migration-helper (1), e2e-tester (2), frontend-developer (2), security-reviewer (1), perf-checker (1), deploy-checker (1), test-runner (used in pipelines), code-reviewer (used in pipelines), context-manager (final step always)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Apply Alembic migrations 018/019 | migration-helper | 0 | — | pending |
| 02 | Seed pairs and backfill historical data | e2e-tester | 0 | 01 | pending |
| 03 | Provision 5 agent accounts | e2e-tester | 0 | 01 | pending |
| 04 | Fix RedisMemoryCache glob bug | backend-developer | 0 | — | pending |
| 05 | Wire LogBatchWriter into AgentServer | backend-developer | 0 | — | pending |
| 06 | Register IntentRouter handlers | backend-developer | 0 | — | pending |
| 07 | Add TTL to working memory + fix PermissionDenied | backend-developer | 0 | — | pending |
| 08 | Enhance regime classifier features | ml-engineer | 1 | 02 | pending |
| 09 | Train regime classifier | ml-engineer | 1 | 08 | pending |
| 10 | Add composite reward function for RL | ml-engineer | 1 | 02 | pending |
| 11 | Train PPO RL multi-seed | ml-engineer | 1 | 10 | pending |
| 12 | Upgrade evolutionary fitness function | ml-engineer | 1 | 02 | pending |
| 13 | Run evolutionary optimization | ml-engineer | 1 | 03, 12 | pending |
| 14 | Optimize ensemble weights | ml-engineer | 1 | 09, 11, 13 | pending |
| 15 | Full pipeline backtest validation | ml-engineer | 1 | 14 | pending |
| 16 | Implement position sizing overhaul | backend-developer | 2 | — | pending |
| 17 | Implement configurable drawdown profiles | backend-developer | 2 | — | pending |
| 18 | Implement correlation-aware portfolio construction | backend-developer | 2 | — | pending |
| 19 | Implement strategy-level circuit breakers | backend-developer | 2 | — | pending |
| 20 | Add advanced order type tools to SDK | backend-developer | 2 | — | pending |
| 21 | Implement drawdown recovery protocol | backend-developer | 2 | 17 | pending |
| 22 | Security review of risk management changes | security-reviewer | 2 | 16-21 | pending |
| 23 | Implement dynamic ensemble weights | backend-developer | 3 | 14, 16 | pending |
| 24 | Add enhanced signal generation tools | backend-developer | 3 | — | pending |
| 25 | Implement concept drift detection | backend-developer | 3 | 14 | pending |
| 26 | Implement smart pair selector | backend-developer | 3 | — | pending |
| 27 | Integrate WebSocket for real-time data | backend-developer | 3 | — | pending |
| 28 | Build automated retraining pipeline | ml-engineer | 4 | 14, 23 | pending |
| 29 | Implement walk-forward validation | ml-engineer | 4 | 14 | pending |
| 30 | Create decision outcome settlement task | backend-developer | 4 | — | pending |
| 31 | Wire strategy attribution to ensemble weights | backend-developer | 4 | 23 | pending |
| 32 | Implement memory-driven learning loop | backend-developer | 4 | — | pending |
| 33 | Add backtest comparison and decision analysis tools | backend-developer | 5 | — | pending |
| 34 | Build battle system frontend | frontend-developer | 5 | — | pending |
| 35 | Build agent trading dashboard | frontend-developer | 5 | — | pending |
| 36 | Production monitoring and Prometheus fixes | deploy-checker | 6 | — | pending |
| 37 | Performance optimization pass | perf-checker | 6 | 27 | pending |

## Execution Order

### Phase 0: Foundation (Must Do First)
Run these first — tasks 04-07 can run in parallel:
```
01 (migrations) → 02 (data load), 03 (agents)
04, 05, 06, 07 (bug fixes — all parallel)
```

### Phase 1: Training Pipeline (After Phase 0)
Sequential chain with parallel branches:
```
08 → 09 (regime: enhance → train)
10 → 11 (RL: reward → train)
12 → 13 (GA: fitness → evolve)
All three converge → 14 (ensemble weights) → 15 (validation backtest)
```

### Phase 2: Risk Hardening (Parallel with Phase 1)
All can run in parallel, then security review:
```
16, 17, 18, 19, 20 (parallel risk tasks)
17 → 21 (drawdown → recovery)
All → 22 (security review)
```

### Phase 3: Intelligence (After Phase 1 + 2)
```
23 (dynamic weights — needs 14 + 16)
24, 25, 26, 27 (parallel: signals, drift, pairs, websocket)
```

### Phase 4: Continuous Learning (After Phase 3)
```
28 (retrain pipeline), 29 (walk-forward) — parallel
30, 31, 32 — parallel
```

### Phase 5: Platform + UI (After Phase 2 + 3)
```
33, 34, 35 — can run in parallel
```

### Phase 6: Hardening (After Phase 4)
```
36, 37 — parallel
```

## New Agents Created
None — all 16 existing agents cover the required capabilities.
