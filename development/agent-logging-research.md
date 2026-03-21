---
type: research-report
title: "Agent Logging Research: Ecosystem-Level Analysis"
status: active
phase: agent-logging
tags:
  - research
  - agent-logging
---

# Agent Logging Research: Ecosystem-Level Analysis

> **Audience:** CTO / Technical Leadership
> **Date:** 2026-03-21
> **Scope:** Complete analysis of logging needs across the agent-platform ecosystem

---

## Executive Summary

The TradeReady platform and its autonomous trading agent form a **closed-loop ecosystem**: the agent exercises the platform's trading capabilities, discovers bugs and performance issues, and feeds improvement ideas back — while the platform provides market data, execution, risk controls, and persistence that shape the agent's behavior. **Logging is the nervous system of this loop.** Without comprehensive, structured, correlated logging, neither side can effectively improve the other.

### Current State: What Exists

| Area | Status | Details |
|------|--------|---------|
| Platform structured logging | Partial | `structlog` JSON in services/repos; stdlib plain text in routes, Celery, WebSocket |
| Agent structured logging | Good foundation | 54/80 files use `structlog`; remaining are pure models, `__init__`, tests |
| Request correlation | Basic | `request_id` UUID in HTTP middleware; not propagated to agent calls |
| Database audit trail | Schema only | `AuditLog` table defined (7 columns), zero active writers |
| Agent decision tracking | Active | 7 dedicated tables (`agent_decisions`, `agent_journal`, `agent_learnings`, etc.) |
| Prometheus metrics | Minimal | Default process collectors only; no custom counters/gauges/histograms |
| External error tracking | None | No Sentry, Datadog, Rollbar integration |
| Training run tracking | Strong | Episode-level metrics persisted as JSONB, learning curve API exists |
| Log aggregation | None | No ELK, Loki, CloudWatch — logs go to stdout/files |

### The Core Problem

The agent and platform are **observable in isolation but opaque as a system**. We can see HTTP requests hitting the platform and we can see agent decisions in the database — but we cannot trace a single agent decision from signal generation through API call through order execution through PnL outcome. The ecosystem's improvement loop is blind.

---

## Part 1: The Ecosystem Mental Model

### The Improvement Loop

```
┌──────────────────────────────────────────────────────────────────┐
│                    THE IMPROVEMENT LOOP                          │
│                                                                  │
│  ┌──────────┐    API calls     ┌──────────────┐                 │
│  │          │ ──────────────►  │              │                 │
│  │  AGENT   │                  │  PLATFORM    │                 │
│  │          │ ◄──────────────  │              │                 │
│  └────┬─────┘    responses     └──────┬───────┘                 │
│       │                               │                         │
│       │  learns from                  │  surfaces via           │
│       │  outcomes                     │  monitoring             │
│       ▼                               ▼                         │
│  ┌──────────┐                  ┌──────────────┐                 │
│  │ AGENT    │   feeds into     │  PLATFORM    │                 │
│  │ MEMORY   │ ──────────────►  │  METRICS     │                 │
│  │ SYSTEM   │                  │  & LOGS      │                 │
│  └──────────┘                  └──────────────┘                 │
│       │                               │                         │
│       │  improves                     │  improves               │
│       │  strategies                   │  infrastructure         │
│       ▼                               ▼                         │
│  ┌──────────┐                  ┌──────────────┐                 │
│  │ BETTER   │   exercises      │  BETTER      │                 │
│  │ AGENT    │ ──────────────►  │  PLATFORM    │                 │
│  └──────────┘                  └──────────────┘                 │
└──────────────────────────────────────────────────────────────────┘
```

### Four Integration Channels (All Need Logging)

The agent talks to the platform through four channels, each with different observability characteristics:

