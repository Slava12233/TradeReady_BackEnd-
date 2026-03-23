---
name: monitoring_stack_patterns
description: Prometheus + Grafana config patterns and issues found in AiTradingAgent monitoring setup
type: project
---

The agent ecosystem has two separate Prometheus metric registries:
- `api:8000/metrics` — platform's default Prometheus registry (4 platform metrics)
- `agent:8001/metrics` — agent's custom `AGENT_REGISTRY` (16 agent metrics)

**Why:** `AGENT_REGISTRY = CollectorRegistry()` in `agent/metrics.py` keeps agent metrics isolated from platform metrics to avoid label collisions. `AgentServer._metrics_server_loop()` serves it on `agent_server_port` (default 8001).

**How to apply:** Both endpoints must be scraped in `prometheus.yml` as separate `scrape_configs` jobs. When only `api:8000` is configured, all dashboards and alerts for `agent_*` prefixed metrics silently return no data.

---

Alert rules in `monitoring/alerts/agent-alerts.yml` are NOT automatically loaded by Prometheus — they must be referenced via a `rule_files:` stanza in `prometheus.yml` AND the rules file must be volume-mounted into the Prometheus container at the path referenced.

**Why:** Without `rule_files:`, Prometheus evaluates no alert rules regardless of what files exist on disk.

**How to apply:** Always verify prometheus.yml has both `rule_files:` (with container-internal path) and the docker-compose volume mount for the rules file.

---

Grafana dashboards in `monitoring/dashboards/` are not auto-provisioned without provisioning config files.

**Why:** Grafana only auto-imports from `GF_PATHS_PROVISIONING` subdirectories. Without `provisioning/datasources/` and `provisioning/dashboards/` configs, dashboards must be manually imported every time the grafana_data volume is recreated.

**How to apply:** Create `monitoring/provisioning/datasources/prometheus.yml` and `monitoring/provisioning/dashboards/dashboards.yml`, then mount them into the Grafana container in docker-compose alongside the dashboard JSON directory.
