---
type: c-level-report
date: 2026-04-01
scope: deployment-analysis
generated-by: c-level-report-skill
platform: AI Trading Agent
version: "2.0"
tags:
  - executive
  - deployment
  - data-pipeline
  - infrastructure
  - database
  - gap-fill
  - rollback
---

# Deployment & Data Continuity Analysis — AI Trading Agent Platform

**Date:** 2026-04-01
**Scope:** Server Deployment, Database Migrations, Candle Data Continuity, Gap Handling
**Report ID:** 2026-04-01-deployment-analysis
**Audience:** CTO / Infrastructure Lead

---

## 1. Executive Summary

This report provides a comprehensive analysis of how the TradeReady AI Trading Platform handles **production deployment**, **database migration safety**, **candle data continuity during deploys**, and **market data gap recovery**. The platform runs 9 Docker services on a single production server, deploys via GitHub Actions CI/CD (SSH-based), and uses TimescaleDB with continuous aggregates for time-series data.

### Key Findings

| Area | Status | Risk | Notes |
|------|--------|------|-------|
| CI/CD Pipeline | ✅ Operational | LOW | Auto-deploy on push to `main`, with backup + rollback |
| Database Migrations | ✅ Safe | LOW | Additive-only pattern enforced; pre-migration backup mandatory |
| Rolling Restart Strategy | ✅ Implemented | MEDIUM | ~5-20 sec ingestion gap during restart |
| Data Gap Detection | ⚠️ Planned | MEDIUM | Gap-fill task designed but not yet deployed |
| Candle Data for Backtesting | ✅ Resilient | LOW | `DataReplayer` UNIONs live aggregates + backfill table |
| Historical Backfill | ✅ Available | LOW | `backfill_history.py` covers 2017–present, multi-exchange |
| Backup Strategy | ⚠️ Partial | MEDIUM | Pre-deploy backup exists; no scheduled backup cron |
| Tick Loss During Deploy | ⚠️ Unavoidable | MEDIUM | In-memory tick buffer lost on ingestion restart |
| Rollback Capability | ✅ Implemented | LOW | Git commit + Alembic downgrade + image rebuild |
| Monitoring & Alerting | ✅ Operational | LOW | Prometheus + 11 alert rules + 7 Grafana dashboards |

**Overall Deployment Maturity:** `[███████░░░] 70%` — Core pipeline works; gap-fill automation and scheduled backups needed for production-grade resilience.

---

## 2. Deployment Architecture Overview

### 2.1 Infrastructure Stack

```
┌─────────────────────────────────────────────────────────────┐
│                    PRODUCTION SERVER                         │
│               (~8 CPU, ~10 GB RAM minimum)                  │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │
│  │ TimescaleDB  │  │    Redis    │  │   Prometheus       │  │
│  │ (PG16+TS)   │  │ (7-alpine)  │  │   + Grafana        │  │
│  │ 2 CPU, 4 GB │  │ 1 CPU,512MB │  │   0.5+0.5 CPU     │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────────────┘  │
│         │                │                                   │
│  ┌──────┴───────────────┴──────────────────────────────┐    │
│  │              Docker Internal Network                 │    │
│  └──────┬───────────┬────────────┬────────────┬────────┘    │
│         │           │            │            │              │
│  ┌──────┴──┐ ┌──────┴──┐ ┌──────┴──┐ ┌──────┴──────┐      │
│  │   API   │ │Ingestion│ │ Celery  │ │ Celery Beat │      │
│  │ 2C, 2G  │ │ 1C, 1G  │ │ 1C, 1G  │ │ 0.5C,256M  │      │
│  │ :8000   │ │ (no port)│ │ (no port)│ │ (no port)  │      │
│  └─────────┘ └─────────┘ └─────────┘ └────────────┘      │
│                                                             │
│  Total: ~8.5 CPU, ~10 GB RAM allocated                     │
└─────────────────────────────────────────────────────────────┘
```

**Key files:**
- `docker-compose.yml` — 9 services, bridge network, 4 named volumes
- `Dockerfile` — API service (Python 3.12-slim, non-root user)
- `Dockerfile.ingestion` — Price ingestion service
- `Dockerfile.celery` — Shared by celery worker + celery-beat
- `.env` — All secrets and configuration (never committed)

