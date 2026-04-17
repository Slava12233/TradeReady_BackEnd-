#!/usr/bin/env bash
# =============================================================================
# AgentExchange Platform — Database Backup Script
# =============================================================================
#
# Creates a compressed pg_dump of all application data (schema + data).
# Excludes heavy, regenerable time-series hypertables (ticks, candles_backfill,
# portfolio_snapshots, backtest_snapshots, battle_snapshots).
#
# RETENTION POLICY
# ─────────────────
#   Daily  : keep last 7  (agentexchange-daily-YYYYMMDD-HHMMSS.sql.gz)
#   Weekly : keep last 4  (agentexchange-weekly-YYYYMMDD-HHMMSS.sql.gz)
#   Weekly backups are written automatically on Sundays (ISO day 7).
#
# EXECUTION MODES
# ─────────────────
#   Direct (sidecar container) — set POSTGRES_HOST to the DB hostname.
#     pg_dump connects over the Docker network. No docker compose exec needed.
#
#   Via docker compose exec (host cron) — leave POSTGRES_HOST unset.
#     pg_dump is invoked inside the timescaledb container via:
#       docker compose exec -T timescaledb pg_dump ...
#
# USAGE
# ─────────────────
#   # From host (cron):
#   COMPOSE_DIR=/opt/agentexchange ./scripts/backup_db.sh
#
#   # From sidecar container (POSTGRES_HOST is set by docker-compose):
#   /scripts/backup_db.sh
#
#   # Host crontab entry:
#   0 2 * * * BACKUP_DIR=/backups COMPOSE_DIR=/opt/agentexchange \
#             /opt/agentexchange/scripts/backup_db.sh \
#             >> /var/log/agentexchange-backup.log 2>&1
#
# ENVIRONMENT VARIABLES
# ─────────────────────
#   BACKUP_DIR          Backup destination directory    (default: /backups)
#   COMPOSE_DIR         Docker Compose project root     (default: current directory)
#   POSTGRES_HOST       DB hostname (sets direct mode)  (default: unset → exec mode)
#   POSTGRES_PORT       DB port                         (default: 5432)
#   POSTGRES_USER       PostgreSQL username             (loaded from .env if not set)
#   POSTGRES_PASSWORD   PostgreSQL password             (loaded from .env if not set)
#   POSTGRES_DB         PostgreSQL database name        (loaded from .env if not set)
#
# RESTORE
# ─────────────────
#   See scripts/restore_database.sh for full restore instructions.
#   Quick reference:
#
#     # List available backups
#     ls -lht /backups/agentexchange-*.sql.gz
#
#     # Restore (destructive — overwrites target database)
#     gunzip -c /backups/agentexchange-daily-20260415-020001.sql.gz \
#       | docker compose exec -T timescaledb psql \
#           -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
#
#     # Non-destructive inspect into alternate database
#     gunzip -c /backups/agentexchange-daily-20260415-020001.sql.gz \
#       | docker compose exec -T timescaledb psql \
#           -U "${POSTGRES_USER}" -d "agentexchange_restore"
#
# =============================================================================

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/backups}"
COMPOSE_DIR="${COMPOSE_DIR:-$(pwd)}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
DAY_OF_WEEK=$(date +%u)   # 1=Monday … 7=Sunday (ISO 8601)

DAILY_RETAIN=7
WEEKLY_RETAIN=4

POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# ─────────────────────────────────────────────────────────────
# Logging helpers
# ─────────────────────────────────────────────────────────────
log()  { echo "[$(date -Iseconds)] [INFO]  $*"; }
warn() { echo "[$(date -Iseconds)] [WARN]  $*" >&2; }
die()  { echo "[$(date -Iseconds)] [ERROR] $*" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────
# Error trap — notify and clean up on any unhandled error
# ─────────────────────────────────────────────────────────────
_on_error() {
    local exit_code=$?
    local line_no=${1:-unknown}
    warn "Backup FAILED at line ${line_no} (exit code ${exit_code})."
    warn "Last backup file (if any): ${BACKUP_FILE:-<not created>}"
    # Remove an incomplete backup file so health-check does not treat it as valid.
    if [[ -n "${BACKUP_FILE:-}" && -f "$BACKUP_FILE" ]]; then
        rm -f "$BACKUP_FILE"
        warn "Removed incomplete backup file: $BACKUP_FILE"
    fi
    exit "${exit_code}"
}
trap '_on_error $LINENO' ERR

# ─────────────────────────────────────────────────────────────
# Load environment (.env in COMPOSE_DIR if vars not already set)
# ─────────────────────────────────────────────────────────────
ENV_FILE="$COMPOSE_DIR/.env"
if [[ -z "${POSTGRES_USER:-}" || -z "${POSTGRES_DB:-}" ]]; then
    if [[ -f "$ENV_FILE" ]]; then
        log "Loading environment from $ENV_FILE"
        set -a
        # shellcheck source=/dev/null
        source "$ENV_FILE"
        set +a
    else
        die ".env not found at $ENV_FILE and POSTGRES_USER/POSTGRES_DB not set."
    fi
fi

: "${POSTGRES_USER:?POSTGRES_USER must be set}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"

# ─────────────────────────────────────────────────────────────
# Determine backup type (daily vs weekly)
# ─────────────────────────────────────────────────────────────
if [[ "$DAY_OF_WEEK" -eq 7 ]]; then
    BACKUP_TYPE="weekly"
else
    BACKUP_TYPE="daily"
fi

BACKUP_FILE="$BACKUP_DIR/agentexchange-${BACKUP_TYPE}-${TIMESTAMP}.sql.gz"

# ─────────────────────────────────────────────────────────────
# Ensure backup directory exists
# ─────────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR" || die "Cannot create backup directory: $BACKUP_DIR"

# ─────────────────────────────────────────────────────────────
# Shared pg_dump flags (table exclusions and format options)
# ─────────────────────────────────────────────────────────────
PGDUMP_FLAGS=(
    -U "${POSTGRES_USER}"
    -d "${POSTGRES_DB}"
    --no-owner
    --no-acl
    --exclude-table-data='_timescaledb_internal._hyper_*'
    --exclude-table-data='ticks'
    --exclude-table-data='candles_backfill'
    --exclude-table-data='portfolio_snapshots'
    --exclude-table-data='backtest_snapshots'
    --exclude-table-data='battle_snapshots'
)

# ─────────────────────────────────────────────────────────────
# Run pg_dump
#   Direct mode : POSTGRES_HOST is set (sidecar container)
#   Exec mode   : POSTGRES_HOST is unset (host cron)
# ─────────────────────────────────────────────────────────────
log "Starting ${BACKUP_TYPE} backup → $BACKUP_FILE"
log "Database: ${POSTGRES_DB}  User: ${POSTGRES_USER}"

if [[ -n "${POSTGRES_HOST:-}" ]]; then
    log "Mode: direct (POSTGRES_HOST=${POSTGRES_HOST})"
    # Pass password via env var (never command line)
    PGPASSWORD="${POSTGRES_PASSWORD:-}" \
        pg_dump -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" \
            "${PGDUMP_FLAGS[@]}" \
        | gzip > "$BACKUP_FILE"
else
    log "Mode: docker compose exec (COMPOSE_DIR=${COMPOSE_DIR})"
    cd "$COMPOSE_DIR"
    docker compose exec -T timescaledb pg_dump \
        "${PGDUMP_FLAGS[@]}" \
        | gzip > "$BACKUP_FILE"
fi

# Verify the file was actually written and is non-empty
if [[ ! -s "$BACKUP_FILE" ]]; then
    die "Backup file is empty or was not created: $BACKUP_FILE"
fi

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
log "Backup written: $BACKUP_FILE ($BACKUP_SIZE)"

# ─────────────────────────────────────────────────────────────
# Retention: prune old daily backups (keep last DAILY_RETAIN)
# ─────────────────────────────────────────────────────────────
mapfile -t daily_files < <(
    find "$BACKUP_DIR" -maxdepth 1 -name "agentexchange-daily-*.sql.gz" \
        | sort -r
)
if [[ ${#daily_files[@]} -gt $DAILY_RETAIN ]]; then
    to_delete=("${daily_files[@]:$DAILY_RETAIN}")
    for f in "${to_delete[@]}"; do
        rm -f "$f"
        log "Pruned old daily backup: $f"
    done
    log "Retained ${DAILY_RETAIN} daily backup(s), pruned ${#to_delete[@]}."
else
    log "Daily backups: ${#daily_files[@]} file(s) — retention limit (${DAILY_RETAIN}) not reached."
fi

# ─────────────────────────────────────────────────────────────
# Retention: prune old weekly backups (keep last WEEKLY_RETAIN)
# ─────────────────────────────────────────────────────────────
mapfile -t weekly_files < <(
    find "$BACKUP_DIR" -maxdepth 1 -name "agentexchange-weekly-*.sql.gz" \
        | sort -r
)
if [[ ${#weekly_files[@]} -gt $WEEKLY_RETAIN ]]; then
    to_delete=("${weekly_files[@]:$WEEKLY_RETAIN}")
    for f in "${to_delete[@]}"; do
        rm -f "$f"
        log "Pruned old weekly backup: $f"
    done
    log "Retained ${WEEKLY_RETAIN} weekly backup(s), pruned ${#to_delete[@]}."
else
    log "Weekly backups: ${#weekly_files[@]} file(s) — retention limit (${WEEKLY_RETAIN}) not reached."
fi

# ─────────────────────────────────────────────────────────────
# Optional: Upload to S3 (uncomment and set S3_BACKUP_BUCKET)
# ─────────────────────────────────────────────────────────────
# if command -v aws &>/dev/null && [[ -n "${S3_BACKUP_BUCKET:-}" ]]; then
#     aws s3 cp "$BACKUP_FILE" \
#         "s3://${S3_BACKUP_BUCKET}/agentexchange/${BACKUP_TYPE}/${TIMESTAMP}.sql.gz"
#     log "Uploaded to S3: s3://${S3_BACKUP_BUCKET}/agentexchange/${BACKUP_TYPE}/${TIMESTAMP}.sql.gz"
# fi

log "Backup job finished successfully (${BACKUP_TYPE})."
