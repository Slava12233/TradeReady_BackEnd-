#!/usr/bin/env bash
# Daily database backup for AgentExchange platform.
# Excludes heavy time-series hypertable data (ticks, candles_backfill,
# portfolio_snapshots, backtest_snapshots) — these are large and regenerable.
# Includes all schema + application data (accounts, agents, orders, trades,
# positions, strategies, webhook_subscriptions, etc.).
#
# Usage:  ./scripts/backup_db.sh
# Cron:   0 3 * * * /path/to/scripts/backup_db.sh >> /var/log/agentexchange-backup.log 2>&1
#
# Environment variables (from .env):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#
# Retention: 30 days (configurable via BACKUP_RETENTION_DAYS)

set -euo pipefail

# --- Configuration ---
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/TradeReady_BackEnd-}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/agentexchange-daily-$TIMESTAMP.sql.gz"

# --- Load environment ---
cd "$COMPOSE_DIR"
set -a && source .env && set +a

# --- Ensure backup directory exists ---
mkdir -p "$BACKUP_DIR"

# --- Run pg_dump via Docker ---
echo "[$(date -Iseconds)] Starting daily backup..."

docker compose exec -T timescaledb pg_dump \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  --no-owner --no-acl \
  --exclude-table-data='_timescaledb_internal._hyper_*' \
  --exclude-table-data='ticks' \
  --exclude-table-data='candles_backfill' \
  --exclude-table-data='portfolio_snapshots' \
  --exclude-table-data='backtest_snapshots' \
  --exclude-table-data='battle_snapshots' \
  | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date -Iseconds)] Backup complete: $BACKUP_FILE ($BACKUP_SIZE)"

# --- Prune old backups ---
PRUNED=$(find "$BACKUP_DIR" -name "agentexchange-daily-*.sql.gz" -mtime +$BACKUP_RETENTION_DAYS -delete -print | wc -l)
echo "[$(date -Iseconds)] Pruned $PRUNED backup(s) older than $BACKUP_RETENTION_DAYS days"

# --- Optional: Upload to S3 ---
# Uncomment and configure if S3 backup is desired:
# if command -v aws &>/dev/null; then
#   aws s3 cp "$BACKUP_FILE" "s3://${S3_BACKUP_BUCKET:-agentexchange-backups}/daily/$TIMESTAMP.sql.gz"
#   echo "[$(date -Iseconds)] Uploaded to S3: s3://${S3_BACKUP_BUCKET}/daily/$TIMESTAMP.sql.gz"
# fi

echo "[$(date -Iseconds)] Backup job finished successfully"