### 2.2 Service Dependencies

```
timescaledb ──┐
              ├──→ api ──→ (serves traffic on :8000)
redis ────────┤
              ├──→ ingestion (WS → Redis + TimescaleDB)
              ├──→ celery (background tasks)
              └──→ celery-beat (task scheduler)

prometheus ──→ grafana (:3001)
timescaledb ──→ pgadmin (:5050)
```

All app services wait for `timescaledb` and `redis` health checks before starting (`condition: service_healthy`).

---

## 3. CI/CD Deployment Pipeline

### 3.1 Pipeline Flow

```
Developer pushes to main
         │
         ▼
┌─────────────────────────────┐
│  GitHub Actions: test.yml   │
│  1. Checkout code           │
│  2. Install Python 3.12     │
│  3. ruff check src/ tests/  │
│  4. ruff format --check     │
│  5. mypy src/               │
│  6. pytest tests/unit       │
│     (with CI Redis)         │
└────────────┬────────────────┘
             │ (all pass)
             ▼
┌─────────────────────────────┐
│  GitHub Actions: deploy.yml │
│  SSH into production server │
│                             │
│  Step 1: Record rollback    │
│    git rev-parse HEAD       │
│    → /tmp/last-deploy-      │
│      rollback.txt           │
│                             │
│  Step 2: Database backup    │
│    pg_dump (gzipped)        │
│    Excludes hypertable      │
│    chunk data (ticks,       │
│    candles_backfill,        │
│    portfolio_snapshots,     │
│    backtest_snapshots)      │
│                             │
│  Step 3: Pull latest main   │
│    git fetch + reset --hard │
│                             │
│  Step 4: Build images       │
│    docker compose build     │
│    api ingestion celery     │
│                             │
│  Step 5: Ensure infra up    │
│    timescaledb + redis      │
│    (15 sec wait)            │
│                             │
│  Step 6: Record migration   │
│    revision (for rollback)  │
│                             │
│  Step 7: Run migrations     │
│    alembic upgrade head     │
│                             │
│  Step 8: Rolling restart    │
│    celery-beat → celery →   │
│    api (5s gap) →           │
│    ingestion                │
│                             │
│  Step 9: Health check       │
│    curl /health (15s wait)  │
│    On failure → ROLLBACK    │
└─────────────────────────────┘
```

**File:** `.github/workflows/deploy.yml`

### 3.2 Rollback Mechanism

If the health check at Step 9 fails:

```bash
# Automatic rollback sequence:
1. git checkout "$ROLLBACK_COMMIT"      # Revert code
2. docker compose build api ingestion celery  # Rebuild old images
3. docker compose up -d api ingestion celery celery-beat  # Restart with old code
4. alembic downgrade "${ROLLBACK_REVISION}"  # Revert migrations
```

**Strengths:**
- Automatic — no human intervention needed
- Covers both code AND database schema rollback
- Pre-deploy backup provides nuclear option if downgrade fails

**Weaknesses:**
- Rollback rebuilds images (~3-5 min), during which services are down
- Migration rollback assumes all migrations have clean `downgrade()` functions
- No notification/alerting on rollback — team discovers it from GitHub Actions logs

### 3.3 What Triggers a Deploy

| Trigger | Action |
|---------|--------|
| Push to `main` | Full pipeline: test → deploy |
| Pull request to `main` | Test only (no deploy) |
| Manual merge to `main` | Triggers auto-deploy |

---

## 4. Database Migration Strategy

### 4.1 Migration Safety Rules

The project enforces strict migration safety:

1. **Additive-only preferred** — New tables, new nullable columns, new indexes
2. **Two-phase NOT NULL** — Add column nullable → backfill data → enforce NOT NULL in separate migration
3. **Pre-migration backup mandatory** — `pg_dump` before every `alembic upgrade head`
4. **Dry-run verification** — `alembic upgrade head --sql` to inspect SQL before execution
5. **Migration chain verification** — `down_revision` chain checked before deployment
6. **No hypertable PK modifications** — TimescaleDB hypertables have special constraints

### 4.2 Migration Execution During Deploy

