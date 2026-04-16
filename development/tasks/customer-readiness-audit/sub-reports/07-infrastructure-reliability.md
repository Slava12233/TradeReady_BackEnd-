---
type: task
board: customer-readiness-audit
tags:
  - infrastructure
  - reliability
  - monitoring
  - backup
  - audit
---

# Sub-Report 07: Infrastructure Reliability

**Date:** 2026-04-15
**Auditor:** deploy-checker agent
**Scope:** Docker configuration, CI/CD pipeline, backup strategy, monitoring, database configuration, environment variables, logging, SSL/TLS

---

## Infrastructure Scorecard

| Area | Status | Risk Level | Notes |
|------|--------|------------|-------|
| Docker: Health Checks | PASS | Low | All 7 services have health checks |
| Docker: Restart Policies | PASS | Low | All services use `unless-stopped` |
| Docker: Resource Limits | PASS | Low | CPU + memory limits on every service |
| Docker: Volume Persistence | PASS | Low | 4 named volumes (timescaledb, redis, grafana, pgadmin) |
| Docker: Network Isolation | PASS | Low | All services on `internal` bridge; Redis has no host port |
| CI/CD: Gate Coverage | PASS | Low | Lint + unit tests required; deploy only after test job succeeds |
| CI/CD: Rollback Documented | PASS | Medium | Rollback present but has a correctness risk (see below) |
| CI/CD: continue-on-error Jobs | WARN | Medium | 3 of 5 test jobs are non-blocking |
| Backup: Script Exists | PASS | Medium | `scripts/backup_db.sh` with 30-day retention |
| Backup: Pre-Deploy Backup | PASS | Low | deploy.yml takes a backup before every deploy |
| Backup: Scheduled Cron | FAIL | HIGH | No cron job configured; daily backups depend entirely on manual/deploy triggers |
| Backup: Off-Site Storage | FAIL | HIGH | S3 upload is commented out; backups stored only on the server |
| Monitoring: Prometheus | PASS | Low | Running, scrapes API + self |
| Monitoring: Grafana Dashboards | PASS | Low | 7 dashboards auto-provisioned |
| Monitoring: Alert Rules | PASS | Low | 11 Prometheus alert rules loaded |
| Monitoring: Alertmanager | FAIL | HIGH | No Alertmanager service; alerts fire in Prometheus but go nowhere |
| Database: Pool Configuration | PASS | Low | pool_size=10, max_overflow=20, pre_ping, recycle=3600 |
| Database: Migration Chain | PASS | Low | 23 migrations, linear chain, head=023 |
| Env Vars: Required Fields | PASS | Low | DATABASE_URL, REDIS_URL, JWT_SECRET all required at startup |
| Env Vars: Sensitive Defaults | WARN | HIGH | `change_me_in_production` default passwords exist in config.py |
| Logging: Format | PASS | Low | structlog JSON with ISO timestamps configured at startup |
| Logging: Rotation | WARN | Medium | Log rotation delegated entirely to Docker json-file driver (10 MB / 3 files per service); no application-level retention |
| SSL/TLS | FAIL | HIGH | No HTTPS enforcement anywhere; API exposed on HTTP port 8000 with no reverse proxy config in repository |

---

## Detailed Findings

### 1. Docker Configuration

**Services (9 total core, 1 profile-gated):**

| Service | Health Check | Restart Policy | Resource Limit | External Port |
|---------|-------------|----------------|----------------|---------------|
| `timescaledb` | `pg_isready` — 10s/5s/10 retries/30s start | `unless-stopped` | 2 CPU / 4 GB | 5432 |
| `redis` | `redis-cli ping` — 10s/3s/5 retries/10s start | `unless-stopped` | 1 CPU / 512 MB | None (internal only) |
| `api` | `curl -f http://localhost:8000/health` — 15s/5s/5 retries/30s start | `unless-stopped` | 2 CPU / 2 GB | 8000 |
| `ingestion` | Redis BTCUSDT freshness check (2-minute window) — 30s/10s/3 retries/60s start | `unless-stopped` | 1 CPU / 1 GB | None |
| `celery` | No health check | `unless-stopped` | 1 CPU / 1 GB | None |
| `celery-beat` | PID file test (`/tmp/celerybeat.pid`) — 30s/10s/3 retries/15s start | `unless-stopped` | 0.5 CPU / 256 MB | None |
| `pgadmin` | No health check | `unless-stopped` | 0.5 CPU / 512 MB | 5050 |
| `prometheus` | HTTP readiness probe — 15s/5s/5 retries/15s start | `unless-stopped` | 0.5 CPU / 512 MB | 9090 |
| `grafana` | HTTP health API — 15s/5s/5 retries/30s start | `unless-stopped` | 0.5 CPU / 512 MB | 3001 |

