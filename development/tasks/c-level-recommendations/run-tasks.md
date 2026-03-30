---
type: task
title: "Execution Guide: C-Level Recommendations"
tags:
  - execution
  - guide
---

# Execution Guide: C-Level Report Recommendations

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. To execute a task:

1. Read the task file
2. Delegate to the specified agent using the Agent tool with the task content as the prompt
3. After the agent completes, update the task's `status` field:
   - `"pending"` → `"in_progress"` → `"completed"` or `"failed"`
4. Run mandatory post-change agents (code-reviewer, test-runner, context-manager)

## Execution Order

Always respect the `depends_on` field. Tasks with no dependencies can run in parallel.

### Parallel Execution Groups

**Group A — Start immediately (no dependencies):**
- R1-01 (create .env) → `backend-developer`
- R2-02 (BudgetManager ensure_future) → `security-reviewer`
- R2-05 (PPO checksum) → `security-reviewer`
- R2-06 (joblib checksum) → `security-reviewer`
- R2-07 (--api-key audit) → `security-reviewer`
- R2-08 (float/Decimal fixes) → `backend-developer`
- R4-01 (fix float(c.close)) → `backend-developer`
- R4-02 (audit float/Decimal) → `code-reviewer`
- R4-03 (5 MEDIUM perf fixes) → `backend-developer`
- R4-04 (verify Redis fix) → `test-runner`
- R4-05 (verify writer fix) → `test-runner`

**Group B — After R1-02 (Docker running):**
- R1-03 (apply migrations) → `migration-helper`
- R2-03 (Redis requirepass) → `security-reviewer`

**Group C — After R1-03 (DB ready):**
- R1-04 (seed pairs) → `backend-developer`
- R2-01 (ADMIN role check) → `security-reviewer`
- R2-04 (audit log table) → `security-reviewer`

**Group D — After R1-05 (platform healthy):**
- R1-06 (Grafana/Prometheus) → `deploy-checker`
- R1-07 (backfill history) → `backend-developer` [LONG RUNNING]
- R1-08 (provision agents) → `e2e-tester`
- R1-09 (smoke test) → `e2e-tester`

**Group E — After all security fixes (R2-01..R2-08):**
- R2-09 (security audit) → `security-auditor`
- R2-10 (regression tests) → `test-runner`

**Group F — After R1-07 (data loaded):**
- R3-01 (train regime) → `ml-engineer`
- R3-02 (validate accuracy) → `ml-engineer`
- R3-03 (switcher demo) → `ml-engineer`
- R3-04 (walk-forward) → `ml-engineer`
- R3-05 (backtest comparison) → `ml-engineer`
- R3-06 (baseline metrics) → `ml-engineer`

**Group G — After R3-01 (model trained):**
- R5-01 (Celery retrain task) → `backend-developer`
- R5-02 (beat schedule) → `backend-developer`
- R5-03 (drift detector wiring) → `backend-developer`
- R5-04 (retrain metrics) → `backend-developer`
- R5-05 (Grafana panel) → `backend-developer`
- R5-06 (retrain tests) → `test-runner`

**Group H — After all tasks:**
- QG-01 (code review) → `code-reviewer`
- QG-02 (full test suite) → `test-runner`
- QG-03 (update context) → `context-manager`

### Sequential Chains

```
R1-01 → R1-02 → R1-03 → R1-04 → R1-05 → R1-07 → R3-01 → R5-01 → R5-02
                                       ↘ R1-08 → R1-09
R2-01..R2-08 → R2-09 → R2-10
R3-01 → {R3-02, R3-03, R3-04, R3-05} → R3-06
R5-01 → {R5-02, R5-03, R5-04} → R5-05
All → QG-01 → QG-02 → QG-03
```

## Post-Task Checklist

After each task completes:
- [ ] code-reviewer agent validates the changes
- [ ] test-runner agent runs relevant tests
- [ ] context-manager agent logs what changed
- [ ] If API changed: api-sync-checker + doc-updater
- [ ] If security-sensitive: security-auditor
- [ ] If DB changed: migration-helper validates first

## Estimated Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Phase 1: Infrastructure | 1-2 days | R1-07 backfill is the bottleneck (10-30 min) |
| Phase 2: Security + Quality | 2-3 days | Most fixes are pure code; parallel with Phase 1 |
| Phase 3: Training Pipeline | 1-2 days | Regime training < 2 min; walk-forward takes longer |
| Phase 4: Retraining | 1-2 days | Celery integration + testing |
| Phase 5: Quality Gate | 1 day | Sequential: review → test → context |
| **Total** | **5-8 days** | Heavy parallelism between Phase 1+2 saves 2-3 days |
