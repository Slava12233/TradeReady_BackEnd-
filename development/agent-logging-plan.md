---
type: plan
title: "Agent Logging Implementation Plan"
status: active
phase: agent-logging
tags:
  - plan
  - agent-logging
---

# Agent Logging Implementation Plan

> **Companion to:** `development/agent-logging-research.md`
> **Date:** 2026-03-21
> **Status:** Draft — awaiting CTO approval

---

## Overview

5-phase implementation plan to build ecosystem-level logging for the agent-platform system. Each phase is self-contained, delivers immediate value, and builds on the previous phase.

```
Phase 1: Foundation ──► Phase 2: Agent-Side ──► Phase 3: Cross-System ──► Phase 4: Metrics ──► Phase 5: Intelligence
   (1 sprint)              (1 sprint)              (0.5 sprint)             (0.5 sprint)         (1 sprint)
```

---

## Phase 1: Logging Foundation & Standardization

**Goal:** Unified structured logging across the entire codebase. Every log line is JSON, machine-parseable, and consistently formatted.

### Task 1.1: Create Agent Logging Module

**New file:** `agent/logging.py`

```python
"""Centralized logging configuration and utilities for the agent ecosystem."""

import structlog
from contextvars import ContextVar
from uuid import uuid4

# Context variables for correlation
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_span_id: ContextVar[str] = ContextVar("span_id", default="")
_agent_id: ContextVar[str] = ContextVar("agent_id", default="")


def get_trace_id() -> str:
    return _trace_id.get()

def set_trace_id(trace_id: str | None = None) -> str:
    tid = trace_id or uuid4().hex[:16]
    _trace_id.set(tid)
    return tid

def new_span_id() -> str:
    sid = uuid4().hex[:12]
    _span_id.set(sid)
    return sid

def set_agent_id(agent_id: str) -> None:
    _agent_id.set(agent_id)


def add_correlation_context(logger, method_name, event_dict):
    """Structlog processor that injects trace/span/agent IDs."""
    trace = _trace_id.get()
    if trace:
        event_dict["trace_id"] = trace
    span = _span_id.get()
    if span:
        event_dict["span_id"] = span
    agent = _agent_id.get()
    if agent:
        event_dict["agent_id"] = agent
    return event_dict


def configure_agent_logging(log_level: str = "INFO") -> None:
    """Configure structlog for the agent process.

    Call once at process startup (main.py, server.py, strategy CLIs).
    Do NOT call from modules that run inside the FastAPI process.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_correlation_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

**Why centralized:** Currently `main.py`, `server.py`, and 3 strategy CLIs each have their own `structlog.configure()` calls. One module, one config.

### Task 1.2: Migrate `agent/main.py` Structlog Config

**File:** `agent/main.py` (lines 63-77)

Replace the inline `structlog.configure(...)` with:
```python
from agent.logging import configure_agent_logging
configure_agent_logging(log_level)
```

### Task 1.3: Migrate `agent/server.py` Structlog Config

**File:** `agent/server.py`

Same migration as Task 1.2. The `AgentServer.__init__()` should call `set_agent_id(agent_id)` to bind the agent context for all subsequent log lines.

### Task 1.4: Migrate Strategy CLI Configs

**Files:**
- `agent/strategies/rl/config.py` (or wherever `main()` calls `structlog.configure`)
- `agent/strategies/evolutionary/config.py`
- `agent/strategies/ensemble/config.py`

Replace each with `configure_agent_logging()`.

### Task 1.5: Standardize Event Names

**Convention:** `"{component}.{operation}[.{outcome}]"`

| Component prefix | Scope |
|-----------------|-------|
| `agent.server` | AgentServer lifecycle |
| `agent.session` | Conversation session management |
| `agent.decision` | Trade decision pipeline |
| `agent.trade` | Trade execution |
| `agent.memory` | Memory CRUD operations |
| `agent.permission` | Permission checks |
| `agent.budget` | Budget enforcement |
| `agent.strategy` | Strategy pipeline |
| `agent.api` | Outbound API calls |
| `agent.llm` | LLM interactions |
| `agent.workflow` | Workflow step execution |
| `agent.task` | Celery task execution |

**Action:** Audit all 54 files with structlog and normalize event names. This is a search-and-replace task — the existing events are already mostly dot-notation but inconsistent in prefix.

### Task 1.6: Fix Celery Task Logging

**File:** `agent/tasks.py`

Replace `logging.getLogger(__name__)` with `structlog.get_logger(__name__)`. Add `configure_agent_logging()` call at module level (Celery workers are separate processes).

### Task 1.7: Eliminate Remaining `print()` Statements

**30 files** have `print()` calls. Three categories:

| Category | Action |
|----------|--------|
| Config load failures (before structlog configured) | Keep as `sys.stderr` writes — these are pre-logger |
| CLI progress output | Replace with `structlog.get_logger().info(...)` |
| Rich terminal UI fallback | Keep — user-facing display, not logging |

### Deliverables

- [ ] `agent/logging.py` — centralized config + correlation context
- [ ] All `structlog.configure()` calls consolidated
- [ ] All event names follow `component.operation.outcome` convention
- [ ] Celery tasks use structlog
- [ ] Unnecessary `print()` replaced with structured logging

### Files Changed

| File | Change |
|------|--------|
| `agent/logging.py` | **NEW** — centralized logging config |
| `agent/main.py` | Use `configure_agent_logging()` |
| `agent/server.py` | Use `configure_agent_logging()`, bind `agent_id` |
| `agent/tasks.py` | Migrate to structlog |
| `agent/strategies/rl/config.py` | Use `configure_agent_logging()` |
| `agent/strategies/evolutionary/config.py` | Use `configure_agent_logging()` |
| `agent/strategies/ensemble/config.py` | Use `configure_agent_logging()` |
| ~20 files | Normalize event name strings |

---

## Phase 2: Agent-Side API Call & LLM Logging

**Goal:** Every outbound call the agent makes (API, LLM, DB) is logged with timing, status, and correlation.

### Task 2.1: Create API Call Logger Middleware

**New file:** `agent/logging_middleware.py`

A decorator/context manager that wraps every outbound API call:

```python
"""Middleware for logging all outbound API calls from the agent."""

