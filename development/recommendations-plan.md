---
type: plan
title: "Implementation Plan: C-Level Report Recommendations (2026-03-23)"
status: active
priority: P0
created: 2026-03-23
source: "[[C-level_reports/report-2026-03-23]]"
tags:
  - plan
  - recommendations
  - infrastructure
  - security
  - training
  - testing
  - retraining
---

# Implementation Plan: C-Level Report Recommendations

## Overview

This plan addresses all 5 recommendations from the C-level executive report dated 2026-03-23. The recommendations span infrastructure startup, security hardening, ML training pipeline validation, test quality fixes, and continuous retraining automation. Combined, they transform the platform from code-complete to operationally running with trained models and automated improvement cycles.

## CLAUDE.md Files Consulted

- Root `CLAUDE.md` -- architecture overview, dependency direction, Docker setup, environment variables
- `src/tasks/CLAUDE.md` -- Celery beat schedule, task patterns, adding new tasks
- `src/database/CLAUDE.md` -- migration workflow, repository pattern
- `agent/CLAUDE.md` -- agent package structure, workflows, CLI commands
- `agent/strategies/CLAUDE.md` -- 5-strategy system, CLI commands, training pipeline
- `agent/strategies/regime/CLAUDE.md` -- RegimeClassifier, training CLI
- `agent/strategies/rl/CLAUDE.md` -- PPO training, evaluation, deployment
- `agent/strategies/ensemble/CLAUDE.md` -- MetaLearner, weight optimizer
- `agent/strategies/risk/CLAUDE.md` -- RiskMiddleware, VetoPipeline
- `agent/permissions/CLAUDE.md` -- CapabilityManager, BudgetManager, enforcement
- `agent/memory/CLAUDE.md` -- RedisMemoryCache, memory retrieval
- `agent/tests/CLAUDE.md` -- test inventory, mock patterns
- `tests/CLAUDE.md` -- test philosophy, fixtures
- `alembic/CLAUDE.md` -- migration workflow
- `development/CLAUDE.md` -- development planning docs
- `.claude/agents/CLAUDE.md` -- 16 sub-agent definitions, pipeline rules
- `.claude/agent-memory/CLAUDE.md` -- agent memory storage

## Agent Memory Files Consulted

- `.claude/agent-memory/security-reviewer/MEMORY.md` -- 4 CRITICAL fixed, 7 HIGH deferred (4 permissions, 3 strategies)
- `.claude/agent-memory/perf-checker/MEMORY.md` -- 8 HIGH fixed, 5 MEDIUM outstanding
- `.claude/agent-memory/code-reviewer/MEMORY.md` -- `float(Decimal)` casts, Redis glob bug (fixed), writer wiring (fixed)
- `.claude/agent-memory/planner/MEMORY.md` -- task board patterns, architectural constraints

## Reference Documents Consulted

- `development/C-level_reports/report-2026-03-23.md` -- source of all 5 recommendations
- `development/trading-agent-master-plan.md` -- Phase 0-6 infrastructure and training plan
- `development/plan.md` -- deployment plan (Phases 1-9)
- `development/code-reviews/review_2026-03-22_01-53_phase0-group-a.md` -- phantom test details

---

## Pre-Plan Triage: What Is Already Fixed

Before detailing each recommendation, three issues referenced in the C-level report have already been resolved in the codebase:

| Issue | Status | Evidence |
|-------|--------|----------|
| Redis GET with glob pattern (`agent:memory:*:{id}`) | **FIXED** | `agent/memory/redis_cache.py:220` -- `get_cached()` now delegates to `get_cached_for_agent(agent_id, memory_id)` with exact key construction |
| 61 phantom tests exercising missing `writer` parameter | **FIXED** | `agent/logging_middleware.py:59` -- `writer: LogBatchWriter \| None = None` is now an explicit keyword arg; writer wiring at lines 140-152 and 178-189 calls `writer.add_api_call()` |
| `float(c.close)` in `handle_analyze()` | **NOT FIXED** | `agent/server_handlers.py:210` -- `closes = [float(c.close) for c in candles]` still present |

The plan accounts for these findings: Recommendation 4 is reduced in scope (Redis glob and phantom tests are resolved; `float(Decimal)` casts remain).

---

## Task Summary Table

