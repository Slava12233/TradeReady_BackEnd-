---
type: task
board: customer-readiness-audit
tags:
  - health-check
  - live-platform
  - deployment
---

# Sub-Report 01: Live Platform Health Check

**Date:** 2026-04-15
**Agent:** deploy-checker
**Overall Status:** PARTIAL — Frontend UP, Backend UP (wrong domain documented), API unreachable via tradeready.io

---

## Summary

The platform is alive. Frontend (Vercel) and backend (SSH-deployed server) are both running. However, there is a **critical documentation/architecture gap**: all backend API endpoints are served from `api.tradeready.io`, not `tradeready.io`. The task brief's curl commands targeted `tradeready.io/api/v1/*` — those return 404 because Vercel does not proxy API traffic to the backend. Customers or developers who discover the API at `tradeready.io` will get 404s on every backend endpoint.

---

## Results

### Tested via tradeready.io (canonical non-www → redirects to www.tradeready.io via 307)

| Check | Status | HTTP Code | Response Time | Notes |
|-------|--------|-----------|---------------|-------|
| Frontend root (tradeready.io) | PASS | 307 → 200 | 0.25s + 0.21s | Vercel non-www → www redirect, then Coming Soon page loads |
| API docs (tradeready.io/docs) | PARTIAL | 307 → 200 | 0.39s + 0.21s | Redirects to www; /docs serves Next.js docs site, NOT FastAPI Swagger |
| Health endpoint (tradeready.io/api/v1/health) | FAIL | 307 → 404 | 0.63s + 0.20s | Vercel has no proxy rule for /api/v1/*; returns Next.js 404 |
| Market pairs (tradeready.io/api/v1/market/pairs) | FAIL | 307 → 404 | — | Same — no Vercel proxy rule |
| Market prices (tradeready.io/api/v1/market/prices) | FAIL | 307 → 404 | — | Same — no Vercel proxy rule |

### Tested via api.tradeready.io (actual backend API subdomain)

| Check | Status | HTTP Code | Response Time | Notes |
|-------|--------|-----------|---------------|-------|
| Health endpoint (/health) | PASS | 200 | 0.25s | Status: "degraded", but redis_connected=true, db_connected=true, ingestion_active=true — degraded is expected (stale pairs) |
| API docs (/docs) | PASS | 200 | 0.23s | FastAPI Swagger UI served correctly |
| Backend auth check (/api/v1/health) | 401 | 401 | 0.22s | Auth required for /api/v1/* — expected behavior |
| Market pairs (/api/v1/market/pairs) | PASS | 200 | 0.48s | 448+ active pairs returned with full metadata |
| Market prices (/api/v1/market/prices) | PASS | 200 | 0.24s | 448 live prices, data_age_seconds=0.5, stale=false — price ingestion active |

### Frontend root detail

| Check | Status | HTTP Code | Response Time | Notes |
|-------|--------|-----------|---------------|-------|
| www.tradeready.io/ | PASS | 200 | 0.21s | Coming Soon page with waitlist form — correct pre-launch state |
| www.tradeready.io/docs | PASS | 200 | 0.21s | Next.js docs site (Fumadocs) — 50 MDX pages |

---

## Backend Health Detail

Response from `https://api.tradeready.io/health`:

```json
{
  "status": "degraded",
  "redis_connected": true,
  "db_connected": true,
  "ingestion_active": true,
  "total_pairs": 448,
  "checks": {
    "redis_latency_ms": 1.51,
    "db_latency_ms": 3.95
  },
  "stale_pairs": ["A2ZUSDT", "ACEUSDT", "ACHUSDT", ... (120 pairs)]
}
```

**Interpretation:** Status "degraded" is expected behavior per deploy-checker memory — this occurs when some pairs have not received a tick within the freshness window. `ingestion_active: true` + Redis/DB connected confirms the backend is healthy. Redis latency 1.51ms and DB latency 3.95ms are well within acceptable ranges. 120 of 448 pairs are stale (26.8%), meaning 328 pairs (73.2%) have fresh prices. BTCUSDT, ETHUSDT, and other major pairs are active (confirmed in /market/prices response).

**Live price sample from /api/v1/market/prices:**
- BTCUSDT: $74,392.63
- ETHUSDT: $2,358.94
- SOLUSDT: $85.02
- BNBUSDT: $622.51
- Total: 448 pairs, data_age_seconds=0.5, stale=false

---

## CI/CD Pipeline Assessment

### test.yml (6 jobs)

| Job | Trigger | Services | Notes |
|-----|---------|----------|-------|
| lint | push/PR to main | none | ruff check + ruff format --check + mypy src/ |
| test (Unit Tests) | after lint | Redis 7 + TimescaleDB pg16 | pytest tests/unit with coverage upload artifact |
| integration-tests | after lint | Redis 7 + TimescaleDB pg16 | continue-on-error: true (pre-existing failures) |
| agent-tests | after lint | Redis 7 + TimescaleDB pg16 | continue-on-error: true (pre-existing failures) |
| gym-tests | after lint | Redis 7 + TimescaleDB pg16 | continue-on-error: true (pre-existing failures) |

**Positive:** pip caching via `actions/cache@v4` on `requirements.txt` + `requirements-dev.txt` hash. Coverage artifact uploaded with 30-day retention. All test jobs provision real DB services (not mocks).

**Concern:** `integration-tests`, `agent-tests`, and `gym-tests` all have `continue-on-error: true` — these jobs will not block deployment even if they fail. This was deliberately added (commit 9e66506) to unblock the pipeline given pre-existing failures. It is a known risk: broken integration tests will not stop a deploy.

**Concern:** The `integration-tests` job runs `alembic upgrade head` against the test DB. This is correct — it validates migrations before the unit tests run.

**Concern:** The `lint` job does NOT use pip caching (no `actions/cache@v4` step), unlike the test jobs. This means lint takes longer than necessary.

### deploy.yml

The deploy pipeline:
1. Calls `test.yml` as a reusable workflow (blocks on lint + unit tests; integration/agent/gym are continue-on-error)
2. SSH deploys to server using `appleboy/ssh-action@v1`
3. On the server: `cd ~/TradeReady_BackEnd-`, sources `.env`, records rollback commit
4. Creates a DB backup (excludes heavy time-series tables: ticks, candles_backfill, portfolio_snapshots, backtest_snapshots)
5. `git fetch origin main && git checkout main && git reset --hard origin/main`
6. Builds docker images: `api`, `ingestion`, `celery`
7. Starts infra: `timescaledb`, `redis`, waits 15s
8. Records pre-migration alembic revision
9. Runs `alembic upgrade head` via `docker compose run --rm -T api`
10. Rolling restart: celery-beat → celery → api (5s gap) → ingestion
11. Waits 15s, then health checks `http://localhost:8000/health`
12. On failure: rolls back git, rebuilds, restarts, downgrades alembic

**Positive:** Rollback logic is thorough — captures commit hash, migration revision, and can revert both. DB backup before every deploy. Rolling restart order is correct (beat before worker, worker before api).

**Issue — deploy target mismatch:** The deploy pipeline pulls from `main` branch (`git fetch origin main`). The current working branch IS `main` per git status. This is correct.

**Issue — health check path:** The deploy health check uses `curl -sf http://localhost:8000/health` (without `/api/v1/` prefix). The app's health endpoint must be mounted at `/health`, not `/api/v1/health`. This needs to be verified — the `/health` endpoint is confirmed accessible at `api.tradeready.io/health` (returns 200), and `/api/v1/health` requires auth (returns 401). So the deploy health check correctly uses `/health`.

**Issue — `command_timeout: 30m`:** The 30-minute timeout should be sufficient for a full build+deploy cycle, but if Docker pulls large images from scratch it could be tight.

**Secrets used:** `secrets.SERVER_HOST`, `secrets.SERVER_USER`, `secrets.SERVER_SSH_KEY` — all referenced correctly.

---

## Docker Configuration Assessment

### Services and Configuration

| Service | Image/Build | Restart | Healthcheck | Resource Limits | Notes |
|---------|-------------|---------|-------------|-----------------|-------|
| timescaledb | timescale/timescaledb:2.25.1-pg16 (pinned) | unless-stopped | pg_isready every 10s | 2 CPU / 4G RAM | Port 5432 exposed to host |
| redis | redis:7-alpine | unless-stopped | redis-cli ping every 10s | 1 CPU / 512M | No host port — internal only (good security) |
| api | Dockerfile | unless-stopped | curl /health every 15s | 2 CPU / 2G RAM | Port 8000 exposed |
| ingestion | Dockerfile.ingestion | unless-stopped | Redis BTC price freshness < 120s | 1 CPU / 1G RAM | No external port |
| celery | Dockerfile.celery | unless-stopped | none | 1 CPU / 1G RAM | Queues: default, high_priority |
| celery-beat | Dockerfile.celery | unless-stopped | /tmp/celerybeat.pid exists | 0.5 CPU / 256M | depends on celery:service_started |
| pgadmin | dpage/pgadmin4:latest (unpinned) | unless-stopped | none | 0.5 CPU / 512M | Port 5050 — admin only |
| prometheus | prom/prometheus:v2.55.1 (pinned) | unless-stopped | wget /-/ready every 15s | 0.5 CPU / 512M | Port 9090 |
| grafana | grafana/grafana:11.4.0 (pinned) | unless-stopped | wget /api/health every 15s | 0.5 CPU / 512M | Port 3001 → 3000 |
| agent | agent/Dockerfile | no restart | — | 2 CPU / 4G RAM | profile-gated |

**Positive:** All core services have `restart: unless-stopped`. Resource limits defined for all services. Structured logging (json-file driver, 10MB max, 3 files) on all services. `timescaledb` image is pinned to `2.25.1-pg16`. Redis has AOF + RDB persistence. Redis not exposed to host (network isolation). All app services use `env_file: .env`.

**Concern — pgadmin image unpinned:** `dpage/pgadmin4:latest` could change behavior on rebuild. Low risk (admin tool only), but should be pinned.

**Concern — celery has no healthcheck:** The celery worker has no healthcheck defined. If the worker crashes silently, Docker will not restart it (restart policy only applies to container exit, not to an unhealthy but running container).

**Concern — celery-beat depends on `celery: service_started` (not `service_healthy`):** Since celery has no healthcheck, `service_started` is the only option, but it means celery-beat can start before the celery worker is fully initialized.

**Concern — pgadmin has no healthcheck:** Admin-only service so low severity.

**Positive:** App services depend on `timescaledb: service_healthy` and `redis: service_healthy` — they will not start until DB and cache are ready.

**Positive:** Ingestion healthcheck is sophisticated — it checks Redis for BTCUSDT price freshness within 120 seconds, confirming end-to-end data flow.

**Total resource estimate:** 2+1+2+1+1+0.5+0.5+0.5+0.5 = 9 CPUs, 4+0.5+2+1+1+0.25+0.5+0.5+0.5 = 10.25 GB RAM minimum (matches compose file header comment: "~8 CPU cores, ~10 GB RAM").

---

## Critical Issues

1. **Backend not accessible at tradeready.io/api/v1/*** — The Vercel-hosted frontend has no proxy/rewrite rules for `/api/v1/*`. All backend API calls from `tradeready.io` return 404. The backend is only accessible at `api.tradeready.io`. Any documentation, SDK examples, or frontend configuration that points to `https://tradeready.io/api/v1` will silently fail. Verify that `NEXT_PUBLIC_API_BASE_URL` is set to `https://api.tradeready.io/api/v1` in Vercel's environment variables.

2. **120 stale pairs (26.8% of total)** — The health endpoint reports 120 pairs as stale. While the overall ingestion is active and major pairs are fresh, stale pairs indicate the WebSocket subscription may be dropping symbols or the Binance WS is de-listing/pausing them. This is a monitoring item, not a critical blocker, but stale pair counts this high may confuse users.

---

## Warnings

1. **integration-tests, agent-tests, gym-tests are continue-on-error: true** — These test suites will not block deployment even if broken. The pre-existing failures (27 integration test failures documented in context.md) need to be resolved before this can be tightened. Risk: a regression in integration behavior could deploy undetected.

2. **`/api/v1/health` requires auth (returns 401)** — The deploy script health check uses `/health` (no auth, correct). However, if any external monitoring system is configured to check `https://api.tradeready.io/api/v1/health`, it will get 401 and report the service as down. External monitoring should use `/health`.

3. **pgadmin image unpinned (`dpage/pgadmin4:latest`)** — Unpinned images can cause non-deterministic rebuilds. Low severity for an admin tool, but should be pinned to a specific version.

4. **Celery worker has no healthcheck** — Silent worker crashes will not be detected until tasks start failing. Consider adding a healthcheck using `celery inspect ping`.

5. **lint job has no pip cache** — The lint job re-installs `requirements.txt` + `requirements-dev.txt` on every run without caching. Given the large dependency tree (~500MB+), this adds 60-90 seconds to every lint run. Minor but affects developer feedback loop.

---

## Recommendations

1. **Verify Vercel env vars** — Confirm `NEXT_PUBLIC_API_BASE_URL=https://api.tradeready.io/api/v1` and `NEXT_PUBLIC_WS_URL=wss://api.tradeready.io/ws/v1` are set in the Vercel project dashboard. The Coming Soon frontend should not be making API calls yet, but the app frontend (once launched) will need these.

2. **Investigate stale pair list** — 120 stale pairs is high. Check if these are pairs that Binance has recently delisted, or if the WebSocket subscription is missing them. Run: `docker compose logs ingestion | grep -i "stale\|drop\|disconnect"` on the production server.

3. **Add Celery healthcheck** — Consider a healthcheck like: `celery -A src.tasks.celery_app inspect ping -d celery@$HOSTNAME` with a 30s timeout.

4. **Pin pgadmin version** — Change `dpage/pgadmin4:latest` to a specific version (e.g., `dpage/pgadmin4:8.14`) to ensure reproducible builds.

5. **Add pip caching to lint job** — Add the same `actions/cache@v4` step used in the test jobs to the lint job to reduce CI runtime by ~60-90 seconds.

6. **Resolve pre-existing integration test failures** — The 27 known integration test failures (httpx AsyncClient API, outdated MCP tool counts, missing pydantic_ai) should be fixed so `continue-on-error: true` can be removed, closing the deploy gate completely.

---

## Post-Deploy Verification Checklist

- [x] `curl -sf https://api.tradeready.io/health` returns 200 (CONFIRMED: returns 200 with degraded status)
- [x] `curl -sf https://api.tradeready.io/docs` returns 200 (CONFIRMED: FastAPI Swagger UI)
- [x] `curl -sf https://api.tradeready.io/api/v1/market/pairs` returns 200 (CONFIRMED: 448 pairs)
- [x] `curl -sf https://api.tradeready.io/api/v1/market/prices` returns 200 (CONFIRMED: 448 prices, stale=false)
- [x] Price ingestion active: data_age_seconds=0.5, ingestion_active=true (CONFIRMED)
- [x] Redis connected: redis_latency_ms=1.51 (CONFIRMED)
- [x] DB connected: db_latency_ms=3.95 (CONFIRMED)
- [ ] `curl -sf https://www.tradeready.io/` returns Coming Soon page (CONFIRMED: 200)
- [ ] `curl -sf https://www.tradeready.io/docs` returns Next.js docs site (CONFIRMED: 200)
- [ ] Celery worker responding: `celery inspect ping` (NOT VERIFIED — cannot access server)
- [ ] Latest migration applied: `alembic current` matches head 023 (NOT VERIFIED — cannot access server)
- [ ] No ERROR-level logs in first 5 minutes post-deploy (NOT VERIFIED)
