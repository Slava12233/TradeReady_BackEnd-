# Task Board: Agent Deployment & Training

**Plan source:** `development/plan.md`
**Generated:** 2026-03-20
**Total tasks:** 23
**Agents involved:** backend-developer (6), ml-engineer (5), e2e-tester (4), security-reviewer (2), codebase-researcher (1), test-runner (1), deploy-checker (1), doc-updater (1), context-manager (1), perf-checker (1)

## Task Overview

| # | Task | Agent | Phase | Depends On | Status |
|---|------|-------|-------|------------|--------|
| 01 | Add ML optional deps to pyproject.toml | backend-developer | 1 | — | pending |
| 02 | Verify platform services & prerequisites | deploy-checker | 2 | 01 | pending |
| 03 | Backfill historical data & validate coverage | e2e-tester | 3 | 02 | pending |
| 04 | Run V1 agent full validation (4 workflows) | e2e-tester | 4 | 03 | pending |
| 05 | Train regime classifier | ml-engineer | 5 | 03 | pending |
| 06 | Train PPO agent (3 seeds) | ml-engineer | 5 | 03 | pending |
| 07 | Evaluate PPO models vs benchmarks | ml-engineer | 5 | 06 | pending |
| 08 | Investigate battle historical mode bug | codebase-researcher | 5 | 02 | pending |
| 09 | Fix battle historical mode (if broken) | backend-developer | 5 | 08 | pending |
| 10 | Run evolutionary training (30 gen) | ml-engineer | 6 | 09 | pending |
| 11 | Analyze evolution results | ml-engineer | 6 | 10 | pending |
| 12 | Validate individual strategies (regime + PPO) | e2e-tester | 7 | 05, 07 | pending |
| 13 | Run ensemble weight optimization | e2e-tester | 8 | 05, 07, 11 | pending |
| 14 | Run ensemble final validation | e2e-tester | 8 | 13 | pending |
| 15 | Fix N+1 API call patterns (6 locations) | backend-developer | 9 | — | pending |
| 16 | Fix blocking sync in async contexts | backend-developer | 9 | — | pending |
| 17 | Fix unbounded growth & add caching | backend-developer | 9 | — | pending |
| 18 | Add model checksum verification | security-reviewer | 9 | — | pending |
| 19 | Remove CLI --api-key arguments | security-reviewer | 9 | — | pending |
| 20 | Create agent Dockerfile & compose service | backend-developer | 10 | 01 | pending |
| 21 | Run full test suite & fix failures | test-runner | 11 | 15, 16, 17, 18, 19 | pending |
| 22 | Update documentation for deployment | doc-updater | 12 | 20, 21 | pending |
| 23 | Final context update | context-manager | 12 | 22 | pending |

## Execution Order

### Group 1 — Setup (sequential, do first)
```
01 → 02 → 03 → 04
```

### Group 2 — Training (parallel after Group 1, step 03)
```
05 (regime)     ─────────────────────────────┐
06 → 07 (PPO)   ────────────────────────────┤→ 12 (validate) → 13 → 14
08 → 09 → 10 → 11 (evolution) ─────────────┘
```

### Group 3 — Fixes (parallel, no dependencies on training)
```
15 (N+1 API)    ──┐
16 (async fixes) ─┤→ 21 (test suite)
17 (growth caps) ─┤
18 (checksums)   ─┤
19 (CLI keys)    ─┘
```

### Group 4 — Docker (parallel with Group 3)
```
20 (Dockerfile)
```

### Group 5 — Final (after all above)
```
21 → 22 → 23
```

## New Agents Created
None — all 16 existing agents cover the required capabilities.