**Issues:**
- `celery` worker has no health check. A stuck or crashed worker will show as "running" with no automatic restart signal beyond Docker's own exit code detection.
- `pgadmin` has no health check. This is acceptable for a non-critical admin tool.
- `celery-beat` depends on `celery` with `service_started` condition, not `service_healthy` (celery has no healthcheck). This is acceptable since beat cannot meaningfully health-check a worker it does not communicate with synchronously.
- Redis persistence is correctly configured: AOF (appendfsync everysec) + RDB snapshots (60s/1write, 300s/10writes, 900s/100writes). This provides durability with at most 1 second of data loss on crash.
- `timescaledb` exposes port 5432 on the host. This is a potential attack surface if the server has a public IP with no firewall. The database password must be non-default in production.

**Volumes:**
- `timescaledb_data` — PostgreSQL data directory
- `redis_data` — Redis AOF + RDB persistence
- `grafana_data` — Dashboard state and provisioning
- `pgadmin_data` — pgAdmin sessions and saved server configs

No volume for Prometheus means Prometheus metrics history is ephemeral and lost on container restart. This is a medium-severity gap for trending and anomaly detection over time.

**Network isolation:**
All services are on the `internal` bridge network. Redis has no host port — it is only accessible from within the Docker network. This is the correct security posture.

---

### 2. CI/CD Pipeline

**Pipeline structure:**
- `test.yml` defines 5 jobs: `lint` (blocking), `test` (blocking, needs lint), `integration-tests` (non-blocking), `agent-tests` (non-blocking), `gym-tests` (non-blocking)
- `deploy.yml` calls `test.yml` via `workflow_call` and then runs `deploy` (needs test)

**Gate analysis:**
- `lint` and `test` (unit tests) are required gates — a failure blocks deployment
- `integration-tests`, `agent-tests`, and `gym-tests` all have `continue-on-error: true` — they cannot block a deploy

This means production deploys can succeed even if all integration tests are failing. This is explicitly documented in context.md as intentional due to pre-existing failures (httpx AsyncClient API, missing pydantic_ai, stale MCP tool counts). The risk is that regressions introduced in new code will not be caught by integration tests in CI.

**Rollback mechanism (deploy.yml):**
The deploy script records `ROLLBACK_COMMIT` and `ROLLBACK_REVISION` before applying changes. On health check failure it checks out the old commit, rebuilds images, and calls `alembic downgrade`. This is functionally correct with one risk:

```bash
docker compose exec -T api alembic downgrade "${ROLLBACK_REVISION:-017}"
```

The fallback value `017` is hardcoded. If the production database is already at migration 023 and `ROLLBACK_REVISION` was not captured correctly (e.g., `alembic current` returned no output), the downgrade will target 017, dropping 6 migrations worth of schema changes. This could cause data loss.

**No staging environment:** Deploys go directly from main branch to production. There is no staging step in the pipeline.

**pip caching:** The `test` job uses `actions/cache@v4` for pip. The `lint` job does not use caching, causing a full pip install on every lint run.

---

### 3. Backup Strategy

**Pre-deploy backup (`deploy.yml`):**
Every deploy triggers a `pg_dump` that excludes hypertable data (ticks, candles_backfill, portfolio_snapshots, backtest_snapshots) and compresses to `~/backups/pre-deploy-YYYYMMDD-HHMMSS.sql.gz`. This protects application data before schema migrations.

**Daily backup script (`scripts/backup_db.sh`):**
- Excludes: `_timescaledb_internal._hyper_*`, `ticks`, `candles_backfill`, `portfolio_snapshots`, `backtest_snapshots`, `battle_snapshots`
- Includes: accounts, agents, orders, trades, positions, strategies, webhook_subscriptions, all application state
- Retention: 30 days
- Compression: gzip