import time
from contextlib import asynccontextmanager
from decimal import Decimal
import structlog

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def log_api_call(
    channel: str,      # "sdk", "mcp", "rest", "db"
    endpoint: str,     # "/api/v1/trade/order" or tool name
    method: str = "",  # "GET", "POST", or "" for non-HTTP
    **extra_context,
):
    """Context manager that logs API call start, duration, and outcome.

    Usage:
        async with log_api_call("sdk", "/api/v1/prices", method="GET") as ctx:
            result = await client.get_price("BTCUSDT")
            ctx["response_status"] = 200
            ctx["response_size"] = len(str(result))
    """
    from agent.logging import new_span_id
    span_id = new_span_id()
    ctx = {"response_status": None, "error": None, **extra_context}
    start = time.monotonic()

    try:
        yield ctx
    except Exception as exc:
        ctx["error"] = f"{type(exc).__name__}: {exc}"
        ctx["response_status"] = getattr(exc, "status_code", 0)
        logger.error(
            "agent.api.failed",
            channel=channel,
            endpoint=endpoint,
            method=method,
            span_id=span_id,
            latency_ms=round((time.monotonic() - start) * 1000, 2),
            **{k: v for k, v in ctx.items() if v is not None},
        )
        raise
    else:
        latency = round((time.monotonic() - start) * 1000, 2)
        logger.info(
            "agent.api.completed",
            channel=channel,
            endpoint=endpoint,
            method=method,
            span_id=span_id,
            latency_ms=latency,
            status=ctx.get("response_status"),
        )
```

### Task 2.2: Instrument SDK Tools

**File:** `agent/tools/sdk_tools.py`

Wrap each of the 7 tool functions with `log_api_call("sdk", ...)`. Example:

```python
async def get_price(symbol: str) -> dict:
    async with log_api_call("sdk", "get_price", symbol=symbol):
        return await client.get_price(symbol)