| Task ID | Title | Rec | Phase | Agent | Complexity | Depends On |
|---------|-------|-----|-------|-------|------------|------------|
| **Recommendation 1: Docker Infrastructure** |
| R1-01 | Create `.env` from `.env.example` with secure values | 1 | 1 | backend-developer | S | -- |
| R1-02 | Start Docker Compose services | 1 | 1 | deploy-checker | S | R1-01 |
| R1-03 | Apply Alembic migrations (head = 019) | 1 | 1 | migration-helper | S | R1-02 |
| R1-04 | Seed exchange pairs | 1 | 1 | backend-developer | S | R1-03 |
| R1-05 | Verify all services healthy | 1 | 1 | deploy-checker | S | R1-04 |
| R1-06 | Import Grafana dashboards and verify Prometheus scraping | 1 | 1 | deploy-checker | S | R1-05 |
| R1-07 | Backfill historical candle data (12+ months) | 1 | 1 | backend-developer | L | R1-05 |
| R1-08 | Provision agent accounts (5 trading agents) | 1 | 1 | e2e-tester | M | R1-04 |
| R1-09 | Run smoke test to validate full stack | 1 | 1 | e2e-tester | S | R1-08 |
| **Recommendation 2: Security Fixes** |
| R2-01 | Add ADMIN role check to `grant_capability` and `set_role` | 2 | 2 | security-reviewer | M | R1-03 |
| R2-02 | Track and await `ensure_future` tasks in `BudgetManager.close()` | 2 | 2 | security-reviewer | M | -- |
| R2-03 | Enable Redis `requirepass` and bind to Docker internal network | 2 | 2 | security-reviewer | M | R1-02 |
| R2-04 | Persist "allow" audit events to `agent_audit_log` table | 2 | 2 | security-reviewer | L | R1-03 |
| R2-05 | Add SHA-256 checksum verification before `PPO.load()` | 2 | 2 | security-reviewer | M | -- |
| R2-06 | Add checksum verification before `joblib.load()` | 2 | 2 | security-reviewer | M | -- |
| R2-07 | Remove `--api-key` CLI arg exposure risk (audit remaining scripts) | 2 | 2 | security-reviewer | S | -- |
| R2-08 | Fix remaining `float(Decimal)` casts in agent handlers | 2 | 2 | code-reviewer | S | -- |
| R2-09 | Security audit of all fixes | 2 | 2 | security-auditor | M | R2-01..R2-08 |
| R2-10 | Write regression tests for all security fixes | 2 | 2 | test-runner | M | R2-01..R2-08 |
| **Recommendation 3: Train and Validate One Strategy E2E** |
| R3-01 | Train regime classifier on 12 months BTC 1h data | 3 | 3 | ml-engineer | L | R1-07 |
| R3-02 | Validate regime classifier accuracy >= 70% | 3 | 3 | ml-engineer | S | R3-01 |
| R3-03 | Run regime switcher demo to verify switching logic | 3 | 3 | ml-engineer | S | R3-01 |
| R3-04 | Run 3-month walk-forward validation on regime strategy | 3 | 3 | ml-engineer | L | R3-01 |
| R3-05 | Run regime-adaptive backtest vs static MACD vs buy-and-hold | 3 | 3 | ml-engineer | L | R3-01 |
| R3-06 | Record baseline performance metrics | 3 | 3 | ml-engineer | S | R3-04, R3-05 |
| **Recommendation 4: Fix Remaining Test and Code Quality Issues** |
| R4-01 | Fix `float(c.close)` cast in `server_handlers.py` | 4 | 2 | backend-developer | S | -- |
| R4-02 | Audit and fix all `float(Decimal)` casts across agent package | 4 | 2 | code-reviewer | M | -- |
| R4-03 | Fix 5 MEDIUM perf issues (indicator cache, unbounded lists) | 4 | 2 | perf-checker | M | -- |
| R4-04 | Verify Redis glob bug fix is complete (confirm tests pass) | 4 | 2 | test-runner | S | -- |
| R4-05 | Verify writer wiring tests pass against current implementation | 4 | 2 | test-runner | S | -- |
| **Recommendation 5: Continuous Retraining Schedule** |
| R5-01 | Create Celery task `trigger_retraining_cycle` wrapping `RetrainOrchestrator` | 5 | 4 | backend-developer | M | R3-01 |
| R5-02 | Add 4 Celery beat schedule entries for retraining | 5 | 4 | backend-developer | M | R5-01 |
| R5-03 | Wire `DriftDetector` into live `TradingLoop` with automatic retrain trigger | 5 | 4 | backend-developer | M | R5-01 |
| R5-04 | Add Prometheus metrics for retrain events | 5 | 4 | backend-developer | S | R5-01 |
| R5-05 | Add Grafana dashboard panel for retraining status | 5 | 4 | backend-developer | S | R5-04 |
| R5-06 | Write integration tests for retrain Celery tasks | 5 | 4 | test-runner | M | R5-01 |
| **Quality Gate** |
| QG-01 | Full code review of all changes | all | 5 | code-reviewer | M | all |
| QG-02 | Run full test suite and fix regressions | all | 5 | test-runner | M | QG-01 |
| QG-03 | Update `development/context.md` and all CLAUDE.md files | all | 5 | context-manager | M | QG-02 |

**Total: 36 tasks** (within the 18-36 sweet spot)

---

## Dependency Graph

```
Phase 1: Infrastructure (R1-01 to R1-09)
  R1-01 (.env)
    └── R1-02 (docker compose up)
         ├── R1-03 (alembic upgrade head)
         │    ├── R1-04 (seed pairs)
         │    │    ├── R1-05 (health checks)
         │    │    │    ├── R1-06 (Grafana/Prometheus)
         │    │    │    └── R1-07 (backfill history)  ← LONG RUNNING
         │    │    └── R1-08 (provision agents) → R1-09 (smoke test)
         │    ├── R2-01 (grant_capability fix)  ← Phase 2 can start
         │    └── R2-04 (audit log table)       ← Phase 2 can start
         └── R2-03 (Redis requirepass)

Phase 2: Security + Quality (R2-01..R2-10, R4-01..R4-05)
  Independent cluster (no infra dependency):
    R2-02, R2-05, R2-06, R2-07, R2-08
    R4-01, R4-02, R4-03, R4-04, R4-05
  Infra-dependent:
    R2-01 ← R1-03
    R2-03 ← R1-02
    R2-04 ← R1-03
  Gate:
    R2-09 (security audit) ← R2-01..R2-08
    R2-10 (regression tests) ← R2-01..R2-08

Phase 3: Training Pipeline (R3-01..R3-06)
  R3-01 ← R1-07 (needs historical data)
    ├── R3-02 (validate accuracy)
    ├── R3-03 (switcher demo)
    ├── R3-04 (walk-forward)
    └── R3-05 (backtest comparison)
         └── R3-06 (record baseline)

Phase 4: Continuous Retraining (R5-01..R5-06)
  R5-01 ← R3-01 (needs at least one trained model)
    ├── R5-02 (beat schedule)
    ├── R5-03 (drift detector wiring)
    ├── R5-04 (metrics) → R5-05 (dashboard)
    └── R5-06 (tests)

Phase 5: Quality Gate (QG-01..QG-03)
  QG-01 ← all tasks complete
    └── QG-02 ← QG-01
         └── QG-03 ← QG-02
```

---

## Detailed Implementation Steps

### Recommendation 1: Start Docker Infrastructure Immediately

**Goal:** All 10 Docker services running, healthy, with data loaded and agents provisioned.

**Why this is P0:** Every other recommendation depends on running infrastructure. Training, security testing with Redis auth, and retraining all require a live platform.

#### R1-01: Create `.env` from `.env.example` (Agent: `backend-developer`, Complexity: S)

- **Action:** Copy `.env.example` to `.env`. Generate secure values for:
  - `POSTGRES_PASSWORD` -- random 32-char string
  - `JWT_SECRET` -- `python -c "import secrets; print(secrets.token_urlsafe(64))"`
  - `GRAFANA_ADMIN_PASSWORD` -- random 16-char string
- **Files:** `.env` (new, gitignored), `.env.example` (reference)
- **Dependencies:** None
- **Risk:** Low -- template is complete; just needs value generation
- **Acceptance:** `.env` file exists with all required vars populated; no placeholder values remain

