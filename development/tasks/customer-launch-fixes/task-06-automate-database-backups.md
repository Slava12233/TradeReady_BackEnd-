---
task_id: 06
title: "Automate database backups"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["scripts/backup_database.sh", "docker-compose.yml"]
tags:
  - task
  - infrastructure
  - backup
  - database
  - P0
---

# Task 06: Automate database backups

## Assigned Agent: `backend-developer`

## Objective
A backup script exists (`scripts/backup_database.sh`) but no cron job runs it. Data between deploys has no backup. Set up automated daily backups.

## Context
Infrastructure audit (SR-07) flagged this as a P0 data loss risk. The script is ready, it just needs scheduling.

## Files to Modify
- `scripts/backup_database.sh` — Verify it works, add retention policy (keep last 7 daily + 4 weekly)
- `docker-compose.yml` — Optionally add a backup sidecar container with cron
- Create `scripts/backup_cron.sh` — Wrapper with logging and error notification

## Acceptance Criteria
- [ ] Database backup runs automatically on a daily schedule
- [ ] Backup script includes retention (delete backups older than 30 days)
- [ ] Backup failure sends a notification (stderr logging at minimum)
- [ ] Documented: how to restore from backup
- [ ] Backup location is configurable via environment variable

## Agent Instructions
1. Read `scripts/CLAUDE.md` for existing script patterns
2. Read the existing `scripts/backup_database.sh` to understand what it does
3. Add a cron-based scheduling mechanism — either host crontab entry or a Docker sidecar
4. Add retention cleanup (find + delete by age)
5. Document the restore procedure in a comment block at the top of the script

## Estimated Complexity
Low — script enhancement + cron setup