```

### Task 2.3: Instrument REST Tools

**File:** `agent/tools/rest_tools.py`

Wrap each of the 11 `PlatformRESTClient` methods with `log_api_call("rest", ...)`.

### Task 2.4: Instrument Agent Tools (Direct DB)

**File:** `agent/tools/agent_tools.py`

Wrap each of the 5 tools with `log_api_call("db", ...)`.

### Task 2.5: LLM Call Logging

**Files:**
- `agent/conversation/session.py` (session summarization)
- `agent/conversation/context.py` (context assembly — indirect LLM via ContextBuilder)
- `agent/trading/journal.py` (reflection LLM calls)
- `agent/workflows/trading_workflow.py` (analysis LLM calls)
- `agent/workflows/backtest_workflow.py` (analysis LLM calls)
- `agent/workflows/strategy_workflow.py` (review LLM calls)

Add structured logging for every LLM call:

```python
logger.info(
    "agent.llm.completed",
    model=model_name,
    purpose="trade_reflection",    # or "analysis", "summarization", "review"
    input_tokens=response.usage.input_tokens,
    output_tokens=response.usage.output_tokens,
    latency_ms=latency,
    cost_estimate_usd=estimated_cost,
)
```

### Task 2.6: Memory Operation Logging

**Files:**
- `agent/memory/postgres_store.py`
- `agent/memory/redis_cache.py`
- `agent/memory/retrieval.py`

Add structured logging:

```python
# On save
logger.info("agent.memory.saved", memory_type=memory.memory_type, source=memory.source)

# On retrieval
logger.info("agent.memory.retrieved", query=query[:50], results=len(results),
            cache_hits=cache_count, db_hits=db_count, top_score=top_score)

# On cache hit/miss
logger.debug("agent.memory.cache_hit", memory_id=memory_id)
logger.debug("agent.memory.cache_miss", memory_id=memory_id)

# On reinforce
logger.info("agent.memory.reinforced", memory_id=memory_id, times=new_count)
```

### Deliverables

- [ ] `agent/logging_middleware.py` — API call logging context manager
- [ ] All 7 SDK tools instrumented
- [ ] All 11 REST methods instrumented
- [ ] All 5 agent tools instrumented
- [ ] All LLM calls logged with token counts and cost estimates
- [ ] Memory system fully instrumented (save, retrieve, cache, reinforce)

### Files Changed

| File | Change |
|------|--------|
| `agent/logging_middleware.py` | **NEW** — API call logging |
| `agent/tools/sdk_tools.py` | Wrap 7 tools |
| `agent/tools/rest_tools.py` | Wrap 11 methods |
| `agent/tools/agent_tools.py` | Wrap 5 tools |
| `agent/conversation/session.py` | LLM call logging |
| `agent/trading/journal.py` | LLM call logging |
| `agent/workflows/trading_workflow.py` | LLM call logging |
| `agent/workflows/backtest_workflow.py` | LLM call logging |
| `agent/workflows/strategy_workflow.py` | LLM call logging |
| `agent/memory/postgres_store.py` | Memory CRUD logging |
| `agent/memory/redis_cache.py` | Cache hit/miss logging |
| `agent/memory/retrieval.py` | Retrieval scoring logging |

---

## Phase 3: Cross-System Correlation & Database Tables

**Goal:** Trace a single agent decision from signal generation through API call through order execution through PnL outcome.

### Task 3.1: Add Trace ID Propagation to SDK Client

**File:** `sdk/agentexchange/async_client.py`

Add `X-Trace-Id` header to every HTTP request:

```python
headers = {
    "X-API-Key": self.api_key,
    "X-Trace-Id": trace_id or "",
}
```

The `trace_id` should be passed via a new optional parameter on the client, or read from `contextvars`.

### Task 3.2: Add Trace ID Propagation to REST Client

**File:** `agent/tools/rest_tools.py`

Same pattern — inject `X-Trace-Id` header into `PlatformRESTClient` requests.

### Task 3.3: Platform-Side Trace ID Extraction

**File:** `src/api/middleware/logging.py`

Modify `LoggingMiddleware` to read `X-Trace-Id` from incoming requests and include it in log output:

```python
trace_id = request.headers.get("X-Trace-Id", "")
if trace_id:
    event_dict["trace_id"] = trace_id
```

### Task 3.4: Create `agent_api_calls` Table

**New migration via Alembic:**

```sql
CREATE TABLE agent_api_calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        VARCHAR(32) NOT NULL,
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    channel         VARCHAR(10) NOT NULL,  -- 'sdk', 'mcp', 'rest', 'db'
    endpoint        VARCHAR(200) NOT NULL,
    method          VARCHAR(10),           -- 'GET', 'POST', etc.
    status_code     SMALLINT,
    latency_ms      NUMERIC(10,2),
    request_size    INTEGER,
    response_size   INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_agent_api_calls_agent_trace ON agent_api_calls(agent_id, trace_id);