```
Old code running (serving traffic)
         │
         ▼
alembic upgrade head  ← Migrations run BEFORE restarting app services
         │               (old code can still serve while migrations apply)
         ▼
Rolling restart of services
         │
         ▼
New code running (uses new schema)
```

**Critical insight:** Migrations are applied while the OLD code is still serving. This means:
- **Additive migrations are safe** — old code ignores new columns/tables
- **Destructive migrations would break** — old code would fail on missing columns
- This is why the project enforces the additive-only pattern

### 4.3 Current Migration State

| Migration | Description | Type | Risk |
|-----------|-------------|------|------|
| 001-017 | Core platform schema | Applied | — |
| 018 | Agent logging tables + trace_id | Additive | LOW |
| 019 | Feedback lifecycle columns | Additive | LOW |
| 020 | Agent audit log table | Additive | LOW |

All migrations use Alembic with async SQLAlchemy (`asyncpg`). Migration head on production: varies by deployment state.

### 4.4 Rollback Capability Per Migration

```bash
# Roll back to specific revision
alembic downgrade 017     # Reverts 018, 019, 020

# Nuclear option: restore full backup
zcat ~/backups/pre-deploy-*.sql.gz | \
  docker compose exec -T timescaledb psql -U agentexchange -d agentexchange
```

---

## 5. Data Pipeline & Candle Storage Architecture

### 5.1 The Two Data Worlds

The platform maintains **two completely separate data planes**:

```
┌─────────────────────────────────────────────────────────┐
│              WORLD 1: LIVE (Redis)                       │
│                                                         │
│  Purpose: "What is the price RIGHT NOW?"                │
│  Latency: < 1 millisecond                               │
│  Data age: < 1 second                                   │
│  Written by: Ingestion service (every tick)              │
│  Read by: Order engine, risk manager, portfolio,         │
│           WebSocket clients, battle snapshots            │
│                                                         │
│  Key: HSET prices {SYMBOL} {price}                      │
│  Meta: HSET prices:meta {SYMBOL} {ISO timestamp}        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│         WORLD 2: HISTORICAL (TimescaleDB)               │
│                                                         │
│  Purpose: "What was the price at any point in history?" │
│  Latency: 1-100 milliseconds                            │
│  Data age: 2017 to present                              │
│  Written by: Ingestion flush + backfill scripts          │
│  Read by: Backtesting, candle endpoints, analytics      │
│                                                         │
│  Tables:                                                │
│  ├── ticks (hypertable, 1h chunks)                     │
│  ├── candles_1m (continuous aggregate)                  │
│  ├── candles_5m (continuous aggregate)                  │
│  ├── candles_1h (continuous aggregate)                  │
│  ├── candles_1d (continuous aggregate)                  │
│  └── candles_backfill (hypertable, 1mo chunks)         │
└─────────────────────────────────────────────────────────┘
```

### 5.2 Price Ingestion Flow

```
Exchange WebSocket (Binance/OKX/Bybit via CCXT)
    │
    │  Real-time trade ticks (~1000/sec for 600+ pairs)
    ▼
┌──────────────────────────────────────┐
│         INGESTION SERVICE            │
│                                      │
│  For EACH tick:                      │
│    1. HSET prices {SYMBOL} {price}   │ → Redis (instant)
│    2. HSET prices:meta {SYMBOL} {ts} │ → Redis (staleness tracking)
│    3. Update 24h ticker stats (Lua)  │ → Redis
│    4. Append to in-memory buffer     │
│                                      │
│  Every 1 second (or 5000 ticks):     │
│    5. asyncpg COPY to ticks table    │ → TimescaleDB
│    6. Publish to Redis pub/sub       │ → WebSocket bridge
│    7. Clear buffer                   │
└──────────────────────────────────────┘
         │                    │
         ▼                    ▼
    ┌─────────┐       ┌──────────────────┐
    │  Redis   │       │   TimescaleDB    │
    │ prices   │       │   ticks table    │
    │ (live)   │       │     │            │
    └─────────┘       │     ▼            │
                      │  Continuous       │
                      │  Aggregates:      │
                      │  candles_1m (1m)  │
                      │  candles_5m (5m)  │
                      │  candles_1h (1h)  │
                      │  candles_1d (1d)  │
                      └──────────────────┘
```

