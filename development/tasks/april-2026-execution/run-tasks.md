---
type: task
title: "Execution Guide — April 2026 Execution Plan"
created: 2026-04-12
tags:
  - task
  - execution-guide
---

# Execution Guide: April 2026 Execution Plan

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Phase 1: Parallel Start (Day 1-2)

**Group 1 — Independent, start immediately:**
- A-01 (deploy-checker) — Verify Docker services
- D-01 (frontend-developer) — Fix vitest setup
- E-01 (backend-developer) — Add TimescaleDB to CI
- E-05 (frontend-developer) — Add frontend build to CI

**Group 2 — After A-01:**
- A-02 → A-03 → A-04 → A-05 (backend-developer, sequential)

**Group 3 — After D-01:**
- D-02 (frontend-developer) — Create test utilities

**Group 4 — After E-01:**
- E-02, E-03, E-04 (backend-developer, parallel)

### Phase 2: Training + Tests (Day 2-5)

**Group 5 — After A-05 (data loaded):**
- B-01 → B-02 → B-03 → B-04 → B-05 (ml-engineer, sequential, long-running)

**Group 6 — After D-02 (all parallel):**
- D-03 (dashboard), D-04 (agents), D-05 (battles), D-06 (strategies), D-07 (market), D-08 (wallet), D-09 (shared), D-10 (hooks)

**Group 7 — After E-02:**
- E-07, E-08 (backend-developer, parallel)

**Group 8 — After E-02..E-06:**
- E-09 → E-10 → E-11 (sequential)

### Phase 3: Trading + Validation (Day 5-8)

**Group 9 — After B-05:**
- B-06 → B-07 → B-08 → B-09 (ml-engineer + doc-updater, sequential)

**Group 10 — After A-06:**
- C-01 → C-02 → C-03 → C-04 → C-05 → C-06 → C-07 → C-08 (sequential)

**Group 11 — After D-03..D-10:**
- D-11 (test-runner) → D-12 (frontend-developer)

## Post-Task Checklist

After each code-changing task completes:
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed
- [ ] If API changed: api-sync-checker + doc-updater
- [ ] If security-sensitive: security-auditor
- [ ] If DB changed: migration-helper

## Critical Path Warning

The critical path is: **A-04 → A-05 → B-02 → B-05 → C-03 → C-05 → C-07**

Any delay on this chain delays the entire plan. Prioritize these tasks above all others. Tracks D and E run in parallel and do not block the critical path.

## Agent Quick Reference

| Agent | Tasks | When to Use |
|-------|-------|-------------|
| deploy-checker | A-01 | Infrastructure verification |
| backend-developer | A-02..A-05, E-01..E-04, E-07..E-09 | Python code, scripts, CI config |
| ml-engineer | B-01..B-08, C-03..C-05, C-07 | ML training, trading loop |
| frontend-developer | D-01..D-10, D-12, E-05, E-06 | React/TS tests, frontend CI |
| e2e-tester | A-06, C-01, C-02, C-06 | End-to-end validation |
| test-runner | D-11, E-10 | Running test suites |
| doc-updater | A-07, B-09, C-08, E-11 | Documentation |
