---
name: docker-compose-devops
description: |
  Teaches the agent how to configure Docker Compose orchestration for the AiTradingAgent platform.
  Use when: adding services, Dockerfiles, volumes, healthchecks; configuring resource limits;
  setting up dev overrides; or working with docker-compose in this project.
---

# Docker Compose DevOps

## Services

| Service | Image/Build | Port | Purpose |
|---------|-------------|------|---------|
| api | Dockerfile | 8000 | FastAPI application |
| ingestion | Dockerfile.ingestion | — | Price feed (no external port) |
| celery | Dockerfile.celery | — | Celery worker |
| celery-beat | Dockerfile.celery | — | Celery scheduler |
| redis | redis:alpine | 6379 | Cache, pub/sub, rate limiting |
| timescaledb | timescale/timescaledb | 5432 | Time-series database |
| prometheus | prom/prometheus | 9090 | Metrics |
| grafana | grafana/grafana | 3000 | Dashboards |

## Dockerfiles

| File | Builds |
|------|--------|
| `Dockerfile` | API service |
| `Dockerfile.ingestion` | Ingestion service |
| `Dockerfile.celery` | Celery worker and beat |

## Resource Limits

| Service | CPU | Memory |
|---------|-----|--------|
| api | 2 | 2GB |
| ingestion | 1 | 1GB |
| celery | 1 | 1GB |
| redis | 1 | 512MB |
| timescaledb | 2 | 4GB |
| prometheus | 0.5 | 512MB |
| grafana | 0.5 | 512MB |

- Total: ~8 CPU, ~10GB RAM.
- Use `deploy.resources.limits` in compose.

## Volumes

| Volume | Mounted By | Purpose |
|--------|------------|---------|
| timescaledb_data | timescaledb | Persistent DB |
| redis_data | redis | Persistent cache |
| grafana_data | grafana | Dashboards, config |

## Network

- Single internal network for all services.
- No external network required for inter-service communication.

## Environment (.env.example)

| Variable | Purpose |
|----------|---------|
| POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB | TimescaleDB credentials |
| DATABASE_URL | Async connection string for API/celery |
| REDIS_URL | Redis connection string |
| BINANCE_WS_URL | Binance WebSocket endpoint |
| API_HOST, API_PORT | API bind address |
| JWT_SECRET | JWT signing key |
| DEFAULT_STARTING_BALANCE | Sim account initial balance |
| TRADING_FEE_PCT | Fee percentage |
| DEFAULT_SLIPPAGE_FACTOR | Slippage for market orders |
| GRAFANA_ADMIN_PASSWORD | Grafana admin password |

## Healthchecks

- Define healthchecks for all services.
- API: `GET /health`
- Redis: `redis-cli ping`
- TimescaleDB: `pg_isready`
- Prometheus/Grafana: HTTP readiness probes where applicable.

## Restart Policy

- Use `restart: unless-stopped` for all services.

## Logging

- Driver: `json-file`
- Max size: 10MB per file
- Max files: 3

## Development Overrides

- `docker-compose.dev.yml` for development.
- Override: volume mounts for hot-reload, debug ports, relaxed limits.
- Run: `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up`

## Conventions

- Use `depends_on` with `condition: service_healthy` where services depend on DB/Redis.
- Do not hardcode secrets; use env vars or secrets.
- Keep base compose minimal; use override files for env-specific config.