**Key configuration:**
- `TICK_FLUSH_INTERVAL=1.0` — Flush buffer every 1 second
- `TICK_BUFFER_MAX_SIZE=5000` — Force flush if buffer exceeds 5000 ticks
- `EXCHANGE_ID=binance` — Default exchange (supports 110+ via CCXT)

### 5.3 TimescaleDB Continuous Aggregates

TimescaleDB automatically materializes candle views from raw ticks:

| View | Interval | Source | Auto-refresh |
|------|----------|--------|--------------|
| `candles_1m` | 1 minute | `ticks` hypertable | Every 1 min |
| `candles_5m` | 5 minutes | `ticks` hypertable | Every 5 min |
| `candles_1h` | 1 hour | `ticks` hypertable | Every 1 hour |
| `candles_1d` | 1 day | `ticks` hypertable | Every 1 day |

**Important:** These aggregates can ONLY build candles from ticks that exist. If ticks are missing (due to ingestion downtime), the resulting candles will be **incomplete or absent**.

---

## 6. What Happens to Data During Deployment

### 6.1 The Deployment Data Gap Problem

During a production deployment, the ingestion service restarts. This creates a **data gap**:

```
Timeline:
─────────────────────────────────────────────────────────
  Normal ticks    │  DEPLOY GAP  │    Normal ticks
  flowing in      │  (no ticks)  │    flowing again
──────────────────┤              ├────────────────────────
                  │              │
            ingestion         ingestion
            stops             reconnects
                  │              │
                  └──── ~20-30 seconds ────┘
                    (image rebuild + WS reconnect)
```

### 6.2 Impact by Component

| Component | Impact During Deploy | Recovery |
|-----------|---------------------|----------|
| **Redis prices** | Stale for ~20-30 sec | Auto-updates on first tick after reconnect |
| **In-memory tick buffer** | **LOST** — unflushed ticks destroyed | Ticks in the gap are permanently lost |
| **TimescaleDB ticks** | Gap of ~20-30 sec | No auto-recovery; requires gap-fill |
| **Continuous aggregates** | Affected candle may be incomplete | Re-materialization won't help (source ticks missing) |
| **candles_backfill** | Unaffected | Historical data is persistent |
| **Order execution** | Paused during API restart (~5 sec) | Resumes on API restart; pending orders preserved in DB |
| **WebSocket clients** | Disconnected briefly | Clients auto-reconnect (frontend has retry logic) |
| **Celery tasks** | Brief queue delay | Redis-backed queue preserves tasks; worker resumes |

### 6.3 The Rolling Restart Minimizes the Gap

The deploy script uses a **rolling restart** to minimize disruption:

```
Step 1: celery-beat restarts     → No data impact (scheduler only)
Step 2: celery worker restarts   → Brief task processing delay
        (5 sec wait)
Step 3: API restarts             → ~5 sec API unavailability
        (5 sec wait)
Step 4: ingestion restarts       → ~20-30 sec tick gap
        (15 sec wait for WS reconnect)
```

**Ingestion is restarted LAST** — this is intentional. It minimizes the time that live prices are stale while other services are already running the new code.

### 6.4 Realistic Gap Size

| Scenario | Gap Duration | Ticks Lost | Candles Affected |
|----------|-------------|------------|------------------|
| Clean deploy (no migration) | ~20-30 sec | ~1,000-2,000 | 0-1 one-minute candle |
| Deploy with migrations | ~30-60 sec | ~2,000-5,000 | 1-2 one-minute candles |
| Deploy with rollback | ~5-10 min | ~50,000+ | 5-10 one-minute candles |
| Full server restart | ~2-5 min | ~20,000+ | 2-5 one-minute candles |

---

## 7. How Backtesting Handles Data Gaps

### 7.1 The DataReplayer UNION Strategy

The `DataReplayer` (backtesting engine) is **resilient to gaps** by design:

```sql
-- Simplified query logic:
SELECT bucket, symbol, open, high, low, close, volume
FROM (
    -- Source 1: Live continuous aggregates (from real-time ticks)
    SELECT * FROM candles_1h WHERE symbol = :sym AND bucket <= :virtual_clock
    UNION ALL
    -- Source 2: Historical backfill (from Binance REST API)
    SELECT * FROM candles_backfill WHERE symbol = :sym AND interval = '1h' AND bucket <= :virtual_clock
) combined
ORDER BY bucket
```