CREATE INDEX ix_agent_api_calls_created ON agent_api_calls(created_at DESC);
```

**Note:** This is NOT a TimescaleDB hypertable. It's a regular table with time-based indexes. Hypertables require the time column in the PK, which would complicate UUID-based lookups.

### Task 3.5: Create `agent_strategy_signals` Table

**New migration:**

```sql
CREATE TABLE agent_strategy_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id        VARCHAR(32) NOT NULL,
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    strategy_name   VARCHAR(50) NOT NULL,  -- 'rl_ppo', 'evolutionary', 'regime', 'risk', 'ensemble'
    symbol          VARCHAR(20) NOT NULL,
    action          VARCHAR(10) NOT NULL,  -- 'buy', 'sell', 'hold'
    confidence      NUMERIC(5,4),
    weight          NUMERIC(5,4),          -- weight in ensemble
    signal_data     JSONB,                 -- strategy-specific details
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_agent_signals_trace ON agent_strategy_signals(trace_id);
CREATE INDEX ix_agent_signals_agent_created ON agent_strategy_signals(agent_id, created_at DESC);
```

### Task 3.6: Activate the Dead `AuditLog` Table

**File:** `src/api/middleware/logging.py` or new `src/api/middleware/audit.py`

Add an async audit log writer for key platform operations. Write asynchronously (fire-and-forget via `asyncio.create_task`) to avoid adding latency:

```python
AUDITABLE_ACTIONS = {
    ("POST", "/api/v1/trade/order"): "place_order",
    ("POST", "/api/v1/auth/register"): "register",
    ("POST", "/api/v1/auth/login"): "login",
    ("DELETE", "/api/v1/agents/"): "delete_agent",
    ("POST", "/api/v1/backtest/create"): "create_backtest",
}
```

### Task 3.7: Link `agent_decisions.trace_id`

**Migration:** Add `trace_id VARCHAR(32)` column to `agent_decisions` table.

**Code change:** `agent/trading/loop.py` — set `trace_id` on each `AgentDecision` record during the decision phase.

### Task 3.8: Create Repositories for New Tables

**New files:**
- `src/database/repositories/agent_api_call_repo.py`
- `src/database/repositories/agent_strategy_signal_repo.py`

**Update:** `src/dependencies.py` — add dependency injection aliases.

### Task 3.9: Batch Writer for API Call Logs

To avoid per-call DB writes (which would double API latency), create a batched async writer:

**New file:** `agent/logging_writer.py`

```python
"""Async batch writer for persisting log events to database tables."""

import asyncio
from collections import deque

class LogBatchWriter:
    """Buffers log events and flushes to DB in batches.

    Flush triggers:
    - Buffer reaches max_batch_size (default: 50)
    - Flush interval elapsed (default: 10 seconds)
    - Manual flush() call (e.g., on shutdown)
    """

    def __init__(self, session_factory, max_batch_size=50, flush_interval=10.0):
        self._buffer: deque = deque()
        self._session_factory = session_factory
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval
        self._flush_task: asyncio.Task | None = None

    async def start(self):
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def add(self, record):
        self._buffer.append(record)
        if len(self._buffer) >= self._max_batch_size:
            await self.flush()

    async def flush(self):
        if not self._buffer:
            return
        batch = []
        while self._buffer and len(batch) < self._max_batch_size:
            batch.append(self._buffer.popleft())
        # Bulk insert via session.add_all()
        ...

    async def stop(self):
        if self._flush_task:
            self._flush_task.cancel()
        await self.flush()  # Final drain
