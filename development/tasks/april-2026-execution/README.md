---
type: task-board
title: "April 2026 Execution Plan — From Platform Built to Platform Trading"
source: "[[april-2026-execution-plan]]"
created: 2026-04-12
status: active
tags:
  - task-board
  - execution
  - rl-training
  - ci-cd
  - frontend-testing
  - live-trading
---

# Task Board: April 2026 Execution Plan

**Plan source:** `development/april-2026-execution-plan.md`
**Generated:** 2026-04-12
**Total tasks:** 47
**Agents involved:** ml-engineer (11), backend-developer (10), frontend-developer (9), e2e-tester (4), doc-updater (4), test-runner (2), deploy-checker (1)
**Timeline:** 14 days (2026-04-12 → 2026-04-26)

## Task Overview

### Track A: Load Historical Data (Days 1-2)

| # | Task | Agent | Depends On | Status |
|---|------|-------|------------|--------|
| A-01 | Verify Docker services running | deploy-checker | — | pending |
| A-02 | Refresh trading pairs | backend-developer | A-01 | pending |
| A-03 | Dry-run daily backfill | backend-developer | A-02 | pending |
| A-04 | Execute daily backfill (top 20) | backend-developer | A-03 | pending |
| A-05 | Execute hourly backfill (top 5) | backend-developer | A-04 | pending |
| A-06 | Validate data completeness | e2e-tester | A-05 | pending |
| A-07 | Document data inventory | doc-updater | A-06 | pending |

### Track B: PPO Training Pipeline (Days 2-5)

| # | Task | Agent | Depends On | Status |
|---|------|-------|------------|--------|
| B-01 | Verify gym installation | ml-engineer | A-05 | pending |
| B-02 | Smoke-test headless env | ml-engineer | B-01 | pending |
| B-03 | Run PPO training (100K steps) | ml-engineer | B-02 | pending |
| B-04 | Verify TensorBoard output | ml-engineer | B-03 | pending |
| B-05 | Run full PPO training (500K steps) | ml-engineer | B-04 | pending |
| B-06 | Evaluate OOS performance | ml-engineer | B-05 | pending |
| B-07 | Validate with DSR API | ml-engineer | B-06 | pending |
| B-08 | Save model artifact | ml-engineer | B-07 | pending |
| B-09 | Document training results | doc-updater | B-08 | pending |

### Track C: End-to-End Trade Loop (Days 5-8)

| # | Task | Agent | Depends On | Status |
|---|------|-------|------------|--------|
| C-01 | Provision test agent | e2e-tester | A-06 | pending |
| C-02 | Verify agent SDK connectivity | e2e-tester | C-01 | pending |
| C-03 | Run single observe cycle | ml-engineer | C-02 | pending |
| C-04 | Run single decide cycle | ml-engineer | C-03 | pending |
| C-05 | Execute first live trade | ml-engineer | C-04 | pending |
| C-06 | Verify trade in DB + API | e2e-tester | C-05 | pending |
| C-07 | Run full trade cycle | ml-engineer | C-06 | pending |
| C-08 | Document integration findings | doc-updater | C-07 | pending |

### Track D: Frontend Test Coverage (Days 1-10)

| # | Task | Agent | Depends On | Status |
|---|------|-------|------------|--------|
| D-01 | Fix vitest setup | frontend-developer | — | pending |
| D-02 | Create test utilities | frontend-developer | D-01 | pending |
| D-03 | Test dashboard components (5) | frontend-developer | D-02 | pending |
| D-04 | Test agent components (4) | frontend-developer | D-02 | pending |
| D-05 | Test battle components (4) | frontend-developer | D-02 | pending |
| D-06 | Test strategy components (3) | frontend-developer | D-02 | pending |
| D-07 | Test market components (3) | frontend-developer | D-02 | pending |
| D-08 | Test wallet components (3) | frontend-developer | D-02 | pending |
| D-09 | Test shared components (5) | frontend-developer | D-02 | pending |
| D-10 | Test hooks (5) | frontend-developer | D-02 | pending |
| D-11 | Run full frontend test suite | test-runner | D-03..D-10 | pending |
| D-12 | Add test script to CI | frontend-developer | D-11, E-05 | pending |

### Track E: CI/CD Pipeline (Days 1-5)

| # | Task | Agent | Depends On | Status |
|---|------|-------|------------|--------|
| E-01 | Add TimescaleDB service | backend-developer | — | pending |
| E-02 | Add integration test job | backend-developer | E-01 | pending |
| E-03 | Add agent test job | backend-developer | E-01 | pending |
| E-04 | Add gym test job | backend-developer | E-01 | pending |
| E-05 | Add frontend build + lint job | frontend-developer | — | pending |
| E-06 | Add frontend test job | frontend-developer | D-11 | pending |
| E-07 | Add dependency caching | backend-developer | E-02 | pending |
| E-08 | Add coverage upload | backend-developer | E-02 | pending |
| E-09 | Update deploy.yml gate | backend-developer | E-02..E-06 | pending |
| E-10 | Test pipeline on branch | test-runner | E-09 | pending |
| E-11 | Document CI/CD pipeline | doc-updater | E-10 | pending |

## Execution Order

### Day 1-2 (Parallel Start)
- **Track A:** A-01 → A-02 → A-03 → A-04 → A-05 → A-06 → A-07 (sequential, long-running)
- **Track D:** D-01 → D-02 (vitest setup)
- **Track E:** E-01 → E-02, E-03, E-04 (parallel after E-01) + E-05 (independent)

### Day 2-5
- **Track B:** B-01 → B-02 → B-03 → B-04 → B-05 (training is long-running)
- **Track D:** D-03, D-04, D-05, D-06, D-07, D-08, D-09 (all parallel after D-02)
- **Track E:** E-07, E-08 (after E-02) + E-09 → E-10 → E-11

### Day 5-7
- **Track B:** B-06 → B-07 → B-08 → B-09
- **Track C:** C-01 → C-02 → C-03 → C-04 → C-05 → C-06
- **Track D:** D-10, D-11

### Day 7-8
- **Track C:** C-07 → C-08
- **Track D:** D-12 (after D-11 + E-05)

### Critical Path
```
A-04 → A-05 → B-02 → B-05 → B-06 → C-03 → C-05 → C-07
```

## New Agents Created
None — all 7 required agents already exist in `.claude/agents/`.