**Critical invariant:** `WHERE bucket <= virtual_clock` — prevents look-ahead bias.

**Why this is resilient:**
1. If a candle is missing from `candles_1h` (due to tick gap), the backfill table may have it
2. If both sources have the candle, `UNION ALL` returns both (dedup may be needed)
3. The `candles_backfill` table is populated by the backfill script and gap-fill task — independent of live ingestion

### 7.2 Historical Data Sources for Backtesting

```
                    ┌────────────────────────┐
                    │   DataReplayer Query    │
                    │   (backtesting engine)  │
                    └───────┬───────┬─────────┘
                            │       │
              UNION ALL     │       │     UNION ALL
                            │       │
                ┌───────────┘       └──────────────┐
                ▼                                   ▼
    ┌───────────────────────┐          ┌───────────────────────┐
    │   candles_1m/5m/1h/1d │          │    candles_backfill    │
    │  (continuous aggs)    │          │   (historical klines)  │
    │                       │          │                        │
    │  Source: live ticks   │          │  Source: Binance REST  │
    │  Coverage: since      │          │  Coverage: 2017-present│
    │  ingestion started    │          │  Intervals: 1d, 1h     │
    │  Gap-prone: YES       │          │  Gap-prone: NO         │
    └───────────────────────┘          └───────────────────────┘
```

### 7.3 The Backfill Script

**File:** `scripts/backfill_history.py`

```bash
# Full daily backfill (all pairs from 2017)
python scripts/backfill_history.py --daily --resume

# Hourly backfill (top 100 pairs, 5 years)
python scripts/backfill_history.py --hourly --resume

# Specific pairs and intervals
python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT --interval 1d --start 2017-01-01

# Multi-exchange support via CCXT
python scripts/backfill_history.py --exchange okx --daily
```

**Key features:**
- Fetches from Binance public REST API (no API key needed)
- CCXT support for 110+ exchanges (`--exchange` flag)
- `ON CONFLICT DO NOTHING` upsert — safe to run repeatedly
- `--resume` flag skips already-fetched ranges
- `--dry-run` for preview
- Batch insert size: 5,000 rows per commit

**Important:** The backfill script must run AFTER `seed_pairs.py` populates the `trading_pairs` table.

---

## 8. Data Gap Detection & Recovery

### 8.1 Current State: Gap-Fill Task (Designed, Not Yet Deployed)

A Celery periodic task has been **fully designed and documented** but is **not yet deployed to production**:

**Design document:** `development/gap_fill_implementation_plan.md`
**Research document:** `development/market_data_gap_fill.md`

**Proposed architecture:**

```
┌─────────────────────────────────────────────────┐
│          Gap-Fill Celery Task (Planned)          │
│                                                  │
│  Schedule: Every 4 hours (crontab */4)           │
│  Scope: Top 50 pairs by volume                   │
│                                                  │
│  Step 1: Get target symbols                      │
│    Intersect trading_pairs ∩ Binance top volume  │
│                                                  │
│  Step 2: Detect gaps                             │
│    SELECT symbol, MAX(bucket) FROM candles_backfill│
│    WHERE interval = '1h'                         │
│    → Any symbol >2 hours stale = gap             │
│                                                  │
│  Step 3: Fill gaps                               │
│    Fetch from Binance REST GET /api/v3/klines    │
│    Insert into candles_backfill                  │
│    ON CONFLICT DO NOTHING                        │
│                                                  │
│  Safety caps:                                    │
│    Max gap per run: 7 days (168 hours)           │
│    Rate limit: 150ms between API pages           │
│    Hard timeout: 10 minutes                      │
└─────────────────────────────────────────────────┘
```

### 8.2 Why Gap-Fill Uses `candles_backfill` (Not `ticks`)

```
Option A (chosen): Fill candles_backfill
  ✅ Zero schema changes needed
  ✅ DataReplayer already UNIONs this table
  ✅ ON CONFLICT prevents duplicates
  ✅ Available to backtesting immediately

Option B (rejected): Fill ticks table
  ❌ Would need to reconstruct individual ticks from candle data
  ❌ Reconstructed ticks would be synthetic (not real trades)
  ❌ Much higher data volume
  ❌ Continuous aggregates would re-materialize (extra compute)
```