**Critical gap — no cron job:**
The `backup_db.sh` script is well-written but is not wired into any scheduler. The crontab line in the script comment shows the intended usage:
```
# Cron:   0 3 * * * /path/to/scripts/backup_db.sh >> /var/log/agentexchange-backup.log 2>&1
```
This cron job must be manually created on the production server. There is no evidence it has been done. If the server was provisioned without it, daily backups are not running. The deploy backup only covers pre-deploy moments; weekday data between deploys has no backup coverage.

**Backup health check (`scripts/check_backup_health.sh`):**
The script exists and checks for a backup file newer than 26 hours. However it is not wired to Prometheus or any alerting system. It is a standalone script that must be manually run or called by a separate monitoring agent.

**S3 off-site storage:**
The S3 upload block in `backup_db.sh` is commented out. All backups are stored only on the production server's local filesystem (`~/backups/`). A disk failure or server loss would destroy both the application and its backups simultaneously.

---

### 4. Monitoring

**Prometheus configuration (`prometheus.yml`):**
- Scrape interval: 15s
- Scrapes: self (`localhost:9090`), API (`api:8000/metrics`), agent (`agent:8001/metrics` — always configured but only active with `--profile agent`)
- Alert rules loaded: `agent-alerts.yml` (11 rules)

**Grafana dashboards (7 total, auto-provisioned):**
- `agent-overview.json` — trades, signals, API calls per agent
- `agent-api-calls.json` — per-tool latency, token usage, cost
- `agent-llm-usage.json` — LLM costs, model distribution, error rate
- `agent-memory.json` — cache hit/miss, retrieval latency
- `agent-strategy.json` — signal distribution, PnL attribution
- `ecosystem-health.json` — budget utilization, permission denials, trade success rate
- `retraining.json` — retrain events, A/B gate outcomes, drift detection

All dashboards are agent-ecosystem focused. There are no dashboards for platform infrastructure: no API request rate, no database query latency, no Redis memory usage, no container CPU/memory graphs. The 4 platform metrics (`platform_orders_total`, `platform_order_latency_seconds`, `platform_api_errors_total`, `platform_price_ingestion_lag_seconds`) are defined in `src/monitoring/metrics.py` but have no dedicated Grafana dashboard.

**Alert routing — critical gap:**
Prometheus alert rules are defined and loaded. However, there is no Alertmanager service in `docker-compose.yml` and no `alerting:` stanza in `prometheus.yml`. Alerts will fire in the Prometheus alerts UI but will not be sent to any notification channel (Slack, PagerDuty, email, etc.). There is no way for on-call engineers to receive automated notification of production incidents. The 11 alert rules including `PlatformIngestionStale` (critical) and `AgentConsecutiveErrors` (critical) are effectively silent.

---

### 5. Database Configuration

**Connection pool:**
- SQLAlchemy async pool: `pool_size=10`, `max_overflow=20` (max 30 concurrent connections), `pool_pre_ping=True` (validates connections before use), `pool_recycle=3600` (recycles connections after 1 hour to avoid stale state)
- asyncpg raw pool (for COPY bulk inserts): `min_size=2`, `max_size=10`, `command_timeout=60`
- Total maximum DB connections from API container: up to 40 (SQLAlchemy 30 + asyncpg 10)

With 4 application containers (api, ingestion, celery, celery-beat) all connecting, the database needs to support up to ~120 concurrent connections. TimescaleDB's default `max_connections=100` may be insufficient. This is not explicitly configured in the compose file, relying on the Docker image default.

**Migration chain:**
- 23 migrations on disk, linear chain (010 → 012 intentional gap, 011 missing by design)
- Current head: 023 (`webhook_subscriptions` table)
- Every migration has a `downgrade()` function
- Monetary columns use `Numeric(20, 8)`, timestamps use `TIMESTAMP(timezone=True)`, hypertable PKs include partition column

**Database backup exclusions:**
The backup strategy correctly excludes regenerable time-series data (ticks, candles_backfill) to keep backup size manageable. Application state (accounts, agents, orders, trades, strategies) is included.

