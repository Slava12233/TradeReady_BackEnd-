# monitoring/ — Grafana Dashboards and Prometheus Alert Rules

<!-- last-updated: 2026-03-21 -->

> Infrastructure monitoring configuration: 6 Grafana dashboard JSON definitions and 11 Prometheus alert rules for the agent ecosystem.

## What This Directory Does

Contains all **external monitoring configuration** for the AiTradingAgent platform. These files are consumed by Grafana and Prometheus (Alertmanager), not by the Python application itself.

- Platform and application code metrics are defined in `src/monitoring/metrics.py` (4 platform metrics) and `agent/metrics.py` (16 agent metrics in `AGENT_REGISTRY`).
- This directory contains the **dashboards** and **alert rules** that visualize those metrics.

## Key Files

| File | Purpose |
|------|---------|
| `alerts/agent-alerts.yml` | 11 Prometheus alert rules for the agent ecosystem (high error rate, high latency, budget exceeded, etc.) |
| `dashboards/agent-overview.json` | Grafana: top-level agent activity summary — trades, signals, API calls per agent |
| `dashboards/agent-api-calls.json` | Grafana: per-tool API call latency, token usage, cost breakdown |
| `dashboards/agent-llm-usage.json` | Grafana: LLM call costs, model usage distribution, error rate |
| `dashboards/agent-memory.json` | Grafana: memory store operations, cache hit/miss ratio, retrieval latency |
| `dashboards/agent-strategy.json` | Grafana: per-strategy signal distribution, confidence histogram, PnL attribution |
| `dashboards/ecosystem-health.json` | Grafana: cross-agent health overview — budget utilization, permission denials, trade success rate |

## Alert Rules (`alerts/agent-alerts.yml`)

11 alert rules covering:
- High agent API error rate (>5% over 5m)
- High LLM call latency (P95 >5s)
- Budget limit approached (>90% daily trades used)
- Permission denial spike (>10 denials/min)
- Agent memory retrieval degradation (cache hit ratio <50%)
- Strategy signal anomaly (confidence consistently <0.3)
- LogBatchWriter queue depth growing (unprocessed DB writes)
- Agent Celery task failures
- Platform order latency regression
- Price ingestion lag (>30s)
- Agent ecosystem DB connection pool exhaustion

## Patterns

- Dashboard JSON files are Grafana-native format (provisioned via `docker-compose.yml` volumes or manual import)
- Alert rules follow the standard `groups[].rules[]` YAML format for Prometheus Alertmanager
- All dashboards use `AGENT_REGISTRY`-scoped metric names (`agent_*` prefix) and platform metric names (`platform_*` prefix)
- Dashboards are parameterized by `agent_id` variable for per-agent drill-down

## Gotchas

- **Dashboard files are not auto-synced** — if you change a metric name in `agent/metrics.py` or `src/monitoring/metrics.py`, you must also update the PromQL queries in the corresponding dashboard JSON files.
- **Alert rules require Alertmanager** — the `agent-alerts.yml` file is a rules file loaded by Prometheus, not Alertmanager config. Route it via `alertmanager.yml` for notification delivery.
- **`AGENT_REGISTRY` vs default registry** — agent metrics use a separate `CollectorRegistry` to avoid polluting the platform's default Prometheus registry. The agent's `/metrics` endpoint serves `AGENT_REGISTRY` only; the platform `/metrics` serves the default registry.

## Recent Changes

- `2026-03-21` — Initial creation: 6 Grafana dashboards + 11 Prometheus alert rules added as part of Agent Logging System (34 tasks, 5 phases).