### 8.3 Current Gap Recovery Workflow (Manual)

Until the automated gap-fill task is deployed:

```bash
# Step 1: Identify gaps (manual check)
docker compose exec -T timescaledb psql -U agentexchange -d agentexchange -c "
  SELECT symbol, MAX(bucket) as latest_candle,
         NOW() - MAX(bucket) as gap_size
  FROM candles_backfill
  WHERE interval = '1h'
  GROUP BY symbol
  HAVING NOW() - MAX(bucket) > INTERVAL '2 hours'
  ORDER BY gap_size DESC
  LIMIT 20;
"

# Step 2: Backfill the gaps
python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT --interval 1h --start 2026-03-31 --resume

# Step 3: Verify
docker compose exec -T timescaledb psql -U agentexchange -d agentexchange -c "
  SELECT COUNT(*) FROM candles_backfill
  WHERE interval = '1h' AND bucket > NOW() - INTERVAL '24 hours';
"
```

---

## 9. Backup Strategy

### 9.1 Current Backup Coverage

| Backup Type | When | What's Included | What's Excluded | Storage |
|-------------|------|-----------------|-----------------|---------|
| Pre-deploy backup | Every deployment | Full schema + app data (accounts, agents, orders, trades, positions, strategies, etc.) | Hypertable chunk data (ticks, candles_backfill, portfolio_snapshots, backtest_snapshots) | `~/backups/` on server |
| Manual backup | On demand | Full DB dump | Nothing (full dump) | `~/backups/` on server |
| Redis persistence | Continuous | AOF (every second) + RDB snapshots (60/300/900 sec thresholds) | Nothing | `redis_data` Docker volume |
| Docker volumes | Persistent | TimescaleDB data, Redis data, Grafana config | — | Named Docker volumes |

### 9.2 Why Hypertable Data is Excluded from Deploy Backups

The deploy backup excludes heavy time-series tables for speed:

```
Excluded tables (can be 10s of GB):
  _timescaledb_internal._hyper_*  (hypertable chunk data)
  ticks                           (raw trade data)
  candles_backfill                (historical klines)
  portfolio_snapshots             (equity curves)
  backtest_snapshots              (backtest state)
```

**Rationale:** These tables can be tens of gigabytes. A full dump would take 30+ minutes and block the deployment. The schema and app data (~50-200 MB) backs up in seconds.

**Risk mitigation:**
- `candles_backfill` data is **recoverable** via `backfill_history.py --resume`
- `ticks` data from before the backup can be rebuilt from exchange REST APIs
- `portfolio_snapshots` are derived data (can be regenerated from trades)
- Docker volumes persist across container restarts (data is not lost on deploy)

### 9.3 Backup Gaps (Areas for Improvement)

| Gap | Risk | Recommendation |
|-----|------|----------------|
| No scheduled backup cron | HIGH | Add daily backup via Celery beat or system cron |
| Backups only on deploy server | MEDIUM | Add off-site backup (S3, rsync to second server) |
| No backup retention policy | LOW | Keep 7 daily + 4 weekly + 3 monthly, auto-prune old |
| No backup restore testing | MEDIUM | Monthly drill: restore backup to staging environment |
| Hypertable data not backed up | LOW (recoverable) | Consider weekly full dump for disaster recovery |

---

## 10. Health Checks & Service Recovery

### 10.1 Docker Health Checks

Every service has a health check defined in `docker-compose.yml`:

| Service | Health Check | Interval | Start Period |
|---------|-------------|----------|--------------|
| `timescaledb` | `pg_isready` | 10s | 30s |
| `redis` | `redis-cli ping` | 10s | 10s |
| `api` | `curl http://localhost:8000/health` | 15s | 30s |
| `ingestion` | Python script checks `prices:meta` freshness in Redis (<120s) | 30s | 60s |
| `celery-beat` | PID file exists | 30s | 15s |
| `prometheus` | `wget --spider http://localhost:9090/-/ready` | 15s | 15s |
| `grafana` | `wget --spider http://localhost:3000/api/health` | 15s | 30s |

### 10.2 Automatic Recovery

All services have `restart: unless-stopped` — Docker automatically restarts crashed containers.

