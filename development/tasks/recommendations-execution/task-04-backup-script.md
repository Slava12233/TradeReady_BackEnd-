---
task_id: 4
title: "Create database backup script + health check"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files:
  - "scripts/backup_db.sh"
  - "scripts/check_backup_health.sh"
tags:
  - task
  - infrastructure
  - backup
---

# Task 04: Create Database Backup Script + Health Check

## Assigned Agent: `backend-developer`

## Objective
Create `scripts/backup_db.sh` for daily automated pg_dump backups with 30-day retention and a health check script.

## Context
R4 from the C-level report. Currently only pre-deploy backups exist. Need scheduled daily backups. The plan has the full script at `development/recommendations-execution-plan.md` Section R4.

## Files to Modify/Create
- `scripts/backup_db.sh` — Daily backup: pg_dump via Docker, gzip, 30-day prune, optional S3 upload
- `scripts/check_backup_health.sh` — Returns exit 1 if no backup in last 26 hours

## Acceptance Criteria
- [ ] `scripts/backup_db.sh` exists and is executable
- [ ] Uses `set -euo pipefail` for safety
- [ ] Excludes hypertable data (ticks, candles_backfill, snapshots)
- [ ] Compresses with gzip
- [ ] 30-day retention with automatic pruning
- [ ] S3 upload section present (commented out, ready to enable)
- [ ] `scripts/check_backup_health.sh` exists and is executable
- [ ] Health check returns exit 0 when recent backup exists, exit 1 when missing
- [ ] Both scripts have clear usage comments

## Agent Instructions
1. Read `development/recommendations-execution-plan.md` Section R4 for the full script
2. Read `.github/workflows/deploy.yml` for the existing pg_dump flags pattern
3. Create both scripts following the plan exactly
4. Make them executable with `chmod +x`

## Estimated Complexity
Low — scripts are fully specified in the plan.