```

### Deliverables

- [ ] `X-Trace-Id` header propagated from agent to platform
- [ ] Platform middleware reads and logs `trace_id`
- [ ] `agent_api_calls` table + repository
- [ ] `agent_strategy_signals` table + repository
- [ ] `AuditLog` activated for key platform operations
- [ ] `agent_decisions.trace_id` column added
- [ ] `LogBatchWriter` for async DB persistence

### Files Changed

| File | Change |
|------|--------|
| `sdk/agentexchange/async_client.py` | Add `X-Trace-Id` header |
| `agent/tools/rest_tools.py` | Add `X-Trace-Id` header |
| `src/api/middleware/logging.py` | Read `X-Trace-Id` from request |
| `src/database/models.py` | New `AgentApiCall`, `AgentStrategySignal` models; `trace_id` on `AgentDecision` |
| `src/database/repositories/agent_api_call_repo.py` | **NEW** |
| `src/database/repositories/agent_strategy_signal_repo.py` | **NEW** |
| `src/api/middleware/audit.py` | **NEW** — async audit log writer |
| `src/dependencies.py` | New dependency aliases |
| `agent/logging_writer.py` | **NEW** — batch writer |
| `agent/trading/loop.py` | Set `trace_id` on decisions |
| `agent/strategies/ensemble/run.py` | Log per-strategy signals to `agent_strategy_signals` |
| Alembic migration | New tables + column |

---

## Phase 4: Prometheus Metrics & Dashboards

**Goal:** Real-time monitoring with alerting capability for both agent and platform.

### Task 4.1: Create Metrics Registry Module

**New file:** `agent/metrics.py`

```python
"""Prometheus metrics for the agent ecosystem."""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

# Use a custom registry to avoid conflicts with the platform's default registry
AGENT_REGISTRY = CollectorRegistry()

# Decision metrics
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

# API call metrics
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