**Ingestion reconnection:** The WebSocket client (CCXT adapter) has built-in reconnection logic. When the ingestion service restarts:
1. Container starts (~5 sec)
2. WebSocket connection to exchange (~5-15 sec)
3. First tick received → Redis updated
4. Tick buffer starts filling → first flush after 1 second

**Total reconnection time:** ~10-30 seconds

### 10.3 Monitoring & Alerting

**Prometheus** scrapes the API every 15 seconds and evaluates 11 alert rules:

| Alert | Condition | Severity |
|-------|-----------|----------|
| `AgentUnhealthy` | Agent health metric down | Critical |
| `AgentHighErrorRate` | Error rate > threshold | Warning |
| `AgentHighLLMCost` | LLM spending exceeds budget | Warning |
| + 8 more rules | Various agent/system conditions | Mixed |

**Grafana** provides 7 dashboards for visual monitoring:
1. Agent Overview
2. Agent API Calls
3. Agent LLM Usage
4. Agent Memory
5. Agent Strategy
6. Ecosystem Health
7. Retraining

---

## 11. Deployment Checklist & Procedures

### 11.1 Standard Deployment (Auto — Push to Main)

```
1. ✅ All tests pass locally (ruff, mypy, pytest)
2. ✅ Push/merge to main branch
3. 🤖 GitHub Actions: test.yml runs (lint + type check + unit tests)
4. 🤖 GitHub Actions: deploy.yml runs:
   a. SSH to production server
   b. Record rollback point (git commit + alembic revision)
   c. Database backup (schema + app data, compressed)
   d. Pull latest main
   e. Build Docker images
   f. Ensure infra services healthy
   g. Run alembic upgrade head
   h. Rolling restart: celery-beat → celery → api → ingestion
   i. Health check (curl /health)
   j. On failure: automatic rollback
5. ✅ Deploy complete
```

### 11.2 Manual Deployment (When CI/CD Not Trusted)

Documented in `development/deployment-plan-v002.md`, Phase 6.2. Follows the same steps as the automated pipeline but executed manually via SSH.

### 11.3 First-Time Server Setup

```bash
# 1. Start infrastructure
docker compose up -d timescaledb redis

# 2. Run all migrations
docker compose run --rm api alembic upgrade head

# 3. Seed trading pairs (600+ USDT pairs from Binance)
docker compose exec api python scripts/seed_pairs.py

# 4. Validate infrastructure
docker compose exec api python scripts/validate_phase1.py

# 5. (Optional) Backfill historical candles for backtesting
docker compose exec api python scripts/backfill_history.py --daily --resume
docker compose exec api python scripts/backfill_history.py --hourly --resume

# 6. Start all services
docker compose up -d

# 7. Seed test data (optional, for development)
docker compose exec api python -m scripts.seed_test_user
```

---

## 12. Risk Assessment & Recommendations

### 12.1 Risk Matrix

| # | Risk | Likelihood | Impact | Current Mitigation | Recommended Action |
|---|------|-----------|--------|-------------------|-------------------|
| R1 | Tick loss during deploy | HIGH (every deploy) | LOW (20-30 sec gap) | Rolling restart minimizes gap | Deploy automated gap-fill task |
| R2 | No scheduled backups | MEDIUM | HIGH (data loss on disk failure) | Pre-deploy backup only | Add daily automated backup cron |
| R3 | Gap-fill not deployed | MEDIUM | MEDIUM (accumulating gaps) | Manual backfill script | Implement and deploy the designed Celery task |
| R4 | No off-site backups | LOW (single server) | CRITICAL (total data loss) | Docker volumes persist | Add S3/remote backup replication |
| R5 | Rollback image rebuild time | LOW | MEDIUM (5-10 min downtime) | Automatic rollback works | Pre-build and tag images; keep previous image |
| R6 | No staging environment | MEDIUM | MEDIUM (untested in prod-like env) | CI tests + E2E scripts | Add staging server or docker-compose.staging.yml |
| R7 | Ingestion single point of failure | LOW | HIGH (no price data) | Docker restart policy | Add redundant ingestion instance or failover |
| R8 | No backup restore testing | MEDIUM | HIGH (backup may be corrupt) | Backups created but never tested | Monthly restore drill to staging |