#### R1-02: Start Docker Compose Services (Agent: `deploy-checker`, Complexity: S)

- **Action:** Run `docker compose up -d`. Wait for health checks to pass on all services.
- **Commands:**
  ```bash
  docker compose up -d
  docker compose ps  # all services should show "healthy"
  ```
- **Files:** `docker-compose.yml` (read-only reference)
- **Dependencies:** R1-01
- **Risk:** Medium -- Docker resource requirements (~8 CPU, ~10 GB RAM) may exceed development machine. Dockerfiles must exist and build successfully.
- **Verification:** `docker compose ps` shows healthy status for: `timescaledb`, `redis`, `api`, `ingestion`, `celery`, `celery-beat`, `pgadmin`, `prometheus`, `grafana`
- **Acceptance:** All 9 default-profile services running and healthy

#### R1-03: Apply Alembic Migrations (Agent: `migration-helper`, Complexity: S)

- **Action:** Run `alembic upgrade head` to apply all migrations through 019.
- **Commands:**
  ```bash
  alembic upgrade head
  alembic current  # should show 019
  ```
- **Files:** `alembic/versions/` (19 migration files)
- **Dependencies:** R1-02 (TimescaleDB must be running)
- **Risk:** Low -- migrations 018/019 are additive only (no destructive ops). Validated safe by code review.
- **Acceptance:** `alembic current` shows head at revision 019; all tables exist including `agent_api_calls`, `agent_strategy_signals`, and feedback lifecycle columns

#### R1-04: Seed Exchange Pairs (Agent: `backend-developer`, Complexity: S)

- **Action:** Run `python scripts/seed_pairs.py` to seed 600+ USDT pairs from Binance.
- **Dependencies:** R1-03
- **Risk:** Low -- script is idempotent
- **Acceptance:** `SELECT count(*) FROM exchange_pairs WHERE quote_asset = 'USDT'` returns 600+

#### R1-05: Verify All Services Healthy (Agent: `deploy-checker`, Complexity: S)

- **Action:** Run comprehensive health verification:
  ```bash
  curl http://localhost:8000/health               # API health
  curl http://localhost:8000/api/v1/market/prices  # Price data flowing
  redis-cli -h localhost ping                      # Redis responsive
  celery -A src.tasks.celery_app inspect ping      # Celery workers alive
  ```
- **Dependencies:** R1-04
- **Risk:** Low
- **Acceptance:** All 4 checks pass; API returns 200 with `{"status": "healthy"}`

#### R1-06: Import Grafana Dashboards and Verify Prometheus (Agent: `deploy-checker`, Complexity: S)

- **Action:** Verify Grafana auto-provisioning loaded all 6 dashboards from `monitoring/dashboards/`. Verify Prometheus is scraping both `:8000/metrics` and agent metrics.
- **Commands:**
  ```bash
  curl http://localhost:3001/api/dashboards  # Grafana dashboard list (port 3001 maps to 3000)
  curl http://localhost:9090/api/v1/targets  # Prometheus scrape targets
  ```
- **Dependencies:** R1-05
- **Risk:** Low -- dashboards are auto-provisioned via volume mounts
- **Acceptance:** 6 dashboards visible in Grafana; Prometheus shows 2+ scrape targets with status "up"

#### R1-07: Backfill Historical Candle Data (Agent: `backend-developer`, Complexity: L)

- **Action:** Run the backfill script for 12+ months of 1h candle data for top trading pairs.
  ```bash
  python scripts/backfill_history.py \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
    --interval 1h \
    --start 2024-01-01
  ```
- **Files:** `scripts/backfill_history.py`
- **Dependencies:** R1-05 (services healthy)
- **Risk:** Medium -- takes 10-30 minutes depending on Binance API rate limits. Script supports `--resume` for interruption recovery.
- **Acceptance:** Data coverage >= 95% for all 5 symbols across Jan 2024 to present. Validated via:
  ```bash
  python -m agent.strategies.rl.data_prep \
    --base-url http://localhost:8000 \
    --assets BTCUSDT ETHUSDT SOLUSDT \
    --min-coverage 95
  ```

#### R1-08: Provision Agent Accounts (Agent: `e2e-tester`, Complexity: M)

- **Action:** Run the provisioning script to create 5 trading agents:
  ```bash
  python scripts/e2e_provision_agents.py
  ```
  Then configure `agent/.env` with the returned API keys.
- **Files:** `scripts/e2e_provision_agents.py`, `agent/.env` (new from `agent/.env.example`)
- **Dependencies:** R1-04
- **Risk:** Low -- script is designed for this purpose
- **Acceptance:** 5 agents exist in the database; `agent/.env` populated with valid `PLATFORM_API_KEY` and `PLATFORM_API_SECRET`

#### R1-09: Run Smoke Test (Agent: `e2e-tester`, Complexity: S)

- **Action:** Run the 10-step connectivity validation:
  ```bash
  python -m agent.main smoke
  ```
- **Dependencies:** R1-08
- **Risk:** Low -- smoke test is LLM-free; validates SDK connectivity, order execution, and health endpoints
- **Acceptance:** All 10 steps pass with `status: pass`

---

### Recommendation 2: Fix the 7 HIGH Security Issues

**Goal:** Close all known HIGH-severity security issues before allowing any shared or multi-user access.

**Why this is P1:** These are exploitable in a multi-user environment. The permission escalation (HIGH-1) is the most critical -- any caller can make any agent an ADMIN.

#### R2-01: Add ADMIN Role Check to `grant_capability` and `set_role` (Agent: `security-reviewer`, Complexity: M)

- **Action:** In `agent/permissions/capabilities.py`, modify `grant_capability()` (line 450) and `set_role()` to verify the `granted_by` account has `AgentRole.ADMIN` before performing the mutation.
- **File:** `agent/permissions/capabilities.py`
- **Current code (line 450-484):**
  ```python
  async def grant_capability(self, agent_id, capability, granted_by):
      # Currently: validates UUIDs, upserts capability, invalidates cache
      # Missing: NO check that granted_by is an ADMIN
  ```
