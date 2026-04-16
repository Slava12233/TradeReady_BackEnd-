---
type: task-board
title: "Execution Guide — Production Deployment"
tags:
  - execution
  - guide
  - deployment
---

# Execution Guide: Production Deployment

## How to Run Tasks

Each task file specifies an `agent` in its frontmatter. For deployment tasks, most are hands-on operations that require SSH access to the production server — these should be executed by a human operator with the `deploy-checker` agent providing validation.

### Workflow
1. Read the task file
2. If the task is an operator action (SSH, config edit, service start): perform the action on the server
3. Delegate validation to the `deploy-checker` agent
4. Update task `status` field: `"pending"` → `"in_progress"` → `"completed"` or `"failed"`

## Execution Order

Respect the `depends_on` field. Tasks with no unfulfilled dependencies can run in parallel.

### Phase 1: Pre-Deploy Configuration (Sequential)
**Estimated duration: 30 minutes**

1. **Task 01**: Pull latest code → `deploy-checker`
2. After Task 01, run in parallel:
   - **Task 02**: Apply migration 024 → `migration-helper`
   - **Task 03**: Set ENVIRONMENT=production → `deploy-checker`
   - **Task 06**: Configure Alertmanager SMTP → `deploy-checker`
3. After Task 03, run in parallel:
   - **Task 04**: Verify JWT_SECRET → `deploy-checker`
   - **Task 05**: Verify DATABASE_URL → `deploy-checker`

**Gate:** All Phase 1 tasks must complete before Phase 2 starts.

### Phase 2: Deploy & Smoke Tests (Parallel After Task 07)
**Estimated duration: 45 minutes**

1. **Task 07**: `docker compose up -d` → `deploy-checker`
2. After Task 07, run in parallel:
   - **Task 08**: Verify Alertmanager UI → `deploy-checker`
   - **Task 09**: Verify API health → `deploy-checker`
   - **Task 10**: Verify root URL → `e2e-tester`
   - **Task 11**: Verify legal pages → `e2e-tester`
   - **Task 12**: Test registration → `e2e-tester`
   - **Task 13**: Test Cmd+K search → `e2e-tester`
   - **Task 14**: Verify OG image → `deploy-checker`

**Gate:** If any Phase 2 task fails, consider rollback (see Rollback Procedure below).

### Phase 3: Post-Deploy Monitoring (First 24 Hours)
**Estimated duration: 24 hours observation**

1. **Task 15**: Monitor Alertmanager baseline → `deploy-checker`
2. **Task 16**: Verify first backup (after 2AM UTC) → `deploy-checker`
3. **Task 17**: Review Grafana dashboard → `deploy-checker`
4. **Task 18**: Monitor rate-limit 429s → `deploy-checker`

## Parallel Execution Groups

### Group A — Pre-Deploy Validation (after Task 01)
Tasks 02, 03, 06 can run concurrently.

### Group B — Credential Checks (after Task 03)
Tasks 04, 05 can run concurrently.

### Group C — Smoke Tests (after Task 07)
Tasks 08, 09, 10, 11, 12, 13, 14 can run concurrently.

### Group D — Post-Deploy Monitoring (after Task 07)
Tasks 15, 16, 17, 18 can run concurrently over 24 hours.

## Sequential Chains

- Task 01 → Task 02 (migration needs code)
- Task 01 → Task 03 → Tasks 04, 05 (env must be set before credential checks)
- All Phase 1 → Task 07 (deploy only after pre-deploy complete)
- Task 07 → All Phase 2 + 3 tasks

## Rollback Procedure

If Phase 2 smoke tests fail critically:

1. **Stop services**: `docker compose down`
2. **Rollback migration**: `alembic downgrade $ROLLBACK_REV` (captured in Task 02) or `alembic downgrade -1`
3. **Revert code**: `git reset --hard <previous-deploy-sha>`
4. **Restart services**: `docker compose up -d`
5. **Verify health**: re-run Task 09
6. **Investigate the failure** in a non-production environment before retrying

## Post-Task Checklist

After each task completes:
- [ ] Update task `status` field
- [ ] Log any issues encountered in the task file's "Notes" section
- [ ] If a task fails: don't force-pass it — investigate or rollback

After the final task:
- [ ] `context-manager` agent updates `development/context.md`
- [ ] Mark the board as DONE in `development/CLAUDE.md`
- [ ] Write a deployment report in `development/tasks/production-deployment/`

## Agent Task Counts

| Agent | Tasks | IDs |
|-------|-------|-----|
| deploy-checker | 13 | 01, 03, 04, 05, 06, 07, 08, 09, 14, 15, 16, 17, 18 |
| migration-helper | 1 | 02 |
| e2e-tester | 4 | 10, 11, 12, 13 |

## Timeline

| Milestone | Target | Effort |
|-----------|--------|--------|
| Phase 1 complete | Apr 17 morning | 30 min |
| Phase 2 complete (smoke tests pass) | Apr 17 afternoon | 45 min |
| Phase 3 complete (24h observation) | Apr 18 afternoon | Passive monitoring |
| Soft launch to 5-10 users | Apr 20 | Day 3 post-deploy |