| Channel | Transport | Auth | Current Logging | Gap |
|---------|-----------|------|-----------------|-----|
| **SDK** (`AsyncAgentExchangeClient`) | HTTP REST | API Key + JWT | Platform-side only (HTTP middleware) | No agent-side request/response logging, no latency tracking |
| **MCP** (stdio subprocess) | JSON-RPC over pipes | API Key env var | `LOG_LEVEL=WARNING` suppresses most | LLM tool call context lost, no correlation to agent decision |
| **REST** (`PlatformRESTClient`) | HTTP | API Key | Platform-side only | Same as SDK — agent side invisible |
| **Direct DB** (`agent_tools.py`) | SQLAlchemy sessions | Co-located trust | Writes to journal/learnings tables | No audit trail of DB mutations, no correlation |

### Seven Agent Database Tables (The Structured Log)

These tables are the agent's structured log — but they're designed for agent self-improvement, not for platform observability:

| Table | Records | Used For | Missing |
|-------|---------|----------|---------|
| `agent_decisions` | Trade decisions with reasoning | Agent strategy evaluation | Platform-side correlation (order_id often NULL) |
| `agent_journal` | Reflections, insights, reviews | Agent learning | No severity, no tags searchable, no structured metrics |
| `agent_learnings` | Extracted knowledge | Memory system | No provenance chain (which decision led to which learning) |
| `agent_feedback` | Platform improvement ideas | Backlog generation | No status tracking (submitted but never actioned) |
| `agent_observations` | Market snapshots at decision time | Context replay | Not linked to decisions |
| `agent_performance` | Rolling strategy metrics | Strategy comparison | No granularity below window_size (20 trades) |
| `agent_sessions` / `agent_messages` | Conversation history | Context assembly | No LLM cost tracking aggregation, no token budget analysis |

---

## Part 2: Gap Analysis

### Gap 1: No Cross-System Correlation

**Problem:** When the agent places a trade, three systems record it independently:
- Agent: `agent_decisions` row with `reasoning` and `confidence`
- Platform: `orders` row with `order_id`, `fill_price`, `status`
- Platform: `trades` row with `pnl`, `fee`

These are linked by `order_id` — but only when the order succeeds. Failed orders, rejected orders, rate-limited requests, and timeout errors leave no trace connecting agent intent to platform outcome.

**Impact:** Cannot answer: "Why did the agent lose money last Tuesday?" or "Which agent decisions correlate with platform errors?"

### Gap 2: No Agent-Side API Call Logging

**Problem:** The agent makes 20+ API calls per trading loop tick via SDK, REST, and MCP channels. None of these calls are logged on the agent side — only the platform's HTTP middleware records them. The agent has no record of:
- Which API calls it made
- How long they took
- Which ones failed and why
- What data it received

**Impact:** Cannot debug: "Was the agent's bad trade caused by stale price data?" or "Is the platform's response time degrading the agent's performance?"

### Gap 3: Strategy Pipeline Observability is Black-Box

**Problem:** The 5-strategy ensemble pipeline (`RL → Evolutionary → Regime → Risk → Ensemble`) produces a final `ConsensusSignal`, but the intermediate signals, weights, vetoes, and sizing decisions are not logged. Only the final decision reaches `agent_decisions`.

**Impact:** Cannot answer: "Which strategy is contributing the most to PnL?" or "Is the risk overlay vetoing profitable trades?"

### Gap 4: Celery Tasks Produce Plain Text Logs

**Problem:** The 4 agent Celery tasks (`morning_review`, `budget_reset`, `memory_cleanup`, `performance_snapshot`) run as separate processes without structlog configuration. Their logs are plain text, not JSON — invisible to structured log aggregation.

**Impact:** Cannot correlate scheduled maintenance with agent behavior changes. Cannot monitor budget reset timing relative to trading activity.

### Gap 5: Memory System Operations are Invisible

**Problem:** The 4-layer memory system (Retriever → Redis Cache → Postgres Store → Repository) operates silently. We don't know:
- How often memories are retrieved vs. stored
- Cache hit rates
- Which memories influence decisions
- Memory scoring distribution

