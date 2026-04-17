#!/usr/bin/env bash
# =============================================================================
# AgentExchange Platform — Backup Health Check
# =============================================================================
#
# Verifies that a recent database backup exists.
# Returns exit code 0 if a backup was created within the last 26 hours,
# exit code 1 otherwise.
#
# Used by:
#   - docker-compose healthcheck on the db-backup sidecar
#   - Prometheus node_exporter textfile collector (when wired up)
#   - Manual spot-checks
#
# USAGE
# ─────────────────────────────────────────────────────────────
#   ./scripts/check_backup_health.sh
#
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────
#   BACKUP_DIR   Directory to check for backups  (default: /backups)
#
# =============================================================================

BACKUP_DIR="${BACKUP_DIR:-/backups}"
STALENESS_MINUTES=1560   # 26 hours — allows a 2-hour window past the 24-hour schedule

RECENT=$(find "$BACKUP_DIR" -maxdepth 1 \
    \( -name "agentexchange-daily-*.sql.gz" -o -name "agentexchange-weekly-*.sql.gz" \) \
    -mmin -"${STALENESS_MINUTES}" 2>/dev/null | wc -l)

if [ "$RECENT" -eq 0 ]; then
    echo "[$(date -Iseconds)] WARNING: No backup found in the last 26 hours in ${BACKUP_DIR}!"
    exit 1
fi

echo "[$(date -Iseconds)] OK: ${RECENT} recent backup(s) found in ${BACKUP_DIR}"
exit 0
