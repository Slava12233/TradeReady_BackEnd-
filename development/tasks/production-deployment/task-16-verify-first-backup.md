---
task_id: 16
title: "Verify first backup ran (2AM UTC)"
type: task
agent: "deploy-checker"
phase: 3
depends_on: [7]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: ["scripts/backup_db.sh", "scripts/restore_database.sh"]
tags:
  - task
  - backup
  - post-deploy
---

# Task 16: Verify first backup ran (2AM UTC)

## Objective
Confirm the automated backup sidecar runs successfully at the scheduled time.

## Context
Task 06 (customer launch fixes) added a `db-backup` sidecar that runs daily at 2AM UTC with 7 daily + 4 weekly retention.

## Acceptance Criteria
- [ ] After 2AM UTC: `docker compose logs db-backup` shows successful backup
- [ ] Backup file exists in the `backup_data` volume: `docker compose exec db-backup ls -lh /backups/`
- [ ] Filename matches format: `agentexchange-daily-YYYY-MM-DD.sql.gz` (or weekly if Sunday)
- [ ] Backup file size is reasonable (not 0 bytes, not absurdly small)
- [ ] `docker compose exec db-backup ./check_backup_health.sh` exits 0
- [ ] Restore dry-run works: test restoring to a temp database

## Dependencies
Task 07 — db-backup sidecar must be running.

## Agent Instructions
1. Wait until after 2AM UTC (or trigger manually: `docker compose exec db-backup /scripts/backup_db.sh`)
2. Check logs: `docker compose logs db-backup | tail -30`
3. List backups: `docker compose exec db-backup ls -lh /backups/`
4. Verify backup integrity by restoring to a test DB (optional but recommended):
   ```bash
   docker compose exec db-backup bash
   RESTORE_DB=test_restore /scripts/restore_database.sh /backups/agentexchange-daily-XXXX.sql.gz
   ```
5. Verify the health check script: `docker compose exec db-backup /scripts/check_backup_health.sh`
6. Document restore procedure in runbook

## Estimated Complexity
Medium — requires waiting for scheduled time OR manual trigger + restore test