**Impact:** Cannot optimize the memory system. Cannot answer: "Is the agent learning from its mistakes?" or "Are old memories diluting recent learnings?"

### Gap 6: Permission and Budget Enforcement is Logged But Not Aggregated

**Problem:** `PermissionEnforcer` buffers audit entries to the `agent_feedback` table (flushes at 100 entries or 30 seconds) — but these are raw entries with no aggregation, alerting, or trend detection.

**Impact:** Cannot detect: "Agent X is hitting its daily loss limit every day at 2pm" or "Permission denials spiked after the last config change."

### Gap 7: LLM Interactions Have No Cost Tracking

**Problem:** The agent makes LLM calls via OpenRouter for:
- Trade analysis (primary model, ~$0.015/call)
- Trade reflections (cheap model, ~$0.001/call)
- Session summarization (primary model, ~$0.01/call)
- Strategy review (cheap model, ~$0.001/call)

Token counts are stored per-message in `agent_messages.tokens_used` but never aggregated. No cost tracking exists.

**Impact:** Cannot answer: "How much does each agent cost per day in LLM calls?" or "Is the session summarization threshold optimal?"

### Gap 8: The Platform's AuditLog Table is Dead Code

**Problem:** `AuditLog` model exists with a proper schema (action, details JSONB, ip_address INET) and a cleanup task (30-day retention) — but nothing writes to it. It was designed but never activated.

**Impact:** No forensic audit trail for platform operations. The agent's `agent_feedback` table partially fills this role but only for agent-initiated events.

### Gap 9: Prometheus Metrics Are Empty

**Problem:** Only default Python process collectors (GC, memory, CPU) are registered. No application-level metrics exist for:
- Orders per minute
- Trade execution latency
- Price ingestion throughput
- Agent decision rate
- API error rates
- Memory retrieval latency

**Impact:** Grafana dashboards show process health but zero business metrics. Cannot set alerts on trading activity anomalies.

### Gap 10: No Unified Log Format Across Agent + Platform

**Problem:** Three different log formats coexist:
1. `structlog` JSON (platform services, agent core) — machine-parseable
2. stdlib plain text (platform routes, Celery) — not machine-parseable
3. `print()` output (agent CLI, strategy scripts) — ephemeral

**Impact:** Cannot aggregate logs from all components into a single queryable system.

---

## Part 3: What Logging Enables for the Ecosystem

### For Agent Improvement

| Capability | Requires | Enables |
|------------|----------|---------|
| Decision replay | Correlated decision → signal → order → outcome chain | "Show me every BTC trade where confidence > 0.8 but PnL was negative" |
| Strategy attribution | Per-strategy signal logging with final ensemble weights | "RL contributed 60% of profitable signals, regime detection 10%" |
| Memory effectiveness | Memory retrieval logging with decision outcome correlation | "Decisions that used procedural memories had 15% higher win rate" |
| Cost optimization | LLM call logging with token counts and model used | "Switching reflections to Gemini Flash saved $4.20/day with no quality loss" |
| Learning velocity | Temporal analysis of memory confidence scores | "Agent stopped making the same mistake after 3 occurrences" |

### For Platform Improvement

| Capability | Requires | Enables |
|------------|----------|---------|
| API reliability scoring | Agent-side latency + error logging per endpoint | "The candle endpoint has p99 latency of 2.3s — investigate" |
| Feature usage analytics | API call frequency by endpoint and agent | "No agent uses the WebSocket price stream — deprioritize" |
| Bug detection | Agent `bugs_found` correlation with platform error logs | "Agent found 3 bugs in backtest API last week — auto-create tickets" |
| Capacity planning | Request rate metrics + price ingestion throughput | "At 10 concurrent agents, the candle endpoint saturates" |
| Data quality monitoring | Agent observations vs. actual price feed comparison | "BTC price was stale for 45 seconds during the flash crash" |

