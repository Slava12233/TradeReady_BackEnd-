---
type: plan
title: "Deployment Plan: V.0.0.2 to Production"
tags:
  - deployment
  - v0.0.2
  - production
  - plan
created: 2026-03-30
status: active
branch: V.0.0.2
target: main
---

# Deployment Plan: V.0.0.2 to Production

## Executive Summary

Merge branch `V.0.0.2` (15 commits ahead of `main`) to production. This release adds the agent ecosystem (conversation, memory, permissions, trading intelligence), agent logging/audit infrastructure, 7 Grafana dashboards, 11 alert rules, and 3 new database migrations (018-020). The deployment requires CI/CD pipeline fixes, a CORS configuration change, safe migration of 3 additive-only schemas, and full monitoring stack verification.

**Estimated total time:** 2-3 hours (excluding optional historical backfill)

**Risk level:** MEDIUM -- all 3 migrations are additive-only (no destructive ALTERs), but the CI/CD pipeline itself has bugs that must be fixed first.

---

## Table of Contents

1. [Pre-Deployment Checklist](#phase-1-pre-deployment-checklist)
2. [CI/CD Pipeline Fixes](#phase-2-cicd-pipeline-fixes)
3. [CORS Configuration Fix](#phase-3-cors-configuration-fix)
4. [Environment Setup](#phase-4-environment-setup)
5. [Database Migration Strategy](#phase-5-database-migration-strategy)
6. [Docker Deployment Sequence](#phase-6-docker-deployment-sequence)
7. [Frontend Deployment](#phase-7-frontend-deployment)
8. [Post-Deployment Validation](#phase-8-post-deployment-validation)
9. [Monitoring Setup Verification](#phase-9-monitoring-setup-verification)
10. [Agent Deployment](#phase-10-agent-deployment)
11. [Rollback Procedure](#phase-11-rollback-procedure)
12. [Training Pipeline Activation](#phase-12-training-pipeline-activation)

---

## Phase 1: Pre-Deployment Checklist

**Time estimate:** 30-45 minutes
**Dependencies:** None -- this is the starting gate

### 1.1 Code Quality Gate

Run all quality checks locally on `V.0.0.2` before touching production.

```bash
cd ~/Desktop/AiTradingAgent
git checkout V.0.0.2
git pull origin V.0.0.2

# Lint
ruff check src/ tests/
# Expected: 0 errors

# Format check
ruff format --check src/ tests/
# Expected: 0 files would be reformatted

# Type check
mypy src/ --ignore-missing-imports
# Expected: Success

# Unit tests
pytest tests/unit -v --tb=short
# Expected: All pass (981+ tests)
```

**If lint/type check fails:** Fix violations before proceeding. Do not deploy with lint errors.
**If tests fail:** Investigate and fix. The deploy pipeline runs the same test suite.

### 1.2 Verify Migration Chain Integrity

```bash
# Confirm current head in the codebase
grep -r "^revision" alembic/versions/020_add_agent_audit_log.py
# Expected: revision: str = "020"

grep -r "^down_revision" alembic/versions/020_add_agent_audit_log.py
# Expected: down_revision: str | None = "019"

grep -r "^down_revision" alembic/versions/019_add_feedback_lifecycle_columns.py
# Expected: down_revision: str | None = "018"

grep -r "^down_revision" alembic/versions/018_add_agent_logging_tables.py
# Expected: down_revision: str | None = "017"
```

Verify the chain is unbroken: `017 -> 018 -> 019 -> 020`.

### 1.3 Verify Migration Safety

All three migrations are marked "Safe for zero-downtime production deployment" in their docstrings. Confirm:

- **018**: Creates 2 new tables (`agent_api_calls`, `agent_strategy_signals`) + adds nullable `trace_id` column to `agent_decisions`. Additive only.
- **019**: Adds nullable `resolution` column to `agent_feedback`, updates CHECK constraint (adds `submitted` as valid status). Non-destructive.
- **020**: Creates 1 new table (`agent_audit_log`) with 3 indexes. Additive only.

None of these migrations:
- Drop columns or tables
- Add NOT NULL constraints to existing data
- Modify hypertables
- Require backfill scripts between steps

All three can be applied in sequence with a single `alembic upgrade head`.

### 1.4 Check Production Server Access

```bash
# Verify SSH access
ssh -o ConnectTimeout=5 <SERVER_USER>@<SERVER_HOST> "echo 'SSH OK'"

# Verify the repo exists on server
ssh <SERVER_USER>@<SERVER_HOST> "cd ~/TradeReady_BackEnd- && git status"

# Check current branch on server
ssh <SERVER_USER>@<SERVER_HOST> "cd ~/TradeReady_BackEnd- && git branch --show-current"
# Note the current branch -- this is your rollback target

# Check current DB migration head on server
ssh <SERVER_USER>@<SERVER_HOST> "cd ~/TradeReady_BackEnd- && docker compose exec -T api alembic current"
# Expected: 017 (head) -- this is the last migration applied before V.0.0.2
```

**Record these values -- you will need them for rollback:**
- Current branch: ___________
- Current migration head: ___________
- Current git commit hash: ___________

### 1.5 Verify Docker Resources on Server

```bash
ssh <SERVER_USER>@<SERVER_HOST> "docker system df"
ssh <SERVER_USER>@<SERVER_HOST> "free -h"
ssh <SERVER_USER>@<SERVER_HOST> "df -h /"
```

**Minimum requirements:** 8 CPU cores, 10 GB RAM, 20 GB free disk space.
**If low on disk:** Run `docker system prune -f` (removes stopped containers and dangling images).

### 1.6 Pre-Deployment Checklist Summary

| Item | Status | Notes |
|------|--------|-------|
| `ruff check` passes | [ ] | Zero errors required |
| `ruff format --check` passes | [ ] | Zero reformats required |
| `mypy src/` passes | [ ] | Zero errors required |
| `pytest tests/unit` passes | [ ] | All 981+ tests pass |
| Migration chain verified (017->018->019->020) | [ ] | |
| All 3 migrations are additive-only | [ ] | No destructive ops |
| SSH access to server confirmed | [ ] | |
| Current server state recorded | [ ] | Branch, commit, migration head |
| Server resources sufficient | [ ] | 8 CPU, 10 GB RAM, 20 GB disk |

**STOP if any item fails. Fix before proceeding.**

---

## Phase 2: CI/CD Pipeline Fixes

**Time estimate:** 15-20 minutes
**Dependencies:** Phase 1 complete
**Risk:** LOW -- these are configuration changes, not application code

### 2.1 Fix `test.yml` Branch Triggers

**File:** `.github/workflows/test.yml`

**Current (broken):**
```yaml
on:
  push:
    branches: [V0.0.1, main]
  pull_request:
    branches: [V0.0.1, main]
  workflow_call:
```

**Change to:**
```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_call:
```

**Rationale:** After merging V.0.0.2 to main, the old branch name is obsolete. CI should trigger on pushes/PRs to `main` only. The `workflow_call` trigger stays for `deploy.yml` to chain to.

### 2.2 Fix `deploy.yml` Git Pull Target

**File:** `.github/workflows/deploy.yml`

**Current (broken):**
```yaml
script: |
  cd ~/TradeReady_BackEnd-
  git pull origin V0.0.1
  docker compose build api ingestion celery
  docker compose up -d api ingestion celery celery-beat
  docker compose exec -T api alembic upgrade head
  sleep 5
  curl -sf http://localhost:8000/health || exit 1
  echo "Deploy successful - $(date)"
```

**Replace the entire `script:` block with:**
```yaml
script: |
  set -euo pipefail
  cd ~/TradeReady_BackEnd-

  echo "=== Pre-deploy: record rollback point ==="
  ROLLBACK_COMMIT=$(git rev-parse HEAD)
  echo "Rollback commit: $ROLLBACK_COMMIT" | tee /tmp/last-deploy-rollback.txt

  echo "=== Pre-deploy: database backup ==="
  docker compose exec -T timescaledb pg_dump \
    -U ${POSTGRES_USER:-agentexchange} \
    -d ${POSTGRES_DB:-agentexchange} \
    --no-owner --no-acl \
    | gzip > /tmp/pre-deploy-backup-$(date +%Y%m%d-%H%M%S).sql.gz
  echo "Backup saved to /tmp/pre-deploy-backup-*.sql.gz"

  echo "=== Pull latest main ==="
  git fetch origin main
  git checkout main
  git pull origin main

  echo "=== Build all application images ==="
  docker compose build api ingestion celery

  echo "=== Rolling restart: celery-beat first (stateless scheduler) ==="
  docker compose up -d celery-beat

  echo "=== Rolling restart: celery worker ==="
  docker compose up -d celery

  echo "=== Run database migrations ==="
  docker compose exec -T api alembic upgrade head

  echo "=== Rolling restart: API (serves traffic) ==="
  docker compose up -d api

  echo "=== Rolling restart: ingestion ==="
  docker compose up -d ingestion

  echo "=== Wait for health checks ==="
  sleep 10

  echo "=== Verify API health ==="
  curl -sf http://localhost:8000/health || {
    echo "HEALTH CHECK FAILED -- initiating rollback"
    git checkout "$ROLLBACK_COMMIT"
    docker compose build api ingestion celery
    docker compose up -d api ingestion celery celery-beat
    docker compose exec -T api alembic downgrade -3
    exit 1
  }

  echo "=== Verify price ingestion ==="
  curl -sf http://localhost:8000/api/v1/market/prices | head -c 200 || echo "WARNING: price endpoint not responding"

  echo "=== Deploy successful - $(date) ==="
```

### 2.3 Key Improvements in the New deploy.yml

| Issue | Fix |
|-------|-----|
| Pulls `V0.0.1` instead of `main` | Changed to `git pull origin main` |
| No database backup | Added `pg_dump` before migration |
| No rollback on failure | Added rollback block on health check failure |
| `celery-beat` not rebuilt | All 3 images share `Dockerfile.celery`; `celery-beat` uses the celery image but is now explicitly restarted |
| No migration timing control | Migrations run before API restart (while old API still serves) |
| Minimal health check | Added price endpoint verification |

### 2.4 CI Redis Password Mismatch

**Issue:** CI Redis has no password (`redis:7-alpine` with no `--requirepass`), but production Redis requires `REDIS_PASSWORD`. Tests use `REDIS_URL: redis://localhost:6379/0` (no password).

**Assessment:** This is acceptable IF unit tests mock Redis or use password-less connections. The CI `REDIS_URL` env var is set without a password, matching the password-less CI Redis container. Production `REDIS_URL` includes the password in the connection string. No fix needed -- just document the intentional difference.

### 2.5 Commit the CI/CD Fixes

```bash
cd ~/Desktop/AiTradingAgent
git checkout V.0.0.2

# Make the changes to test.yml and deploy.yml as described above

git add .github/workflows/test.yml .github/workflows/deploy.yml
git commit -m "fix(ci): update deploy.yml to pull main, add backup/rollback; fix test.yml branch triggers"
```

**Success criteria:** Both YAML files parse without syntax errors.
**If it fails:** Validate YAML syntax with `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))"`.

---

## Phase 3: CORS Configuration Fix

**Time estimate:** 10-15 minutes
**Dependencies:** Phase 1 complete (can run in parallel with Phase 2)
**Risk:** MEDIUM -- incorrect CORS will block all frontend requests

### 3.1 Add CORS Settings to `src/config.py`

**File:** `src/config.py`

Add a new field to the `Settings` class, after the `api_base_url` field (around line 67):

```python
    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
        description=(
            "Comma-separated list of allowed CORS origins. "
            "Set to your production frontend URL(s) in production."
        ),
    )
```

### 3.2 Update `src/main.py` CORS Middleware

**File:** `src/main.py`

Replace the hardcoded origins block (lines 171-187) with:

```python
    # ── CORS ──────────────────────────────────────────────────────────────────
    # Origins loaded from CORS_ORIGINS env var (comma-separated).
    # Defaults to localhost for development; set to production domain in .env.
    from src.config import get_settings
    settings = get_settings()
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )
```

### 3.3 Update `.env.example`

**File:** `.env.example`

Add after the `API_BASE_URL` line:

```env
# ── CORS ─────────────────────────────────────────────────────────────────
# Comma-separated list of allowed origins for CORS.
# Include your frontend domain(s) for production.
CORS_ORIGINS=http://localhost:3000,http://localhost:3001
```

### 3.4 Production `.env` Entry

When setting up production (Phase 4), add to `.env`:

```env
CORS_ORIGINS=https://your-frontend-domain.com,http://localhost:3000
```

Replace `your-frontend-domain.com` with your actual production frontend URL. Keep localhost entries if you ever need to connect a local dev frontend to production (remove them for strict security).

### 3.5 Commit the CORS Fix

```bash
git add src/config.py src/main.py .env.example
git commit -m "feat(cors): make CORS origins configurable via CORS_ORIGINS env var"
```

**Success criteria:** Application starts without import errors; `GET /health` returns 200; frontend at configured origin can reach the API without CORS errors.

**If it fails:** Check that `get_settings()` is not cached with old values. In tests, ensure the mock patches `src.config.get_settings` before the cached instance is created.

---

## Phase 4: Environment Setup

**Time estimate:** 10-15 minutes
**Dependencies:** Phase 3 complete (CORS field added to Settings)

### 4.1 Production `.env` Template

Generate a complete `.env` for the production server. Every value marked `GENERATE` must be replaced with a unique, random string.

```bash
# Generate secrets (run these on any machine with Python):
python -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(64))"
python -c "import secrets; print('GRAFANA_ADMIN_PASSWORD=' + secrets.token_urlsafe(24))"
python -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
```

### 4.2 Complete Production `.env`

```env
# ── Database ────────────────────────────────────────────────────────────────
POSTGRES_USER=agentexchange
POSTGRES_PASSWORD=<GENERATED_POSTGRES_PASSWORD>
POSTGRES_DB=agentexchange
DATABASE_URL=postgresql+asyncpg://agentexchange:<GENERATED_POSTGRES_PASSWORD>@timescaledb:5432/agentexchange

# ── Redis ───────────────────────────────────────────────────────────────────
REDIS_PASSWORD=<GENERATED_REDIS_PASSWORD>
REDIS_URL=redis://:<GENERATED_REDIS_PASSWORD>@redis:6379/0

# ── Binance WebSocket ───────────────────────────────────────────────────────
BINANCE_WS_URL=wss://stream.binance.com:9443/stream

# ── API ─────────────────────────────────────────────────────────────────────
API_HOST=0.0.0.0
API_PORT=8000
API_BASE_URL=https://api.agentexchange.com

# ── CORS ────────────────────────────────────────────────────────────────────
CORS_ORIGINS=https://your-frontend-domain.com,http://localhost:3000

# ── Auth ────────────────────────────────────────────────────────────────────
JWT_SECRET=<GENERATED_JWT_SECRET>
JWT_EXPIRY_HOURS=1

# ── Trading Defaults ────────────────────────────────────────────────────────
DEFAULT_STARTING_BALANCE=10000
TRADING_FEE_PCT=0.1
DEFAULT_SLIPPAGE_FACTOR=0.1

# ── Tick Ingestion ──────────────────────────────────────────────────────────
TICK_FLUSH_INTERVAL=1.0
TICK_BUFFER_MAX_SIZE=5000

# ── Monitoring ──────────────────────────────────────────────────────────────
GRAFANA_ADMIN_PASSWORD=<GENERATED_GRAFANA_PASSWORD>
```

### 4.3 Verify Consistency

The `POSTGRES_PASSWORD` must appear in exactly 2 places: the `POSTGRES_PASSWORD` field and inside the `DATABASE_URL` connection string. Same for `REDIS_PASSWORD` in `REDIS_PASSWORD` and `REDIS_URL`.

```bash
# Quick check on the server after creating .env:
grep -c "POSTGRES_PASSWORD" .env
# Expected: 2 (the variable and inside DATABASE_URL)

grep -c "REDIS_PASSWORD" .env
# Expected: 2 (the variable and inside REDIS_URL)
```

### 4.4 Agent `.env` (Optional -- Phase 10)

If deploying the agent service later, create `agent/.env`:

```env
OPENROUTER_API_KEY=<your-openrouter-key>
PLATFORM_BASE_URL=http://api:8000
PLATFORM_API_KEY=<generated-after-seeding>
PLATFORM_API_SECRET=<generated-after-seeding>
AGENT_MODEL=openrouter:anthropic/claude-sonnet-4-5
AGENT_CHEAP_MODEL=openrouter:google/gemini-2.0-flash-001
```

The `PLATFORM_API_KEY` and `PLATFORM_API_SECRET` values come from running `scripts/e2e_provision_agents.py` (Phase 10).

### 4.5 Frontend `.env.local` (Phase 7)

```env
NEXT_PUBLIC_API_BASE_URL=https://api.your-domain.com/api/v1
NEXT_PUBLIC_WS_URL=wss://api.your-domain.com/ws/v1
NEXTAUTH_SECRET=<GENERATED_SECRET>
NEXTAUTH_URL=https://your-frontend-domain.com
```

**Success criteria:** `.env` file exists on server, all `<GENERATED_*>` placeholders replaced, `DATABASE_URL` and `REDIS_URL` contain the correct inline passwords.

**If it fails:** Double-check password escaping -- if the generated password contains special characters (`@`, `:`, `/`), URL-encode them in the connection strings or regenerate without special chars.

---

## Phase 5: Database Migration Strategy

**Time estimate:** 5-10 minutes (migrations themselves are fast)
**Dependencies:** Phase 1 (server access verified), Phase 4 (`.env` configured)
**Risk:** LOW -- all additive-only, but backup is mandatory

### 5.1 Pre-Migration: Database Backup

**This is non-negotiable. Always back up before migrations.**

```bash
# SSH into server
ssh <SERVER_USER>@<SERVER_HOST>
cd ~/TradeReady_BackEnd-

# Create backup (compressed, ~2-5 minutes depending on data size)
docker compose exec -T timescaledb pg_dump \
  -U agentexchange \
  -d agentexchange \
  --no-owner --no-acl \
  | gzip > ~/backups/pre-v002-migration-$(date +%Y%m%d-%H%M%S).sql.gz

# Verify backup is non-empty
ls -lh ~/backups/pre-v002-migration-*.sql.gz
# Expected: file size > 1 MB (depends on data volume)

# Verify backup is valid (dry-run restore check)
zcat ~/backups/pre-v002-migration-*.sql.gz | head -20
# Expected: SQL CREATE/INSERT statements
```

**If backup fails:** Do NOT proceed. Fix the backup before any migration.

### 5.2 Check Current Migration Head

```bash
docker compose exec -T api alembic current
# Expected output: 017 (head)
```

If the output is anything other than `017`, investigate. The server should be at migration 017 from the V0.0.1 deployment. If it shows an earlier migration, you may need to apply intermediate migrations first.

### 5.3 Dry-Run Migration (Inspect SQL)

```bash
# Generate the SQL that would be executed, without running it
docker compose exec -T api alembic upgrade head --sql 2>/dev/null | head -100
```

Review the output. You should see:

1. `CREATE TABLE agent_api_calls (...)` -- from 018
2. `CREATE TABLE agent_strategy_signals (...)` -- from 018
3. `ALTER TABLE agent_decisions ADD COLUMN trace_id VARCHAR(32)` -- from 018
4. `ALTER TABLE agent_feedback ADD COLUMN resolution TEXT` -- from 019
5. `ALTER TABLE agent_feedback DROP CONSTRAINT ... ADD CONSTRAINT ...` -- from 019
6. `CREATE TABLE agent_audit_log (...)` -- from 020
7. Three `CREATE INDEX` statements -- from 020

**No DROP TABLE, no DROP COLUMN, no NOT NULL on existing columns.** If you see any destructive operation, STOP and investigate.

### 5.4 Apply Migrations

```bash
# Apply all pending migrations (018, 019, 020)
docker compose exec -T api alembic upgrade head

# Verify new head
docker compose exec -T api alembic current
# Expected: 020 (head)
```

**Expected output:**
```
INFO  [alembic.runtime.migration] Running upgrade 017 -> 018, Add agent logging tables
INFO  [alembic.runtime.migration] Running upgrade 018 -> 019, Add feedback lifecycle columns
INFO  [alembic.runtime.migration] Running upgrade 019 -> 020, Add agent audit log
```

### 5.5 Post-Migration Verification

```bash
# Verify new tables exist
docker compose exec -T timescaledb psql \
  -U agentexchange -d agentexchange \
  -c "\dt agent_api_calls; \dt agent_strategy_signals; \dt agent_audit_log;"

# Verify new columns exist
docker compose exec -T timescaledb psql \
  -U agentexchange -d agentexchange \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='agent_decisions' AND column_name='trace_id';"
# Expected: trace_id

docker compose exec -T timescaledb psql \
  -U agentexchange -d agentexchange \
  -c "SELECT column_name FROM information_schema.columns WHERE table_name='agent_feedback' AND column_name='resolution';"
# Expected: resolution

# Verify indexes on agent_audit_log
docker compose exec -T timescaledb psql \
  -U agentexchange -d agentexchange \
  -c "SELECT indexname FROM pg_indexes WHERE tablename='agent_audit_log';"
# Expected: 3 indexes (agent_id, created_at, composite)
```

### 5.6 Migration Rollback (If Needed)

If migrations fail or cause issues:

```bash
# Roll back all 3 migrations (reverse order: 020 -> 019 -> 018 -> 017)
docker compose exec -T api alembic downgrade 017

# Verify
docker compose exec -T api alembic current
# Expected: 017 (head)
```

If even downgrade fails, restore from backup:

```bash
# Nuclear option: restore from backup
docker compose down api ingestion celery celery-beat
zcat ~/backups/pre-v002-migration-*.sql.gz | \
  docker compose exec -T timescaledb psql -U agentexchange -d agentexchange
docker compose up -d api ingestion celery celery-beat
```

**Success criteria:** `alembic current` shows `020 (head)`, all 3 new tables exist, all new columns exist, all indexes present.

---

## Phase 6: Docker Deployment Sequence

**Time estimate:** 15-25 minutes
**Dependencies:** Phase 2 (CI/CD fixes committed), Phase 3 (CORS fix committed), Phase 5 (migrations ready)

### 6.1 Merge V.0.0.2 to main (Triggers Auto-Deploy)

**Option A: Auto-deploy via CI/CD (recommended after pipeline fixes)**

```bash
# On your local machine
cd ~/Desktop/AiTradingAgent
git checkout main
git merge V.0.0.2

# Review the merge
git log --oneline -5

# Push to trigger deploy.yml
git push origin main
```

The fixed `deploy.yml` will:
1. Run `test.yml` (lint, type check, unit tests)
2. SSH to server, backup DB, pull main, build images, restart services, migrate, health check

**Monitor the GitHub Actions run** at `https://github.com/<repo>/actions`.

**Option B: Manual deploy (if CI/CD not yet trusted)**

If you prefer to deploy manually the first time and then trust CI/CD for subsequent deploys:

```bash
# SSH into server
ssh <SERVER_USER>@<SERVER_HOST>
cd ~/TradeReady_BackEnd-

# Record rollback point
git rev-parse HEAD > /tmp/rollback-commit.txt
echo "Rollback commit: $(cat /tmp/rollback-commit.txt)"
```

### 6.2 Manual Deployment Steps (Option B)

Execute these in order on the production server:

```bash
cd ~/TradeReady_BackEnd-

# 1. Pull the latest code
git fetch origin main
git checkout main
git pull origin main

# 2. Verify the code is what you expect
git log --oneline -3
# Expected: Your merge commit at the top

# 3. Build application images (api, ingestion, celery share 3 Dockerfiles)
docker compose build api ingestion celery
# Expected: Successfully built (3 images)
# Time: 3-5 minutes

# 4. Pre-deploy DB backup (if not already done in Phase 5)
docker compose exec -T timescaledb pg_dump \
  -U agentexchange -d agentexchange --no-owner --no-acl \
  | gzip > ~/backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sql.gz

# 5. Run migrations BEFORE restarting services (old code can still serve)
docker compose exec -T api alembic upgrade head
# Expected: 017 -> 018 -> 019 -> 020

# 6. Rolling restart -- stateless services first
docker compose up -d celery-beat
sleep 5
docker compose up -d celery
sleep 5

# 7. Restart API (brief interruption -- ~5 seconds)
docker compose up -d api
sleep 10

# 8. Restart ingestion (price feed will reconnect automatically)
docker compose up -d ingestion
sleep 15

# 9. Verify all services are healthy
docker compose ps
# Expected: All services show "healthy" or "running"
```

### 6.3 Verify Docker Service Health

```bash
# Check all container states
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

# Expected output (approximate):
# NAME                STATUS              PORTS
# timescaledb         Up X minutes (healthy)   0.0.0.0:5432->5432/tcp
# redis               Up X minutes (healthy)   (no host port)
# api                 Up X minutes (healthy)   0.0.0.0:8000->8000/tcp
# ingestion           Up X minutes (healthy)   (no port)
# celery              Up X minutes             (no port)
# celery-beat         Up X minutes (healthy)   (no port)
# pgadmin             Up X minutes             0.0.0.0:5050->5050/tcp
# prometheus          Up X minutes (healthy)   0.0.0.0:9090->9090/tcp
# grafana             Up X minutes (healthy)   0.0.0.0:3001->3000/tcp

# Check for any restarting containers
docker compose ps --filter "status=restarting"
# Expected: empty (no containers restarting)

# Check recent logs for errors
docker compose logs --tail=20 api 2>&1 | grep -i error
docker compose logs --tail=20 ingestion 2>&1 | grep -i error
docker compose logs --tail=20 celery 2>&1 | grep -i error
```

### 6.4 Ensure Monitoring Stack is Running

The monitoring stack (prometheus, grafana, pgadmin) uses pre-built images (not built from Dockerfiles), so they do not need rebuilding. But they should be running:

```bash
# If monitoring is not up (check docker compose ps), bring it up:
docker compose up -d prometheus grafana pgadmin
```

**Success criteria:** All 9 services show healthy/running in `docker compose ps`. No containers in restart loop. API responds on port 8000, Prometheus on 9090, Grafana on 3001.

**If API fails to start:** Check logs: `docker compose logs --tail=50 api`. Common issues:
- Bad `.env` values (especially `DATABASE_URL` or `REDIS_URL`)
- Migration error (check `alembic current`)
- Import error from new code (check Python traceback in logs)

**If ingestion fails:** The Binance WebSocket connection may take 30-60 seconds to establish. Wait and re-check. If it continues restarting, check: `docker compose logs --tail=50 ingestion`.

---

## Phase 7: Frontend Deployment

**Time estimate:** 15-30 minutes
**Dependencies:** Phase 6 complete (API is live and healthy)

### 7.1 Deployment Options Analysis

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **Vercel** | Zero-config for Next.js, automatic SSL, preview deploys, CDN | Vendor lock-in, cost at scale, less control | **RECOMMENDED** for initial deployment |
| **nginx + PM2** | Full control, cheap VPS, no vendor lock-in | Manual SSL (certbot), no CDN without Cloudflare, manual scaling | Good for budget-conscious |
| **Docker (custom Dockerfile)** | Consistent with backend, single server | More server resources needed, manual routing | Good for all-in-one server |

### 7.2 Recommended: Vercel Deployment

Vercel is the native deployment target for Next.js and requires minimal configuration.

**Step 1: Connect repo to Vercel**
```
1. Go to https://vercel.com/new
2. Import your GitHub repository
3. Set root directory to: Frontend
4. Framework preset: Next.js (auto-detected)
5. Build command: pnpm build (auto-detected)
6. Output directory: .next (auto-detected)
```

**Step 2: Set environment variables in Vercel dashboard**
```
NEXT_PUBLIC_API_BASE_URL = https://api.your-domain.com/api/v1
NEXT_PUBLIC_WS_URL = wss://api.your-domain.com/ws/v1
NEXTAUTH_SECRET = <generate a 64-char random string>
NEXTAUTH_URL = https://your-frontend-domain.com
```

**Step 3: Deploy**
```
Vercel will automatically build and deploy on push to main.
```

**Step 4: Configure custom domain (optional)**
```
1. In Vercel dashboard > Settings > Domains
2. Add your custom domain
3. Follow DNS instructions (CNAME or A record)
```

### 7.3 Alternative: Docker Deployment

If you prefer to keep everything on one server, create a Frontend Dockerfile:

**File:** `Frontend/Dockerfile` (new file)

```dockerfile
FROM node:22-alpine AS base
RUN corepack enable && corepack prepare pnpm@latest --activate

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_WS_URL
RUN pnpm build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]
```

**Note:** This requires adding `output: "standalone"` to `next.config.ts`. If using this approach, also add a `frontend` service to `docker-compose.yml`:

```yaml
  frontend:
    build:
      context: ./Frontend
      dockerfile: Dockerfile
      args:
        NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL}
        NEXT_PUBLIC_WS_URL: ${NEXT_PUBLIC_WS_URL}
    restart: unless-stopped
    ports:
      - "3000:3000"
    networks:
      - internal
    depends_on:
      api:
        condition: service_healthy
```

### 7.4 Post-Frontend-Deploy Verification

```bash
# Test the frontend loads
curl -sf https://your-frontend-domain.com | head -20
# Expected: HTML content

# Test API connectivity from frontend (CORS must work)
# Open browser dev tools > Console and verify:
# 1. No CORS errors in Network tab
# 2. /health endpoint returns 200
# 3. WebSocket connects (check WS tab)
```

### 7.5 Frontend Build Verification (Local)

Before deploying, verify the frontend builds cleanly:

```bash
cd Frontend
pnpm install --frozen-lockfile
pnpm build
# Expected: Build succeeds with 0 TypeScript errors, 0 lint errors
# The build runs `tsx scripts/generate-docs-md.ts && next build`

# Run tests
pnpm test
# Expected: 207 tests pass
```

**Success criteria:** Frontend loads in browser, can reach API without CORS errors, WebSocket connects and shows live prices.

**If CORS errors appear:** Verify `CORS_ORIGINS` in backend `.env` includes the exact frontend origin (protocol + domain + port).

---

## Phase 8: Post-Deployment Validation

**Time estimate:** 15-20 minutes
**Dependencies:** Phase 6 complete (all backend services running)

### 8.1 API Health Check

```bash
curl -sf http://localhost:8000/health | python -m json.tool
# Expected:
# {
#   "status": "ok",      (or "degraded" if prices not flowing yet)
#   "version": "0.1.0",
#   "services": { ... }
# }
```

### 8.2 Swagger Documentation

Open `http://<server-ip>:8000/docs` in a browser.

Verify:
- [ ] Swagger UI loads
- [ ] All endpoint groups are visible (auth, market, trading, agents, backtest, battles, strategies, training, analytics, waitlist)
- [ ] Can click "Try it out" on `/health` and get a 200 response

### 8.3 Price Ingestion Verification

```bash
# Check Redis has prices
docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" HLEN prices
# Expected: > 0 (should be 600+ after ingestion connects)

# Check a specific price
docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" HGET prices BTCUSDT
# Expected: A decimal number (current BTC price)

# Check via API
curl -sf http://localhost:8000/api/v1/market/prices | python -m json.tool | head -20
# Expected: JSON object with symbol:price pairs
```

**If prices are 0 or missing:** Wait 60 seconds for the Binance WebSocket to connect. Check ingestion logs: `docker compose logs --tail=50 ingestion`.

### 8.4 Database Verification

```bash
# Check trading pairs are seeded (should already be populated from previous deploy)
docker compose exec -T timescaledb psql \
  -U agentexchange -d agentexchange \
  -c "SELECT COUNT(*) FROM trading_pairs;"
# Expected: 600+ rows

# If 0 rows, seed pairs:
docker compose exec -T api python scripts/seed_pairs.py
```

### 8.5 Run Phase 1 Validation Script

```bash
# From inside the API container (has all dependencies)
docker compose exec -T api python scripts/validate_phase1.py
# Expected: All checks pass
```

**If `validate_phase1.py` expects localhost connections**, it may fail inside Docker. In that case, run it from the host with appropriate env vars:

```bash
# Set env vars for host-side script execution
export DATABASE_URL="postgresql+asyncpg://agentexchange:<password>@localhost:5432/agentexchange"
export REDIS_URL="redis://:<password>@localhost:6379/0"
export API_BASE_URL="http://localhost:8000"
python scripts/validate_phase1.py
```

**Note:** Redis has no host port exposed in `docker-compose.yml`. To run `validate_phase1.py` from the host, you would need to temporarily add a host port mapping to Redis, or run it from within a Docker container that shares the `internal` network. The safest approach:

```bash
docker compose exec -T api python scripts/validate_phase1.py
```

### 8.6 E2E Smoke Test

Run a quick end-to-end test to verify the full stack:

```bash
# Create a test user + agents + trades (run from host if API port is exposed)
python scripts/e2e_multi_agent_test.py
# Expected: Test account created, 3 agents created, trades placed, isolation verified

# Or run the comprehensive scenario:
python scripts/e2e_full_scenario_live.py --base-url http://localhost:8000
# Expected: Account, agents, trades, backtests all created successfully
```

### 8.7 Celery Task Verification

```bash
# Check celery worker is responsive
docker compose exec -T celery celery -A src.tasks.celery_app inspect ping
# Expected: pong response from worker

# Check beat scheduler is running
docker compose exec -T celery-beat cat /tmp/celerybeat.pid
# Expected: a PID number

# Check registered tasks
docker compose exec -T celery celery -A src.tasks.celery_app inspect registered
# Expected: List of registered task names
```

### 8.8 Post-Deployment Validation Summary

| Check | Command | Expected | Status |
|-------|---------|----------|--------|
| API health | `curl /health` | `{"status": "ok"}` | [ ] |
| Swagger docs | Browser `/docs` | UI loads | [ ] |
| Redis prices | `HLEN prices` | > 0 | [ ] |
| Trading pairs | `SELECT COUNT(*) FROM trading_pairs` | 600+ | [ ] |
| Phase 1 validation | `validate_phase1.py` | All pass | [ ] |
| E2E smoke test | `e2e_multi_agent_test.py` | All pass | [ ] |
| Celery worker | `inspect ping` | pong | [ ] |
| Celery beat | PID file exists | PID number | [ ] |
| Migration head | `alembic current` | 020 | [ ] |

---

## Phase 9: Monitoring Setup Verification

**Time estimate:** 10-15 minutes
**Dependencies:** Phase 6 complete (Prometheus and Grafana running)

### 9.1 Prometheus Verification

```bash
# Check Prometheus is scraping the API
curl -sf http://localhost:9090/api/v1/targets | python -m json.tool | grep -A5 '"job":"api"'
# Expected: "health": "up"

# Check the agent scrape target (will be "down" until agent profile is activated)
curl -sf http://localhost:9090/api/v1/targets | python -m json.tool | grep -A5 '"job":"agent"'
# Expected: "health": "down" (this is OK -- agent is not running yet)

# Verify alert rules are loaded
curl -sf http://localhost:9090/api/v1/rules | python -m json.tool | grep -c '"name"'
# Expected: 11 (one for each alert rule in agent-alerts.yml)

# Quick metric check
curl -sf http://localhost:9090/api/v1/query?query=up | python -m json.tool
# Expected: shows up{job="api"} = 1, up{job="prometheus"} = 1
```

### 9.2 Grafana Verification

Open `http://<server-ip>:3001` in a browser.

**Login:** admin / (GRAFANA_ADMIN_PASSWORD from .env)

Verify:
- [ ] Login succeeds
- [ ] Prometheus datasource is auto-provisioned (Settings > Data Sources > Prometheus)
- [ ] 7 dashboards are auto-provisioned (Dashboards > Browse):
  1. Agent Overview
  2. Agent API Calls
  3. Agent LLM Usage
  4. Agent Memory
  5. Agent Strategy
  6. Ecosystem Health
  7. Retraining

**If dashboards are missing:** Check provisioning:
```bash
docker compose logs --tail=20 grafana | grep -i provision
# Should show: "msg"="Provisioning" for dashboards and datasources
```

If provisioning failed, verify the volume mounts are correct:
```bash
docker compose exec -T grafana ls /var/lib/grafana/dashboards/
# Expected: 7 JSON files
docker compose exec -T grafana ls /etc/grafana/provisioning/datasources/
# Expected: prometheus.yml
docker compose exec -T grafana ls /etc/grafana/provisioning/dashboards/
# Expected: dashboards.yml
```

### 9.3 Alert Rules Verification

```bash
# Check that Prometheus has loaded the agent alert rules
curl -sf http://localhost:9090/api/v1/rules | python -m json.tool | grep '"alertname"'
# Expected: 11 alert names (AgentUnhealthy, AgentHighErrorRate, AgentHighLLMCost, etc.)
```

**Note:** Alert rules will not fire until the agent service is running and generating metrics. This is expected. The alert rule definitions being loaded is sufficient for this phase.

### 9.4 Monitoring Checklist

| Check | Status |
|-------|--------|
| Prometheus is UP | [ ] |
| API scrape target is "up" | [ ] |
| Agent scrape target is "down" (expected) | [ ] |
| 11 alert rules loaded | [ ] |
| Grafana login works | [ ] |
| Prometheus datasource provisioned | [ ] |
| 7 dashboards provisioned | [ ] |

---

## Phase 10: Agent Deployment (Optional)

**Time estimate:** 20-30 minutes
**Dependencies:** Phase 8 complete (platform fully validated), Phase 9 complete (monitoring ready)
**Risk:** LOW -- agent is profile-gated and does not affect core platform

**Deploy the agent only after the core platform is stable for at least 30 minutes.**

### 10.1 Provision Agent Accounts

Before starting the agent service, create agent accounts with API keys:

```bash
# Run from host (requires API to be reachable)
python scripts/e2e_provision_agents.py
# Expected output: 5 agent accounts created with API keys

# SAVE THE OUTPUT -- you need the API keys for agent/.env
```

### 10.2 Configure Agent Environment

Create `agent/.env` on the server:

```bash
ssh <SERVER_USER>@<SERVER_HOST>
cd ~/TradeReady_BackEnd-

cat > agent/.env << 'EOF'
OPENROUTER_API_KEY=<your-openrouter-api-key>
PLATFORM_BASE_URL=http://api:8000
PLATFORM_API_KEY=<from-provision-script-output>
PLATFORM_API_SECRET=<from-provision-script-output>
AGENT_MODEL=openrouter:anthropic/claude-sonnet-4-5
AGENT_CHEAP_MODEL=openrouter:google/gemini-2.0-flash-001
EOF
```

### 10.3 Run Agent Smoke Test

```bash
# Start agent with smoke workflow (no LLM, just connectivity)
docker compose --profile agent run --rm agent python -m agent.main smoke
# Expected: 10 connectivity checks pass, JSON report written
```

### 10.4 Start Agent Service

```bash
# Start the agent service (profile-gated)
docker compose --profile agent up -d agent

# Check status
docker compose --profile agent ps agent
# Expected: running (will exit after completing its task)
```

### 10.5 Verify Agent Metrics in Prometheus

After the agent runs at least once:

```bash
# Check the agent scrape target
curl -sf http://localhost:9090/api/v1/targets | python -m json.tool | grep -A5 '"job":"agent"'
# Expected: "health": "up" (while agent is running)
```

**Note:** The agent service runs a task and exits (`no restart policy`). The Prometheus scrape target will show "down" between runs. This is by design.

### 10.6 Run Full Agent Workflows (Optional)

```bash
# Trading workflow (requires LLM -- costs money)
docker compose --profile agent run --rm agent python -m agent.main trade

# Backtest workflow
docker compose --profile agent run --rm agent python -m agent.main backtest

# Strategy workflow
docker compose --profile agent run --rm agent python -m agent.main strategy

# All workflows
docker compose --profile agent run --rm agent python -m agent.main all
```

---

## Phase 11: Rollback Procedure

### 11.1 When to Rollback

Trigger a rollback if ANY of these occur:
- API `/health` returns non-200 for > 5 minutes after deploy
- Price ingestion fails to reconnect after 5 minutes
- Database migration fails and `alembic downgrade` also fails
- Critical user-facing errors reported

### 11.2 Quick Rollback (Code Only, No Migration Revert)

If the issue is in application code (not database):

```bash
ssh <SERVER_USER>@<SERVER_HOST>
cd ~/TradeReady_BackEnd-

# Get the rollback commit (saved in Phase 6)
ROLLBACK_COMMIT=$(cat /tmp/rollback-commit.txt 2>/dev/null || cat /tmp/last-deploy-rollback.txt)
echo "Rolling back to: $ROLLBACK_COMMIT"

# Checkout the previous code
git checkout $ROLLBACK_COMMIT

# Rebuild and restart
docker compose build api ingestion celery
docker compose up -d api ingestion celery celery-beat

# Wait and verify
sleep 15
curl -sf http://localhost:8000/health
echo "Rollback complete - $(date)"
```

**Time:** ~5 minutes

### 11.3 Full Rollback (Code + Database)

If migrations caused data issues:

```bash
ssh <SERVER_USER>@<SERVER_HOST>
cd ~/TradeReady_BackEnd-

# 1. Roll back code
ROLLBACK_COMMIT=$(cat /tmp/rollback-commit.txt)
git checkout $ROLLBACK_COMMIT

# 2. Roll back migrations (020 -> 019 -> 018 -> 017)
docker compose exec -T api alembic downgrade 017

# 3. Verify migration state
docker compose exec -T api alembic current
# Expected: 017 (head)

# 4. Rebuild and restart
docker compose build api ingestion celery
docker compose up -d api ingestion celery celery-beat

# 5. Verify
sleep 15
curl -sf http://localhost:8000/health
echo "Full rollback complete - $(date)"
```

**Time:** ~10 minutes

### 11.4 Nuclear Rollback (Database Restore from Backup)

If `alembic downgrade` fails or data corruption is suspected:

```bash
ssh <SERVER_USER>@<SERVER_HOST>
cd ~/TradeReady_BackEnd-

# 1. Stop application services (keep DB running)
docker compose stop api ingestion celery celery-beat

# 2. Restore from backup
BACKUP_FILE=$(ls -t ~/backups/pre-v002-migration-*.sql.gz | head -1)
echo "Restoring from: $BACKUP_FILE"

# Drop and recreate the database
docker compose exec -T timescaledb psql -U agentexchange -d postgres \
  -c "DROP DATABASE agentexchange; CREATE DATABASE agentexchange OWNER agentexchange;"

# Restore
zcat "$BACKUP_FILE" | docker compose exec -T timescaledb psql -U agentexchange -d agentexchange

# 3. Roll back code
ROLLBACK_COMMIT=$(cat /tmp/rollback-commit.txt)
git checkout $ROLLBACK_COMMIT

# 4. Rebuild and restart
docker compose build api ingestion celery
docker compose up -d api ingestion celery celery-beat

# 5. Re-run migrations to the pre-deploy head
docker compose exec -T api alembic upgrade head
# Should stop at 017 (the head before V.0.0.2)

# 6. Verify
sleep 15
curl -sf http://localhost:8000/health
echo "Nuclear rollback complete - $(date)"
```

**Time:** 15-30 minutes (depends on backup size)

### 11.5 Rollback Decision Matrix

| Symptom | Action | Migration Revert? |
|---------|--------|-------------------|
| API 500 errors but DB queries work | Quick rollback (11.2) | No |
| Migration failed mid-run | Full rollback (11.3) | Yes |
| Data corruption or wrong query results | Nuclear rollback (11.4) | Restore backup |
| Price ingestion down, API works | Restart ingestion only | No |
| Celery tasks failing | Restart celery only | No |
| Frontend CORS errors | Fix `CORS_ORIGINS` in `.env` | No |

---

## Phase 12: Training Pipeline Activation

**Time estimate:** 10-15 minutes (configuration only; actual training runs on schedule)
**Dependencies:** Phase 10 complete (agent service functional)
**Risk:** LOW -- training runs via Celery beat on separate queues

### 12.1 Training Schedule Overview

The continuous retraining pipeline is wired into Celery beat with 4 schedules:

| Component | Schedule | Queue | Celery Task |
|-----------|----------|-------|-------------|
| Ensemble weights | Every 8 hours | `ml_training` | Recalculates MetaLearner weights from recent performance |
| Regime classifier | Every 7 days | `ml_training` | Retrains XGBoost/RF regime classifier on recent market data |
| Genetic algorithm | Every 7 days | `ml_training` | Runs evolutionary genome optimization |
| PPO RL model | Every 30 days | `ml_training` | Retrains PPO agent (SB3) |

### 12.2 Verify Celery Beat Schedule

```bash
# Check beat schedule includes ml_training tasks
docker compose exec -T celery celery -A src.tasks.celery_app inspect scheduled
# Expected: should list scheduled tasks including retraining tasks

# Check that the ml_training queue is being consumed
docker compose exec -T celery celery -A src.tasks.celery_app inspect active_queues
# Check if ml_training is listed
```

**Note:** The default celery worker command in `docker-compose.yml` consumes `-Q default,high_priority`. ML training tasks go to the `ml_training` queue. If you want training to run, you need a worker consuming that queue.

### 12.3 Add ML Training Worker (Optional)

To consume ML training tasks, either:

**Option A:** Add the queue to the existing worker (simpler, shares resources):

Modify the celery service command in `docker-compose.yml`:
```yaml
command: ["celery", "-A", "src.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=4", "-Q", "default,high_priority,ml_training"]
```

**Option B:** Add a dedicated ML worker service (recommended for production):

Add to `docker-compose.yml`:
```yaml
  celery-ml:
    build:
      context: .
      dockerfile: Dockerfile.celery
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
    command: ["celery", "-A", "src.tasks.celery_app", "worker", "--loglevel=info", "--concurrency=2", "-Q", "ml_training"]
    networks:
      - internal
    depends_on:
      timescaledb:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 4G
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

### 12.4 Monitor Training Runs

After the first scheduled training run completes:

1. Check the Grafana "Retraining" dashboard for retrain event counts
2. Check Prometheus for `retrain_*` metrics
3. Check agent reports in `agent/reports/` volume mount

### 12.5 Training Activation Decision

Do NOT activate training immediately after deployment. Wait at least:
- **24 hours** of stable platform operation
- **Price ingestion** flowing continuously
- **At least 1 successful agent smoke/trade workflow** completed

Then activate training by deploying Option A or B from section 12.3.

---

## Complete Deployment Checklist

Print this out and check off each item as you go.

### Pre-Deploy
- [ ] `ruff check` passes
- [ ] `ruff format --check` passes
- [ ] `mypy src/` passes
- [ ] Unit tests pass (981+)
- [ ] Migration chain verified (017->020)
- [ ] Server SSH access confirmed
- [ ] Server state recorded (branch, commit, migration head)
- [ ] Server disk/RAM sufficient

### CI/CD Fixes (Phase 2)
- [ ] `test.yml` branch triggers updated to `main`
- [ ] `deploy.yml` git pull target changed to `main`
- [ ] `deploy.yml` backup step added
- [ ] `deploy.yml` rollback step added
- [ ] Changes committed to `V.0.0.2`

### Code Fixes (Phase 3)
- [ ] `CORS_ORIGINS` field added to `src/config.py`
- [ ] `src/main.py` reads origins from settings
- [ ] `.env.example` updated with `CORS_ORIGINS`
- [ ] Changes committed to `V.0.0.2`

### Environment (Phase 4)
- [ ] Production `.env` created with generated secrets
- [ ] `DATABASE_URL` password matches `POSTGRES_PASSWORD`
- [ ] `REDIS_URL` password matches `REDIS_PASSWORD`
- [ ] `CORS_ORIGINS` includes frontend domain

### Database (Phase 5)
- [ ] Pre-migration backup taken
- [ ] Backup file verified non-empty
- [ ] Dry-run SQL reviewed (no destructive ops)
- [ ] Migrations applied (018, 019, 020)
- [ ] `alembic current` shows 020
- [ ] New tables verified (agent_api_calls, agent_strategy_signals, agent_audit_log)
- [ ] New columns verified (trace_id, resolution)
- [ ] New indexes verified (3 on agent_audit_log)

### Docker Deploy (Phase 6)
- [ ] Code pulled/merged to `main` on server
- [ ] Images built (api, ingestion, celery)
- [ ] Services restarted in correct order
- [ ] All 9 services healthy (docker compose ps)
- [ ] No containers in restart loop

### Frontend (Phase 7)
- [ ] Frontend builds locally (`pnpm build`)
- [ ] Frontend tests pass (`pnpm test`)
- [ ] Frontend deployed (Vercel / nginx / Docker)
- [ ] Frontend can reach API (no CORS errors)
- [ ] WebSocket connects from frontend

### Post-Deploy (Phase 8)
- [ ] `/health` returns 200
- [ ] Swagger docs load
- [ ] Redis has prices (HLEN > 0)
- [ ] Trading pairs seeded (600+)
- [ ] `validate_phase1.py` passes
- [ ] E2E smoke test passes
- [ ] Celery worker responsive (ping/pong)
- [ ] Celery beat PID exists

### Monitoring (Phase 9)
- [ ] Prometheus scraping API target
- [ ] 11 alert rules loaded
- [ ] Grafana login works
- [ ] 7 dashboards provisioned
- [ ] Prometheus datasource connected

### Agent (Phase 10 - Optional)
- [ ] Agent accounts provisioned
- [ ] `agent/.env` configured
- [ ] Agent smoke test passes
- [ ] Agent metrics visible in Prometheus (while running)

### Training (Phase 12 - Optional, Delayed)
- [ ] ML training queue worker configured
- [ ] 24h platform stability confirmed
- [ ] Training worker activated

---

## Known Issues to Track Post-Deploy

These are non-blocking issues that should be addressed in a follow-up release:

1. **R2-04 Audit Trail Routing** -- `enforcement.py` routes permission denials to `agent_feedback` table, not the new `agent_audit_log` table. Migration 020 created the table, but the code path needs updating. Track as a follow-up task.

2. **5 MEDIUM Performance Findings** -- Outstanding from the perf audit. Should be addressed in the next sprint:
   - Review `perf-checker` agent output for specifics
   - Typically N+1 queries, missing indexes, or async bottlenecks

3. **Monitoring Stack Ports** -- Prometheus (9090), Grafana (3001), pgAdmin (5050) are exposed to the host. In production, these should be behind a reverse proxy or firewall. Consider:
   - Removing host port mappings and using a reverse proxy (nginx/Traefik)
   - Or restricting access via firewall rules (`ufw allow from <admin-ip> to any port 9090`)

4. **No Alertmanager** -- Prometheus alert rules are loaded, but Alertmanager is not configured for notification delivery (email, Slack, PagerDuty). Alerts will fire in Prometheus but nobody will be notified. Add Alertmanager as a follow-up.

5. **Agent Scrape Target** -- The `agent:8001` scrape job in `prometheus.yml` will show as DOWN when the agent profile is not running. This generates Prometheus scrape errors in logs. Consider adding a `scrape_timeout` and `honor_labels: true` to suppress noise, or conditionally include the job only when the agent profile is active.

---

## Timing Estimate

| Phase | Time | Parallel? |
|-------|------|-----------|
| Phase 1: Pre-deployment checklist | 30-45 min | No |
| Phase 2: CI/CD fixes | 15-20 min | Yes (with Phase 3) |
| Phase 3: CORS fix | 10-15 min | Yes (with Phase 2) |
| Phase 4: Environment setup | 10-15 min | No |
| Phase 5: Database migration | 5-10 min | No |
| Phase 6: Docker deployment | 15-25 min | No |
| Phase 7: Frontend deployment | 15-30 min | Yes (after Phase 6) |
| Phase 8: Post-deployment validation | 15-20 min | No |
| Phase 9: Monitoring verification | 10-15 min | Yes (with Phase 8) |
| Phase 10: Agent deployment | 20-30 min | After Phase 8 |
| Phase 11: Rollback procedure | N/A (reference) | N/A |
| Phase 12: Training activation | 10-15 min | After 24h stability |
| **Total** | **~2-3 hours** | |

**Critical path:** Phase 1 -> Phase 2+3 (parallel) -> Phase 4 -> Phase 5 -> Phase 6 -> Phase 8 -> Phase 9

Phases 7, 10, and 12 can be done after the core platform is confirmed stable.