---

### 6. Environment Variables

**Required vars with no default (validated at startup):**
- `JWT_SECRET` — validated 32+ chars; `.env.example` shows `change_me_to_random_64_char_string` which is 32 chars exactly and would pass the validator in test environments but is not a real secret
- `DATABASE_URL` — validated to use `postgresql+asyncpg://` scheme

**Vars with insecure defaults in `src/config.py`:**
- `database_url` defaults to `postgresql+asyncpg://agentexchange:change_me_in_production@timescaledb:5432/agentexchange`
- `postgres_password` defaults to `change_me_in_production`
- `grafana_admin_password` defaults to `change_me`

These defaults mean the application can start without a `.env` file using insecure credentials. If `.env` is missing on the server (e.g., after a fresh clone), the platform will start with default credentials and data will be written to a database that an attacker could access with `change_me_in_production`.

**Notable absences from `.env.example`:**
- `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` are referenced in `docker-compose.yml` with inline defaults (`admin@agentexchange.dev` / `admin1234`) but are not documented in `.env.example`. pgAdmin is exposed on port 5050.

---

### 7. Logging

**Application logging:**
structlog is configured at startup in the lifespan handler (`src/main.py` lines 83-95) with:
- JSON rendering via `structlog.processors.JSONRenderer()`
- ISO timestamps via `TimeStamper(fmt="iso")`
- Log level and logger name attached to each record
- Stack traces and exception info rendered inline

This is a production-appropriate structured logging configuration.

**Log retention:**
Log rotation is handled by Docker's json-file logging driver, configured identically on all services:
```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```
This provides 30 MB maximum per service (10 MB × 3 files). For a trading platform processing hundreds of orders and thousands of ticks per minute, 30 MB of logs may cover only hours of operation before older logs are rotated out. There is no log aggregation, centralized log storage, or shipping to an external system (e.g., Loki, CloudWatch, ELK).

**No application-level log file writes.** All logging goes to stdout/stderr and is captured by Docker. There is no mechanism to retain logs beyond what Docker's rotation window allows.

---

### 8. SSL/TLS

No HTTPS configuration is present anywhere in the repository:
- No nginx, Caddy, or Traefik reverse proxy configuration files
- No TLS certificates or certificate management configuration
- No HTTPS enforcement in the FastAPI application (no redirect, no HSTS)
- The API is served directly on HTTP port 8000

The API has CORS configured for `https://tradeready.io` and `https://www.tradeready.io`, indicating a production frontend exists over HTTPS. However, all API traffic from the frontend to the backend travels over unencrypted HTTP unless a reverse proxy is configured externally on the production server (outside this repository).

The CORS origins configuration explicitly includes the production domain, which suggests external TLS termination may exist at the server level (e.g., via a cloud load balancer or manually configured nginx). However, this is not documented or verifiable from the repository alone.

---

## Top 3 Operational Risks

### Risk 1: No Automated Backup Execution (CRITICAL)
**Likelihood:** High — the cron job comment in `backup_db.sh` suggests it was intended but not automated
**Impact:** Complete data loss on server failure or disk corruption
**Detail:** The daily backup script is well-written but has no scheduler. Only pre-deploy backups run automatically. A week of trading data between deploys has zero backup coverage. Backups are also stored only on the server — no off-site copy.
**Resolution:** (1) Add a cron job to the production server: `0 3 * * * /path/to/scripts/backup_db.sh`. (2) Uncomment and configure the S3 upload block. (3) Wire `check_backup_health.sh` into a Prometheus textfile exporter or Celery beat task to alert when backups are missing.

### Risk 2: Alerting Is Completely Silent (HIGH)
**Likelihood:** Certain — Alertmanager is missing from the stack
**Impact:** Production incidents (price ingestion stall, high error rate, agent unhealthy) produce no notifications. Downtime is discovered only via manual monitoring or user reports.
**Detail:** 11 Prometheus alert rules including `PlatformIngestionStale` (critical, 2-minute trigger) and `AgentConsecutiveErrors` (critical) are loaded and will fire in the Prometheus UI, but with no Alertmanager and no `alerting:` routing config in `prometheus.yml`, they are never delivered to any human.
**Resolution:** Add Alertmanager to `docker-compose.yml` with an `alertmanager.yml` config routing critical alerts to Slack or email. Add `alerting:` stanza to `prometheus.yml`.

