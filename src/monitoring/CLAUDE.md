# Monitoring

<!-- last-updated: 2026-03-19 -->

> Health checks and Prometheus metrics exposure for platform infrastructure observability.

## What This Module Does

Provides a `GET /health` endpoint that probes Redis, TimescaleDB, and the price ingestion pipeline concurrently, returning a structured JSON report with connection status, latency measurements, and stale-pair detection. Prometheus metrics are exposed at `/metrics` via `prometheus_client.make_asgi_app()` mounted in `src/main.py`.

The health endpoint drives Docker/Kubernetes liveness and readiness checks, Grafana dashboards, and external uptime monitors.

## Key Files

| File | Purpose |
|------|---------|
| `health.py` | `GET /health` route with three async probe helpers (Redis, DB, ingestion) |
| `__init__.py` | Empty package marker |
| `src/main.py` (lines 276-278) | Mounts Prometheus ASGI app at `/metrics` via `prometheus_client.make_asgi_app()` |

## Architecture & Patterns

### Health Check Status Logic

The endpoint runs three probes in parallel via `asyncio.gather`:

| Probe | What It Does | Failure Impact |
|-------|-------------|----------------|
| `_probe_redis()` | `PING` Redis, measures round-trip latency | `unhealthy` (503) |
| `_probe_db()` | `SELECT 1` via SQLAlchemy async engine | `unhealthy` (503) |
| `_probe_ingestion()` | Reads `PriceCache.get_all_prices()` and `get_stale_pairs(threshold_seconds=60)` | `degraded` (200) |

Status resolution:
- **`ok` (200)** -- Redis up, DB up, zero stale pairs
- **`degraded` (200)** -- Redis up, DB up, but some pairs have not received a tick in 60+ seconds
- **`unhealthy` (503)** -- Redis or DB is unreachable

### Prometheus Metrics

Prometheus metrics use the default `prometheus_client` process/platform collectors plus any custom metrics registered elsewhere in the codebase. The ASGI app is mounted at `/metrics` with no authentication or rate limiting (both middleware skip that path).

### Lazy Imports

All probe helpers use lazy imports (`# noqa: PLC0415`) inside the function body to avoid circular import issues at module load time. This is a project-wide pattern; do not move these to the top of the file.

## Public API / Interfaces

### `GET /health`

No authentication required. Skipped by `AuthMiddleware`, `RateLimitMiddleware`, and `LoggingMiddleware`.

**Response (200 or 503):**

```json
{
  "status": "ok | degraded | unhealthy",
  "redis_connected": true,
  "db_connected": true,
  "ingestion_active": true,
  "stale_pairs": ["XYZUSDT"],
  "total_pairs": 612,
  "checks": {
    "redis_latency_ms": 0.4,
    "db_latency_ms": 1.2
  }
}
```

### `GET /metrics`

Standard Prometheus text exposition format. No authentication required. Mounted in `src/main.py`, not in this module.

### Router

`health.py` exports `router` (an `APIRouter` with tag `"health"`), imported and included in `src/main.py` as `health_router`.

## Dependencies

| Dependency | Usage |
|------------|-------|
| `src.cache.redis_client.get_redis_client` | Redis PING probe |
| `src.cache.price_cache.PriceCache` | Ingestion staleness check |
| `src.database.session.get_engine` | DB `SELECT 1` probe |
| `prometheus_client` | ASGI metrics app (used in `src/main.py`) |

## Common Tasks

**Add a new health probe:** Write an `async def _probe_<name>()` function returning a tuple, add it to the `asyncio.gather` call in `health_check()`, and include the result in the response body. Update status resolution logic if the new probe should affect the overall status.

**Add custom Prometheus metrics:** Register counters/histograms/gauges anywhere in the codebase using `prometheus_client`. They will automatically appear at `/metrics` since `make_asgi_app()` serves all registered collectors.

## Gotchas & Pitfalls

- **Lazy imports are intentional.** Do not refactor probe helpers to use top-level imports; this will cause circular import errors at startup.
- **Staleness threshold is hardcoded to 60 seconds** in `_probe_ingestion()`. Changing it affects what counts as "degraded."
- **Latency returns -1.0 on failure.** Consumers should treat negative latency as "probe failed," not as actual timing data.
- **No auth on `/health` or `/metrics`.** These paths are explicitly excluded in `AuthMiddleware`, `RateLimitMiddleware`, and `LoggingMiddleware`. If you add sensitive data to the health response, reconsider this.
- **Prometheus app is mounted, not routed.** It lives at `/metrics` as a separate ASGI sub-application, not as a FastAPI route, so it will not appear in the OpenAPI/Swagger docs.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
