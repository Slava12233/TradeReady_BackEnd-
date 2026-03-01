# Metrics Registry

Complete metrics definitions with implementation examples for the AiTradingAgent platform.

## Price Ingestion Metrics

```python
from prometheus_client import Counter, Gauge, Histogram

price_ticks_received_total = Counter(
    'price_ticks_received_total',
    'Total ticks received from Binance',
    ['symbol']
)

price_ticks_per_second = Gauge(
    'price_ticks_per_second',
    'Current tick ingestion rate'
)

tick_buffer_size = Gauge(
    'tick_buffer_size',
    'Number of ticks pending flush to TimescaleDB'
)

tick_flush_duration_seconds = Histogram(
    'tick_flush_duration_seconds',
    'Time to flush tick buffer to DB',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

tick_flush_failures_total = Counter(
    'tick_flush_failures_total',
    'Number of failed tick buffer flushes'
)

stale_pairs_count = Gauge(
    'stale_pairs_count',
    'Number of trading pairs with no tick in 60s'
)
```

## API Metrics

```python
api_requests_total = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

api_request_duration_seconds = Histogram(
    'api_request_duration_seconds',
    'API request latency',
    ['method', 'endpoint'],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

websocket_connections_active = Gauge(
    'websocket_connections_active',
    'Number of active WebSocket connections'
)
```

## Trading Metrics

```python
orders_placed_total = Counter(
    'orders_placed_total',
    'Total orders placed',
    ['type', 'side', 'status']
)

order_execution_duration_seconds = Histogram(
    'order_execution_duration_seconds',
    'Order execution latency',
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

trades_executed_total = Counter(
    'trades_executed_total',
    'Total trades executed',
    ['symbol', 'side']
)

trade_volume_usd_total = Counter(
    'trade_volume_usd_total',
    'Total trade volume in USD',
    ['symbol']
)
```

## Account Metrics

```python
active_agents_count = Gauge(
    'active_agents_count',
    'Number of active trading agents'
)

circuit_breakers_tripped_total = Counter(
    'circuit_breakers_tripped_total',
    'Number of circuit breaker trips'
)
```

## Infrastructure Metrics

```python
redis_memory_bytes = Gauge('redis_memory_bytes', 'Redis used memory')
redis_hit_rate = Gauge('redis_hit_rate', 'Redis cache hit ratio')
db_connection_pool_size = Gauge('db_connection_pool_size', 'DB connection pool size')
db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)
```

## Usage Patterns

### Middleware instrumentation

```python
@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    api_requests_total.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    api_request_duration_seconds.labels(
        method=request.method,
        endpoint=request.url.path
    ).observe(duration)
    return response
```

### Timer context

```python
with tick_flush_duration_seconds.time():
    await flush_ticks_to_db(buffer)
```

## Alerting Rules (Prometheus)

```yaml
groups:
  - name: agentexchange
    rules:
      - alert: StalePairs
        expr: stale_pairs_count > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "{{ $value }} trading pairs have stale data"

      - alert: HighAPIErrorRate
        expr: rate(api_requests_total{status=~"5.."}[5m]) / rate(api_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: critical

      - alert: CircuitBreakerTripped
        expr: increase(circuit_breakers_tripped_total[1h]) > 0
        labels:
          severity: warning

      - alert: TickFlushFailures
        expr: increase(tick_flush_failures_total[5m]) > 0
        labels:
          severity: warning

      - alert: HighOrderLatency
        expr: histogram_quantile(0.95, rate(order_execution_duration_seconds_bucket[5m])) > 0.5
        for: 5m
        labels:
          severity: warning
```
