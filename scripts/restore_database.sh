#!/usr/bin/env bash
# =============================================================================
# AgentExchange Platform — Database Restore Script
# =============================================================================
#
# Restores a compressed pg_dump backup produced by backup_db.sh.
#
# USAGE
# ─────────────────────────────────────────────────────────────
#   ./scripts/restore_database.sh <backup-file.sql.gz>
#
# EXAMPLES
# ─────────────────────────────────────────────────────────────
#   # Restore latest daily backup
#   ./scripts/restore_database.sh /backups/agentexchange-daily-20260415-020001.sql.gz
#
#   # Restore into an alternate database (non-destructive inspection)
#   RESTORE_DB=agentexchange_inspect \
#     ./scripts/restore_database.sh /backups/agentexchange-daily-20260415-020001.sql.gz
#
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────────────────────
#   COMPOSE_DIR    Docker Compose project root      (default: current directory)
#   RESTORE_DB     Database to restore INTO         (default: $POSTGRES_DB from .env)
#   POSTGRES_USER  PostgreSQL username              (loaded from .env if not set)
#   POSTGRES_DB    PostgreSQL database name         (loaded from .env if not set)
#
# WHAT THIS RESTORES
# ─────────────────────────────────────────────────────────────
#   Restores ALL schema and application data from the backup:
#     accounts, agents, balances, orders, trades, positions,
#     strategies, backtest_sessions, battles, webhooks, etc.
#
#   NOT included in backup (and therefore NOT restored):
#     ticks, candles_backfill, portfolio_snapshots,
#     backtest_snapshots, battle_snapshots
#   These tables must be repopulated separately (price ingestion,
#   backfill scripts) if needed.
#
# DISASTER RECOVERY CHECKLIST
# ─────────────────────────────────────────────────────────────
#   1. docker compose up -d timescaledb        # start only the DB
#   2. alembic upgrade head                    # apply any missing schema migrations
#   3. ./scripts/restore_database.sh <file>    # restore data
#   4. docker compose up -d                    # start remaining services
#   5. python scripts/validate_phase1.py       # confirm health
#
# =============================================================================

set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Logging helpers
# ─────────────────────────────────────────────────────────────
log()  { echo "[$(date -Iseconds)] [INFO]  $*"; }
warn() { echo "[$(date -Iseconds)] [WARN]  $*" >&2; }
die()  { echo "[$(date -Iseconds)] [ERROR] $*" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────
# Argument validation
# ─────────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
    die "Usage: $0 <backup-file.sql.gz>"
fi

BACKUP_FILE="$1"

if [[ ! -f "$BACKUP_FILE" ]]; then
    die "Backup file not found: $BACKUP_FILE"
fi

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
COMPOSE_DIR="${COMPOSE_DIR:-$(pwd)}"
ENV_FILE="$COMPOSE_DIR/.env"

# ─────────────────────────────────────────────────────────────
# Load environment
# ─────────────────────────────────────────────────────────────
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

RESTORE_DB="${RESTORE_DB:-$POSTGRES_DB}"

# ─────────────────────────────────────────────────────────────
# Safety confirmation
# ─────────────────────────────────────────────────────────────
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
warn "=========================================================="
warn "  DATABASE RESTORE — THIS WILL OVERWRITE EXISTING DATA"
warn "=========================================================="
warn "  Backup file : $BACKUP_FILE ($BACKUP_SIZE)"
warn "  Target DB   : $RESTORE_DB"
warn "  DB host     : Docker service 'timescaledb' (${COMPOSE_DIR})"
warn "=========================================================="

if [[ "${FORCE_RESTORE:-}" != "yes" ]]; then
    read -r -p "Type 'yes' to confirm restore: " confirmation
    if [[ "$confirmation" != "yes" ]]; then
        die "Restore cancelled by user."
    fi
fi

# ─────────────────────────────────────────────────────────────
# Create the target database if it does not already exist
# ─────────────────────────────────────────────────────────────
cd "$COMPOSE_DIR"

log "Ensuring database '$RESTORE_DB' exists..."
docker compose exec -T timescaledb psql \
    -U "${POSTGRES_USER}" \
    -d postgres \
    -c "SELECT pg_catalog.pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${RESTORE_DB}' AND pid <> pg_backend_pid();" \
    > /dev/null 2>&1 || true

docker compose exec -T timescaledb psql \
    -U "${POSTGRES_USER}" \
    -d postgres \
    -tc "SELECT 1 FROM pg_database WHERE datname = '${RESTORE_DB}'" \
    | grep -q 1 || \
docker compose exec -T timescaledb psql \
    -U "${POSTGRES_USER}" \
    -d postgres \
    -c "CREATE DATABASE \"${RESTORE_DB}\";" \
    > /dev/null

# ─────────────────────────────────────────────────────────────
# Perform the restore
# ─────────────────────────────────────────────────────────────
log "Starting restore: $BACKUP_FILE → database '${RESTORE_DB}'..."
log "This may take several minutes depending on database size."

gunzip -c "$BACKUP_FILE" \
    | docker compose exec -T timescaledb psql \
        -U "${POSTGRES_USER}" \
        -d "${RESTORE_DB}" \
        --single-transaction \
        -v ON_ERROR_STOP=1

log "Restore complete. Database '${RESTORE_DB}' has been restored."
log ""
log "Next steps:"
log "  1. Run 'alembic upgrade head' to apply any schema migrations added after this backup."
log "  2. Run 'python scripts/validate_phase1.py' to confirm platform health."
log "  3. Repopulate time-series data if needed:"
log "       python scripts/backfill_history.py --daily --resume"
