#!/usr/bin/env bash
# Health check: verify a recent database backup exists.
# Returns exit code 1 if no backup exists from the last 26 hours.
#
# Usage:  ./scripts/check_backup_health.sh
# Wire into Prometheus via node_exporter textfile collector or a custom script exporter.

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RECENT=$(find "$BACKUP_DIR" -name "agentexchange-daily-*.sql.gz" -mmin -1560 | wc -l)
if [ "$RECENT" -eq 0 ]; then
  echo "WARNING: No backup found in the last 26 hours!"
  exit 1
fi
echo "OK: $RECENT recent backup(s) found"
exit 0
