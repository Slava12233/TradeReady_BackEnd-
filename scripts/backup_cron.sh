#!/usr/bin/env bash
# =============================================================================
# AgentExchange Platform — Backup Cron Wrapper
# =============================================================================
#
# This script is the entry point for the `db-backup` Docker sidecar container.
# It installs a crontab that runs the backup daily at 02:00 UTC, then keeps
# the container alive by tailing the log file.
#
# The backup script itself is mounted at /scripts/backup_db.sh inside the
# container (read from the host via a bind mount).
#
# ENVIRONMENT VARIABLES (passed by docker-compose)
# ─────────────────────────────────────────────────
#   BACKUP_DIR        Where to write backup files   (default: /backups)
#   COMPOSE_DIR       Docker Compose project root   (default: /app)
#   POSTGRES_USER     PostgreSQL username
#   POSTGRES_PASSWORD PostgreSQL password
#   POSTGRES_DB       PostgreSQL database name
#   BACKUP_LOG        Log file path                 (default: /var/log/backup.log)
#
# CRON SCHEDULE
# ─────────────────────────────────────────────────
#   Daily at 02:00 UTC  →  backup_db.sh runs
#   Sunday 02:00 UTC    →  backup_db.sh also writes a weekly snapshot
#                          (detected internally via day-of-week check)
#
# =============================================================================

set -euo pipefail

BACKUP_LOG="${BACKUP_LOG:-/var/log/backup.log}"
BACKUP_SCRIPT="${BACKUP_SCRIPT:-/scripts/backup_db.sh}"

log() { echo "[$(date -Iseconds)] [cron-wrapper] $*"; }

# ─────────────────────────────────────────────────────────────
# Validate prerequisites
# ─────────────────────────────────────────────────────────────
if [[ ! -f "$BACKUP_SCRIPT" ]]; then
    echo "[$(date -Iseconds)] [ERROR] Backup script not found: $BACKUP_SCRIPT" >&2
    exit 1
fi

chmod +x "$BACKUP_SCRIPT"

# ─────────────────────────────────────────────────────────────
# Create log file so tail -f does not fail before first run
# ─────────────────────────────────────────────────────────────
touch "$BACKUP_LOG"

# ─────────────────────────────────────────────────────────────
# Write environment file for cron (cron runs with a minimal env)
# ─────────────────────────────────────────────────────────────
ENV_FILE="/etc/backup-env"
cat > "$ENV_FILE" <<EOF
BACKUP_DIR=${BACKUP_DIR:-/backups}
COMPOSE_DIR=${COMPOSE_DIR:-/app}
POSTGRES_USER=${POSTGRES_USER:-}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-}
POSTGRES_DB=${POSTGRES_DB:-}
BACKUP_LOG=${BACKUP_LOG}
BACKUP_SCRIPT=${BACKUP_SCRIPT}
EOF
chmod 600 "$ENV_FILE"

# ─────────────────────────────────────────────────────────────
# Install crontab (daily at 02:00 UTC)
# ─────────────────────────────────────────────────────────────
CRON_JOB="0 2 * * * . ${ENV_FILE} && ${BACKUP_SCRIPT} >> ${BACKUP_LOG} 2>&1"

log "Installing crontab: $CRON_JOB"
echo "$CRON_JOB" | crontab -

# ─────────────────────────────────────────────────────────────
# Start crond in the background, then tail log
# ─────────────────────────────────────────────────────────────
log "Starting crond..."
crond -b -l 8

log "Backup sidecar ready. Daily backup scheduled at 02:00 UTC."
log "Log output: $BACKUP_LOG"
log "Tailing log file..."

# Keep the container alive and stream log output
exec tail -F "$BACKUP_LOG"