- **Fix:**
  ```python
  async def grant_capability(self, agent_id, capability, granted_by):
      # Step 1: Validate UUIDs (existing)
      # Step 2: NEW -- check grantor is ADMIN
      grantor_role = await self.get_role(granted_by)
      if ROLE_HIERARCHY.get(grantor_role, 0) < ROLE_HIERARCHY[AgentRole.ADMIN]:
          raise PermissionDenied(
              agent_id=granted_by,
              action="grant_capability",
              reason=f"Grantor {granted_by} is {grantor_role.value}, not ADMIN",
          )
      # Step 3: Proceed with upsert (existing)
  ```
- **Apply same pattern to `set_role()` and `revoke_capability()`.**
- **Dependencies:** R1-03 (DB must be running to test)
- **Risk:** Medium -- must ensure the check does not break legitimate admin flows. Must handle case where `granted_by` is not in the agents table (could be an account UUID).
- **Acceptance:** Calling `grant_capability()` with a non-ADMIN grantor raises `PermissionDenied`. Existing ADMIN flows still work.

#### R2-02: Track and Await `ensure_future` Tasks in `BudgetManager` (Agent: `security-reviewer`, Complexity: M)

- **Action:** In `agent/permissions/budget.py`, replace fire-and-forget `asyncio.ensure_future()` calls (lines 902, 986) with tracked futures that are awaited on shutdown.
- **File:** `agent/permissions/budget.py`
- **Fix:**
  1. Add `self._pending_persists: set[asyncio.Task] = set()` to `__init__`.
  2. Replace `asyncio.ensure_future(self._maybe_persist(agent_id))` with:
     ```python
     task = asyncio.create_task(self._maybe_persist(agent_id))
     self._pending_persists.add(task)
     task.add_done_callback(self._pending_persists.discard)
     ```
  3. Add `async def close(self)` method:
     ```python
     async def close(self) -> None:
         if self._pending_persists:
             await asyncio.gather(*self._pending_persists, return_exceptions=True)
     ```
  4. Wire `close()` into `AgentServer._shutdown()`.
- **Dependencies:** None (pure code change)
- **Risk:** Low -- only affects shutdown path; existing runtime behavior unchanged
- **Acceptance:** No pending persistence tasks are cancelled on shutdown. New test verifies `close()` awaits all pending tasks.

#### R2-03: Enable Redis `requirepass` and Bind to Docker Internal Network (Agent: `security-reviewer`, Complexity: M)

- **Action:** Add password authentication to Redis in Docker to prevent unauthenticated writes to the permissions cache.
- **Files:** `docker-compose.yml`, `.env.example`, `.env`
- **Fix:**
  1. Add `REDIS_PASSWORD=<secure_random>` to `.env.example` and `.env`.
  2. Update Redis service command in `docker-compose.yml`:
     ```yaml
     command: >
       redis-server
       --requirepass ${REDIS_PASSWORD}
       --appendonly yes
       ...
     ```
  3. Update `REDIS_URL` format: `redis://:${REDIS_PASSWORD}@redis:6379/0`
  4. Verify Redis `ports` only expose to `internal` network (currently `"6379:6379"` -- consider removing host binding or restricting to `127.0.0.1:6379:6379`).
- **Dependencies:** R1-02 (Docker must be running to test)
- **Risk:** Medium -- all services connecting to Redis must use the updated URL with password. `CELERY_BROKER_URL` defaults to `REDIS_URL` which will pick up the change automatically. Must verify price ingestion, API server, and Celery workers all reconnect successfully.
- **Acceptance:** `redis-cli` without password fails; all services reconnect with authenticated URL; permissions cache writes require auth.

#### R2-04: Persist "Allow" Audit Events to `agent_audit_log` Table (Agent: `security-reviewer`, Complexity: L)

- **Action:** Create a new `agent_audit_log` table and persist both "allow" and "deny" permission check outcomes.
- **Files:**
  - `src/database/models.py` -- add `AgentAuditLog` model
  - `alembic/versions/020_add_agent_audit_log.py` -- new migration
  - `src/database/repositories/agent_audit_log_repo.py` -- new repository
  - `agent/permissions/enforcement.py` -- modify to persist allow events
- **Model fields:** `id` (UUID PK), `agent_id`, `action`, `outcome` ("allow"/"deny"), `reason` (nullable), `trade_value` (nullable Decimal), `metadata` (JSONB), `created_at`
- **Fix in `enforcement.py`:**
  1. After a successful `check()`, buffer an "allow" audit record (same batching pattern as deny events).
  2. Flush both allow and deny events in the same periodic flush cycle.
  3. Consider a configurable `audit_allow_events: bool = True` flag for performance opt-out.
- **Dependencies:** R1-03 (DB must be running for migration)
- **Risk:** Medium -- "allow" events are much higher volume than "deny" events. Must use the existing batch-flush pattern (100 entries or 30 seconds) to avoid write amplification. Consider sampling if volume is too high.
- **Acceptance:** After running a trade workflow, both "allow" and "deny" audit records appear in `agent_audit_log`. Migration is safe and reversible.

#### R2-05: Add SHA-256 Checksum Verification Before `PPO.load()` (Agent: `security-reviewer`, Complexity: M)

- **Action:** Enforce `verify_checksum()` before every `PPO.load()` call.
- **Files:**
  - `agent/strategies/rl/runner.py:281` -- `model = PPO.load(model_path)`
  - `agent/strategies/rl/deploy.py:547` -- `self._model = PPO.load(self._model_path)`
  - `agent/strategies/rl/evaluate.py:402` -- `models[label] = PPO.load(str(path))`
  - `agent/strategies/ensemble/run.py:665` -- `model = PPO.load(model_path_str)`
- **Fix:** Before each `PPO.load()`, insert:
  ```python
  from agent.strategies.checksum import verify_checksum, SecurityError
  verify_checksum(model_path)  # raises SecurityError on mismatch
  ```
  The `verify_checksum()` function already exists in `agent/strategies/checksum.py` and currently only warns on missing sidecar. Change the behavior: **missing sidecar = error for production loads, warning for development**. Add a `strict: bool = True` parameter.
- **Dependencies:** None (pure code change)
- **Risk:** Low -- checksum utility already built; just needs enforcement at all load sites
- **Acceptance:** Loading a model without a `.sha256` sidecar file raises `SecurityError` in strict mode. Loading a model with a tampered checksum raises `SecurityError`. All 4 load sites are protected.

