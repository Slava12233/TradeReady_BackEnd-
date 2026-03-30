"""Prometheus metrics for the agent ecosystem.

This module defines a centralized registry (``AGENT_REGISTRY``) and all
Prometheus metrics used across the agent package — decisions, API calls,
memory operations, LLM usage, permission/budget tracking, strategy signals,
and health indicators.

Using a custom :class:`~prometheus_client.CollectorRegistry` keeps these
metrics isolated from the platform's default ``REGISTRY``, so the agent
package can be imported in the same process without label collisions.

Usage::

    from agent.metrics import agent_decisions_total, agent_llm_duration

    agent_decisions_total.labels(
        agent_id="agent-123",
        decision_type="trade",
        direction="long",
    ).inc()

    with agent_llm_duration.labels(
        agent_id="agent-123",
        model="anthropic/claude-sonnet",
        purpose="trade_analysis",
    ).time():
        result = await llm_call()
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Custom registry — avoids conflicts with platform's default registry
AGENT_REGISTRY = CollectorRegistry()

# ---------------------------------------------------------------------------
# Decision metrics
# ---------------------------------------------------------------------------

agent_decisions_total = Counter(
    "agent_decisions_total",
    "Total agent trade decisions",
    ["agent_id", "decision_type", "direction"],
    registry=AGENT_REGISTRY,
)

agent_trade_pnl = Histogram(
    "agent_trade_pnl_usd",
    "Trade PnL distribution in USD",
    ["agent_id", "symbol"],
    buckets=[-1000, -500, -100, -50, -10, 0, 10, 50, 100, 500, 1000],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# API call metrics
# ---------------------------------------------------------------------------

agent_api_call_duration = Histogram(
    "agent_api_call_duration_seconds",
    "Outbound API call latency",
    ["agent_id", "channel", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=AGENT_REGISTRY,
)

agent_api_errors_total = Counter(
    "agent_api_errors_total",
    "API call errors",
    ["agent_id", "channel", "endpoint", "error_type"],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# Memory metrics
# ---------------------------------------------------------------------------

agent_memory_ops_total = Counter(
    "agent_memory_operations_total",
    "Memory system operations",
    ["agent_id", "operation"],
    registry=AGENT_REGISTRY,
)

agent_memory_cache_hits = Counter(
    "agent_memory_cache_hits_total",
    "Memory Redis cache hits",
    ["agent_id"],
    registry=AGENT_REGISTRY,
)

agent_memory_cache_misses = Counter(
    "agent_memory_cache_misses_total",
    "Memory Redis cache misses",
    ["agent_id"],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------

agent_llm_tokens_total = Counter(
    "agent_llm_tokens_total",
    "LLM tokens consumed",
    ["agent_id", "model", "direction"],
    registry=AGENT_REGISTRY,
)

agent_llm_duration = Histogram(
    "agent_llm_call_duration_seconds",
    "LLM call latency",
    ["agent_id", "model", "purpose"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
    registry=AGENT_REGISTRY,
)

agent_llm_cost_usd = Counter(
    "agent_llm_cost_usd_total",
    "Estimated LLM cost in USD",
    ["agent_id", "model"],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# Permission / budget metrics
# ---------------------------------------------------------------------------

agent_permission_denials = Counter(
    "agent_permission_denials_total",
    "Permission check denials",
    ["agent_id", "capability"],
    registry=AGENT_REGISTRY,
)

agent_budget_usage = Gauge(
    "agent_budget_usage_ratio",
    "Current budget utilization (0-1)",
    ["agent_id", "limit_type"],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# Strategy metrics
# ---------------------------------------------------------------------------

agent_strategy_confidence = Histogram(
    "agent_strategy_signal_confidence",
    "Strategy signal confidence distribution",
    ["agent_id", "strategy_name"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# Retraining metrics
# ---------------------------------------------------------------------------

agent_retrain_runs_total = Counter(
    "agent_retrain_runs_total",
    "Total retraining job runs",
    ["strategy", "trigger"],
    registry=AGENT_REGISTRY,
)

agent_retrain_duration_seconds = Histogram(
    "agent_retrain_duration_seconds",
    "Retraining job wall-clock duration in seconds",
    ["strategy"],
    buckets=[60, 300, 600, 1200, 1800, 2700, 3600, 5400, 7200],
    registry=AGENT_REGISTRY,
)

agent_retrain_deployed_total = Counter(
    "agent_retrain_deployed_total",
    "Total retraining jobs where the new model was deployed (passed A/B gate)",
    ["strategy"],
    registry=AGENT_REGISTRY,
)

# ---------------------------------------------------------------------------
# Health metrics
# ---------------------------------------------------------------------------

agent_consecutive_errors = Gauge(
    "agent_consecutive_errors",
    "Current consecutive error count",
    ["agent_id"],
    registry=AGENT_REGISTRY,
)

agent_health_status = Gauge(
    "agent_health_status",
    "Agent health (1=healthy, 0.5=degraded, 0=unhealthy)",
    ["agent_id"],
    registry=AGENT_REGISTRY,
)