# Memory metrics
agent_memory_ops_total = Counter(
    "agent_memory_operations_total",
    "Memory system operations",
    ["agent_id", "operation"],  # save, retrieve, reinforce, forget
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

# LLM metrics
agent_llm_tokens_total = Counter(
    "agent_llm_tokens_total",
    "LLM tokens consumed",
    ["agent_id", "model", "direction"],  # input, output
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

# Permission/budget metrics
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

# Strategy metrics
agent_strategy_confidence = Histogram(
    "agent_strategy_signal_confidence",
    "Strategy signal confidence distribution",
    ["agent_id", "strategy_name"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
    registry=AGENT_REGISTRY,
)

# Health metrics
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
```

### Task 4.2: Expose Agent Metrics Endpoint

**File:** `agent/server.py`

Add a `/metrics` HTTP endpoint to `AgentServer` (it already binds to port 8001):

```python
from prometheus_client import generate_latest
from agent.metrics import AGENT_REGISTRY

async def metrics_handler(request):
    return web.Response(
        body=generate_latest(AGENT_REGISTRY),
        content_type="text/plain; version=0.0.4",
    )
```

### Task 4.3: Instrument Code with Metrics Calls

Add `metrics.observe()` / `metrics.inc()` calls alongside existing log calls from Phase 2. The logging middleware (`log_api_call`) should also emit Prometheus metrics:

```python
# Inside log_api_call context manager
agent_api_call_duration.labels(
    agent_id=get_agent_id(),
    channel=channel,
    endpoint=endpoint,
).observe(latency_seconds)
```

### Task 4.4: Platform-Side Metrics Registration

**File:** `src/main.py`

Register application-level Prometheus metrics for the platform:

```python
from prometheus_client import Counter, Histogram

platform_orders_total = Counter("platform_orders_total", "Orders placed", ["agent_id", "side", "type"])
platform_order_latency = Histogram("platform_order_latency_seconds", "Order processing time", ["type"])
platform_api_errors = Counter("platform_api_errors_total", "API errors", ["endpoint", "status_code"])
platform_price_ingestion_lag = Gauge("platform_price_ingestion_lag_seconds", "Price data staleness")
```

### Task 4.5: Grafana Dashboard Definitions

**New files:** `monitoring/dashboards/`

Create JSON dashboard definitions for Grafana:

| Dashboard | Panels |
|-----------|--------|
| **Agent Overview** | Decision rate, PnL chart, win rate, active agents, health status |
| **Agent API Calls** | Latency heatmap, error rate, calls by endpoint, top slow calls |
| **Agent LLM Usage** | Token consumption, cost per day, latency by model, calls by purpose |
| **Agent Memory** | Cache hit rate, memory count by type, retrieval scores, reinforcement trends |
| **Agent Strategy** | Per-strategy confidence distribution, ensemble weights over time, veto rate |
| **Ecosystem Health** | Agent + platform health combined, error correlation, decision-to-outcome latency |

### Task 4.6: Alert Rules

**New file:** `monitoring/alerts/agent-alerts.yml`

| Alert | Condition | Severity |
|-------|-----------|----------|
| `AgentUnhealthy` | `agent_health_status == 0` for 5m | Critical |
| `AgentHighErrorRate` | `rate(agent_api_errors_total[5m]) > 0.1` | Warning |
| `AgentHighLLMCost` | `increase(agent_llm_cost_usd_total[1h]) > 5.0` | Warning |
| `AgentBudgetExhausted` | `agent_budget_usage_ratio > 0.95` | Warning |
| `AgentDecisionDrop` | `rate(agent_decisions_total[15m]) == 0` for 30m | Warning |
| `AgentMemoryCacheLow` | `agent_memory_cache_hits / (hits + misses) < 0.5` for 1h | Info |

### Deliverables

- [ ] `agent/metrics.py` — full Prometheus metrics registry
- [ ] Agent `/metrics` endpoint exposed
- [ ] All Phase 2 instrumentation also emits Prometheus metrics
- [ ] Platform-side application metrics registered
- [ ] 6 Grafana dashboards defined
- [ ] Alert rules for critical conditions

### Files Changed

| File | Change |
|------|--------|
| `agent/metrics.py` | **NEW** — metrics registry |
| `agent/server.py` | `/metrics` endpoint |
| `agent/logging_middleware.py` | Add metrics emission |
| `agent/memory/postgres_store.py` | Memory operation metrics |
| `agent/memory/redis_cache.py` | Cache hit/miss metrics |
| `agent/trading/loop.py` | Decision + trade metrics |
| `agent/trading/journal.py` | LLM metrics |
| `agent/permissions/enforcement.py` | Permission denial metrics |
| `agent/permissions/budget.py` | Budget usage gauge |
| `src/main.py` | Platform application metrics |
| `monitoring/dashboards/*.json` | **NEW** — Grafana dashboards |
| `monitoring/alerts/agent-alerts.yml` | **NEW** — alert rules |

---

## Phase 5: Intelligence Layer

**Goal:** Turn logging data into actionable insights that automatically improve both the agent and the platform.

### Task 5.1: Decision Replay Query API

**New endpoints in platform API:**

```
GET /api/v1/agents/{id}/decisions/trace/{trace_id}
    → Returns full decision chain: signals → decision → API calls → order → trade → PnL

GET /api/v1/agents/{id}/decisions/analyze
    ?start=2026-03-01&end=2026-03-21
    ?min_confidence=0.7
    ?direction=buy
    ?pnl_outcome=negative
    → Returns filtered decisions with aggregated stats
```

### Task 5.2: Strategy Attribution Report

**New Celery task:** `agent_strategy_attribution`

Runs daily. For each agent:
1. Query `agent_strategy_signals` for the last 24h
2. Join with `agent_decisions` on `trace_id`
3. Join with `trades` on `order_id` (from decision)
4. Calculate per-strategy contribution to PnL
5. Store results in `agent_performance` with `period="attribution"`

### Task 5.3: Memory Effectiveness Analysis

**New Celery task:** `agent_memory_effectiveness`

Runs weekly. For each agent:
1. Query decisions where memory was used in context (logged in Phase 2)
2. Compare win rate / PnL of memory-assisted vs. non-memory decisions
3. Identify most-reinforced memories and their correlation to outcomes
4. Generate `agent_journal` entry with findings

### Task 5.4: Platform Health from Agent Perspective

**New Celery task:** `agent_platform_health_report`

Runs daily. Aggregates `agent_api_calls`:
1. p50/p95/p99 latency per endpoint
2. Error rate per endpoint
3. Availability (success rate) per endpoint
4. Comparison to previous day (regression detection)
5. Auto-creates `agent_feedback` entries for degraded endpoints

### Task 5.5: Anomaly Detection

**File:** `agent/trading/loop.py` (enhancement to `_learn()` phase)

After each trading loop tick, compare current metrics to rolling averages:
- Decision confidence distribution shift
- API latency spike (>2x rolling p95)
- Error rate spike (>3x rolling rate)
- PnL outlier (>3 standard deviations)

Log anomalies at `warning` level with full context for investigation.

### Task 5.6: Feedback Loop Automation

**Enhancement to `agent_feedback` table:**

Add columns:
- `status` — `submitted`, `acknowledged`, `in_progress`, `resolved`, `wont_fix`
- `resolved_at` — timestamp
- `resolution` — text

**New endpoint:**
```
PATCH /api/v1/agents/{id}/feedback/{feedback_id}
    body: {"status": "resolved", "resolution": "Fixed in commit abc123"}
```

This closes the loop: agent discovers bug → creates feedback → developer fixes → marks resolved → agent can verify.

### Deliverables

- [ ] Decision trace API endpoint
- [ ] Decision analysis/filter API endpoint
- [ ] Strategy attribution Celery task
- [ ] Memory effectiveness analysis task
- [ ] Platform health report from agent perspective
- [ ] Anomaly detection in trading loop
- [ ] Feedback lifecycle management (status tracking)

### Files Changed

| File | Change |
|------|--------|
| `src/api/routes/agents.py` | Decision trace + analysis endpoints |
| `src/tasks/agent_analytics.py` | **NEW** — attribution, memory effectiveness, platform health tasks |
| `src/database/models.py` | `AgentFeedback` status/resolution columns |
| `src/api/routes/agents.py` | Feedback PATCH endpoint |
| `agent/trading/loop.py` | Anomaly detection in learn phase |
| Alembic migration | `AgentFeedback` columns |

---

## Implementation Priority Matrix

| Phase | Business Value | Effort | Risk | Priority |
|-------|---------------|--------|------|----------|
| Phase 1: Foundation | Medium | Low | Very Low | **P0 — Do first** |
| Phase 2: API/LLM Logging | High | Medium | Low | **P0 — Do immediately after** |
| Phase 3: Correlation | Very High | Medium | Medium (migrations) | **P1 — Core value** |
| Phase 4: Metrics | High | Medium | Low | **P1 — Enables monitoring** |
| Phase 5: Intelligence | Very High | High | Medium | **P2 — Multiplier** |

---

## Testing Strategy

### Unit Tests

| Component | Test Focus |
|-----------|-----------|
| `agent/logging.py` | Correlation context vars set/get correctly |
| `agent/logging_middleware.py` | Timing accuracy, error capture, context propagation |
| `agent/metrics.py` | Metric labels match, counters increment |
| `agent/logging_writer.py` | Batch size triggers, flush interval, shutdown drain |

### Integration Tests

| Scenario | Validates |
|----------|----------|
| Agent places trade → trace_id appears in platform logs | Cross-system correlation |
| API call logs → `agent_api_calls` table rows | DB persistence |
| Strategy signals → `agent_strategy_signals` table rows | Pipeline logging |
| LLM call → token count in Prometheus | Metrics emission |

### Load Tests

| Scenario | Target |
|----------|--------|
| 100 API calls/second with logging | <5% latency increase vs. without logging |
| 1000 log events buffered for batch write | Flush completes in <100ms |
| 10 concurrent agents with full logging | No metric label cardinality explosion |

---

## Rollback Plan

Each phase can be independently disabled:

| Phase | Rollback Mechanism |
|-------|-------------------|
| Phase 1 | Revert to per-file structlog.configure(); no data loss |
| Phase 2 | Remove log_api_call wrappers; no functional change |
| Phase 3 | Drop new tables (additive-only migration); remove X-Trace-Id header |
| Phase 4 | Unregister metrics; remove /metrics endpoint |
| Phase 5 | Disable Celery tasks; keep API endpoints (they're read-only) |

---

## Success Criteria

### Phase 1 Complete When:
- `grep -r "import logging" agent/` returns zero hits (excluding tests and `__init__`)
- All agent log lines are valid JSON with `timestamp`, `level`, `event` fields

### Phase 2 Complete When:
- Every outbound API call produces a log line with `channel`, `endpoint`, `latency_ms`
- Every LLM call produces a log line with `model`, `tokens`, `cost_estimate`
- Memory cache hit rate is measurable from logs

### Phase 3 Complete When:
- Given a `trace_id`, can reconstruct: signal → decision → API calls → order → trade → PnL
- `agent_api_calls` table accumulates rows on every trading loop tick
- Platform HTTP logs include `trace_id` for agent-originated requests

### Phase 4 Complete When:
- Grafana dashboards show real-time agent activity
- At least 3 alert rules are firing correctly (test with synthetic failures)
- LLM cost per agent per day is visible

### Phase 5 Complete When:
- Strategy attribution report runs daily and identifies which strategy contributes most to PnL
- Platform health report auto-creates feedback entries for degraded endpoints
- Anomaly detection logs warnings for p95 latency spikes