#### R2-06: Add Checksum Verification Before `joblib.load()` (Agent: `security-reviewer`, Complexity: M)

- **Action:** Enforce `verify_checksum()` before the `joblib.load()` call in the regime classifier.
- **File:** `agent/strategies/regime/classifier.py:406`
- **Current code:** `payload = joblib.load(path)`
- **Fix:**
  ```python
  from agent.strategies.checksum import verify_checksum
  verify_checksum(path)
  payload = joblib.load(path)
  # Post-load structure check: verify payload is a dict with expected keys
  if not isinstance(payload, dict) or "classifier" not in payload:
      raise SecurityError(f"Unexpected payload structure in {path}")
  ```
- **Dependencies:** None
- **Risk:** Low -- same pattern as R2-05
- **Acceptance:** Loading a regime classifier model without checksum or with tampered checksum raises `SecurityError`. Payload structure is validated after load.

#### R2-07: Audit Remaining `--api-key` CLI Arg Exposure (Agent: `security-reviewer`, Complexity: S)

- **Action:** Grep the entire codebase for `--api-key` or `--api_key` CLI arguments and verify none remain. The C-level report says this was "partially fixed."
- **Commands:**
  ```bash
  grep -rn "\-\-api.key\|argparse.*api.key\|add_argument.*api.key" agent/ src/ scripts/
  ```
- **Fix:** Any remaining instances should read from `agent/.env` via `AgentConfig` (pydantic-settings).
- **Dependencies:** None
- **Risk:** Low -- audit task
- **Acceptance:** Zero occurrences of `--api-key` or `--api_key` CLI arguments in any Python file

#### R2-08: Fix Remaining `float(Decimal)` Casts (Agent: `code-reviewer`, Complexity: S)

- **Action:** Fix all `float(Decimal(...))` casts found in the agent package. Current instances (from grep):
  - `agent/server_handlers.py:210` -- `float(c.close)` for SMA calculation
  - `agent/trading/ab_testing.py:921` -- `float(r.outcome_pnl)` for outcome list
  - `agent/trading/journal.py:844` -- `float(r.outcome_pnl)` for journal dict
  - `agent/strategies/ensemble/attribution.py:309` -- `float(row.pnl_sum)`
  - `agent/strategies/rl/deploy.py:235,397,617,625,856` -- multiple `float(prices.get(...))`
  - `agent/strategies/risk/middleware.py:745` -- `float(max(Decimal(...)))`
- **Fix pattern:** Use `Decimal` arithmetic throughout, or only convert to float at the JSON serialization boundary. For numpy/SB3 interop in `rl/deploy.py`, the `float()` conversion is acceptable since the RL model requires numpy arrays (document with inline comment).
- **Dependencies:** None
- **Risk:** Low -- mechanical fix; ensure `Decimal` arithmetic produces identical results
- **Acceptance:** `grep -rn "float(.*Decimal\|float(.*\.close\|float(.*\.pnl\|float(.*\.price" agent/` returns only documented exceptions (RL/numpy interop).

#### R2-09: Security Audit of All Fixes (Agent: `security-auditor`, Complexity: M)

- **Action:** Read-only security audit to verify all 7 HIGH issues are properly resolved.
- **Dependencies:** R2-01 through R2-08
- **Risk:** Low -- read-only audit
- **Acceptance:** Security auditor report shows 0 CRITICAL, 0 HIGH remaining

#### R2-10: Write Regression Tests for Security Fixes (Agent: `test-runner`, Complexity: M)

- **Action:** Write targeted regression tests for each security fix:
  - Test non-ADMIN cannot call `grant_capability()` (R2-01)
  - Test `BudgetManager.close()` awaits pending persists (R2-02)
  - Test `verify_checksum()` blocks load on mismatch (R2-05, R2-06)
  - Test audit log persists both allow and deny events (R2-04)
- **Files:** `agent/tests/test_security_regressions.py` (new)
- **Dependencies:** R2-01 through R2-08
- **Risk:** Low
- **Acceptance:** All regression tests pass; new file has 15+ test functions covering all 7 fixed issues

---

### Recommendation 3: Train and Validate One Strategy End-to-End

**Goal:** Establish baseline performance metrics by training and validating the regime classifier -- the fastest strategy to train.

**Why regime first:** No RL training needed (XGBoost trains in < 2 minutes). Provides the regime signal for the ensemble. Validates the full observe-decide-execute pipeline.

#### R3-01: Train Regime Classifier (Agent: `ml-engineer`, Complexity: L)

- **Action:** Train the XGBoost regime classifier on 12 months of BTC 1h candle data:
  ```bash
  python -m agent.strategies.regime.classifier \
    --train \
    --data-url http://localhost:8000
  ```
- **Files:** `agent/strategies/regime/classifier.py`, output to `agent/strategies/regime/models/regime_classifier.joblib`
- **Dependencies:** R1-07 (historical data must be loaded)
- **Risk:** Medium -- depends on data quality and coverage. XGBoost may not install cleanly on all platforms (falls back to RandomForest).
- **Post-training:** Immediately generate checksum: `python -c "from agent.strategies.checksum import save_checksum; save_checksum('agent/strategies/regime/models/regime_classifier.joblib')"`
- **Acceptance:** Model file saved to disk with `.sha256` sidecar. Training output shows accuracy metrics.

#### R3-02: Validate Classifier Accuracy >= 70% (Agent: `ml-engineer`, Complexity: S)

- **Action:** Check training output for:
  - Overall accuracy >= 70% on temporal test split
  - Confusion matrix shows all 4 regimes are detected
  - No single regime has recall < 40%
- **Dependencies:** R3-01
- **Risk:** Medium -- if accuracy < 70%, may need to adjust features or try RandomForest. The `volume_ratio` feature added in Phase 1 should help.
- **Acceptance:** Accuracy >= 70% on held-out test data; confusion matrix logged

#### R3-03: Run Regime Switcher Demo (Agent: `ml-engineer`, Complexity: S)

- **Action:**
  ```bash
  python -m agent.strategies.regime.switcher --demo --candles 300
  ```
  Verify the switcher correctly transitions between regimes with cooldown enforcement.