### For the Ecosystem

| Capability | Requires | Enables |
|------------|----------|---------|
| End-to-end tracing | Correlation ID propagated from agent → platform → back | "This $500 loss traces to a 200ms price ingestion delay" |
| Improvement velocity tracking | Timestamped agent performance + platform change log | "After fixing the slippage bug, agent Sharpe improved 0.3 → 0.8" |
| Anomaly detection | Prometheus metrics + alerting rules | "Alert: agent decision rate dropped 90% — investigate" |
| Regression detection | Automated comparison of agent metrics pre/post deploy | "Deploy #47 caused 15% more order rejections" |

---

## Part 4: Key Design Decisions

### Decision 1: Structured Logging Library

**Recommendation: Standardize on `structlog` everywhere.**

The platform already uses it in 60%+ of files. The agent uses it in 54/80 files. The remaining stdlib `logging` calls in routes, Celery tasks, and WebSocket handlers should migrate to `structlog`. This unifies the output format (JSON) and enables consistent field naming.

### Decision 2: Log Storage Backend

**Options:**

| Option | Pros | Cons |
|--------|------|------|
| **Stdout JSON → Docker log driver → Loki/ELK** | Industry standard, scalable, queryable | Requires infrastructure setup |
| **Stdout JSON → File rotation** | Simple, no infra cost | Not queryable, hard to correlate |
| **Database tables** | Already exists (agent tables), queryable via SQL | Not suitable for high-volume debug logs |
| **Hybrid: DB for structured events, Loki for debug** | Best of both worlds | More complex |

**Recommendation: Hybrid approach.** High-value structured events (decisions, trades, API calls, errors) go to **database tables** (already have the schema). High-volume debug/trace logs go to **stdout JSON** for collection by whatever log aggregation the deployment uses.

### Decision 3: Correlation Strategy

**Recommendation: Three-level correlation IDs:**

1. **`trace_id`** — spans the entire agent decision cycle (signal → execution → outcome). Generated by `TradingLoop.tick()`.
2. **`span_id`** — individual operation within a trace (API call, memory retrieval, LLM call). Generated per-operation.
3. **`session_id`** — conversation session scope. Already exists in `agent_sessions`.

The `trace_id` must be propagated as an HTTP header (`X-Trace-Id`) so the platform's `LoggingMiddleware` can include it in its log lines.

### Decision 4: Metrics vs. Logs

**Rule of thumb:**
- **Logs** for things you need to investigate (debug, trace, error details, reasoning chains)
- **Metrics** for things you need to monitor and alert on (rates, latencies, counts, percentages)
- **Database records** for things you need to query and analyze (decisions, outcomes, learnings)

All three are complementary, not competing.

### Decision 5: Log Levels for the Agent

| Level | When to use | Example |
|-------|------------|---------|
| `debug` | Internal state changes, cache operations, scoring details | `"memory.retrieval.scored", memory_id=..., score=0.73` |
| `info` | Completed operations, state transitions, API calls | `"agent.trade.executed", symbol="BTCUSDT", side="buy"` |
| `warning` | Degraded operation, retries, fallbacks | `"agent.api.retry", endpoint="/candles", attempt=2` |
| `error` | Failed operations that affect outcomes | `"agent.trade.failed", symbol="BTCUSDT", error="insufficient_balance"` |
| `critical` | System-level failures, data corruption risk | `"agent.server.consecutive_errors", count=10, status="degraded"` |

---

## Part 5: Architecture Recommendations

### The Logging Stack