### 12.2 Priority Recommendations

**P0 — Do This Week:**

1. **Deploy the gap-fill Celery task** — The design is complete (`development/gap_fill_implementation_plan.md`). Implementation is ~4 hours of work. This eliminates the most common data continuity issue.

2. **Add scheduled backup cron** — Add a daily backup job to Celery beat:
   ```python
   "daily-db-backup": {
       "task": "src.tasks.backup.run_daily_backup",
       "schedule": crontab(hour=3, minute=0),  # 3:00 AM daily
   }
   ```

**P1 — Do This Month:**

3. **Off-site backup replication** — Sync backups to S3 or a second server
4. **Pre-build rollback images** — Tag and keep the previous Docker image so rollback doesn't require rebuilding
5. **Deploy failure notifications** — Add Slack/email webhook on rollback trigger

**P2 — Do This Quarter:**

6. **Staging environment** — Mirror production for pre-deploy testing
7. **Blue-green deployment** — Run two API instances and switch traffic, eliminating downtime
8. **Backup restore testing** — Monthly automated drill

---

## 13. Appendix: Key File Reference

### Deployment Files

| File | Purpose |
|------|---------|
| `.github/workflows/deploy.yml` | CI/CD deployment pipeline (SSH-based) |
| `.github/workflows/test.yml` | CI test pipeline (lint + type check + unit tests) |
| `docker-compose.yml` | Production service definitions (9 services) |
| `docker-compose.dev.yml` | Development overrides (hot reload, debug ports) |
| `Dockerfile` | API service image |
| `Dockerfile.ingestion` | Price ingestion service image |
| `Dockerfile.celery` | Celery worker/beat image |
| `.env.example` | Environment variable template |

### Data Pipeline Files

| File | Purpose |
|------|---------|
| `src/price_ingestion/service.py` | Main ingestion service (WS → Redis + TimescaleDB) |
| `src/price_ingestion/tick_buffer.py` | In-memory tick buffer with periodic flush |
| `src/exchange/ccxt_adapter.py` | CCXT exchange abstraction (110+ exchanges) |
| `scripts/backfill_history.py` | Historical candle backfill from exchange REST APIs |
| `scripts/seed_pairs.py` | Trading pair seeding from exchange |
| `scripts/validate_phase1.py` | Infrastructure health validation |

### Database Files

| File | Purpose |
|------|---------|
| `alembic/` | Migration directory (020 migrations) |
| `alembic/env.py` | Async migration environment |
| `src/database/models/` | SQLAlchemy ORM models |
| `src/database/repositories/` | Data access layer (repository pattern) |

### Monitoring Files

| File | Purpose |
|------|---------|
| `prometheus.yml` | Prometheus scrape config |
| `monitoring/alerts/agent-alerts.yml` | 11 Prometheus alert rules |
| `monitoring/dashboards/` | 7 Grafana dashboard JSON files |
| `monitoring/provisioning/` | Auto-provisioning config for Grafana |

### Planning Documents

| File | Purpose |
|------|---------|
| `development/deployment-plan-v002.md` | Comprehensive 12-phase deployment plan |
| `development/deployment-fix-plan.md` | CI/CD pipeline fix guide |
| `development/gap_fill_implementation_plan.md` | Gap-fill task design spec |
| `development/market_data_gap_fill.md` | Gap-fill research and analysis |
| `development/data-pipeline-report.md` | Complete data pipeline A-Z report |

---

## 14. Conclusion

The TradeReady platform has a **solid deployment foundation** with automated CI/CD, rolling restarts, pre-deploy backups, and automatic rollback capability. The database migration strategy is well-designed with safety checks and additive-only patterns.

The primary gap is **automated data recovery**: while the system handles deploy-time tick loss gracefully (20-30 second gaps), there is no automated mechanism to fill those gaps after the fact. The gap-fill Celery task has been fully designed but needs implementation and deployment.

**Bottom line:** The platform is **deployable and recoverable**, but needs the gap-fill automation and scheduled backups to be truly **production-grade** for a financial data platform where data completeness matters.

---

*Report generated by Claude Code agent fleet — 4 research agents + direct file analysis*
*Files analyzed: 25+ across deployment, infrastructure, data pipeline, and monitoring*