- **Dependencies:** R3-01
- **Risk:** Low -- demo uses synthetic data augmented with real model predictions
- **Acceptance:** Demo completes; output shows regime transitions with confidence scores and cooldown enforcement

#### R3-04: Run Walk-Forward Validation (Agent: `ml-engineer`, Complexity: L)

- **Action:**
  ```bash
  python -m agent.strategies.walk_forward --strategy regime
  ```
  This runs rolling walk-forward validation with 6-month train / 1-month test windows.
- **Files:** `agent/strategies/walk_forward.py`
- **Dependencies:** R3-01 (trained model), R1-07 (sufficient historical data for rolling windows)
- **Risk:** High -- walk-forward requires enough data for multiple train/test windows. If only 12 months of data, we get ~6 windows. WFE < 50% means the strategy is overfit.
- **Acceptance:** WFE (Walk-Forward Efficiency) >= 50%. If WFE < 50%, the strategy needs retuning before deployment. Report saved to `agent/strategies/walk_forward_results/`.

#### R3-05: Run Backtest Comparison (Agent: `ml-engineer`, Complexity: L)

- **Action:**
  ```bash
  python -m agent.strategies.regime.validate \
    --base-url http://localhost:8000 \
    --months 3
  ```
  Compare regime-adaptive strategy vs static MACD vs buy-and-hold BTC.
- **Dependencies:** R3-01
- **Risk:** Medium -- backtest engine must be working E2E. Historical battle mode must not return 500 errors (noted as a past issue).
- **Acceptance:** Regime-adaptive strategy outperforms at least one baseline (static MACD or buy-and-hold) on Sharpe ratio

#### R3-06: Record Baseline Performance Metrics (Agent: `ml-engineer`, Complexity: S)

- **Action:** Document the following metrics from R3-04 and R3-05:
  - Sharpe ratio (target >= 1.0)
  - Max drawdown (target <= 8%)
  - Win rate (target >= 55%)
  - Profit factor (target >= 1.3)
  - WFE score
  - Regime detection accuracy
- **Output:** Write results to `agent/reports/regime-baseline-YYYYMMDD.json`
- **Dependencies:** R3-04, R3-05
- **Risk:** Low -- documentation task
- **Acceptance:** Baseline report exists with all metrics. This becomes the reference point for measuring improvement.

---

### Recommendation 4: Fix Remaining Test and Code Quality Issues

**Goal:** Ensure all tests exercise real code, fix precision violations, and resolve outstanding performance issues.

**Note:** The C-level report lists 3 sub-issues. Investigation reveals 2 of 3 are already fixed (Redis glob bug and phantom writer tests). The remaining work focuses on `float(Decimal)` casts and the 5 MEDIUM perf issues.

#### R4-01: Fix `float(c.close)` in `server_handlers.py` (Agent: `backend-developer`, Complexity: S)

- **Action:** In `agent/server_handlers.py:210`, replace `float(c.close)` with `Decimal` arithmetic:
  ```python
  # Before:
  closes = [float(c.close) for c in candles]
  sma_20 = sum(closes[-20:]) / min(20, len(closes))

  # After:
  closes = [Decimal(str(c.close)) if not isinstance(c.close, Decimal) else c.close for c in candles]
  sma_20 = sum(closes[-20:]) / Decimal(str(min(20, len(closes))))
  ```
- **File:** `agent/server_handlers.py`
- **Dependencies:** None
- **Risk:** Low
- **Acceptance:** No `float()` calls on financial values in `server_handlers.py`

#### R4-02: Audit and Fix All `float(Decimal)` Casts (Agent: `code-reviewer`, Complexity: M)

- **Action:** Same as R2-08 (merged for tracking; agent overlap is intentional -- code-reviewer audits, backend-developer fixes).
- **Dependencies:** None
- **Acceptance:** Same as R2-08

#### R4-03: Fix 5 MEDIUM Performance Issues (Agent: `perf-checker`, Complexity: M)

- **Action:** Address the 5 MEDIUM perf findings from the perf-checker memory:
  1. `agent/strategies/regime/switcher.py:194` -- Cache indicator recomputation on last candle timestamp
  2. `agent/strategies/ensemble/run.py:1172` -- Replace sequential candle fetch with `asyncio.gather`
  3. `agent/strategies/ensemble/run.py:384` -- Replace `_step_history` list with `deque(maxlen=500)`
  4. `agent/strategies/regime/switcher.py:153` -- Replace `regime_history` list with `deque(maxlen=500)`
  5. `agent/strategies/evolutionary/evolve.py:231` -- Fix mutable function attribute for cross-run state contamination
- **Files:** Listed above
- **Dependencies:** None
- **Risk:** Low -- each fix is isolated and mechanical
- **Acceptance:** perf-checker re-audit shows 0 MEDIUM findings remaining in these files

#### R4-04: Verify Redis Glob Bug Fix (Agent: `test-runner`, Complexity: S)

- **Action:** Run the `test_redis_memory_cache.py` test file to confirm the glob bug fix is working:
  ```bash
  pytest agent/tests/test_redis_memory_cache.py -v
  ```
  Verify the `TestGetCached` class tests pass (4 tests verifying exact key construction).
- **Dependencies:** None
- **Risk:** Low -- verification only
- **Acceptance:** All 4 `TestGetCached` tests pass

#### R4-05: Verify Writer Wiring Tests Pass (Agent: `test-runner`, Complexity: S)

- **Action:** Run the `test_server_writer_wiring.py` test file to confirm the writer parameter is properly wired:
  ```bash
  pytest agent/tests/test_server_writer_wiring.py -v
  ```
  All 20 tests should pass (10 success path, 10 failure path).
- **Dependencies:** None
- **Risk:** Low -- verification only
- **Acceptance:** All 20 `test_server_writer_wiring.py` tests pass

---

### Recommendation 5: Implement Continuous Retraining Schedule

**Goal:** Wire the existing `RetrainOrchestrator` and `DriftDetector` into the Celery beat schedule so strategies automatically retrain on a fixed cadence and in response to performance drift.

**Why:** Strategy performance degrades as market regimes shift. The `RetrainOrchestrator` and `DriftDetector` code is built (Task 28/31 of master plan) but not scheduled.