### Risk 3: HTTP-Only API in Production (HIGH)
**Likelihood:** Certain — no reverse proxy config exists in the repository
**Impact:** JWT tokens, API keys, and trading data transmitted in plaintext; susceptible to man-in-the-middle attacks; browsers will warn about mixed content when the Vercel frontend (HTTPS) calls the HTTP API
**Detail:** The API is served on HTTP port 8000 with no TLS. CORS origins include `https://tradeready.io`, strongly implying the frontend calls the backend over the internet. If a reverse proxy exists on the production server, it is not in this repository and therefore not reproducible, reviewable, or deployable via CI/CD.
**Resolution:** Add a reverse proxy configuration (nginx or Caddy) to the repository with TLS termination. Add it as a service in `docker-compose.yml` or document the external configuration requirement clearly.

---

## Additional Warnings

**W1: Integration tests are non-blocking in CI**
Three of five test jobs use `continue-on-error: true`. This was intentional (pre-existing failures) but means that new integration test regressions will not block production deploys. Acceptable as a temporary state; the 27 pre-existing failures should be resolved.

**W2: Celery worker has no health check**
A crashed celery worker will not be detected by Docker health checks. Tasks will queue in Redis and never execute. There is no Prometheus alert for Celery task queue depth or worker liveness.

**W3: Prometheus metrics history is ephemeral**
The `prometheus` service has no named volume. A container restart resets all metrics history. Short-lived spikes and historical trending are lost. Add a `prometheus_data` volume.

**W4: Default credentials exist in `src/config.py`**
The Settings class defaults `postgres_password` to `change_me_in_production` and `grafana_admin_password` to `change_me`. These are fallbacks — they are overridden if `.env` is present — but if `.env` is absent on the server, the application will start with insecure credentials. A startup validation check asserting these are not the default values in production mode would prevent this.

**W5: Rollback downgrade fallback to migration 017**
The deploy rollback in `deploy.yml` uses `"${ROLLBACK_REVISION:-017}"` as a fallback. If the current production head is 023 and `ROLLBACK_REVISION` was not captured, a health-check-triggered rollback would run `alembic downgrade 017` — dropping 6 migrations and all the data they created.

**W6: pgAdmin exposed on port 5050 with weak defaults**
pgAdmin runs with `PGADMIN_DEFAULT_PASSWORD: admin1234` unless overridden. Port 5050 is exposed on the host. On a server with a public IP and no firewall, the database admin interface is accessible with default credentials.

**W7: No platform infrastructure Grafana dashboard**
The 7 existing dashboards are all agent-ecosystem focused. There is no dashboard showing API request throughput, database query latency, Redis memory usage, or container resource consumption. The 4 platform Prometheus metrics are collected but never visualized.

---

## Summary Table

| Capability | Implemented | Gaps |
|------------|-------------|------|
| Container health checks | Yes (7/9 services) | celery worker, pgadmin missing |
| Automatic restart | Yes (all services) | — |
| Resource limits | Yes (all services) | — |
| Data persistence | Yes (4 named volumes) | Prometheus history ephemeral |
| Network isolation | Yes | — |
| Pre-deploy backup | Yes | — |
| Daily automated backup | No (script only, no cron) | Cron job not configured |
| Off-site backup | No | S3 code commented out |
| Backup health alerting | No | Script not wired to monitoring |
| Prometheus metrics | Yes | — |
| Grafana dashboards | Yes (7 agent-focused) | No platform infra dashboard |
| Alert rules defined | Yes (11 rules) | — |
| Alert delivery | No | No Alertmanager |
| Structured logging | Yes | — |
| Log retention/aggregation | Partial (Docker 30 MB/svc) | No central log store |
| HTTPS/TLS | Unknown (not in repo) | No reverse proxy config |
| DB connection pooling | Yes | max_connections check needed |
| Migration safety | Yes (23 migrations) | Rollback fallback risk |
| Integration test gate | Partial | 3/5 jobs non-blocking |
