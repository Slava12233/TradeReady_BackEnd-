"""Platform-wide Prometheus application metrics.

All metrics use the DEFAULT registry so they are automatically served by the
``/metrics`` ASGI app mounted in ``src/main.py`` via
``prometheus_client.make_asgi_app()``.

Import the metric objects directly from this module wherever instrumentation
is needed::

    from src.monitoring.metrics import platform_orders_total
    platform_orders_total.labels(agent_id=str(agent_id), side="buy", order_type="market").inc()
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Order metrics
# ---------------------------------------------------------------------------

platform_orders_total: Counter = Counter(
    "platform_orders_total",
    "Orders placed on the platform",
    ["agent_id", "side", "order_type"],
)
"""Counter incremented once per order placement.

Labels:
    agent_id:   String UUID of the agent that placed the order, or ``"none"``
                when the order has no associated agent.
    side:       ``"buy"`` or ``"sell"``.
    order_type: ``"market"``, ``"limit"``, ``"stop_loss"``, or ``"take_profit"``.
"""

platform_order_latency: Histogram = Histogram(
    "platform_order_latency_seconds",
    "Order processing time from receipt to commit",
    ["order_type"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
"""Histogram of end-to-end order processing latency in seconds.

Labels:
    order_type: ``"market"``, ``"limit"``, ``"stop_loss"``, or ``"take_profit"``.
"""

# ---------------------------------------------------------------------------
# API error metrics
# ---------------------------------------------------------------------------

platform_api_errors: Counter = Counter(
    "platform_api_errors_total",
    "API errors by endpoint and HTTP status code",
    ["endpoint", "status_code"],
)
"""Counter incremented for every 4xx or 5xx response.

Labels:
    endpoint:    URL path (e.g. ``"/api/v1/trade/order"``).
    status_code: HTTP status code as a string (e.g. ``"400"``, ``"500"``).
"""

# ---------------------------------------------------------------------------
# Price ingestion metrics
# ---------------------------------------------------------------------------

platform_price_ingestion_lag: Gauge = Gauge(
    "platform_price_ingestion_lag_seconds",
    "Staleness of the most recently ingested price tick in seconds",
)
"""Gauge tracking how old the latest ingested price tick is.

Set to ``(now - tick.timestamp).total_seconds()`` after each price update.
A value above 60 indicates that the ingestion pipeline may be stalled or
disconnected from the exchange.
"""
