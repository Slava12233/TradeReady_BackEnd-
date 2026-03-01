---
name: prometheus-grafana-monitoring
description: |
  Teaches the agent how to implement and extend Prometheus + Grafana monitoring for the AiTradingAgent crypto trading platform.
  Use when: adding custom metrics, dashboards, alerting rules; configuring health checks; or working with src/monitoring/ in this project.
---

# Prometheus + Grafana Monitoring

## Stack

- Prometheus for metrics scraping
- Grafana for dashboards and visualization
- `prometheus_client` (Python) for instrumentation
- Metrics endpoint at `/metrics`, health at `/health`

## Project Layout

| Purpose | Path |
|---------|------|
| Prometheus metrics | `src/monitoring/prometheus_metrics.py` |
| Health checks | `src/monitoring/health.py` |
| Grafana dashboards | `grafana/dashboards/` (JSON) |
| Alert rules | `prometheus/alerts.yml` or equivalent |

## Custom Metrics

### Price Ingestion

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `price_ticks_received_total` | Counter | `symbol` | Total ticks received per pair |
| `price_ticks_per_second` | Gauge | — | Current tick rate |
| `tick_buffer_size` | Gauge | — | Pending ticks in buffer |
| `tick_flush_duration_seconds` | Histogram | — | Flush latency |
| `tick_flush_failures_total` | Counter | — | Failed flushes |
| `stale_pairs_count` | Gauge | — | Pairs with stale data |

### API

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `api_requests_total` | Counter | `method`, `endpoint`, `status` | Request counts |
| `api_request_duration_seconds` | Histogram | `endpoint` | Request latency |
| `websocket_connections_active` | Gauge | — | Active WS connections |

### Trading

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `orders_placed_total` | Counter | `type`, `side`, `status` | Order placement |
| `order_execution_duration_seconds` | Histogram | — | Execution latency |
| `trades_executed_total` | Counter | `symbol`, `side` | Trade counts |
| `trade_volume_usd_total` | Counter | `symbol` | Volume in USD |

### Accounts

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `active_agents_count` | Gauge | — | Active trading agents |
| `circuit_breakers_tripped_total` | Counter | — | Circuit breaker trips |

### Infrastructure

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `redis_memory_bytes` | Gauge | — | Redis memory usage |
| `redis_hit_rate` | Gauge | — | Cache hit ratio |
| `db_connection_pool_size` | Gauge | — | Pool size |
| `db_query_duration_seconds` | Histogram | `query_type` | DB query latency |

## Metrics Endpoint

- Expose at `/metrics` (Prometheus text format).
- Use `prometheus_client.generate_latest()` for response.
- Do not require auth for `/metrics` (Prometheus scrapes unauthenticated).
- Ensure no PII or secrets in metric labels.

## Grafana Dashboards

### System Overview

- API request rate, latency percentiles (p50, p95, p99)
- Redis memory, hit rate
- DB pool size, query duration
- Error rate by endpoint

### Agent Activity

- Active agents count
- Orders placed by type/side/status
- Trades executed, volume
- Circuit breaker trips

### Price Feed Health

- Ticks per second
- Buffer size
- Flush duration, failures
- Stale pairs count

## Alerting Rules

| Alert | Condition | Severity |
|-------|-----------|----------|
| StalePairs | `stale_pairs_count > 0` for 5m | warning |
| HighErrorRate | `rate(api_requests_total{status=~"5.."}[5m])` > threshold | critical |
| CircuitBreakerTripped | `increase(circuit_breakers_tripped_total[1h]) > 0` | warning |
| TickFlushFailures | `increase(tick_flush_failures_total[5m]) > 0` | warning |

## Health Check Endpoint

- Path: `/health`
- Return JSON with overall status and sub-checks.

Structure:

```json
{
  "status": "healthy",
  "checks": {
    "redis": "ok",
    "timescaledb": "ok",
    "price_feed_freshness": "ok"
  }
}
```

### Sub-checks

| Check | Logic |
|-------|-------|
| Redis | `PING`; fail if no response |
| TimescaleDB | Simple `SELECT 1`; fail if connection error |
| Price feed freshness | Compare latest tick timestamp to now; fail if > threshold (e.g. 60s) |

- Return 503 if any sub-check fails.
- Use `status: "degraded"` if non-critical check fails (optional).

## Instrumentation Conventions

- Use `prometheus_client.Counter`, `Gauge`, `Histogram` from `prometheus_client`.
- Use `@prometheus_client.histogram` or manual `observe()` for timing.
- Increment counters after success/failure; use labels for dimensions.
- Use `with` or context managers for histograms; avoid blocking in metric paths.

## Conventions

- Keep metric names in `snake_case`; suffix counters with `_total`, durations with `_seconds`.
- Use consistent label names across related metrics.
- Avoid high-cardinality labels (e.g. account IDs) unless needed for debugging.
- Scrape interval: 15s default; adjust in Prometheus config if needed.

## References

- For complete metrics definitions with code examples, see [references/metrics-registry.md](references/metrics-registry.md)