#### R5-01: Create Celery Task Wrapping `RetrainOrchestrator` (Agent: `backend-developer`, Complexity: M)

- **Action:** Create a new Celery task that bridges the sync Celery boundary to the async `RetrainOrchestrator.run_scheduled_cycle()`.
- **File:** `src/tasks/retrain_tasks.py` (new)
- **Implementation:**
  ```python
  """Celery tasks for automated ML strategy retraining.

  Wraps :class:`agent.strategies.retrain.RetrainOrchestrator` for
  scheduled execution via Celery Beat.
  """
  import asyncio
  from src.tasks.celery_app import app

  @app.task(
      name="src.tasks.retrain_tasks.run_retraining_cycle",
      soft_time_limit=3600,  # 1 hour
      time_limit=3900,       # 1 hour 5 min hard limit
  )
  def run_retraining_cycle():
      """Execute one retraining cycle for all scheduled strategies."""
      return asyncio.run(_async_retrain())

  async def _async_retrain():
      from agent.strategies.retrain import RetrainOrchestrator, RetrainConfig  # noqa: PLC0415
      # ... lazy imports, create orchestrator, call run_scheduled_cycle()
  ```
- **Register in `celery_app.py`:** Add `"src.tasks.retrain_tasks"` to the `include` list.
- **Dependencies:** R3-01 (at least one trained model must exist)
- **Risk:** Medium -- retraining tasks are long-running (PPO can take hours). Must set appropriate time limits. Consider running in a separate Celery queue with its own concurrency limit.
- **Acceptance:** `run_retraining_cycle.delay()` executes successfully; returns JSON summary with results per strategy

#### R5-02: Add 4 Celery Beat Schedule Entries (Agent: `backend-developer`, Complexity: M)

- **Action:** Add retraining schedule entries to `celery_app.py` beat schedule matching the `RetrainOrchestrator` design:
  ```python
  "retrain-ensemble-weights": {
      "task": "src.tasks.retrain_tasks.retrain_ensemble",
      "schedule": timedelta(hours=8),
  },
  "retrain-regime-classifier": {
      "task": "src.tasks.retrain_tasks.retrain_regime",
      "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),  # Weekly
  },
  "retrain-genome-population": {
      "task": "src.tasks.retrain_tasks.retrain_genome",
      "schedule": crontab(hour=5, minute=0, day_of_week="wednesday"),  # Weekly
  },
  "retrain-rl-models": {
      "task": "src.tasks.retrain_tasks.retrain_rl",
      "schedule": crontab(hour=3, minute=0, day_of_month="1"),  # Monthly
  },
  ```
- **File:** `src/tasks/celery_app.py`
- **Dependencies:** R5-01
- **Risk:** Medium -- must stagger schedules to avoid concurrent CPU-intensive training. Genome evolution and RL training should never overlap.
- **Acceptance:** `celery -A src.tasks.celery_app inspect scheduled` shows all 4 new beat entries

#### R5-03: Wire `DriftDetector` into Live `TradingLoop` (Agent: `backend-developer`, Complexity: M)

- **Action:** The `DriftDetector` is already integrated into `TradingLoop._observe()` (per Task 31 of master plan). Verify it triggers `RetrainOrchestrator` when drift is detected.
- **Files:** `agent/trading/loop.py`, `agent/strategies/drift.py`, `agent/strategies/retrain.py`
- **Fix:** Ensure the drift detection callback in `TradingLoop` calls `retrain_orchestrator.trigger_drift_retrain(strategy_name)` when `DriftDetector.detect()` returns a drift event. If not wired, add the callback.
- **Dependencies:** R5-01
- **Risk:** Medium -- drift-triggered retraining must not overwhelm the system. Add a cooldown (minimum 1 hour between drift-triggered retrains per strategy).
- **Acceptance:** When drift is detected (simulated via test), a retrain task is enqueued. Cooldown prevents multiple retrains within 1 hour.

#### R5-04: Add Prometheus Metrics for Retrain Events (Agent: `backend-developer`, Complexity: S)

- **Action:** Add metrics to track retraining:
  ```python
  retrain_runs_total = Counter(
      "agent_retrain_runs_total",
      "Total retraining runs",
      ["strategy", "trigger"],  # trigger: scheduled, drift, manual
      registry=AGENT_REGISTRY,
  )
  retrain_duration_seconds = Histogram(
      "agent_retrain_duration_seconds",
      "Retraining duration",
      ["strategy"],
      registry=AGENT_REGISTRY,
  )
  retrain_deployed_total = Counter(
      "agent_retrain_deployed_total",
      "Models deployed after A/B gate",
      ["strategy"],
      registry=AGENT_REGISTRY,
  )
  ```
- **File:** `agent/metrics.py` (add to existing `AGENT_REGISTRY`)
- **Dependencies:** R5-01
- **Risk:** Low
- **Acceptance:** Metrics appear at `/metrics` endpoint after a retrain cycle

#### R5-05: Add Grafana Dashboard Panel for Retraining (Agent: `backend-developer`, Complexity: S)

- **Action:** Add a "Retraining" panel row to the existing agent strategy performance dashboard.
- **Panels:**
  - Retrain runs over time (by strategy and trigger type)
  - Retrain duration heatmap
  - Models deployed vs rejected (A/B gate pass rate)
- **File:** `monitoring/dashboards/` (update existing or create `retraining.json`)
- **Dependencies:** R5-04
- **Risk:** Low
- **Acceptance:** Dashboard visible in Grafana with live data after a retrain cycle

#### R5-06: Write Integration Tests for Retrain Tasks (Agent: `test-runner`, Complexity: M)

- **Action:** Write tests verifying:
  - Celery task wraps `RetrainOrchestrator` correctly
  - Beat schedule entries are registered
  - Drift-triggered retrain respects cooldown
  - Retrain results are logged to memory system
- **File:** `agent/tests/test_retrain_celery.py` (new)
- **Dependencies:** R5-01
- **Risk:** Low
- **Acceptance:** 10+ tests covering the Celery integration layer; all pass

---

### Quality Gate (Mandatory Final Phase)

#### QG-01: Full Code Review (Agent: `code-reviewer`)

- Run code-reviewer on all changed files
- Verify no new CRITICAL or WARNING violations introduced
- Check `float(Decimal)` casts are gone (except documented RL/numpy exceptions)

