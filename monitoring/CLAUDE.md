# monitoring/ — Grafana Dashboards and Prometheus Alert Rules

<!-- last-updated: 2026-04-16 -->

> Infrastructure monitoring configuration: 7 Grafana dashboard JSON definitions and 11 Prometheus alert rules for the agent ecosystem.

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
| `dashboards/retraining.json` | Grafana: continuous retraining pipeline — retrain events by component, A/B gate outcomes, drift detection rate, last retrain timestamps |
| `dashboards/platform-infrastructure.json` | Grafana: platform infra health — container CPU/memory, API response time percentiles (P50/P95/P99), API error rate by endpoint, price ingestion lag, service health overview |
| `alertmanager.yml` | Alertmanager config — routes all 11 alert rules to an email receiver; SMTP credentials via env vars |
| `provisioning/datasources/prometheus.yml` | Grafana auto-provisioned datasource — points to `http://prometheus:9090` with uid `prometheus` |
| `provisioning/dashboards/dashboards.yml` | Grafana auto-provisioned dashboard loader — serves all JSON files from `/var/lib/grafana/dashboards` |

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

- Dashboard JSON files are auto-provisioned into Grafana via `monitoring/provisioning/dashboards/dashboards.yml` — no manual import needed after the initial `docker compose up`
- Alert rules are loaded by Prometheus via `rule_files:` in `prometheus.yml` — mounted into the container at `/etc/prometheus/rules/agent-alerts.yml`
- All dashboards use `AGENT_REGISTRY`-scoped metric names (`agent_*` prefix), platform metric names (`platform_*` prefix), and retrain metric names (`retrain_*` prefix for `retraining.json`)
- Dashboards are parameterized by `agent_id` variable for per-agent drill-down
- Two Prometheus scrape jobs: `api` (`:8000/metrics`, default registry) and `agent` (`:8001/metrics`, `AGENT_REGISTRY`). The `agent` job only has data when the agent service profile is running.

## Gotchas

- **Dashboard files are not auto-synced** — if you change a metric name in `agent/metrics.py` or `src/monitoring/metrics.py`, you must also update the PromQL queries in the corresponding dashboard JSON files.
- **Alertmanager uses env-var substitution in its config** — the `${VAR}` placeholders in `alertmanager.yml` are resolved by the shell before the config is written. The Docker service passes the env vars through; if a var is unset, Alertmanager will start but may log a warning about empty SMTP fields.
- **Alertmanager web UI** — accessible at `http://localhost:9093` (host port mapped in docker-compose). Use it to view active alerts, silences, and the current inhibition graph.
- **`AGENT_REGISTRY` vs default registry** — agent metrics use a separate `CollectorRegistry` to avoid polluting the platform's default Prometheus registry. The agent's `/metrics` endpoint serves `AGENT_REGISTRY` only; the platform `/metrics` serves the default registry.
- **Agent scrape job will show DOWN when agent profile is not running** — the `agent:8001` scrape target in `prometheus.yml` is always configured, but will fail to connect unless `docker compose --profile agent up` was used. This produces a Prometheus scrape error but does not break other scrape jobs.
- **Grafana datasource UID** — all 6 dashboard JSON files use `uid: "${datasource}"` (Grafana template variable), so the auto-provisioned datasource uid `prometheus` does not need to match the dashboard UID references — they use the template variable pattern which resolves at render time.

## Recent Changes

- `2026-04-16` — Task 37: Added `dashboards/platform-infrastructure.json` (8th Grafana dashboard) — container CPU/memory, API response time percentiles (P50/P95/P99), API error rate by endpoint, price ingestion lag, service health overview. 6 stat panels + 8 timeseries panels. Dashboard count: 7 → 8.
- `2026-04-15` — Task 05: Alertmanager pipeline wired up. Created `monitoring/alertmanager.yml` (email receiver, severity-based inhibition, env-var credentials). Added `alerting:` stanza to `prometheus.yml`. Added `alertmanager` service to `docker-compose.yml` (port 9093, `prom/alertmanager:v0.27.0`). Added 5 `ALERTMANAGER_*` env vars to `.env.example`. The 11 alert rules that were firing silently are now fully routed.
- `2026-03-23` — R5-05: Added `dashboards/retraining.json` — 7th Grafana dashboard tracking continuous retraining pipeline: retrain event counts by component (ensemble/regime/genome/PPO), A/B gate pass/fail rates, drift detection events, time-since-last-retrain panels. Dashboard count: 6 → 7.
- `2026-03-22` — Task 36: Fixed 3 issues: (1) Added `rule_files:` stanza to `prometheus.yml` so alert rules are actually loaded. (2) Added `agent:8001` scrape job to `prometheus.yml` for `AGENT_REGISTRY` metrics. (3) Added Grafana auto-provisioning via `monitoring/provisioning/` — datasource (Prometheus) and dashboard loader configs, with 3 new volume mounts in `docker-compose.yml`.
- `2026-03-21` — Initial creation: 6 Grafana dashboards + 11 Prometheus alert rules added as part of Agent Logging System (34 tasks, 5 phases).