```
┌────────────────────────────────────────────────────────────┐
│                     LOG CONSUMERS                          │
│                                                            │
│  Grafana ◄── Prometheus ◄── Custom metrics (counters,     │
│  (dashboards,                gauges, histograms)           │
│   alerts)                                                  │
│                                                            │
│  Grafana ◄── Loki ◄── stdout JSON logs (via Docker/promtail) │
│  (log search)                                              │
│                                                            │
│  Platform DB ◄── Structured event tables                   │
│  (SQL queries,    (agent_decisions, agent_api_calls,       │
│   API endpoints)   agent_metrics, audit_log)               │
└────────────────────────────────────────────────────────────┘
        ▲                    ▲                    ▲
        │                    │                    │
┌───────┴────────────────────┴────────────────────┴──────────┐
│                   AGENT LOGGING LAYER                      │
│                                                            │
│  AgentLogger (unified interface)                           │
│    ├── structlog → stdout JSON (debug, info, warning, error)│
│    ├── MetricsCollector → Prometheus counters/histograms   │
│    ├── EventRecorder → DB tables (decisions, API calls)    │
│    └── TraceContext → correlation IDs (trace, span, session)│
└────────────────────────────────────────────────────────────┘
```

### New Database Tables Needed

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `agent_api_calls` | Every API call the agent makes | `trace_id`, `agent_id`, `channel` (sdk/mcp/rest/db), `endpoint`, `method`, `status_code`, `latency_ms`, `request_size`, `response_size`, `error`, `created_at` |
| `agent_metrics` | Periodic aggregated metrics | `agent_id`, `metric_name`, `metric_value`, `period`, `dimensions` (JSONB), `created_at` |
| `agent_strategy_signals` | Per-strategy signals before ensemble | `trace_id`, `agent_id`, `strategy_name`, `symbol`, `signal` (JSONB), `weight`, `created_at` |

### Prometheus Metrics to Register

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `agent_decisions_total` | Counter | `agent_id`, `decision_type`, `direction` | Decision rate |
| `agent_trade_pnl` | Histogram | `agent_id`, `symbol` | PnL distribution |
| `agent_api_call_duration_seconds` | Histogram | `agent_id`, `channel`, `endpoint` | API latency |
| `agent_api_errors_total` | Counter | `agent_id`, `channel`, `endpoint`, `error_code` | Error rate |
| `agent_memory_operations_total` | Counter | `agent_id`, `operation` (save/retrieve/reinforce) | Memory activity |
| `agent_memory_cache_hits_total` | Counter | `agent_id` | Cache effectiveness |
| `agent_llm_tokens_total` | Counter | `agent_id`, `model`, `direction` (input/output) | LLM cost tracking |
| `agent_llm_call_duration_seconds` | Histogram | `agent_id`, `model`, `purpose` | LLM latency |
| `agent_permission_denials_total` | Counter | `agent_id`, `capability` | Permission issues |
| `agent_budget_usage_ratio` | Gauge | `agent_id`, `limit_type` | Budget utilization |
| `agent_strategy_signal_confidence` | Histogram | `agent_id`, `strategy_name` | Signal quality |
| `agent_consecutive_errors` | Gauge | `agent_id` | Health indicator |

---

## Part 6: Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Log volume overwhelms DB | High | Use DB only for structured events; debug/trace to stdout |
| Logging adds latency to trading loop | Medium | Async logging (structlog is sync by default); batch DB writes |
| Correlation IDs not propagated | Medium | Enforce via middleware; add `X-Trace-Id` header to SDK/REST clients |
| Schema migrations for new tables | Low | Standard Alembic workflow; additive-only changes |
| Log format breaking changes | Low | Version the JSON schema; add fields, never remove |
| Over-logging in production | Medium | Default to `INFO`; `DEBUG` only when troubleshooting |

---

## Conclusion

Logging is not a feature — it's infrastructure that makes every other feature improvable. The agent-platform ecosystem has strong foundations (structlog, 7 agent tables, training run tracking) but critical gaps (no cross-system correlation, no API call logging, no Prometheus metrics, dead AuditLog). Closing these gaps transforms the ecosystem from "two systems that talk to each other" into "one system that learns from itself."

The implementation plan (see `agent-logging-plan.md`) details how to close each gap in 5 phases over approximately 3 sprints.