#### QG-02: Full Test Suite (Agent: `test-runner`)

- Run `pytest tests/unit/ agent/tests/ -v --tb=short`
- Fix any regressions
- Verify new tests are in line with `tests/CLAUDE.md` standards

#### QG-03: Update Context and CLAUDE.md Files (Agent: `context-manager`)

- Update `development/context.md` with completion of all 5 recommendations
- Update CLAUDE.md files for any modified modules
- Append to today's daily note
- Update C-level report security risk from "7 HIGH" to "0 HIGH"

---

## Parallel Execution Groups

### Group A (immediate, no dependencies)
- R1-01 (create .env)
- R2-02 (track ensure_future -- pure code)
- R2-05 (PPO checksum -- pure code)
- R2-06 (joblib checksum -- pure code)
- R2-07 (audit --api-key -- pure grep)
- R2-08 / R4-01 / R4-02 (float(Decimal) fixes -- pure code)
- R4-03 (perf fixes -- pure code)
- R4-04 (verify Redis fix -- run tests)
- R4-05 (verify writer fix -- run tests)

### Group B (after R1-02: Docker running)
- R1-03 (migrations)
- R2-03 (Redis requirepass)

### Group C (after R1-03: DB ready)
- R1-04 (seed pairs)
- R2-01 (grant_capability fix)
- R2-04 (audit log table + migration)

### Group D (after R1-04 + R1-05: platform healthy)
- R1-06 (Grafana/Prometheus)
- R1-07 (backfill history -- LONG)
- R1-08 (provision agents)
- R1-09 (smoke test)

### Group E (after all security fixes: R2-01..R2-08)
- R2-09 (security audit)
- R2-10 (regression tests)

### Group F (after R1-07: data loaded)
- R3-01 through R3-06 (training pipeline)

### Group G (after R3-01: model trained)
- R5-01 through R5-06 (retraining automation)

### Group H (after all tasks)
- QG-01, QG-02, QG-03 (quality gate)

---

## Risks and Mitigations

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Docker resource requirements exceed dev machine capacity (8 CPU, 10 GB RAM) | HIGH | MEDIUM | Use `docker-compose.dev.yml` with reduced limits; disable monitoring profile initially |
| Historical data backfill takes too long or hits Binance rate limits | MEDIUM | MEDIUM | Use `--resume` flag; start with 3 months for quick validation, expand to 12 months later |
| Regime classifier accuracy < 70% on held-out test data | MEDIUM | LOW | Fall back to RandomForest; add more features; increase training data window |
| Walk-forward validation WFE < 50% (strategy is overfit) | HIGH | MEDIUM | Re-tune hyperparameters; use more conservative training window; increase regularization |
| Redis `requirepass` breaks existing service connections | MEDIUM | MEDIUM | Test in dev first; update all connection strings in `.env` before restarting services |
| Retraining tasks consume too much CPU during live trading | MEDIUM | LOW | Run retrain tasks on a dedicated Celery queue with `--concurrency=1`; stagger schedules |
| Migration 020 (audit log) conflicts with existing schema | LOW | LOW | Use `migration-helper` agent to validate before applying |
| `float(Decimal)` fix in RL deploy breaks model inference | MEDIUM | LOW | RL models require numpy float arrays -- document exceptions with inline comments; only fix non-numpy paths |
| Security fixes break existing admin workflows | MEDIUM | LOW | Write regression tests BEFORE deploying fixes; test with real agent provisioning flow |

---

## Project-Specific Considerations

- **Agent scoping:** Retraining tasks must be agent-scoped. Each agent trains its own models; never share trained models between agents.
- **Decimal precision:** All monetary values in new audit log table must use `NUMERIC(20,8)`. Checksum verification does not involve monetary values.
- **Async patterns:** All new Celery tasks use the `asyncio.run()` bridge pattern. Retraining tasks use `asyncio.to_thread()` for blocking model I/O.
- **Migration safety:** The new `agent_audit_log` table (R2-04) is a simple CREATE TABLE -- no two-phase needed. Delegate to `migration-helper` for validation.
- **Frontend sync:** None of these recommendations change API response shapes. No TypeScript type updates needed.

---

## Success Criteria

- [ ] All 10 Docker services running and healthy
- [ ] Alembic migrations applied through 020 (including new audit log table)
- [ ] 600+ exchange pairs seeded; 12+ months historical data loaded
- [ ] 5 trading agents provisioned; smoke test passes
- [ ] 0 HIGH security issues remaining (down from 7)
- [ ] `grant_capability` requires ADMIN grantor
- [ ] Redis authenticated with `requirepass`
- [ ] Both "allow" and "deny" audit events persisted
- [ ] All model load paths enforce SHA-256 checksum verification
- [ ] 0 `float(Decimal)` casts on monetary values (except documented RL/numpy exceptions)
- [ ] Regime classifier trained with accuracy >= 70%
- [ ] Walk-forward validation WFE >= 50%
- [ ] Baseline performance metrics recorded
- [ ] 4 Celery beat tasks for automated retraining
- [ ] DriftDetector triggers retrain with cooldown enforcement
- [ ] Prometheus metrics track retrain events
- [ ] All tests pass (4,600+ existing + 25+ new)
- [ ] All CLAUDE.md files updated to reflect changes

---

## Estimated Timeline

| Phase | Duration | Parallelism | Notes |
|-------|----------|-------------|-------|
| Phase 1: Infrastructure | 1-2 days | Groups A+B+C+D | Backfill is the bottleneck (10-30 min) |
| Phase 2: Security + Quality | 2-3 days | Groups A+E (overlap with Phase 1) | Most security fixes are pure code changes |
| Phase 3: Training | 1-2 days | Group F | Training is fast (< 2 min for regime); walk-forward takes longer |
| Phase 4: Retraining | 1-2 days | Group G | Celery integration + testing |
| Phase 5: Quality Gate | 1 day | Group H | Sequential: review -> test -> context |
| **Total** | **5-8 days** | Heavy parallelism possible | Phase 1+2 overlap saves 2-3 days |

---

**Generated:** 2026-03-23
**Author:** planner agent
**Report source:** `development/C-level_reports/report-2026-03-23.md`
**Next review:** After Phase 1 completion
