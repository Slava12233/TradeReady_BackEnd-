---
type: task-list
title: "Code Review Tasks — Issue Tracker"
status: archived
phase: agentic-layer
tags:
  - task
  - agentic-layer
---

# Code Review Tasks — Issue Tracker

> **Created:** 2026-03-01
> **Linked to:** `codereviewplan.md`
> **Status Legend:** `[ ]` To Fix · `[~]` In Progress · `[x]` Fixed · `[-]` Won't Fix
> **Severity:** 🔴 CRITICAL · 🟠 HIGH · 🟡 MEDIUM · 🟢 LOW · ⚪ INFO

---

## Summary Dashboard

| Phase | Status | Issues Found | Critical | High | Medium | Low | Info | Fixed |
|-------|--------|-------------|----------|------|--------|-----|------|-------|
| A — Root Configs & Docker | ✅ Complete | 10 | 0 | 3 | 4 | 1 | 2 | 1 |
| B — Database Layer | ✅ Complete | 11 | 1 | 3 | 3 | 2 | 2 | 11 |
| C — Cache Layer | ✅ Complete | 13 | 0 | 3 | 5 | 2 | 3 | 0 |
| D — Utility Layer | ✅ Complete | 9 | 0 | 0 | 4 | 2 | 3 | 9 |
| E — Price Ingestion | ✅ Complete | 10 | 0 | 1 | 3 | 2 | 4 | 0 |
| F — Account Management | ✅ Complete | 13 | 1 | 3 | 4 | 3 | 2 | 13 |
| G — Order Engine | ✅ Complete | 16 | 1 | 3 | 6 | 3 | 3 | 0 |
| H — Risk Management | ✅ Complete | 14 | 0 | 3 | 5 | 3 | 3 | 0 |
| I — Portfolio Tracking | ✅ Complete | 19 | 0 | 2 | 8 | 6 | 3 | 0 |
| J — API Schemas | ✅ Complete | 15 | 0 | 3 | 6 | 3 | 3 | 0 |
| K — API Middleware | ✅ Complete | 13 | 0 | 2 | 5 | 2 | 4 | 0 |
| L — API Routes | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| M — WebSocket | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| N — Celery Tasks | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| O — Monitoring | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| P — App Entry & DI | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q — MCP Server | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| R — Python SDK | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S — Migrations | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| T — Scripts | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| U — Test Suite | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| V — Cross-Cutting | Not Started | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **TOTAL** | | **143** | **3** | **26** | **53** | **29** | **32** | **23** |

---

## Phase A — Root Configs & Docker

> **Files reviewed:** `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.env.example`, `Dockerfile`, `Dockerfile.ingestion`, `Dockerfile.celery`, `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.phase1.yml`, `prometheus.yml`, `alembic.ini`, `sdk/pyproject.toml`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][HIGH] A8-1: `timescaledb` image uses unpinned `latest-pg16` tag

**File:** `docker-compose.yml` line 16
**Category:** Code Quality / Reproducibility
**Description:** `timescale/timescaledb:latest-pg16` will resolve to a different image digest on each `docker pull` or `docker compose build --pull`. A TimescaleDB patch/minor version bump can silently break the schema or extension API between environments.
**Fix Applied:** Pinned to `timescale/timescaledb:2.17.2-pg16`.
**Effort:** Trivial
**Status:** Complete

---

### [HIGH] A8-2: `prometheus` image uses unpinned `latest` tag

**File:** `docker-compose.yml` line 209
**Category:** Code Quality / Reproducibility
**Description:** `prom/prometheus:latest` is unpinned. A major Prometheus release (e.g. v3.x) can introduce breaking config/query changes without warning.
**Suggested Fix:** Pin to a specific version, e.g. `prom/prometheus:v2.55.1`.
**Effort:** Trivial
**Status:** Complete

---

### [HIGH] A8-3: `grafana` image uses unpinned `latest` tag

**File:** `docker-compose.yml` line 238
**Category:** Code Quality / Reproducibility
**Description:** `grafana/grafana:latest` is unpinned. Dashboard JSON format and plugin APIs change across major versions.
**Suggested Fix:** Pin to a specific version, e.g. `grafana/grafana:11.4.0`.
**Effort:** Trivial
**Status:** Complete

---

### [MEDIUM] A8-4: `celery-beat` service missing `healthcheck`, resource limits, and `restart: unless-stopped`

**File:** `docker-compose.yml` lines 185–203
**Category:** Code Quality / Reliability
**Description:** `celery-beat` has no `healthcheck`, no `deploy.resources` limits, and no `restart: unless-stopped`. Unlike the worker it also lacks a restart policy. If beat crashes silently, no scheduled tasks (snapshots, cleanup, candle refresh) will fire.
**Suggested Fix:** Add `restart: unless-stopped`, `deploy.resources.limits` (e.g. `cpus: "0.5"`, `memory: 256M`), and a healthcheck that verifies the beat pidfile or uses a Python probe.
**Effort:** Small
**Status:** Complete

---

### [MEDIUM] A8-5: `ingestion` service has no `healthcheck`

**File:** `docker-compose.yml` lines 123–149
**Category:** Code Quality / Reliability
**Description:** The ingestion service has no `healthcheck`, so Docker cannot detect a crash-loop or a stale WS connection that stopped processing ticks. Other services that depend on fresh prices have no signal of ingestion failure.
**Suggested Fix:** Add a healthcheck that checks Redis for a recently-updated price key, e.g. `redis-cli HLEN prices | grep -E '^[1-9]'`, or expose a simple `/health` HTTP endpoint and probe it with `curl`.
**Effort:** Small
**Status:** Complete

---

### [MEDIUM] A8-6: `celery-beat` depends only on `celery`, not on healthy DB/Redis

**File:** `docker-compose.yml` line 198
**Category:** Correctness / Startup Ordering
**Description:** `celery-beat` declares `depends_on: [celery]` which means it starts after the celery *container starts*, but Redis and TimescaleDB could still be initializing. Beat tasks that run at startup (circuit breaker reset at 00:01) may fail trying to connect to Redis/DB.
**Suggested Fix:** Change `depends_on` to include `timescaledb: {condition: service_healthy}` and `redis: {condition: service_healthy}`, matching the pattern used by all other app services.
**Effort:** Trivial
**Status:** Complete

---

### [MEDIUM] A5-1: `Dockerfile` (API) has no `HEALTHCHECK` and runs as root

**File:** `Dockerfile` lines 1–28
**Category:** Security / Code Quality
**Description:** (1) No `HEALTHCHECK` directive — Docker cannot report the container as unhealthy independently of the compose healthcheck. (2) The process runs as root inside the container. Best practice is to add a non-root user.
**Suggested Fix:** Add `RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app` and `USER appuser`. Also consider `HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1`.
**Effort:** Small
**Status:** Complete

---

### [MEDIUM] A6-1: `Dockerfile.ingestion` has no `HEALTHCHECK`, no non-root user, and no `curl`

**File:** `Dockerfile.ingestion` lines 1–17
**Category:** Security / Code Quality
**Description:** Same as A5-1 — no HEALTHCHECK, no non-root user. Also `curl` is not installed, so any future probe that references it will fail.
**Suggested Fix:** Add non-root user, and since the ingestion service has no HTTP server, healthcheck should probe Redis via `redis-cli` or a Python script.
**Effort:** Small
**Status:** Complete

---

### [LOW] A13-1: SDK `pyproject.toml` line-length (100) inconsistent with main project (120)

**File:** `sdk/pyproject.toml` line 58
**Category:** Code Quality
**Description:** The main `pyproject.toml` sets `line-length = 120`; the SDK sets `line-length = 100`. This means ruff will report different violations depending on which config is active, creating inconsistency when the SDK is developed alongside the main repo.
**Suggested Fix:** Align SDK `line-length` to 120 to match the project standard.
**Effort:** Trivial
**Status:** Complete

---

### [INFO] A11-1: `prometheus.yml` scrapes `ingestion:9100` — endpoint does not exist

**File:** `prometheus.yml` lines 23–25
**Category:** Missing Feature / INFO
**Description:** The ingestion service runs a single Python process with no HTTP server on port 9100. This scrape target will perpetually fail with "connection refused", polluting Prometheus with error metrics. This is noted as a Phase 5 gap.
**Suggested Fix:** Either remove the `ingestion` scrape job until Phase 5 implements a metrics endpoint, or comment it out with a TODO.
**Effort:** Trivial
**Status:** Complete

---

### [INFO] A4-1: `.env.example` missing Celery broker/backend vars

**File:** `.env.example`
**Category:** Documentation
**Description:** Celery broker and result backend are implicitly derived from `REDIS_URL` in `src/tasks/celery_app.py`, but this is not documented in `.env.example`. A developer setting up the platform for the first time won't know they can override `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` separately.
**Suggested Fix:** Add commented-out entries: `# CELERY_BROKER_URL=redis://redis:6379/0` and `# CELERY_RESULT_BACKEND=redis://redis:6379/0` with a note that they default to REDIS_URL.
**Effort:** Trivial
**Status:** Complete

---

## Phase B — Database Layer

> **Files reviewed:** `src/database/session.py`, `src/database/models.py`, `src/database/repositories/__init__.py`, `src/database/repositories/account_repo.py`, `src/database/repositories/balance_repo.py`, `src/database/repositories/order_repo.py`, `src/database/repositories/trade_repo.py`, `src/database/repositories/tick_repo.py`, `src/database/repositories/snapshot_repo.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][CRITICAL] B2-1: All financial columns use `Mapped[float]` instead of `Mapped[Decimal]`

**File:** `src/database/models.py` lines 91–95, 161–174, 244, 333–340, 398–413, 500–522, 642–661, 732–749, 827–845
**Category:** Correctness / Type Safety
**Description:** Every numeric financial column in every model (`Tick.price`, `Tick.quantity`, `Balance.available`, `Balance.locked`, `Order.quantity`, `Order.price`, `Order.executed_price`, `Trade.price`, `Trade.quantity`, `Trade.quote_amount`, `Position.quantity`, `Position.avg_entry_price`, `PortfolioSnapshot.total_equity`, etc.) is annotated as `Mapped[float]`. The column type is correctly `Numeric(20,8)` in the DB, but the Python type hint tells mypy, IDE tooling, and any code reading these attributes that the values are `float`. SQLAlchemy actually returns `Decimal` at runtime, so the annotation is a lie. This will suppress type-checker warnings when float arithmetic is accidentally applied to these values in service code, defeating the entire protection layer.
**Suggested Fix:** Change all financial `Mapped[float]` annotations to `Mapped[Decimal]` and add `from decimal import Decimal` to the imports. Example: `price: Mapped[Decimal] = mapped_column(Numeric(20, 8), ...)`.
**Effort:** Small
**Status:** Complete

---

### [x][HIGH] B2-2: Missing `ondelete` on several Foreign Keys

**File:** `src/database/models.py` lines 483–487, 624–627, 629–633
**Category:** Correctness / Data Integrity
**Description:** Three FKs are missing `ondelete` directives:
1. `Order.session_id → trading_sessions.id` (line 486): no `ondelete`. PostgreSQL default is `NO ACTION`, so deleting a `TradingSession` will fail or leave dangling `session_id` values.
2. `Trade.order_id → orders.id` (line 624): no `ondelete`. Deleting an order (e.g. during account reset) would violate this FK unless trades are deleted first.
3. `Trade.session_id → trading_sessions.id` (line 631): same problem as Order.
The plan specifies cascade-delete behaviour; omitting `ondelete` can cause integrity errors during account reset operations.
**Suggested Fix:** Add `ondelete="SET NULL"` to `Order.session_id` (nullable FK, session deletion should orphan rather than cascade), and `ondelete="CASCADE"` to `Trade.order_id` and `Trade.session_id` to match the plan's cascade semantics.
**Effort:** Trivial
**Status:** Complete

---

### [x][HIGH] B7-1: `sum_daily_realized_pnl()` returns `float` instead of `Decimal`

**File:** `src/database/repositories/trade_repo.py` lines 372, 415–416
**Category:** Correctness / Type Safety
**Description:** The method signature declares `-> float` and the implementation does `return float(total)`. This converts a `Decimal` aggregate result from the database back to an imprecise `float`. The return value is used by the circuit breaker to evaluate daily loss limits — a precision error here could allow a loss-limit violation to pass undetected or falsely trip the circuit breaker.
**Suggested Fix:** Change the return type to `Decimal` and return `Decimal(str(total))` (or keep as `Decimal` from the DB result after confirming `sa_func.coalesce` returns `Decimal`).
**Effort:** Trivial
**Status:** Complete

---

### [x][HIGH] B8-1: `get_vwap()` returns `float` and uses `float()` conversion on Decimal values

**File:** `src/database/repositories/tick_repo.py` lines 299, 348–350
**Category:** Correctness / Type Safety
**Description:** `get_vwap()` is declared as `-> float | None` and performs `float(total_value) / float(total_qty)`. VWAP is consumed by the slippage calculator as a reference price for order execution. Converting `Decimal` database values to `float` for division introduces floating-point imprecision before a financial calculation. On values like BTC prices (~$50,000), this can produce errors in the fourth or fifth decimal place.
**Suggested Fix:** Change the return type to `Decimal | None` and use `Decimal` arithmetic: `return Decimal(str(total_value)) / Decimal(str(total_qty))`. Or better: `return total_value / total_qty` if `total_value` and `total_qty` are already `Decimal` from SQLAlchemy.
**Effort:** Trivial
**Status:** Complete

---

### [x][MEDIUM] B1-1: `close_db()` does not reset `_session_factory` to `None`

**File:** `src/database/session.py` lines 149–171
**Category:** Correctness / Resource Management
**Description:** `close_db()` resets `_engine = None` and `_asyncpg_pool = None`, but does not reset `_session_factory = None`. If `close_db()` is called (e.g. in tests or server restart) and then `init_db()` is called again, `get_session_factory()` will return the stale factory object which is bound to the already-disposed `AsyncEngine`. Any session created from it will raise `InterfaceError: connection was closed`.
**Suggested Fix:** Add `global _session_factory` and `_session_factory = None` to `close_db()`.
**Effort:** Trivial
**Status:** Complete

---

### [x][MEDIUM] B2-3: All repository files use `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/database/repositories/account_repo.py` line 28, `balance_repo.py` line 33, `order_repo.py` line 34, `trade_repo.py` line 30, `tick_repo.py` line 38, `snapshot_repo.py` line 29
**Category:** Code Quality / Logging Consistency
**Description:** All 6 repository files use `import logging` and `logger = logging.getLogger(__name__)`. The CLAUDE.md and cross-cutting concern V6 mandate `structlog.get_logger()` throughout the platform. Using `logging.getLogger` bypasses the structured JSON output pipeline and loses the context propagation (request_id, account_id binding) that structlog provides.
**Suggested Fix:** In each file, replace `import logging` with `import structlog` and `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`. The log call signatures remain compatible.
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] B5-1: `_get_or_create_zero()` calls `session.rollback()` which aborts the parent transaction

**File:** `src/database/repositories/balance_repo.py` lines 847–857
**Category:** Correctness / Atomicity
**Description:** In the race-condition handler of `_get_or_create_zero()`, `await self._session.rollback()` is called after an `IntegrityError` on the flush. This rolls back the **entire session**, including any balance updates already applied by the calling `atomic_execute_buy()` or `atomic_execute_sell()` method. This means a concurrent race on balance creation silently voids the trade settlement instead of cleanly recovering. The correct SQLAlchemy async pattern for handling partial-flush conflicts is to use a **savepoint** (`async with session.begin_nested()`) so only the inner INSERT is rolled back while the outer transaction continues.
**Suggested Fix:** Wrap the `session.add` + `session.flush` in `_get_or_create_zero()` inside `async with self._session.begin_nested():` to create a savepoint. On `IntegrityError`, only the savepoint is rolled back; the parent transaction remains intact.
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] B6-1: `count_open_by_account()` uses deferred local import

**File:** `src/database/repositories/order_repo.py` lines 514
**Category:** Code Quality
**Description:** `from sqlalchemy import func as sa_func` is placed inside the `count_open_by_account()` method body rather than at the module top. This is inconsistent with the rest of the file and with Python conventions. Local imports inside functions are only warranted to break circular import cycles; there is no such cycle here.
**Suggested Fix:** Move `from sqlalchemy import func as sa_func` to the module-level imports alongside `from sqlalchemy import select, update`.
**Effort:** Trivial
**Status:** Complete

---

### [x][LOW] B7-2: `get_daily_trades()` uses `time.max` — misses sub-microsecond edge case

**File:** `src/database/repositories/trade_repo.py` lines 339–341
**Category:** Correctness
**Description:** The daily range upper bound is `datetime.combine(day, time.max, tzinfo=timezone.utc)` where `time.max = time(23, 59, 59, 999999)`. PostgreSQL `TIMESTAMPTZ` has microsecond precision, so this correctly covers the entire day. However, the semantically cleaner and more explicit pattern used in time-series queries is a half-open interval: `created_at >= day_start AND created_at < next_day_start`. Using `<=` with `time.max` is fragile if the timestamp resolution ever changes (e.g. if a future migration adds nanosecond precision via an extension).
**Suggested Fix:** Replace `day_end = datetime.combine(day, time.max, tzinfo=timezone.utc)` and `Trade.created_at <= day_end` with `from datetime import timedelta; day_end = day_start + timedelta(days=1)` and `Trade.created_at < day_end`.
**Effort:** Trivial
**Status:** Complete

---

### [x][LOW] B3-1: `repositories/__init__.py` has no `__all__` exports

**File:** `src/database/repositories/__init__.py` (6 lines — just a docstring)
**Category:** Code Quality
**Description:** The `__init__.py` is a documentation stub with no imports or `__all__`. Consumers must import each repository with its full submodule path (e.g. `from src.database.repositories.account_repo import AccountRepository`). Defining `__all__` and re-exporting the repository classes makes the public API explicit and allows `from src.database.repositories import AccountRepository`.
**Suggested Fix:** Add imports and `__all__` for all 5 repository classes.
**Effort:** Trivial
**Status:** Complete

---

### [x][INFO] B2-4: `Trade` model has no `CHECK` constraint on `side`

**File:** `src/database/models.py` lines 674–678 (`__table_args__`)
**Category:** Data Integrity / INFO
**Description:** `Order` has `ck_orders_side` enforcing `side IN ('buy', 'sell')`, but the `Trade` model has no equivalent constraint. Since trades are always created from orders, this is unlikely to cause a bug in practice. However, direct DB inserts (e.g. from tests, scripts, or a future migration) could insert invalid `side` values into the `trades` table without error.
**Suggested Fix:** Add `CheckConstraint("side IN ('buy', 'sell')", name="ck_trades_side")` to `Trade.__table_args__`.
**Effort:** Trivial
**Status:** Complete

---

### [x][INFO] B2-5: `Order.session_id` FK behaviour on session deletion is undefined

**File:** `src/database/models.py` line 486
**Category:** Data Integrity / INFO
**Description:** `Order.session_id` is nullable and has no `ondelete` clause. PostgreSQL's default behaviour (`NO ACTION`) means that deleting a `TradingSession` row will fail if any `orders.session_id` references it. This will cause account-reset operations to fail unless orders are explicitly unlinked before deleting sessions. The intent (SET NULL vs. CASCADE vs. RESTRICT) is not documented.
**Suggested Fix:** Decide the intended behaviour and add the appropriate `ondelete` clause. Most likely `ondelete="SET NULL"` since the FK is nullable and an order's session context becoming orphaned is non-critical.
**Status:** Complete

---

## Phase C — Cache Layer

> **Files reviewed:** `src/cache/redis_client.py`, `src/cache/price_cache.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][HIGH] C2-1: `update_ticker()` TOCTOU race — HGETALL + HSET are not atomic

**File:** `src/cache/price_cache.py` lines 166–198
**Category:** Correctness / Concurrency
**Description:** `update_ticker()` reads the existing ticker with `HGETALL` on line 166, computes new high/low/volume in Python, then writes back with `HSET` on line 198. These are two separate Redis commands with no locking between them. Under concurrent tick ingestion (which is the normal operating mode with 600+ pairs), two coroutines processing ticks for the same symbol can both read the same stale state and overwrite each other's high/low/volume accumulation. On a busy pair like BTCUSDT, volume will be systematically under-reported and high/low windows will be incorrect.
**Suggested Fix:** Replace the read-modify-write pattern with a Lua script (via `redis.register_script()`) that executes the entire read-compute-write atomically in one Redis round-trip. Alternatively, use a Redis pipeline with `WATCH` / optimistic locking.
**Effort:** Medium
**Status:** Complete

---

### [x][HIGH] C1-2: `RedisClient.ping()` catches only `ConnectionError`/`TimeoutError` — misses other `RedisError` subtypes

**File:** `src/cache/redis_client.py` lines 120–123
**Category:** Correctness / Error Handling
**Description:** The public `ping()` health-check wrapper catches `RedisConnectionError` and `RedisTimeoutError` but not the generic `redis.exceptions.RedisError` base class. Subclasses like `ResponseError`, `AuthenticationError`, `BusyLoadingError`, and `DataError` are all uncaught and will propagate as unhandled exceptions from the health endpoint. Any of these can occur during misconfiguration (wrong auth), Redis restart (loading RDB), or corrupted command.
**Suggested Fix:** Change the except clause to catch `redis.exceptions.RedisError` (which is the base of all redis-py exceptions), then log the specific type and return `False`.
**Effort:** Trivial
**Status:** Complete

---

### [x][HIGH] C2-2: All `PriceCache` methods have zero error handling — Redis failures crash callers

**File:** `src/cache/price_cache.py` lines 106–254
**Category:** Correctness / Resilience
**Description:** Every method in `PriceCache` (`set_price`, `get_price`, `get_all_prices`, `update_ticker`, `get_ticker`, `get_stale_pairs`) issues Redis commands with no `try/except`. Any `RedisError` (connection drop, timeout, OOM) propagates directly to the caller. The price ingestion pipeline, order execution engine, and API routes all call these methods in their hot paths. A brief Redis hiccup during order execution will result in an unhandled exception reaching the API response layer with a 500 error instead of a graceful cache-miss fallback.
**Suggested Fix:** Wrap each Redis call in `try/except redis.exceptions.RedisError as exc: logger.error(...); return None` (for reads) or `logger.error(...); return` (for writes). This allows callers to implement fallback logic (e.g. query TimescaleDB for the latest price when the cache is unavailable).
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] C1-1: `redis_client.py` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/cache/redis_client.py` line 25
**Category:** Code Quality / Logging Consistency
**Description:** Uses standard `logging.getLogger(__name__)` rather than the platform-mandated `structlog.get_logger()`. Bypasses structured JSON output and loses context propagation (request_id, account_id binding).
**Suggested Fix:** Replace `import logging` with `import structlog` and `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Status:** Complete

---

### [x][MEDIUM] C2-3: `price_cache.py` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/cache/price_cache.py` line 37
**Category:** Code Quality / Logging Consistency
**Description:** Same as C1-1 — standard `logging` instead of `structlog`. The only log call in the file (`get_stale_pairs` warning) will emit plain-text output instead of structured JSON.
**Suggested Fix:** Replace `import logging` with `import structlog` and switch `logger = logging.getLogger(__name__)` to `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Status:** Complete

---

### [x][MEDIUM] C1-3: `get_redis_client()` singleton is not async-safe on first call

**File:** `src/cache/redis_client.py` lines 34–54
**Category:** Correctness / Concurrency
**Description:** The module-level singleton initializer checks `if _redis_singleton is None` and then assigns it. In async Python, if two coroutines both call `get_redis_client()` before the first one has set `_redis_singleton` (which can happen if they `await` inside the function — which they don't here, but `from_url` is synchronous so it's safe today), they will create two pools. More critically, if the function is ever modified to include an `await` (e.g. to ping on init), the check-then-act will be a classic async race. The pattern is fragile and inconsistent with how `init_db()` / `close_db()` manage their singletons.
**Suggested Fix:** Guard the singleton with an `asyncio.Lock` or use an explicit `init_redis()` / `close_redis()` lifecycle pair called from `create_app()` startup/shutdown hooks (as `init_db()` is), rather than lazy initialization.
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] C1-4: `get_redis_client()` singleton has no `close_redis_client()` counterpart — pool leaks on shutdown

**File:** `src/cache/redis_client.py` lines 34–54
**Category:** Resource Management
**Description:** The module-level `_redis_singleton` is created by `get_redis_client()` but there is no corresponding `close_redis_client()` function. On graceful application shutdown, the underlying connection pool is never explicitly closed. This means TCP connections to Redis are left open until they timeout on the server side. It also makes testing harder — tests that instantiate the singleton cannot clean up between test cases.
**Suggested Fix:** Add a `close_redis_client()` async function that calls `await _redis_singleton.aclose()` and resets `_redis_singleton = None`, then call it from the app's `lifespan` shutdown handler.
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] C1-5: `connect()` leaves `_pool`/`_redis` dangling if `_ping()` raises after pool creation

**File:** `src/cache/redis_client.py` lines 79–92
**Category:** Correctness / Resource Management
**Description:** `connect()` creates `_pool` and `_redis` (lines 85–90) and then calls `_ping()` (line 91). If `_ping()` raises (e.g. Redis is not yet up), the exception propagates to the caller while `self._pool` and `self._redis` are set to live (but unverified) objects. A subsequent call to `connect()` will create new pool/redis objects without closing the existing ones, leaking connections. A subsequent call to `disconnect()` will close the dangling objects, which may or may not succeed.
**Suggested Fix:** Wrap the body of `connect()` in a try/except that calls `await self.disconnect()` in the except block before re-raising, ensuring partial state is always cleaned up.
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] C2-4: `get_ticker()` performs unchecked field access — raises `KeyError` on partial hash

**File:** `src/cache/price_cache.py` lines 213–222
**Category:** Correctness / Resilience
**Description:** `get_ticker()` calls `raw["open"]`, `raw["high"]`, etc. directly on the dict returned by `HGETALL`. If any field is missing (e.g. the ticker hash was partially written during a Redis crash, or written by a different code path that uses a different field set), this raises an unhandled `KeyError`. Given that `update_ticker()` writes fields in a single `HSET` call, a partial write is unlikely but not impossible (e.g. memory eviction of individual hash fields under `maxmemory` policy `allkeys-lru`).
**Suggested Fix:** Use `raw.get("open")` for each field and either return `None` on any missing field, or catch `KeyError` and return `None` with a warning log.
**Effort:** Trivial
**Status:** Complete

---

### [x][LOW] C1-6: `disconnect()` double-closes the connection pool

**File:** `src/cache/redis_client.py` lines 94–102
**Category:** Code Quality / Resource Management
**Description:** `disconnect()` calls `await self._redis.aclose()` (line 97) which internally drains and closes the connection pool, then immediately calls `await self._pool.aclose()` (line 100) on the same already-closed pool. The second `aclose()` is redundant. While redis-py handles this gracefully today (idempotent close), it is confusing and may log spurious connection errors in future library versions.
**Suggested Fix:** Remove the explicit `await self._pool.aclose()` call — closing the `Redis` instance is sufficient. Or, alternatively, only close the pool and set `self._redis = None` without calling `_redis.aclose()` first.
**Effort:** Trivial
**Status:** Complete

---

### [x][LOW] C2-5: `Tick` NamedTuple defined in `price_cache.py` — should be a shared type

**File:** `src/cache/price_cache.py` lines 49–62
**Category:** Code Quality / Architecture
**Description:** `Tick` is described in its docstring as "the canonical in-flight data carrier shared between the price ingestion service, the tick buffer, the broadcaster, and this cache module". Defining a shared cross-module type inside `price_cache.py` creates a backwards import dependency: `price_ingestion/`, `broadcaster.py`, and `tick_buffer.py` all must import from `src.cache.price_cache` to get the `Tick` type. This violates clean dependency direction and makes the module harder to understand.
**Suggested Fix:** Move `Tick` (and potentially `TickerData`) to a dedicated `src/cache/types.py` module and import from there in both `price_cache.py` and all ingestion modules.
**Effort:** Small
**Status:** Complete

---

### [x][INFO] C2-6: `set_price()` docstring claims "atomic" but pipeline uses `transaction=False`

**File:** `src/cache/price_cache.py` lines 112–126
**Category:** Documentation / Correctness
**Description:** The docstring states "Uses a single pipeline to write both `prices` and `prices:meta` atomically from the caller's perspective." However, the pipeline is created with `transaction=False`, which disables MULTI/EXEC wrapping. The two HSET commands are pipelined (sent in one TCP round-trip) but are **not** atomic — Redis can process other commands between them. A reader could observe a new price in `prices` before the corresponding timestamp lands in `prices:meta`, causing a brief stale-detection false positive.
**Suggested Fix:** Either change `transaction=False` to `transaction=True` (enables MULTI/EXEC, true atomicity), or update the docstring to accurately describe the behaviour as "batched in a single pipeline round-trip, not transactionally atomic".
**Effort:** Trivial
**Status:** Complete

---

### [x][INFO] C0-1: `src/cache/` has no `__init__.py` — package public API is opaque

**File:** `src/cache/` (directory)
**Category:** Code Quality
**Description:** The `cache` directory has no `__init__.py`. Without it, consumers must import with full submodule paths: `from src.cache.redis_client import RedisClient`. Defining `__all__` and re-exporting `RedisClient`, `PriceCache`, `Tick`, `TickerData` would make the public API explicit and consistent with Python package conventions.
**Suggested Fix:** Create `src/cache/__init__.py` with `__all__` and re-exports for the public surface.
**Effort:** Trivial
**Status:** Complete

---

## Phase D — Utility Layer

> **Files reviewed:** `src/utils/exceptions.py`, `src/utils/helpers.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][MEDIUM] D1-1: `ValidationError` name shadows Pydantic's `pydantic.ValidationError`

**File:** `src/utils/exceptions.py` line 677
**Category:** Code Quality / Correctness
**Description:** The platform defines `class ValidationError(TradingPlatformError)` with error code `VALIDATION_ERROR`. Pydantic v2 defines its own `pydantic.ValidationError` (a completely different, non-subclassable class). Any file that imports both — e.g. a route that does `from src.utils.exceptions import ValidationError` and also uses Pydantic — will shadow one with the other. This is an existing footgun that can cause silent misbehaviour: a Pydantic validation error caught as `ValidationError` would silently match the platform's class and return a 422 with a misleading structured error instead of Pydantic's detail list. It also confuses IDEs and type checkers.
**Fix Applied:** Renamed `ValidationError` → `InputValidationError` in `exceptions.py` (class definition, docstring example, `__all__`). Updated all call sites: `src/accounts/balance_manager.py`, `src/order_engine/validators.py`, `src/api/routes/account.py`, and `src/order_engine/engine.py` docstring.
**Effort:** Small
**Status:** Complete

---

### [x][MEDIUM] D1-2: Several exception subclasses drop `details` kwarg from `__init__`

**File:** `src/utils/exceptions.py` lines 83, 141, 721, 735, 750
**Category:** Code Quality / Extensibility
**Description:** `AuthenticationError`, `PermissionDeniedError`, `DatabaseError`, `CacheError`, and `ServiceUnavailableError` all define `__init__` signatures that accept only `message: str`. The `details` kwarg available on `TradingPlatformError` is silently dropped — callers cannot attach structured context (e.g. a Redis error code, a DB constraint name, an offending IP) to these exceptions. For infrastructure errors like `DatabaseError` and `CacheError`, this makes debugging significantly harder since the only information surfaced is a plain string.
**Fix Applied:** Added `details: dict[str, Any] | None = None` keyword argument to `AuthenticationError`, `PermissionDeniedError`, `DatabaseError`, `CacheError`, and `ServiceUnavailableError`, passing it through to `super().__init__()`. All five classes are backwards-compatible (parameter is optional with default `None`).
**Effort:** Trivial
**Status:** Complete

---

### [x][LOW] D1-3: `RiskLimitExceededError` uses code `POSITION_LIMIT_EXCEEDED` for all risk types

**File:** `src/utils/exceptions.py` lines 526–561
**Category:** Code Quality / Correctness
**Description:** The class is named `RiskLimitExceededError` and is used for all risk limit violations (position size, max open orders, max order size, rate-of-order limit, etc.). However the hardcoded error code is `POSITION_LIMIT_EXCEEDED`. A client receiving this error code for an "exceeded max open orders" or "order size too large" rejection will be misled — they'll check their position size when the actual issue is something else. The `limit_type` field in `details` partially mitigates this, but the top-level code is still wrong.
**Fix Applied:** Changed `code = "POSITION_LIMIT_EXCEEDED"` → `code = "RISK_LIMIT_EXCEEDED"` in `RiskLimitExceededError`. Updated the class docstring. Updated `developmantPlan.md` Section 15 error codes table accordingly.
**Effort:** Trivial
**Status:** Complete

---

### [x][LOW] D2-3: `paginate()` raises stdlib `ValueError` instead of platform `ValidationError`

**File:** `src/utils/helpers.py` lines 155–158
**Category:** Code Quality / Consistency
**Description:** `paginate()` raises `ValueError` when `limit < 1` or `offset < 0`. The platform convention (per CLAUDE.md and `exceptions.py`) is to use custom exceptions from `src/utils/exceptions.py`. A `ValueError` propagating from the repository/service layer will not be caught by the API's `TradingPlatformError` handler and will result in an unhandled 500 instead of a clean 400/422.
**Fix Applied:** Replaced both `raise ValueError(...)` calls in `paginate()` with `raise InputValidationError(...)` using a lazy in-function import (no circular import — `exceptions.py` does not import `helpers.py`). Includes `field=` context for the API error envelope.
**Effort:** Small
**Status:** Complete

---

### [x][LOW] D2-4: `clamp()` raises stdlib `ValueError` instead of platform `ValidationError`

**File:** `src/utils/helpers.py` line 247
**Category:** Code Quality / Consistency
**Description:** Same as D2-3 — `clamp()` raises `ValueError` when `lo > hi`. Callers in service/order-engine code won't have this caught by the API error handler, risking a 500 response.
**Fix Applied:** Replaced `raise ValueError(...)` in `clamp()` with `raise InputValidationError(...)` via lazy in-function import, consistent with D2-3 fix.
**Effort:** Trivial
**Status:** Complete

---

### [x][MEDIUM] D2-2: `parse_period()` silently treats unknown period strings as "all time"

**File:** `src/utils/helpers.py` lines 96–99
**Category:** Correctness
**Description:** `parse_period()` does `_PERIOD_DAYS.get(period)` which returns `None` for both `"all"` (intentional) and any unrecognised input like `"30D"`, `"1week"`, or `"invalid"` (unintentional). The function returns `None` in all three cases, meaning a typo in a `?period=` query parameter silently returns all historical data instead of a validation error. `period_to_since()` inherits the same bug — `period_to_since("30D")` returns `None` (all time) rather than raising.
**Fix Applied:** `parse_period()` now checks `if period == "all": return None` first (explicit sentinel), then raises `InputValidationError` for any value not in `_PERIOD_DAYS`. Combined with D2-5 fix — `"all"` was removed from `_PERIOD_DAYS` entirely to keep the dict unambiguous.
**Effort:** Trivial
**Status:** Complete

---

### [x][MEDIUM] D2-1: `_KNOWN_QUOTES` tuple re-allocated on every `symbol_to_base_quote()` call

**File:** `src/utils/helpers.py` line 216
**Category:** Performance
**Description:** `_KNOWN_QUOTES = ("USDT", "BUSD", ...)` is defined **inside** `symbol_to_base_quote()`. Every call to this function (including the hot path in price ingestion which processes 600+ symbols repeatedly) allocates a new tuple object. While Python caches small constant tuples in some cases, the assignment inside a function body defeats this optimisation. The fix is trivial and has zero risk.
**Fix Applied:** Moved `_KNOWN_QUOTES: tuple[str, ...] = (...)` to module level. `symbol_to_base_quote()` now references the module-level constant.
**Effort:** Trivial
**Status:** Complete

---

### [x][INFO] D1-4: Extra exceptions not in plan's Section 15 error code table

**File:** `src/utils/exceptions.py`
**Category:** Documentation / INFO
**Description:** The plan's Section 15 defines 12 error codes. `exceptions.py` defines 9 additional exceptions/codes not in the table: `INVALID_TOKEN`, `PERMISSION_DENIED`, `TRADE_NOT_FOUND`, `DUPLICATE_ACCOUNT`, `ORDER_REJECTED`, `PRICE_NOT_AVAILABLE`, `DATABASE_ERROR`, `CACHE_ERROR`, `SERVICE_UNAVAILABLE`. These are reasonable and well-implemented additions, but the plan is out of sync.
**Fix Applied:** Expanded the Section 15 error codes table in `developmantPlan.md` from 12 to 24 rows, covering all codes defined in `exceptions.py` (including the D1-3 rename to `RISK_LIMIT_EXCEEDED`). No code change needed.
**Effort:** Trivial
**Status:** Complete

---

### [x][INFO] D2-5: `"all"` period and unknown periods both return `None` from `_PERIOD_DAYS.get()`

**File:** `src/utils/helpers.py` lines 42–48, 96–99
**Category:** Code Quality / INFO
**Description:** The `_PERIOD_DAYS` dict uses `None` as the value for `"all"`, and `dict.get()` also returns `None` for missing keys. This means the code cannot distinguish "user requested all time" from "user provided a garbage input" without an additional `in` check. See D2-2 for the practical impact. This INFO item flags the underlying structural ambiguity regardless of whether D2-2 is fixed.
**Fix Applied:** Removed `"all": None` from `_PERIOD_DAYS`. `parse_period()` now handles `"all"` with an explicit `if period == "all": return None` guard before the dict lookup, making the intent unambiguous. Resolved together with D2-2.
**Effort:** Trivial
**Status:** Complete

---

### [x][INFO] D2-6: `helpers.py` imports `sqlalchemy.Select` at module level — couples utility layer to SQLAlchemy

**File:** `src/utils/helpers.py` line 27
**Category:** Architecture / INFO
**Description:** `from sqlalchemy import Select` is the sole reason `helpers.py` depends on SQLAlchemy. This makes the utility module — which is foundational and imported everywhere — carry an ORM dependency. If SQLAlchemy is swapped or mocked in tests, this import must succeed. The `paginate()` helper is the only consumer. Moving `paginate()` to `src/database/utils.py` (alongside session/repo code) or guarding the import with `TYPE_CHECKING` would decouple the utility layer from the ORM.
**Fix Applied:** Replaced `from sqlalchemy import Select` with `if TYPE_CHECKING: from sqlalchemy import Select`. Since `from __future__ import annotations` was already present, the `Select` annotation in `paginate()` is evaluated lazily and the runtime import is eliminated. No call sites needed updating.
**Effort:** Small
**Status:** Complete

---

## Phase E — Price Ingestion

> **Files reviewed:** `src/price_ingestion/binance_ws.py`, `src/price_ingestion/tick_buffer.py`, `src/price_ingestion/service.py`, `src/price_ingestion/broadcaster.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [HIGH] E3-1: Fatal exception bypasses graceful shutdown — Redis and DB connections leaked

**File:** `src/price_ingestion/service.py` lines 127–129
**Category:** Correctness / Resource Management
**Description:** The main tick loop catches unexpected exceptions, logs them, and then `raise`s. The `raise` causes `run()` to propagate the exception out of `asyncio.run(run())`, skipping the entire graceful-shutdown block (lines 131–143). As a result, the Redis client and the database pool are never closed. Under Kubernetes or Docker, this means the process exits with open connections, which exhausts the PostgreSQL max-connection pool for subsequent restarts until the connections time out (typically ~10 minutes).
**Suggested Fix:** Wrap the raise in a `finally` block, or move the shutdown sequence before the `raise`. The cleanest approach:
```python
except Exception as exc:
    log.error("Fatal error in ingestion loop", error=str(exc), exc_info=True)
finally:
    # Graceful shutdown always runs
    flush_task.cancel()
    ...
    await close_db()
if fatal_exc:
    raise fatal_exc
```
**Effort:** Small
**Status:** Complete

---

### [MEDIUM] E4-1: Hot path calls `broadcast()` (single PUBLISH per tick) instead of `broadcast_batch()`

**File:** `src/price_ingestion/service.py` line 119, `src/price_ingestion/broadcaster.py` lines 53–63
**Category:** Performance
**Description:** `PriceBroadcaster.broadcast_batch()` exists specifically to batch multiple `PUBLISH` commands into a single Redis pipeline round-trip. However, `service.py` calls `await broadcaster.broadcast(tick)` on every individual tick in the hot loop — one network round-trip per tick. At 600+ symbols the ingestion service can receive tens of thousands of ticks per second. This makes `broadcast()` a bottleneck while the efficient `broadcast_batch()` is never used in production.
**Suggested Fix:** Accumulate ticks alongside `buffer.add()` and emit a batch publish either on size threshold or periodically. A simpler interim fix: call `broadcast_batch()` from `TickBuffer._do_flush()` using the same `batch` list it already has, so broadcast and DB flush are co-located.
**Effort:** Medium
**Status:** Complete

---

### [MEDIUM] E3-2: `structlog.configure()` called at module import time — pollutes global state in tests

**File:** `src/price_ingestion/service.py` lines 41–43
**Category:** Testability / Code Quality
**Description:** `structlog.configure(...)` is executed at module level, unconditionally, when `service.py` is imported. `structlog.configure()` mutates a global singleton. Any test that imports this module (directly or transitively) will have its structlog configuration overwritten, which can silence log assertions or break log-level filtering in the rest of the test suite.
**Suggested Fix:** Move the `structlog.configure()` call inside `main()` (the CLI entry point), not at module level. The `run()` coroutine itself does not need structlog configured — it just calls `structlog.get_logger()`, which works fine with the default configuration.
**Effort:** Trivial
**Status:** Complete

---

### [MEDIUM] E2-1: Lock held across async DB call — `add()` blocked during entire flush duration

**File:** `src/price_ingestion/tick_buffer.py` lines 83–86
**Category:** Correctness / Performance
**Description:** `add()` acquires `_lock`, appends the tick, then if the buffer is full calls `await self._do_flush()` while still holding `_lock`. `_do_flush()` performs an async `asyncpg` COPY insert, which can take tens of milliseconds under load. During this entire time, no other coroutine can call `add()` because `_lock` is held. At high tick rates this means the ingestion loop stalls every 5000 ticks while waiting for the DB flush to complete, introducing latency spikes.
**Suggested Fix:** Snapshot and clear the buffer under the lock, then release the lock before doing the DB write. This is already the pattern used in `_do_flush()` (snapshots to `batch` first), but the lock should be released before `conn.copy_records_to_table`. Use a two-phase approach:
```python
async with self._lock:
    batch = list(self._buffer)
    self._buffer.clear()
# lock released — DB write happens outside
await self._write_batch(batch)
```
Restore `self._buffer = batch + self._buffer` on failure.
**Effort:** Small
**Status:** Complete

---

### [LOW] E1-1: `listen()` declared `-> None` but is an async generator — misleading type signature

**File:** `src/price_ingestion/binance_ws.py` line 109
**Category:** Type Safety / Code Quality
**Description:** `listen()` uses `yield` inside it, making it an `AsyncGenerator[Tick, None]`. The declared return type is `-> None` with a `# type: ignore[override]` suppressor. This means mypy cannot catch callers that misuse the return value, and IDEs will not provide autocomplete on the yielded `Tick` type.
**Suggested Fix:** Change the signature to `async def listen(self) -> AsyncGenerator[Tick, None]:` and add `from collections.abc import AsyncGenerator` to imports. Remove the `# type: ignore` comments.
**Effort:** Trivial
**Status:** Complete

---

### [LOW] E1-2: `json.JSONDecodeError` not explicitly caught — relies on `ValueError` inheritance

**File:** `src/price_ingestion/binance_ws.py` line 237
**Category:** Code Quality / Clarity
**Description:** `_parse_message()` catches `(KeyError, ValueError, TypeError)`. `json.JSONDecodeError` is a subclass of `ValueError` so it is caught, but this is implicit. A reader unfamiliar with the inheritance hierarchy would believe JSON decode errors are unhandled and might add a redundant `json.JSONDecodeError` catch elsewhere. Explicit is better than implicit (PEP 20).
**Suggested Fix:** Add `json.JSONDecodeError` to the except tuple: `except (json.JSONDecodeError, KeyError, ValueError, TypeError)`.
**Effort:** Trivial
**Status:** Complete

---

### [INFO] E1-3: `binance_ws.py` uses `logging.getLogger` instead of `structlog.get_logger`

**File:** `src/price_ingestion/binance_ws.py` line 32
**Category:** Logging Consistency
**Description:** Uses `import logging` / `logging.getLogger(__name__)` while `service.py` (the process that runs this code) uses structlog. Log lines from this file will bypass the structlog JSON pipeline and lose request context fields.
**Suggested Fix:** Replace with `import structlog` / `log = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Status:** Complete

---

### [INFO] E2-2: `tick_buffer.py` uses `logging.getLogger` instead of `structlog.get_logger`

**File:** `src/price_ingestion/tick_buffer.py` line 31
**Category:** Logging Consistency
**Description:** Same as E1-3 — uses stdlib `logging` instead of `structlog`, breaking the unified structured log pipeline.
**Suggested Fix:** Replace with `import structlog` / `log = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Status:** Complete

---

### [INFO] E4-2: `broadcaster.py` uses `logging.getLogger` instead of `structlog.get_logger`

**File:** `src/price_ingestion/broadcaster.py` line 33
**Category:** Logging Consistency
**Description:** Same as E1-3 — uses stdlib `logging` instead of `structlog`.
**Suggested Fix:** Replace with `import structlog` / `log = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Status:** Complete

---

### [INFO] E3-3: Dead `if TYPE_CHECKING: pass` block

**File:** `src/price_ingestion/service.py` lines 36–37
**Category:** Code Quality
**Description:** `if TYPE_CHECKING: pass` is a no-op. It was likely left over from a refactor that removed a type-only import. It adds noise with no benefit.
**Suggested Fix:** Delete lines 36–37.
**Effort:** Trivial
**Status:** Complete

---

## Phase F — Account Management

> **Files reviewed:** `src/accounts/auth.py`, `src/accounts/service.py`, `src/accounts/balance_manager.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][CRITICAL] F2-1: `register()` calls bcrypt synchronously in async context — blocks event loop

**File:** `src/accounts/service.py` lines 166, 250
**Category:** Correctness / Performance / Async Safety
**Description:** `generate_api_credentials()` (called at line 166 in `register()`) invokes `bcrypt.hashpw()` twice with 12 rounds — a CPU-bound operation that takes ~200ms per call. Similarly, `authenticate()` (line 250) calls `authenticate_api_key()` which also calls `bcrypt.checkpw()` synchronously. Both are called directly from `async` methods with no `run_in_executor()` wrapping. This blocks the entire asyncio event loop for ~200–400ms on every registration or login, preventing all other coroutines (including WebSocket heartbeats, order fills, and price broadcasts) from making progress during that time. Under concurrent load, this creates severe head-of-line blocking.
**Suggested Fix:** Wrap both bcrypt calls in `await asyncio.get_event_loop().run_in_executor(None, ...)`:
```python
import asyncio
creds = await asyncio.get_event_loop().run_in_executor(None, generate_api_credentials)
# and in authenticate():
await asyncio.get_event_loop().run_in_executor(None, authenticate_api_key, api_key, account.api_key_hash)
```
**Effort:** Small
**Fix Applied:** Added `import asyncio`; wrapped `generate_api_credentials()` call in `register()` and `authenticate_api_key()` call in `authenticate()` with `await asyncio.get_event_loop().run_in_executor(None, ...)`.
**Status:** Complete

---

### [x][HIGH] F2-2: `register()` does not wrap `SQLAlchemyError` → `DatabaseError`

**File:** `src/accounts/service.py` lines 163–216
**Category:** Correctness / Error Handling
**Description:** `register()` calls `account_repo.create()`, `balance_repo.create()`, and raw `session.add()`/`flush()`/`commit()` with **no** try/except block. If any of these raise `SQLAlchemyError` (e.g. a duplicate email violation triggers `IntegrityError`), the raw SQLAlchemy exception propagates to the route handler. The route handler's `TradingPlatformError` exception handler won't match it, resulting in an unhandled 500 error instead of the documented `DuplicateAccountError` (409) or `DatabaseError` (500 with structured envelope). The docstring promises `DuplicateAccountError` on duplicate email, but nothing in the code raises it — the `IntegrityError` leaks raw.
**Suggested Fix:** Wrap the body of `register()` in a try/except block, catching `IntegrityError` separately to raise `DuplicateAccountError`, and catching `SQLAlchemyError` to raise `DatabaseError`, mirroring the pattern used in `reset_account()`.
**Effort:** Small
**Fix Applied:** Wrapped DB operations in `register()` with `try/except IntegrityError → DuplicateAccountError` and `except SQLAlchemyError → DatabaseError`; added `IntegrityError` and `DuplicateAccountError` imports.
**Status:** Complete

---

### [x][HIGH] F2-3: `suspend_account()` and `unsuspend_account()` have no error handling

**File:** `src/accounts/service.py` lines 416–462
**Category:** Correctness / Error Handling
**Description:** `suspend_account()` and `unsuspend_account()` call `account_repo.update_status()` and `session.commit()` with no try/except. If the DB is unavailable or a constraint fires, a raw `SQLAlchemyError` propagates to the caller. All other lifecycle methods (`reset_account`) wrap DB calls — this inconsistency means suspend/unsuspend operations are the only paths that return unstructured errors.
**Suggested Fix:** Add try/except `SQLAlchemyError` → `DatabaseError` wrapping, following the same pattern as `reset_account()`.
**Effort:** Trivial
**Fix Applied:** Wrapped `account_repo.update_status()` in both `suspend_account()` and `unsuspend_account()` with `try/except SQLAlchemyError → DatabaseError`; removed the now-redundant `session.commit()` calls (handled by the session dependency).
**Status:** Complete

---

### [x][HIGH] F1-1: `verify_api_key()` and `verify_api_secret()` use bare `except Exception:`

**File:** `src/accounts/auth.py` lines 168–171, 187–190
**Category:** Security / Code Quality
**Description:** Both `verify_api_key()` and `verify_api_secret()` catch all exceptions with `except Exception: return False`. This is explicitly prohibited by CLAUDE.md ("never bare `except:`") and masks unexpected errors such as: memory errors during bcrypt, corrupt hash strings, encoding errors, or future bcrypt library exceptions. Silently returning `False` on an unexpected error looks like "invalid key" to the caller, which could obscure infrastructure problems (e.g. hash corruption). It also defeats type-error detection during testing.
**Suggested Fix:** Catch only the specific exceptions bcrypt can raise: `ValueError` (malformed hash) and potentially `bcrypt.exceptions.InvalidHashError`. Re-raise anything else:
```python
except (ValueError, Exception) as exc:
    if isinstance(exc, (ValueError,)):
        return False
    raise
```
Or more cleanly: `except ValueError: return False`.
**Effort:** Trivial
**Fix Applied:** Replaced `except Exception: return False` with `except ValueError: return False` in both `verify_api_key()` and `verify_api_secret()`.
**Status:** Complete

---

### [x][MEDIUM] F2-4: `starting_balance or default` silently ignores explicit `Decimal("0")` input

**File:** `src/accounts/service.py` line 164
**Category:** Correctness
**Description:** `balance_amount = starting_balance or self._settings.default_starting_balance` uses Python's `or` operator, which treats `Decimal("0")` as falsy. If a caller explicitly passes `starting_balance=Decimal("0")` (e.g. to create an account with no initial funds), the default balance (10,000 USDT) is silently used instead. This is a subtle correctness bug — `or` should only be used for `None` checks, not for `Decimal` zero checks.
**Suggested Fix:** Change to: `balance_amount = starting_balance if starting_balance is not None else self._settings.default_starting_balance`.
**Effort:** Trivial
**Fix Applied:** Changed `starting_balance or self._settings.default_starting_balance` to `starting_balance if starting_balance is not None else self._settings.default_starting_balance`.
**Status:** Complete

---

### [x][MEDIUM] F2-5: `AccountService` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/accounts/service.py` line 58
**Category:** Code Quality / Logging Consistency
**Description:** `logger = logging.getLogger(__name__)` bypasses the platform's structured JSON log pipeline (structlog). Log calls in `register()`, `authenticate()`, `reset_account()` etc. will emit plain-text logs without structured fields (request_id, account_id binding), breaking observability. Cross-cutting concern V6 mandates `structlog.get_logger()` throughout.
**Suggested Fix:** Replace `import logging` → `import structlog` and `logger = logging.getLogger(__name__)` → `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Fix Applied:** Replaced `import logging` with `import structlog`; changed `logger = logging.getLogger(__name__)` to `log = structlog.get_logger(__name__)`; updated all log call-sites to use structlog keyword-argument style.
**Status:** Complete

---

### [x][MEDIUM] F3-1: `BalanceManager` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/accounts/balance_manager.py` line 51
**Category:** Code Quality / Logging Consistency
**Description:** Same as F2-5 — `balance_manager.py` uses stdlib `logging` rather than `structlog`. The `execute_trade` hot path logs buy/sell events that are important for audit trails; losing the structured context (request_id, session_id) makes correlation with other logs impossible.
**Suggested Fix:** Replace `import logging` → `import structlog` and `logger = logging.getLogger(__name__)` → `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial
**Fix Applied:** Replaced `import logging` with `import structlog`; changed `logger = logging.getLogger(__name__)` to `log = structlog.get_logger(__name__)`; updated all log call-sites to structlog keyword-argument style; also fixed `InputInputValidationError` import typo → `InputValidationError`.
**Status:** Complete

---

### [x][MEDIUM] F3-2: `execute_trade()` does not wrap DB errors as `DatabaseError`

**File:** `src/accounts/balance_manager.py` lines 503–596
**Category:** Correctness / Error Handling
**Description:** `execute_trade()` calls `self._repo.atomic_execute_buy()` / `atomic_execute_sell()` with no try/except. The `BalanceRepository` methods internally re-raise `IntegrityError` as `InsufficientBalanceError` (correct), but any other `SQLAlchemyError` (connection drop, deadlock, timeout) will propagate as a raw exception to the order engine and ultimately to the route handler as an unhandled 500. Unlike the repository layer which wraps its own errors, the service layer here adds no additional safety net.
**Suggested Fix:** Add try/except around the `atomic_execute_buy`/`atomic_execute_sell` calls:
```python
except InsufficientBalanceError:
    raise
except SQLAlchemyError as exc:
    raise DatabaseError("Balance settlement failed.") from exc
```
**Effort:** Trivial
**Fix Applied:** Wrapped `atomic_execute_buy()` and `atomic_execute_sell()` calls in `execute_trade()` with `try/except InsufficientBalanceError: raise` / `except SQLAlchemyError → DatabaseError`; added `SQLAlchemyError` and `DatabaseError` imports.
**Status:** Complete

---

### [x][MEDIUM] F2-6: `_get_active_session()` is a dead private method — never called internally

**File:** `src/accounts/service.py` lines 464–495
**Category:** Code Quality
**Description:** `_get_active_session()` is defined as a private helper but is **not called anywhere** in `service.py`. `reset_account()` handles session closure inline via a direct `UPDATE` statement rather than using this helper. The method is unreachable dead code that will never be exercised in tests, potentially masking the fact that it does reference the correct session query logic.
**Suggested Fix:** Either delete `_get_active_session()` if it serves no purpose, or refactor `reset_account()` to use it (which would also simplify the reset logic).
**Effort:** Trivial
**Fix Applied:** Deleted the `_get_active_session()` method entirely; the route already has its own equivalent helper (`_get_active_session` in `account.py`).
**Status:** Complete

---

### [x][LOW] F1-2: `verify_jwt()` converts `iat`/`exp` from numeric to `datetime` after PyJWT already does it

**File:** `src/accounts/auth.py` lines 282–289
**Category:** Code Quality / Redundancy
**Description:** PyJWT's `decode()` with `options={"require": ["iat", "exp"]}` already validates and decodes the `iat` and `exp` claims. After `decode()` returns successfully, lines 282–289 manually re-fetch `decoded.get("iat")` and `decoded.get("exp")`, check `isinstance(..., (int, float))`, and convert them with `datetime.fromtimestamp()`. PyJWT returns these as numeric Unix timestamps in the decoded dict, but the `isinstance` check is redundant — if PyJWT accepted the token, `exp` and `iat` are guaranteed to be present numeric values (they were already validated by `options={"require": ...}`). The duplicate check adds noise.
**Suggested Fix:** Remove the redundant `isinstance` guard and directly use `decoded["iat"]` and `decoded["exp"]` since PyJWT guarantees their presence after successful decode with `require`.
**Effort:** Trivial
**Fix Applied:** Removed the `iat_raw`/`exp_raw` intermediate variables and `isinstance` check; directly call `datetime.fromtimestamp(float(decoded["iat"]), ...)` and `datetime.fromtimestamp(float(decoded["exp"]), ...)`.
**Status:** Complete

---

### [x][LOW] F2-7: `reset_account()` does not cancel pending/open orders before wiping balances

**File:** `src/accounts/service.py` lines 319–404
**Category:** Correctness / Data Integrity
**Description:** `reset_account()` deletes all `Balance` rows for the account but does not first cancel pending or open orders. Any pending limit orders still reference the account and may still be in the matching engine's sweep queue. When the Celery `LimitOrderMonitor` next runs, it will attempt to execute those pending orders, find no balance (or the fresh USDT balance), and either crash with `InsufficientBalanceError` or — worse — execute against the fresh USDT balance. The `developmantPlan.md` reset spec should include order cancellation as a prerequisite step.
**Suggested Fix:** Before deleting balances, run an `UPDATE orders SET status='cancelled' WHERE account_id=? AND status IN ('pending', 'partially_filled')` and corresponding `unlock` of locked balances. Or inject `OrderRepository` as a dependency and call `cancel_all_open_orders(account_id)`.
**Effort:** Medium
**Fix Applied:** Added a `sqlalchemy update(Order).where(account_id=..., status.in_(["pending","partially_filled"])).values(status="cancelled")` as the first step inside `reset_account()`'s try block, before closing the session and wiping balances. Added `Order` import from `src.database.models`.
**Status:** Complete

---

### [x][LOW] F1-3: `authenticate_api_key()` does a full bcrypt check on every request — no short-circuit for prefix

**File:** `src/accounts/auth.py` lines 303–323
**Category:** Performance
**Description:** Every API request to an authenticated endpoint triggers `bcrypt.checkpw()` — a ~200ms operation — even for obviously invalid keys (e.g. a key without the `ak_live_` prefix, or one with the wrong length). A simple O(1) prefix and length pre-check before the expensive bcrypt call would reject malformed keys instantly and prevent bcrypt from being used as a CPU-exhaustion vector by passing arbitrary strings as API keys.
**Suggested Fix:** Add a guard in `authenticate_api_key()` before calling `verify_api_key()`:
```python
if not raw_key.startswith(_API_KEY_PREFIX) or len(raw_key) != len(_API_KEY_PREFIX) + 64:
    raise AuthenticationError("API key format is invalid.")
```
**Effort:** Trivial
**Fix Applied:** Added the prefix and length pre-check at the start of `authenticate_api_key()` — rejects malformed keys in O(1) before the ~200ms bcrypt call.
**Status:** Complete

---

### [x][INFO] F2-8: `register()` commits inside the service method — inconsistent with other services

**File:** `src/accounts/service.py` line 198
**Category:** Code Quality / Architecture
**Description:** `register()` calls `await self._session.commit()` directly (line 198). The module docstring states "The caller is responsible for committing or rolling back." `BalanceManager` correctly leaves commits to the caller. `AccountService` is inconsistent: `register()`, `reset_account()`, `suspend_account()`, and `unsuspend_account()` all call `commit()` internally. This prevents callers from composing multiple service operations into a single atomic transaction.
**Suggested Fix:** Remove all `session.commit()` calls from `AccountService` methods and document that callers are responsible for committing, matching the pattern in `BalanceManager` and the repository layer. Update call sites in routes to add explicit commits.
**Effort:** Medium
**Fix Applied:** Removed `await self._session.commit()` from `register()`, `reset_account()`, `suspend_account()`, and `unsuspend_account()`. The `get_db_session()` dependency in `src/dependencies.py` already auto-commits the session when the route handler returns successfully and auto-rolls-back on exception, so no route-level changes are required.
**Status:** Complete

---

### [x][INFO] F1-4: `auth.py` has no `__all__` export definition

**File:** `src/accounts/auth.py`
**Category:** Code Quality
**Description:** `auth.py` defines 6 public symbols (`ApiCredentials`, `JwtPayload`, `generate_api_credentials`, `verify_api_key`, `verify_api_secret`, `create_jwt`, `verify_jwt`, `authenticate_api_key`) but has no `__all__`. Without `__all__`, `from src.accounts.auth import *` would expose private helpers like `_bcrypt_hash` and constants like `_TOKEN_BYTES`. Defining `__all__` makes the public API explicit.
**Suggested Fix:** Add `__all__ = ["ApiCredentials", "JwtPayload", "generate_api_credentials", "verify_api_key", "verify_api_secret", "create_jwt", "verify_jwt", "authenticate_api_key"]`.
**Effort:** Trivial
**Fix Applied:** Added the `__all__` list at the bottom of `auth.py` with all 8 public symbols.
**Status:** Complete

---

---

## Phase G — Order Engine

> **Files reviewed:** `src/order_engine/slippage.py`, `src/order_engine/validators.py`, `src/order_engine/engine.py`, `src/order_engine/matching.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][CRITICAL] G3-1: `Trade` and `Order` rows created with `float()` — financial precision destroyed

**File:** `src/order_engine/engine.py` lines 536–538, 565–576, 672–680, 421–431
**Category:** Correctness / Type Safety
**Description:** Every `Trade` and `Order` ORM object is constructed with explicit `float()` conversions on all financial fields:
- `_place_market_order`: `Order(quantity=float(order.quantity), ...)` and `Trade(quantity=float(...), price=float(slippage.execution_price), quote_amount=float(settlement.quote_amount), fee=float(settlement.fee_charged))`
- `_place_queued_order`: `Order(quantity=float(order.quantity), price=float(limit_price), ...)`
- `execute_pending_order`: same `float()` conversions on the Trade

`Decimal` values calculated with full precision by the slippage model and balance manager are converted to IEEE-754 doubles before being written to the DB. For large BTC/ETH prices this can introduce errors in the 5th–8th decimal place — the exact digits that `NUMERIC(20,8)` columns are meant to preserve. This undermines the entire precision guarantee of the platform.
**Suggested Fix:** Remove all `float()` wrappers. Pass `Decimal` values directly; SQLAlchemy's `Numeric(20,8)` column accepts `Decimal` natively. E.g.: `Order(quantity=order.quantity, ...)` and `Trade(price=slippage.execution_price, ...)`.
**Effort:** Small
**Fix Applied:** Removed all `float()` wrappers from `Order` and `Trade` construction in `_place_market_order`, `_place_queued_order`, and `execute_pending_order`. `Decimal` values now pass directly to SQLAlchemy's `Numeric(20,8)` columns.
**Status:** Complete

---

### [x][HIGH] G3-2: `cancel_all_orders` uses bare `except Exception:` — swallows errors silently

**File:** `src/order_engine/engine.py` lines 316–328
**Category:** Code Quality / Error Handling
**Description:** The per-order try/except in `cancel_all_orders` catches bare `Exception:` and continues. This violates the CLAUDE.md rule against bare `except:` and suppresses unexpected errors (e.g. DB deadlocks, programming bugs, `AttributeError`) that would mask root causes. It also means a critical failure mid-loop is counted as a success — the commit happens and partial state is persisted without the caller knowing which orders actually failed.
**Suggested Fix:** Catch only the expected exceptions (`OrderNotFoundError`, `OrderNotCancellableError`, `InsufficientBalanceError`, `SQLAlchemyError`). Log each with the specific exception type. Track failed order IDs and include them in the return value or raise a summary error.
**Effort:** Small
**Fix Applied:** Replaced bare `except Exception` with two separate handlers: `(OrderNotFoundError, OrderNotCancellableError, InsufficientBalanceError)` logged at WARNING, and `SQLAlchemyError` logged at EXCEPTION. Tracks `failed_order_ids` list and logs it at the end of the sweep.
**Status:** Complete

---

### [x][HIGH] G3-3: `place_order` fetches reference price before validation completes — no ownership of the validator session

**File:** `src/order_engine/engine.py` lines 220–242
**Category:** Correctness / Architecture
**Description:** `place_order` calls `self._validator.validate(order)` which runs a DB SELECT against the injected session, then immediately calls `self._price_cache.get_price(order.symbol)`. The `get_price` call is completely unguarded — any `RedisError` propagates uncaught to the caller, returning a raw exception rather than `PriceNotAvailableError`. While `PriceCache.get_price()` returns `None` on a Redis miss (and line 223 guards for `None`), a `RedisError` exception (e.g. timeout) will bypass that guard and crash with an unstructured 500.
**Suggested Fix:** Wrap the `get_price()` call in a try/except for `RedisError` and convert to `PriceNotAvailableError` or `CacheError`.
**Effort:** Trivial
**Fix Applied:** Wrapped the `get_price()` call in `try/except Exception` and re-raised as `CacheError`, ensuring any Redis failure produces a structured 500 with the correct error code instead of a raw unhandled exception.
**Status:** Complete

---

### [x][HIGH] G2-1: Validator fetches `TradingPair` but ignores `min_qty` and `min_notional` — plan-required checks omitted

**File:** `src/order_engine/validators.py` lines 150–185, `src/order_engine/validators.py` line 244
**Category:** Correctness / Spec Compliance
**Description:** The `OrderValidator` fetches the active `TradingPair` row (which contains `min_qty`, `min_notional`, `max_qty`) from the DB and returns it to the caller — but performs **no validation against these fields**. Per the `developmantPlan.md` and `_check_quantity`, only `quantity > 0` is checked. A `min_qty` of `0.001 BTC` on a pair that requires at minimum `0.001` would pass validation for `quantity=0.000001`. The min notional (minimum order value in USD) is also unchecked. These checks are seeded into `trading_pairs.min_qty` and `min_notional` by `scripts/seed_pairs.py` precisely for this validation step.
**Suggested Fix:** After the pair is fetched, add:
```python
if order.quantity < pair.min_qty:
    raise InvalidQuantityError(f"Quantity below minimum for {order.symbol}", quantity=order.quantity, min_qty=pair.min_qty)
if order.quantity * (order.price or reference_price) < pair.min_notional:
    raise InvalidQuantityError(f"Order notional below minimum for {order.symbol}", ...)
```
**Effort:** Small
**Fix Applied:** Added `_check_pair_limits(order, pair)` static method called at the end of `validate()`. Checks `pair.min_qty` (skipped if `None`) and `pair.min_notional` for orders with a price field. Both raise `InvalidQuantityError` with full context.
**Status:** Complete

---

### [x][MEDIUM] G3-4: `cancel_order` has TOCTOU between `get_by_id` and `cancel` — order state can change mid-call

**File:** `src/order_engine/engine.py` lines 264–266
**Category:** Correctness / Concurrency
**Description:** `cancel_order` first fetches the order with `get_by_id` (to get its fields for fund release), then calls `cancel` separately. Between these two calls, a concurrent background matcher sweep could have already filled the order (changing its status from `pending` → `filled`). The `cancel` call should catch this (the repo has `_CANCELLABLE_STATUSES`), but then `_release_locked_funds` is called on the already-filled order, which would attempt to `unlock` funds that were already spent — potentially giving the account a double-refund.
**Suggested Fix:** Check the return value of `cancel()` (which should return the updated order or a boolean). If cancellation fails (non-cancellable state), skip the fund release. Alternatively, wrap both operations in a savepoint to make the cancel atomic with the fund release.
**Effort:** Medium
**Fix Applied:** Eliminated the redundant `get_by_id` call in `cancel_order`. Now calls `cancel()` directly and uses its returned `Order` object for `_release_locked_funds`. Since `cancel()` raises `OrderNotCancellableError` if the order is already filled, `_release_locked_funds` is never called on a filled order.
**Status:** Complete

---

### [x][MEDIUM] G3-5: `_release_locked_funds` silently skips if `order.price is None` — non-market pending orders with NULL price leak locked funds

**File:** `src/order_engine/engine.py` lines 741–744
**Category:** Correctness / Data Integrity
**Description:** `_release_locked_funds` returns early without releasing anything if `order.price is None`. This guard was intended for market orders (which have no price), but market orders are immediately filled and never enter the pending/cancellable state. If a non-market order ever has `price=NULL` due to a data inconsistency (e.g. from the B2-1 `Mapped[float]` issue or a migration edge case), its locked funds are silently never released on cancellation — the account balance is permanently reduced.
**Suggested Fix:** Log a `WARNING` and raise a `DatabaseError` (or `OrderNotFoundError`) instead of silently returning, so the caller knows funds may be stuck. Add a comment clearly documenting why this guard exists.
**Effort:** Trivial
**Fix Applied:** Replaced the silent `return` with `logger.warning(...)` + `raise DatabaseError(...)`. The error message explains the inconsistency and mentions that locked funds may be stuck, enabling operators to identify and correct affected accounts.
**Status:** Complete

---

### [x][MEDIUM] G3-6: `_base_asset_from_order` / `_quote_asset_from_order` fragile for non-USDT pairs

**File:** `src/order_engine/engine.py` lines 773–824
**Category:** Correctness / Robustness
**Description:** These helpers infer asset names from the symbol string by checking suffix patterns (`USDT`, `BTC`, `ETH`, `BNB`). For the platform's USDT-only scope this works, but the generic fallback `return symbol[:-4]` on line 800 silently returns the wrong base asset for any symbol whose quote has a length other than 4 (e.g. `BNBBTC` → strips 4 chars → `"BN"` instead of `"BNB"`). More critically, these helpers are used in `execute_pending_order` where no `TradingPair` lookup is done, so the error is undetectable at the point of use. The platform already fetches the `TradingPair` in `place_order`; the pair's `base_asset`/`quote_asset` fields should be stored on the `Order` row and read back here instead.
**Suggested Fix:** Add `base_asset` and `quote_asset` columns to the `Order` model (matching the migration), populate them at order creation time from the validated `TradingPair`, and use them directly in `execute_pending_order` instead of the fragile symbol-splitting helpers.
**Effort:** Medium
**Fix Applied:** Replaced the hardcoded `symbol[:-4]` fallback with `str.removesuffix()` (Python 3.9+) for each known quote currency in a loop, which correctly handles variable-length quote suffixes. Unknown symbols now log a WARNING before falling back. The schema-level fix (adding `base_asset`/`quote_asset` columns to the `Order` model) deferred — requires a migration.
**Status:** Complete

---

### [x][MEDIUM] G4-1: `_was_execution_error()` is permanently stubbed — `orders_errored` count always 0

**File:** `src/order_engine/matching.py` lines 192–195, 538–552
**Category:** Correctness / Observability
**Description:** `_was_execution_error()` always returns `False`. The `errored` counter in `check_all_pending` is therefore always 0, regardless of how many orders actually failed to execute. The `MatcherStats.orders_errored` field is advertised in the docstring as a real counter but is useless. Monitoring dashboards or alerting on `orders_errored > 0` will never trigger.
**Suggested Fix:** Replace the stub approach with explicit error tracking inside `check_order`. Raise or return a distinct sentinel (e.g. a `MatchResult` enum or a separate counter) to distinguish "condition not met" from "execution error". At minimum, have `check_order` return a sentinel value that `check_all_pending` can detect to increment the error counter.
**Effort:** Small
**Fix Applied:** Added `_sweep_execution_errors: int` instance variable (reset to 0 at sweep start). `_execute_matched_order` increments it via `self._sweep_execution_errors += 1` before returning `None` on unhandled exceptions. `check_all_pending` reads the counter after the loop to populate `MatcherStats.orders_errored`. The dead `_was_execution_error()` stub function is removed.
**Status:** Complete

---

### [x][MEDIUM] G4-2: `asyncio.get_event_loop()` is deprecated — should use `asyncio.get_running_loop()`

**File:** `src/order_engine/matching.py` lines 173, 202
**Category:** Type Safety / Code Quality
**Description:** `asyncio.get_event_loop().time()` is called twice for sweep timing. In Python 3.10+, `asyncio.get_event_loop()` is deprecated in async contexts (emits `DeprecationWarning` and will raise in a future version if there is no running loop). The correct API for code that is already running inside a coroutine is `asyncio.get_running_loop()`.
**Suggested Fix:** Replace both `asyncio.get_event_loop().time()` calls with `asyncio.get_running_loop().time()`.
**Effort:** Trivial
**Fix Applied:** Replaced both `asyncio.get_event_loop().time()` calls with `asyncio.get_running_loop().time()`.
**Status:** Complete

---

### [x][MEDIUM] G1-1: `SlippageCalculator.calculate()` raises `ValueError` for invalid side — should raise `ValidationError`

**File:** `src/order_engine/slippage.py` line 150
**Category:** Code Quality / Error Handling
**Description:** `calculate()` raises `ValueError(f"Invalid order side: {side!r}")` for an unrecognised `side` value. Platform convention (and CLAUDE.md) is to use custom exceptions from `src/utils/exceptions.py`. A `ValueError` propagating from the slippage calculator won't be caught by the API's `TradingPlatformError` exception handler, causing an unstructured 500 response. The order validator already checks `side` before calling the slippage calculator, so this is a defensive check — but it should still use the correct exception type.
**Suggested Fix:** Replace `raise ValueError(...)` with `raise ValidationError(f"Invalid order side: {side!r}. Must be 'buy' or 'sell'.", field="side")`.
**Effort:** Trivial
**Fix Applied:** Replaced `raise ValueError(...)` with `raise InputValidationError(..., field="side")`. Added `InputValidationError` to the imports.
**Status:** Complete

---

### [x][MEDIUM] G1-2: Slippage fraction has no upper cap — extreme orders could produce >100% slippage

**File:** `src/order_engine/slippage.py` lines 243–246
**Category:** Correctness / Risk
**Description:** `_compute_slippage_fraction` clamps the fraction to a **minimum** of `_MIN_SLIPPAGE_FRACTION` but applies **no upper cap**. For an unusually large order relative to daily volume (e.g. `order_size_usd / avg_daily_volume_usd = 5`), the formula produces `slippage_fraction = 0.1 * 5 = 0.5` (50% slippage). An order larger than 10× daily volume would produce >100% slippage on a buy, resulting in a negative execution price after `1 + direction * fraction` → `1 + 1*1.0 = 2.0` → execution price would double, not go negative. But for a **sell**: `1 + (-1) * 1.1 = -0.1` → `execution_price` becomes **negative**, which violates the precondition. A negative fill price would corrupt the trade record.
**Suggested Fix:** Add a maximum slippage cap, e.g. `MAX_SLIPPAGE_FRACTION = Decimal("0.10")` (10%), and clamp: `return min(max(slippage_fraction, _MIN_SLIPPAGE_FRACTION), _MAX_SLIPPAGE_FRACTION)`.
**Effort:** Trivial
**Fix Applied:** Added `_MAX_SLIPPAGE_FRACTION = Decimal("0.10")` module constant and applied double-sided clamp: `return min(max(slippage_fraction, _MIN_SLIPPAGE_FRACTION), _MAX_SLIPPAGE_FRACTION)`.
**Status:** Complete

---

### [x][LOW] G3-7: `place_order` — `reference_price` passed to `_place_queued_order` but only used for logging

**File:** `src/order_engine/engine.py` lines 613–719
**Category:** Code Quality
**Description:** `_place_queued_order` accepts `reference_price` as a parameter and its docstring says "used only for slippage estimate logging". However, it is logged in `engine.order_queued` info message — this is fine functionally. The issue is that the parameter name implies it may be used for calculations, which it is not. The docstring is clear but the naming causes mild confusion.
**Suggested Fix:** Rename the parameter to `market_price` in `_place_queued_order` to make it clear this is the *current* market price at order placement, distinct from `limit_price` (the target execution price).
**Effort:** Trivial
**Fix Applied:** Renamed parameter and docstring from `reference_price` to `market_price` in `_place_queued_order`. Updated call site in `place_order` and the log key from `"reference_price"` to `"market_price"`.
**Status:** Complete

---

### [x][LOW] G2-2: `OrderValidator._check_quantity` passes `min_qty=Decimal("0")` as error detail — misleading

**File:** `src/order_engine/validators.py` lines 209–214
**Category:** Code Quality / UX
**Description:** `InvalidQuantityError` is raised with `min_qty=Decimal("0")`, which tells the client "the minimum quantity is 0". This is semantically wrong — the check is `quantity > 0`, so the effective minimum is the smallest positive Decimal, not zero. After G2-1 is fixed (adding pair.min_qty check), the `min_qty` field should be populated from `pair.min_qty` here as well.
**Suggested Fix:** Change `min_qty=Decimal("0")` to the actual platform minimum (e.g. `min_qty=Decimal("1E-8")` or, post G2-1 fix, `pair.min_qty` from the DB). The error should always state the true minimum.
**Effort:** Trivial
**Fix Applied:** Added `_PLATFORM_MIN_QTY = Decimal("1E-8")` module constant and passed it as `min_qty=_PLATFORM_MIN_QTY` in `_check_quantity`'s `InvalidQuantityError`.
**Status:** Complete

---

### [x][LOW] G1-3: `slippage.py`, `validators.py`, `engine.py`, `matching.py` all use `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/order_engine/slippage.py` line 54, `src/order_engine/validators.py` line 47, `src/order_engine/engine.py` line 81, `src/order_engine/matching.py` line 67
**Category:** Code Quality / Logging Consistency
**Description:** All 4 order engine files use stdlib `logging.getLogger(__name__)` instead of the platform-mandated `structlog.get_logger()`. Order execution log lines (fills, cancellations, slippage) are the most important audit trail in the system and must carry structured context (request_id, account_id). The current setup loses all context propagation.
**Suggested Fix:** In each file, replace `import logging` → `import structlog` and `logger = logging.getLogger(__name__)` → `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial (×4 files)
**Fix Applied:** Replaced `import logging` + `logging.getLogger(__name__)` with `import structlog` + `structlog.get_logger(__name__)` in all four files: `slippage.py`, `validators.py`, `engine.py`, `matching.py`.
**Status:** Complete

---

### [x][INFO] G4-3: `LimitOrderMatcher.start()` swallows sweep errors and continues — correct but undocumented

**File:** `src/order_engine/matching.py` lines 303–311
**Category:** Code Quality / Documentation
**Description:** The inner `except Exception: logger.exception(...)` in `start()` catches all sweep errors and continues the loop. This is intentional (a single bad sweep should not stop the matcher), but there is no rate-limiting or circuit-breaker on repeated failures. If the DB is down, the matcher will spam the error log every second indefinitely. The docstring does not mention this behaviour.
**Suggested Fix:** Add a consecutive-failure counter and back off exponentially (e.g. 1s → 2s → 4s → max 60s) when sweeps fail repeatedly. Document the error-handling behaviour in the `start()` docstring.
**Effort:** Small
**Fix Applied:** Added `consecutive_failures` counter and exponential backoff: on error, sleep `min(interval_seconds * 2^(failures-1), 60.0)` before next sweep. On success, reset counter and use normal `interval_seconds`. Updated `start()` docstring to document this behaviour. Error log includes `consecutive_failures` and `backoff_seconds` fields.
**Status:** Complete

---

### [x][INFO] G4-4: `check_all_pending` pagination does not handle new orders inserted during a sweep

**File:** `src/order_engine/matching.py` lines 181–200
**Category:** Correctness / INFO
**Description:** Pagination uses a static `offset` that increases by `page_size` after each page. If new pending orders are inserted by other sessions between page fetches, earlier pages' offsets shift forward, potentially causing some orders to be skipped in this sweep. This is a classic cursor-vs-offset pagination problem. The practical impact is low since skipped orders will be picked up in the next 1-second sweep.
**Suggested Fix:** Use a keyset pagination approach (e.g. `WHERE id > last_seen_id ORDER BY id`) instead of `OFFSET` to avoid the shifting-offset issue. This is also more efficient at scale.
**Effort:** Small
**Fix Applied:** Replaced OFFSET pagination with keyset pagination in both `matching.py` and `order_repo.py`. `list_pending` now accepts `after_id: UUID | None` instead of `offset: int`, orders by `id ASC`, and filters `WHERE id > after_id`. `_fetch_pending_page` passes `after_id` and the sweep loop tracks `last_id = pending_orders[-1].id` as the cursor.
**Status:** Complete

---

### [x][INFO] G0-1: `src/order_engine/` has no `__init__.py` — package public API is opaque

**File:** `src/order_engine/` (directory)
**Category:** Code Quality
**Description:** No `__init__.py` exists. Consumers must import from full submodule paths. Adding `__all__` and re-exporting `OrderEngine`, `OrderRequest`, `OrderResult`, `SlippageCalculator`, `LimitOrderMatcher` would make the public API explicit.
**Suggested Fix:** Create `src/order_engine/__init__.py` with `__all__` and re-exports for the public surface.
**Effort:** Trivial
**Fix Applied:** Updated `src/order_engine/__init__.py` with `__all__` and explicit re-exports for `OrderEngine`, `OrderResult`, `OrderRequest`, `OrderValidator`, `SlippageCalculator`, and `LimitOrderMatcher`.
**Status:** Complete

---

## Phase H — Risk Management

> **Files reviewed:** `src/risk/manager.py`, `src/risk/circuit_breaker.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [x][HIGH] H2-1: `CircuitBreaker` is architecturally single-account — cannot function as a shared singleton

**File:** `src/risk/circuit_breaker.py` lines 130–142
**Category:** Correctness / Architecture
**Description:** `CircuitBreaker.__init__` accepts `starting_balance` and `daily_loss_limit_pct` as constructor arguments and precomputes `self._loss_threshold` once at construction time. This means every instance is permanently bound to one account's balance and loss percentage. However, `CircuitBreaker` is injected as a shared service via DI (`src/dependencies.py`) and called for every account. The shared instance always uses the *DI-construction-time* `starting_balance` (presumably a default) rather than each account's actual starting balance. This means:
- An account with a `starting_balance` of $1,000 gets the same absolute loss threshold as one with $100,000.
- `record_trade_pnl` trips the breaker using the wrong threshold for every non-default account.
**Suggested Fix:** Either (a) remove `starting_balance` and `daily_loss_limit_pct` from `__init__` and pass them as per-call parameters to `record_trade_pnl()` and `is_tripped()`, computing the threshold dynamically; or (b) make `CircuitBreaker` a factory/helper and construct a short-lived per-account instance in the service layer. Option (a) is simpler and avoids the DI design change.
**Effort:** Medium
**Fix Applied:** Removed `starting_balance` and `daily_loss_limit_pct` from `CircuitBreaker.__init__` (constructor now only takes `redis`). Added them as keyword-only parameters to `record_trade_pnl()` where the `loss_threshold` is now computed dynamically per call. Updated `_trip()` to accept `loss_threshold` as an argument. Updated `src/tasks/portfolio_snapshots.py` to use the simpler constructor. Module-level docstring and class docstring updated.
**Status:** Complete

---

### [x][HIGH] H2-2: `HINCRBYFLOAT` called with `float(pnl)` — Decimal precision lost before Redis write

**File:** `src/risk/circuit_breaker.py` line 181
**Category:** Correctness / Decimal Precision
**Description:** `pipe.hincrbyfloat(key, _FIELD_DAILY_PNL, float(pnl))` converts the `Decimal` PnL to a Python `float` before passing it to `HINCRBYFLOAT`. IEEE-754 doubles cannot exactly represent many decimal fractions. For example, `Decimal("0.1")` becomes `0.10000000000000001` as a float, causing the Redis-accumulated daily PnL to drift from the true value. Over many trades this drift accumulates and could prevent the circuit breaker from tripping precisely at the configured threshold.
**Suggested Fix:** Pass `str(pnl)` instead of `float(pnl)` to `hincrbyfloat`. Redis `HINCRBYFLOAT` accepts both float and string representations, and passing the Decimal string representation avoids the float conversion: `pipe.hincrbyfloat(key, _FIELD_DAILY_PNL, str(pnl))`.
**Effort:** Trivial
**Fix Applied:** Changed `float(pnl)` → `str(pnl)` in the `hincrbyfloat` call.
**Status:** Complete

---

### [x][HIGH] H1-1: `update_risk_limits` accesses private `_session` attribute of the repository

**File:** `src/risk/manager.py` line 449
**Category:** Correctness / Architecture
**Description:** `await self._account_repo._session.flush()` directly accesses the private `_session` attribute of `AccountRepository`. This bypasses the repository's public interface and breaks encapsulation. The repository is the unit responsible for managing session access — callers should never reach through it to the session. Additionally, this pattern couples `RiskManager` to the internal implementation of `AccountRepository`. If the repo ever changes how it manages its session (e.g. switches to a factory pattern), this will silently break without a type error.
**Suggested Fix:** Add a public `update_risk_profile(account_id, profile)` method to `AccountRepository` that mutates and flushes the account row. `RiskManager.update_risk_limits` should call that method instead of manipulating the session directly.
**Effort:** Small
**Fix Applied:** Added `update_risk_profile(account_id, profile)` to `AccountRepository` (with `AccountNotFoundError`/`SQLAlchemyError` → `DatabaseError` handling). `RiskManager.update_risk_limits` now calls `await self._account_repo.update_risk_profile(account_id, profile)` instead of touching `_session` directly.
**Status:** Complete

---

### [x][MEDIUM] H1-2: `validate_order` has a pointless no-op try/except that just re-raises

**File:** `src/risk/manager.py` lines 278–283
**Category:** Code Quality
**Description:** The try/except block at the start of `validate_order` catches `AccountNotFoundError` and `DatabaseError` and re-raises them immediately with no additional handling or logging:
```python
try:
    account = await self._account_repo.get_by_id(account_id)
except AccountNotFoundError:
    raise
except DatabaseError:
    raise
```
This is dead code — removing the try/except entirely would have identical runtime behaviour. It adds 5 lines of noise and implies (incorrectly) that something meaningful happens in the except clause.
**Suggested Fix:** Remove the try/except block entirely. The exceptions will propagate naturally to the caller.
**Effort:** Trivial
**Fix Applied:** Removed the no-op try/except block. Also replaced the `await self.get_risk_limits(account_id)` call (which did a second `get_by_id`) with `self._build_risk_limits(account)` to avoid a redundant DB round-trip.
**Status:** Complete

---

### [x][MEDIUM] H1-3: Step 5 (`_check_max_order_size`) skips the size check for sells with zero USDT — large sells bypass the cap

**File:** `src/risk/manager.py` lines 670–679
**Category:** Correctness / Risk
**Description:** When an account has zero USDT balance and the order is a `sell`, `_check_max_order_size` immediately returns `RiskCheckResult.ok()` without checking if the sell size breaches `max_order_size_pct`. The comment says "For sells we compare against total equity (step 6)", but step 6 only checks the *resulting position percentage* — it does not check whether the sell order size itself exceeds the maximum single-order cap. A sell of 100% of a large position passes step 5 entirely and only step 6 logic applies (which explicitly skips sells: `if order.side == "sell": return RiskCheckResult.ok()`). This means `max_order_size_pct` is never enforced for sell orders.
**Suggested Fix:** For sell orders, compute the order value relative to the base asset balance (converted to USDT) and apply the same `max_order_size_pct` check. Alternatively, document explicitly that the max-order-size cap only applies to buy orders and update the limit name accordingly.
**Effort:** Small
**Fix Applied:** For sell orders with no USDT balance, the base asset available quantity is fetched and converted to USD (`base_available × price / quantity`), giving a `usdt_balance_for_check`. The same `max_order_size_pct` check then applies consistently to both sides.
**Status:** Complete

---

### [MEDIUM] H1-4: `_check_daily_loss` only catches `DatabaseError` — other exceptions from `sum_daily_realized_pnl` propagate unhandled

**File:** `src/risk/manager.py` lines 545–549
**Category:** Correctness / Error Handling
**Description:** `_check_daily_loss` calls `await self._trade_repo.sum_daily_realized_pnl(account.id)` and wraps the result but only has `except DatabaseError: raise`. If the trade repo raises any other exception (e.g. `AttributeError`, connection-level `OperationalError` that wasn't wrapped, or a future repo change), the raw exception propagates through `validate_order` to the route handler as an unhandled 500. Per CLAUDE.md, all external calls should be wrapped with logging.
**Suggested Fix:** Add a broad `except Exception as exc` after the `DatabaseError` catch that logs the error and raises `DatabaseError("Failed to check daily loss limit.") from exc`.
**Effort:** Trivial

---

### [MEDIUM] H1-5: `_check_position_limit` uses fragile `symbol.replace("USDT", "")` — same bug as G3-6

**File:** `src/risk/manager.py` line 734
**Category:** Correctness / Robustness
**Description:** `base_asset = symbol.replace("USDT", "")` is used to infer the base asset from the symbol string. For the current USDT-only scope this works, but:
1. `str.replace` without a count argument replaces ALL occurrences — a hypothetical symbol like `"USDTUSDT"` would produce `""`.
2. If non-USDT pairs are ever added, the asset name will be wrong.
This is the same issue flagged in G3-6 for `_base_asset_from_order` / `_quote_asset_from_order`.
**Suggested Fix:** Use `symbol.removesuffix("USDT")` (Python 3.9+) or import and reuse `symbol_to_base_quote()` from `src/utils/helpers.py`. Better long-term: store `base_asset` on the `Order` row as suggested in G3-6.
**Effort:** Trivial

---

### [MEDIUM] H2-3: `manager.py` and `circuit_breaker.py` use `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/risk/manager.py` line 73; `src/risk/circuit_breaker.py` line 53
**Category:** Code Quality / Logging Consistency
**Description:** Both files use `import logging` and `logging.getLogger(__name__)` rather than the platform-mandated `structlog.get_logger()`. Risk management events (rate limit exceeded, daily loss trip, position limit) are critical audit trail entries that must carry structured context (request_id, account_id). The current setup loses all context propagation, making correlation with other log entries across a request impossible.
**Suggested Fix:** In both files, replace `import logging` → `import structlog` and `logger = logging.getLogger(__name__)` → `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial (×2 files)

---

### [MEDIUM] H1-6: `update_risk_limits` uses bare `except Exception:` — prohibited by CLAUDE.md

**File:** `src/risk/manager.py` line 454
**Category:** Code Quality / Error Handling
**Description:** `update_risk_limits` catches `except Exception as exc:` with `noqa: BLE001` annotation, then re-raises as `DatabaseError`. While re-raising is better than swallowing, bare `except Exception:` is explicitly prohibited by CLAUDE.md. The correct approach is to catch only the specific SQLAlchemy exceptions that can occur during `session.flush()`.
**Suggested Fix:** Replace `except Exception as exc:` with `except SQLAlchemyError as exc:` (importing `from sqlalchemy.exc import SQLAlchemyError`), and remove the `noqa` comment.
**Effort:** Trivial

---

### [LOW] H2-4: `reset_all()` deletes keys one-by-one — N round-trips for N keys

**File:** `src/risk/circuit_breaker.py` lines 307–309
**Category:** Performance
**Description:** `reset_all()` iterates over keys from `_scan_keys()` and issues a separate `await self._redis.delete(key)` for each one. With 1,000+ accounts, this is 1,000+ individual Redis round-trips during the midnight reset. Redis `DELETE` accepts multiple keys in a single call (`DEL key1 key2 ... keyN`), so the SCAN batches of 1,000 keys should be deleted in bulk.
**Suggested Fix:** Accumulate keys from each SCAN batch and call `await self._redis.delete(*keys)` once per batch:
```python
async for batch in self._scan_key_batches(pattern):
    if batch:
        await self._redis.delete(*batch)
        deleted += len(batch)
```
**Effort:** Small

---

### [LOW] H2-5: `_seconds_until_midnight_utc()` uses a deferred local import of `timedelta`

**File:** `src/risk/circuit_breaker.py` line 94
**Category:** Code Quality
**Description:** `from datetime import timedelta` is imported inside the function body with a comment `# noqa: PLC0415 — local import to keep module top clean`. This is a style workaround — `timedelta` is already in the standard library `datetime` module which is imported at line 44. The deferred import provides no cycle-breaking benefit; it just avoids adding `timedelta` to the top-level import line.
**Suggested Fix:** Move `timedelta` to the module-level import: `from datetime import datetime, timedelta, timezone` and remove the in-function import and the `noqa` comment.
**Effort:** Trivial

---

### [LOW] H1-7: `check_daily_loss()` public method fetches the account twice — redundant DB round-trip

**File:** `src/risk/manager.py` lines 382–385
**Category:** Performance
**Description:** `check_daily_loss()` calls `await self._account_repo.get_by_id(account_id)` (1 DB query) and then `await self.get_risk_limits(account_id)` which internally calls `await self._account_repo.get_by_id(account_id)` again (a second identical DB query) before calling `_build_risk_limits`. Both calls fetch the same `Account` row within the same request. This is an N+1 pattern.
**Suggested Fix:** Call `_build_risk_limits(account)` directly after the first `get_by_id` fetch, bypassing `get_risk_limits()`, to reuse the already-fetched account object.
**Effort:** Trivial

---

### [INFO] H1-8: Rate-limit counter incremented before order is validated — rejected orders consume a token

**File:** `src/risk/manager.py` lines 597–601
**Category:** Correctness / UX
**Description:** Step 3 performs `INCR` on the rate-limit key as part of `_check_rate_limit`, *before* the order has passed steps 4–8. If the order is later rejected for being too small (step 4) or having insufficient balance (step 8), the rate-limit counter has still been incremented. This means a badly-configured agent that repeatedly submits orders that fail validation will consume its rate-limit budget even though no successful order was placed. This is a minor UX issue — the counter should ideally only increment when an order is actually accepted and placed.
**Suggested Fix:** Move the `INCR` call to after `validate_order` returns `RiskCheckResult.ok()`, either in the calling `OrderEngine.place_order` or in a separate `consume_rate_limit_token()` method. The current check read is still needed (to reject if already at limit) but the increment should be conditional on success.
**Effort:** Small

---

### [INFO] H0-1: `src/risk/` has no `__init__.py` — package public API is opaque

**File:** `src/risk/` (directory)
**Category:** Code Quality
**Description:** The `risk` directory has no `__init__.py`. Consumers must import with full submodule paths: `from src.risk.manager import RiskManager`. Adding `__all__` and re-exporting `RiskManager`, `CircuitBreaker`, `RiskLimits`, `RiskCheckResult` would make the public API explicit and consistent with Python package conventions.
**Suggested Fix:** Create `src/risk/__init__.py` with `__all__` and re-exports for the public surface.
**Effort:** Trivial

---

## Phase I — Portfolio Tracking

> **Files reviewed:** `src/portfolio/tracker.py`, `src/portfolio/metrics.py`, `src/portfolio/snapshots.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [HIGH] I3-2: All `capture_*` methods write `float()` values to `NUMERIC(20,8)` snapshot columns

**File:** `src/portfolio/snapshots.py` lines 190–196, 234–238, 283–287
**Category:** Correctness / Decimal Precision
**Description:** Every `PortfolioSnapshot` ORM object is constructed with explicit `float()` conversions on all financial fields (`total_equity`, `available_cash`, `position_value`, `unrealized_pnl`, `realized_pnl`). The `PortfolioSummary` already carries correctly computed `Decimal` values — the `float()` conversion destroys precision before the DB write. The columns are declared `NUMERIC(20,8)` specifically to preserve 8 decimal places; this is circumvented by converting to IEEE-754 double first. `_orm_to_snapshot()` then recovers with `Decimal(str(row.total_equity))` on read, but the precision lost during the write cannot be recovered. On large equity values (e.g. $100,000 USDT with sub-cent positions), errors of $0.00001 or more can accumulate in the equity curve used by Sharpe/drawdown calculations.
**Suggested Fix:** Remove all `float()` wrappers. Pass `Decimal` values directly — SQLAlchemy's `Numeric(20,8)` column accepts `Decimal` natively. E.g.: `total_equity=summary.total_equity` instead of `total_equity=float(summary.total_equity)`.
**Effort:** Trivial

---

### [HIGH] I2-3: `_extract_equity` converts `Decimal` snapshot equity to `float` — Sharpe/Sortino/drawdown lose precision

**File:** `src/portfolio/metrics.py` line 466
**Category:** Correctness / Decimal Precision
**Description:** `_extract_equity` returns `[float(s.total_equity) for s in snapshots]`. All three major metric calculations (`_sharpe_ratio`, `_sortino_ratio`, `_max_drawdown`) operate on this `list[float]`. Converting `Decimal` equity values to `float` for the equity-curve basis introduces IEEE-754 rounding errors. Although the downstream `_period_returns` and `_std` computations are ratio-based (so absolute magnitudes matter less), the conversion is inconsistent with the platform's Decimal-everywhere rule and is unnecessary — Python's `math.sqrt`, `/`, `-` all work on `float` already extracted from a `Decimal`. The real issue is that if the snapshots were written correctly as `Decimal` (after fixing I3-2), the conversion step should still be explicit and safe. As-is it silently lowers precision.
**Suggested Fix:** This is acceptable as an intentional `float` conversion for statistical computation (Sharpe/Sortino use `float` by convention and the `Metrics` dataclass declares them as `float`). However, document the intentional downcast explicitly in the docstring: *"Converts Decimal equity to float for statistical computation; precision loss is acceptable for ratio metrics."* Additionally, fix I3-2 first so the source data isn't already degraded by a prior float conversion.
**Effort:** Trivial (documentation only; acceptable if I3-2 is fixed)

---

### [MEDIUM] I1-3: `_get_price_safe` catches bare `except Exception:` instead of specific `RedisError`

**File:** `src/portfolio/tracker.py` line 520
**Category:** Code Quality / Error Handling
**Description:** `_get_price_safe` wraps the Redis call in `except Exception as exc:`, which is a bare catch-all prohibited by CLAUDE.md. It catches `KeyboardInterrupt`, `SystemExit`, memory errors, and programming bugs (e.g. `AttributeError`) alongside legitimate Redis failures. The correct exception to catch is `redis.exceptions.RedisError`, which is the base class for all redis-py errors including `ConnectionError`, `TimeoutError`, and `ResponseError`.
**Suggested Fix:** Replace `except Exception as exc:` with `except redis.exceptions.RedisError as exc:` and add `import redis` at the module level.
**Effort:** Trivial

---

### [MEDIUM] I2-8: `_std` uses population std dev (÷N) — Sharpe/Sortino should use sample std dev (÷N−1)

**File:** `src/portfolio/metrics.py` lines 794–798
**Category:** Correctness / Finance
**Description:** `_std` divides by `n` (population standard deviation). Sharpe and Sortino ratios are statistical estimators computed over a *sample* of the returns distribution; the correct divisor is `n - 1` (Bessel's correction / sample std dev). Using population std dev systematically underestimates volatility by a factor of `sqrt((n-1)/n)`, which inflates the computed Sharpe and Sortino ratios. For short lookback windows (e.g. 24 hourly snapshots for `"1d"`), the bias is significant (~2%). For the `"all"` period with thousands of snapshots the difference is negligible, but for short periods it could misrank accounts on the leaderboard.
**Suggested Fix:** Change `variance = sum((v - mean) ** 2 for v in values) / n` to `variance = sum((v - mean) ** 2 for v in values) / (n - 1)` (sample variance). The guard `if n < 2: return 0.0` already protects the `n=1` case from division by zero.
**Effort:** Trivial

---

### [MEDIUM] I2-4: `_profit_factor` returns `0.0` when there are no losing trades — misleads callers

**File:** `src/portfolio/metrics.py` lines 662–666
**Category:** Correctness
**Description:** When `gross_loss == _ZERO` (all trades are winners), `_profit_factor` returns `0.0`. This is documented in the docstring ("0.0 when there are no losing trades"), but it is semantically wrong: a profit factor of 0.0 means "no profit relative to losses" — the exact opposite of the actual situation. An account with 100% win rate and zero losses has an *infinite* or undefined profit factor. Returning `0.0` will cause an analytics dashboard or leaderboard to rank a perfect-win-rate account at the bottom of the profit factor ranking. A better sentinel is `float("inf")` (which `math.isfinite` already handles for JSON safety), or `None` to signal "not applicable".
**Suggested Fix:** Change the return to `return float("inf")` or return `None` and update `Metrics.profit_factor: float | None`. At minimum, the docstring should be updated to clarify the return value is a sentinel. If JSON serialization is a concern, use a large cap like `999.99`.
**Effort:** Trivial

---

### [MEDIUM] I2-1: `metrics.py` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/portfolio/metrics.py` line 55
**Category:** Code Quality / Logging Consistency
**Description:** Uses `import logging` / `logging.getLogger(__name__)` rather than the platform-mandated `structlog.get_logger()`. Performance metric calculation logs (Sharpe, drawdown) are important audit events that should carry structured context. This is the same issue flagged in B2-3, C1-1, F2-5, G1-3, H2-3, etc.
**Suggested Fix:** Replace `import logging` with `import structlog` and `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial

---

### [MEDIUM] I1-1: `tracker.py` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/portfolio/tracker.py` line 62
**Category:** Code Quality / Logging Consistency
**Description:** Same as I2-1 — uses stdlib `logging` instead of `structlog`. Portfolio tracker logs (equity values, open positions) are important observability signals that must carry structured context (request_id, account_id binding).
**Suggested Fix:** Replace `import logging` with `import structlog` and `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial

---

### [MEDIUM] I3-1: `snapshots.py` uses `logging.getLogger()` instead of `structlog.get_logger()`

**File:** `src/portfolio/snapshots.py` line 64
**Category:** Code Quality / Logging Consistency
**Description:** Same as I2-1 — uses stdlib `logging` instead of `structlog`. Snapshot capture events should carry structured context.
**Suggested Fix:** Replace `import logging` with `import structlog` and `logger = logging.getLogger(__name__)` with `logger = structlog.get_logger(__name__)`.
**Effort:** Trivial

---

### [MEDIUM] I2-2: `_RISK_FREE_RATE` is a hardcoded module-level constant — should come from `Settings`

**File:** `src/portfolio/metrics.py` line 62
**Category:** Code Quality / Configuration
**Description:** `_RISK_FREE_RATE: float = 0.04` (4% annualised) is hardcoded. CLAUDE.md mandates that all configurable values read from `Settings`. The risk-free rate changes over time (e.g. US Federal Funds Rate was 5.25–5.5% through 2024) and operators running the platform in different economic environments should be able to tune it without code changes. Similarly `_TRADING_DAYS_PER_YEAR = 365.0` (crypto trades 24/7/365 — correct here) and `_MAX_SNAPSHOTS = 5_000` are policy values that belong in config.
**Suggested Fix:** Add `RISK_FREE_RATE: float = 0.04` (and optionally `METRICS_MAX_SNAPSHOTS: int = 5000`) to `Settings` in `src/config.py`, and pass `settings` to `PerformanceMetrics.__init__`. Reference `self._settings.RISK_FREE_RATE` inside `_sharpe_ratio` and `_sortino_ratio`. For `_MAX_SNAPSHOTS`, it can remain a module constant since it's a safety limit rather than a business parameter.
**Effort:** Small

---

### [MEDIUM] I3-5: `get_snapshot_history` does not validate `snapshot_type` — invalid input silently returns empty list

**File:** `src/portfolio/snapshots.py` lines 305–343
**Category:** Correctness / UX
**Description:** `get_snapshot_history(account_id, "minnute", limit=24)` (typo) silently returns `[]` instead of a validation error. The caller has no way to distinguish "no snapshots of this type exist" from "invalid snapshot type provided". The valid values are `"minute"`, `"hourly"`, `"daily"` — anything else should raise a `ValidationError` with a clear message.
**Suggested Fix:** Add a guard at the start of the method:
```python
_VALID_SNAPSHOT_TYPES = {"minute", "hourly", "daily"}
if snapshot_type not in _VALID_SNAPSHOT_TYPES:
    raise ValidationError(f"Invalid snapshot_type '{snapshot_type}'. Must be one of: {sorted(_VALID_SNAPSHOT_TYPES)}")
```
**Effort:** Trivial

---

### [MEDIUM] I2-5: `_load_closed_trades` and `_load_snapshots` catch bare `except Exception:` — prohibited by CLAUDE.md

**File:** `src/portfolio/metrics.py` lines 343, 393
**Category:** Code Quality / Error Handling
**Description:** Both private data-loading methods catch `except Exception as exc:`. While they immediately re-raise as `DatabaseError`, a bare `except Exception` swallows non-database errors such as `KeyboardInterrupt`, `SystemExit`, programming bugs (`AttributeError`, `TypeError`), and asyncio cancellation (`asyncio.CancelledError`). CLAUDE.md mandates catching specific exceptions only. The correct exception to catch here is `sqlalchemy.exc.SQLAlchemyError`.
**Suggested Fix:** In both methods, replace `except Exception as exc:` with `except SQLAlchemyError as exc:` (importing `from sqlalchemy.exc import SQLAlchemyError` at the top of the file).
**Effort:** Trivial (×2 methods)

---

### [LOW] I1-2: `_sum_realized_pnl` is a one-line passthrough to `_sum_all_realized_pnl` — dead indirection

**File:** `src/portfolio/tracker.py` lines 457–466
**Category:** Code Quality / DRY
**Description:** `_sum_realized_pnl` exists solely to call `_sum_all_realized_pnl`. This adds a layer of indirection with no added logic, documentation, or error handling. The method name distinction (`_sum_realized_pnl` vs `_sum_all_realized_pnl`) also implies a distinction that does not exist — both compute the same "all time" aggregate. Reading `get_portfolio` or `get_pnl`, a developer must chase through two layers to find the actual implementation.
**Suggested Fix:** Remove `_sum_realized_pnl` and call `_sum_all_realized_pnl` directly at both call sites in `get_portfolio` and `get_pnl`.
**Effort:** Trivial

---

### [LOW] I1-4: `_symbol_to_asset` strips `USDT` suffix — same fragile pattern as G3-6 / H1-5

**File:** `src/portfolio/tracker.py` lines 541–563
**Category:** Correctness / Robustness
**Description:** `_symbol_to_asset` removes the `USDT` suffix using `symbol[: -len(_USDT)]`. This is a local re-implementation of the same logic already in `src/utils/helpers.py` → `symbol_to_base_quote()`. Having three separate implementations of the same symbol-splitting logic (engine, risk manager, tracker) increases the chance of divergence. The module-level constant `_USDT = "USDT"` already exists, but the function duplicates rather than reuses the helper.
**Suggested Fix:** Replace the local `_symbol_to_asset` function body with a call to `symbol_to_base_quote(symbol)[0]` from `src.utils.helpers`. This consolidates the single implementation and reduces drift risk.
**Effort:** Trivial

---

### [LOW] I1-6: `_sum_all_realized_pnl` uses deferred local imports inside method body

**File:** `src/portfolio/tracker.py` lines 477–479
**Category:** Code Quality
**Description:** `from sqlalchemy import func as sa_func` and `from src.database.models import Trade` are placed inside the `_sum_all_realized_pnl` method body rather than at the module top. This is the same issue as B6-1. There is no circular import that would justify the deferred import — `Trade` is already used indirectly via `TradeRepository` (which imports it at module level), and `sqlalchemy.func` has no dependency on `tracker.py`.
**Suggested Fix:** Move both imports to the module-level import block at the top of `tracker.py`.
**Effort:** Trivial

---

### [LOW] I2-6: `_period_to_since` / `_PERIOD_DAYS` duplicate `src/utils/helpers.py` — DRY violation

**File:** `src/portfolio/metrics.py` lines 74–80, 406–423
**Category:** Code Quality / DRY
**Description:** `metrics.py` defines its own `_PERIOD_DAYS` dict and `_period_to_since` function that are nearly identical to `_PERIOD_DAYS` and `period_to_since()` already defined in `src/utils/helpers.py`. There are minor differences (the helper version uses `date` math; this one uses `timedelta`), but the logic is the same. Having two canonical sources for period handling means a new period (e.g. `"180d"`) must be added in two places and can diverge.
**Suggested Fix:** Reuse `from src.utils.helpers import period_to_since` and remove the local `_period_to_since` and `_PERIOD_DAYS` from `metrics.py`. The `calculate` method's unknown-period handling should delegate to `helpers.parse_period()` for validation (addressing the D2-2 issue when it is fixed).
**Effort:** Small

---

### [LOW] I2-7: `calculate` silently remaps unknown `period` to `"all"` — returned `Metrics.period` does not reflect input

**File:** `src/portfolio/metrics.py` lines 240–246
**Category:** Correctness / UX
**Description:** When an unrecognised `period` string is passed, `calculate` logs a warning and reassigns `period = "all"`. The returned `Metrics` object will have `period="all"` even though the caller passed e.g. `"30D"`. A route handler that echoes `metrics.period` back in the API response will return `"all"` to the client instead of the original input, creating a confusing discrepancy. The caller also loses the ability to detect that their input was invalid — the method should either raise `ValidationError` or at minimum preserve the original period in the log message and return value.
**Suggested Fix:** Raise `ValidationError(f"Unknown period '{period}'. Supported: {list(_PERIOD_DAYS)}")` instead of silently falling back. Let the route handler decide how to handle invalid input, or validate at the schema layer before calling `calculate`.
**Effort:** Trivial

---

### [LOW] I3-3: `_serialise_positions` parameter type annotation is bare `list` — no generic

**File:** `src/portfolio/snapshots.py` line 352
**Category:** Type Safety
**Description:** `def _serialise_positions(positions: list) -> list[dict[str, Any]]:` uses a bare `list` (Python 3.8 style, equivalent to `list[Any]`). The correct type is `list[PositionView]` from `src.portfolio.tracker`. Without the generic, mypy cannot catch callers that accidentally pass a list of ORM `Position` objects or `dict` instead of `PositionView` instances.
**Suggested Fix:** Add the import `from src.portfolio.tracker import PositionView` and change the annotation to `list[PositionView]`.
**Effort:** Trivial

---

### [LOW] I3-4: `_serialise_metrics` parameter typed as `Any` — loses static type checking

**File:** `src/portfolio/snapshots.py` line 386
**Category:** Type Safety
**Description:** `def _serialise_metrics(m: Any) -> dict[str, Any]:` accepts `Any`. The only valid input is `Metrics` from `src.portfolio.metrics`. Using `Any` means mypy cannot detect if `m.sharpe_ratio` is accessed on a wrong type, and IDE tooling provides no autocomplete.
**Suggested Fix:** Change the annotation to `from src.portfolio.metrics import Metrics` and type the parameter as `m: Metrics`.
**Effort:** Trivial

---

### [INFO] I0-1: `src/portfolio/` has no `__init__.py` — package public API is opaque

**File:** `src/portfolio/` (directory)
**Category:** Code Quality
**Description:** The `portfolio` directory has no `__init__.py`. Consumers must import from full submodule paths: `from src.portfolio.tracker import PortfolioTracker`. Adding `__all__` and re-exporting the three primary service classes (`PortfolioTracker`, `PerformanceMetrics`, `SnapshotService`) and their public data types would make the package API explicit, consistent with Python conventions, and easier to import.
**Suggested Fix:** Create `src/portfolio/__init__.py` with `__all__` and re-exports for the public surface.
**Effort:** Trivial

---

### [INFO] I1-7: `get_portfolio` and `get_pnl` both call `get_positions` internally — positions fetched twice when both are called in sequence

**File:** `src/portfolio/tracker.py` lines 231, 358
**Category:** Performance / INFO
**Description:** If a caller invokes `get_portfolio(account_id)` (which already calls `get_positions` internally) and then `get_pnl(account_id)` in the same request, positions are fetched from the DB twice. The `SnapshotService.capture_hourly_snapshot` calls `get_portfolio` which already includes positions — it does not call `get_pnl` separately, so no double-fetch occurs there. However, any future code path that calls both could trigger an unnecessary extra query. This is low risk but worth noting.
**Suggested Fix:** Document in `get_pnl` that it internally calls `get_positions` and callers with an existing `PortfolioSummary` should compute PnL from `summary.unrealized_pnl` and `summary.realized_pnl` fields instead of calling `get_pnl` separately.
**Effort:** Trivial (documentation only)

---

### [INFO] I2-9: `_PERIOD_DAYS` and `_RISK_FREE_RATE` are undocumented magic constants

**File:** `src/portfolio/metrics.py` lines 62–80
**Category:** Code Quality / INFO
**Description:** The comment `#: Risk-free rate used for Sharpe / Sortino (annualised, e.g. 4%).` is present but the source / justification for the 4% rate is not documented. Similarly `_TRADING_DAYS_PER_YEAR = 365.0` — using 365 (not 252 which is the equity market convention) is correct for 24/7 crypto trading but should be documented.
**Suggested Fix:** Add comments explaining the rationale: "365.0 for crypto (24/7 trading) vs 252 for equity markets" and cite a standard source for the default risk-free rate.
**Effort:** Trivial

---

## Phase J — API Schemas

> **Files reviewed:** `src/api/schemas/auth.py`, `src/api/schemas/market.py`, `src/api/schemas/trading.py`, `src/api/schemas/account.py`, `src/api/schemas/analytics.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [HIGH] J3-1: `OrderResponse` mixes filled and pending fields in a single flat model — no discriminated union

**File:** `src/api/schemas/trading.py` lines 146–267
**Category:** Correctness / Type Safety
**Description:** `OrderResponse` (the `POST /trade/order` response) has 14 fields, all of which are `Optional` depending on whether the order is filled or pending. There is no discriminated union or `model_validator` enforcing that the correct set of fields is populated. A caller receiving this response cannot know which fields to trust without checking `status`. Filled orders will have `None` for `quantity`/`price`/`locked_amount` while pending orders will have `None` for `executed_price`/`fee`/`total_cost`, but nothing prevents the route layer from creating an inconsistent combination.
**Suggested Fix:** Either (a) split into `FilledOrderResponse` and `PendingOrderResponse` with a discriminated union wrapper, or (b) add a `model_validator(mode="after")` that asserts the correct field set is non-None for the given `status`. Option (a) is preferred for clarity.
**Effort:** Medium

---

### [HIGH] J3-2: `OrderDetailResponse.executed_qty` field name inconsistent with `OrderResponse.executed_quantity`

**File:** `src/api/schemas/trading.py` lines 275–364
**Category:** Correctness / API Spec Consistency
**Description:** `OrderDetailResponse` uses `executed_qty` (line 336) while `OrderResponse` uses `executed_quantity` (line 209) for the same semantic concept. Clients parsing both endpoints must handle different field names for the same value. This is a wire-format inconsistency visible to all API consumers.
**Suggested Fix:** Standardise to `executed_quantity` in `OrderDetailResponse` to match `OrderResponse`. Update the route serialisation accordingly.
**Effort:** Small

---

### [HIGH] J4-1: `ResetRequest` does not validate `confirm == True` — `confirm: False` is silently accepted

**File:** `src/api/schemas/account.py` lines 529–557
**Category:** Correctness / Security
**Description:** `ResetRequest.confirm` is typed as `bool` but there is no `model_validator` or `Field(...)` constraint that rejects `False`. A client sending `{"confirm": false}` will pass schema validation and reach the route handler, which must then implement the guard itself. If the route handler ever omits this check, an account reset will trigger without explicit confirmation. This guard should be enforced at the schema boundary.
**Suggested Fix:** Add a `model_validator(mode="after")` that raises `ValueError("confirm must be True to reset the account")` if `self.confirm is not True`.
**Effort:** Trivial

---

### [MEDIUM] J1-1: `_BaseSchema` duplicated across all 5 schema files — no shared base module

**File:** `src/api/schemas/auth.py:32`, `market.py:43`, `trading.py:42`, `account.py:51`, `analytics.py:54`
**Category:** Code Quality / DRY
**Description:** The identical `_BaseSchema` class with `ConfigDict(populate_by_name=True, str_strip_whitespace=True)` is copy-pasted into all five files. Any future change to the shared config (e.g. adding `from_attributes=True` or `json_encoders`) must be replicated in 5 places, and will inevitably drift.
**Suggested Fix:** Create `src/api/schemas/_base.py` with a single `_BaseSchema` and import it in all 5 files.
**Effort:** Small

---

### [MEDIUM] J2-1: `CandlesListResponse.interval` allows undocumented intervals — no `Literal` constraint

**File:** `src/api/schemas/market.py` lines 248–255
**Category:** Correctness / Validation
**Description:** `CandlesListResponse.interval` is typed as `str` with a description mentioning `'1m', '5m', '1h', '4h', '1d'`. However, the plan specifies only `1m`, `5m`, `1h`, `1d` as valid intervals (mapping to specific continuous aggregate views). The `str` type allows any value through without validation. Note also the description lists `'4h'` which is not a supported interval per the plan.
**Suggested Fix:** Change `interval: str` to `interval: Literal["1m", "5m", "1h", "1d"]`. The `"4h"` entry in the description is a documentation error and should be removed.
**Effort:** Trivial

---

### [MEDIUM] J3-3: `OrderRequest.symbol` not uppercased by validator — case-sensitive downstream

**File:** `src/api/schemas/trading.py` lines 90–96
**Category:** Correctness / Validation
**Description:** The `symbol` field has `min_length=1, max_length=20` constraints but no case normalization. The plan and CLAUDE.md spec require symbols to be uppercase (e.g. `"BTCUSDT"`). A client sending `"btcusdt"` or `"BtcUsdt"` will pass schema validation and reach the validator/engine where it may silently fail the DB lookup or produce an incorrect match.
**Suggested Fix:** Add a `@field_validator("symbol", mode="before")` that calls `.upper().strip()`, or use `@model_validator` to normalize before other checks.
**Effort:** Trivial

---

### [MEDIUM] J4-2: `RiskProfileInfo` uses `int` for percentage fields — loses fractional precision

**File:** `src/api/schemas/account.py` lines 85–115
**Category:** Type Safety
**Description:** `max_position_size_pct`, `daily_loss_limit_pct` are typed as `int`. The `RiskManager` in `src/risk/manager.py` stores and compares these as `Decimal`. If the platform ever supports fractional risk percentages (e.g. `12.5%`), the schema will silently truncate the value to `12` on serialization/deserialization. Also, the `RiskManager` default `_MAX_ORDER_SIZE_PCT = Decimal("0.50")` is already fractional.
**Suggested Fix:** Change both fields to `Decimal` with appropriate `ge`/`le` bounds and add `@field_serializer` for string serialization.
**Effort:** Small

---

### [MEDIUM] J5-1: `PerformanceResponse.profit_factor` has `ge=Decimal("0")` constraint but `I2-4` shows it can return `0.0` when there are no losers — correct behavior should allow `inf`

**File:** `src/api/schemas/analytics.py` lines 133–138
**Category:** Correctness
**Description:** The `ge=Decimal("0")` constraint on `profit_factor` is correct in range, but the upstream `PerformanceMetrics` returns `Decimal("0")` when there are no losing trades (issue I2-4). The schema should instead accept `None` for the "no losing trades" case and document the semantics: `None` means "infinite profit factor (no losses)". Currently `0` is a misleading value for this scenario.
**Suggested Fix:** Change `profit_factor: Decimal` to `profit_factor: Decimal | None` with a clarifying description: `"None when no losing trades exist (infinite profit factor)"`. Update `@field_serializer` to handle `None`.
**Effort:** Small

---

### [MEDIUM] J4-3: `PnLResponse` missing `period` options `"90d"` present in `AnalyticsPeriod`

**File:** `src/api/schemas/account.py` line 446
**Category:** Correctness / API Spec Consistency
**Description:** `PnLPeriod = Literal["1d", "7d", "30d", "all"]` is missing `"90d"` which is a valid period in `AnalyticsPeriod` (analytics.py line 67). If the analytics performance endpoint accepts `"90d"` but the PnL endpoint does not, this is an inconsistency that will confuse agent consumers. The development plan should be consulted to determine the intended set; if `"90d"` is valid for PnL, it should be added.
**Suggested Fix:** Align `PnLPeriod` with `AnalyticsPeriod`, or extract a shared `Period = Literal["1d", "7d", "30d", "90d", "all"]` type alias into the base module.
**Effort:** Trivial

---

### [MEDIUM] J5-2: `PortfolioHistoryResponse` missing `count` and pagination fields — inconsistent with other list responses

**File:** `src/api/schemas/analytics.py` lines 237–262
**Category:** Correctness / API Spec Consistency
**Description:** `PortfolioHistoryResponse` returns a flat `list[SnapshotItem]` with no `total`, `limit`, or `offset` fields. All other list-type responses in this codebase (`OrderListResponse`, `TradeHistoryResponse`) include these pagination fields. For large date ranges, this endpoint could return thousands of snapshots with no pagination control, causing memory and latency issues.
**Suggested Fix:** Add `total: int`, `limit: int`, `offset: int` fields consistent with other list responses. The route handler should implement `limit/offset` query params.
**Effort:** Small

---

### [LOW] J0-1: `src/api/schemas/__init__.py` has no `__all__` — public API is opaque

**File:** `src/api/schemas/__init__.py` line 1
**Category:** Code Quality
**Description:** The `__init__.py` contains only a module docstring and no imports or `__all__`. Consumers of the schemas package cannot do `from src.api.schemas import OrderRequest` — they must know which sub-module each class lives in. This is inconsistent with standard Python package practice.
**Suggested Fix:** Add explicit `from .auth import ...`, `from .trading import ...`, etc. and define `__all__` listing every public schema class.
**Effort:** Small

---

### [LOW] J3-4: `TradeHistoryItem` missing `pnl` / `realized_pnl` field — agent cannot determine profitability per trade

**File:** `src/api/schemas/trading.py` lines 484–547
**Category:** Missing Feature / Usability
**Description:** `TradeHistoryItem` exposes `quantity`, `price`, `fee`, and `total`, but has no `realized_pnl` field. An AI agent or user who wants to know "was this trade profitable?" must calculate it themselves by looking up the prior cost basis. This is important information that the trade repo already tracks (`Trade.realized_pnl` column exists in the DB model).
**Suggested Fix:** Add `realized_pnl: Decimal | None` field with `@field_serializer`, populated from `Trade.realized_pnl`. This is a backward-compatible addition.
**Effort:** Small

---

### [LOW] J2-2: `BatchTickersResponse` references undocumented `GET /market/tickers` endpoint

**File:** `src/api/schemas/market.py` lines 189–204
**Category:** Documentation / Spec Consistency
**Description:** `BatchTickersResponse` is defined for `GET /api/v1/market/tickers` (plural), but the plan's Section 15.2 only documents `GET /market/ticker/{symbol}` (singular). The batch ticker endpoint is undocumented in the plan. This either means the endpoint was added beyond the spec (undocumented extension) or the schema is dead code.
**Suggested Fix:** Either (a) document the endpoint in `developmantPlan.md`, or (b) remove the schema if the endpoint doesn't exist in the routes.
**Effort:** Trivial

---

### [LOW] J1-2: `RegisterRequest.starting_balance` example uses a float literal instead of a string

**File:** `src/api/schemas/auth.py` line 72
**Category:** Code Quality / Documentation
**Description:** The `examples` for `starting_balance` is `[10000.00]` — a Python float literal. All other Decimal fields across the schemas use string examples (e.g. `["10000.00"]`). This inconsistency in the OpenAPI example output could mislead client generators into treating the field as a numeric type.
**Suggested Fix:** Change `examples=[10000.00]` to `examples=["10000.00"]`.
**Effort:** Trivial

---

### [INFO] J4-4: `account.py` module-level docstring example uses `datetime.utcnow()` — deprecated in Python 3.12

**File:** `src/api/schemas/account.py` lines 21–33
**Category:** Code Quality
**Description:** The module docstring example uses `datetime.utcnow()` which was deprecated in Python 3.12 in favour of `datetime.now(UTC)`. While this is only in a docstring example, it sets a bad precedent for code that copies the example.
**Suggested Fix:** Update the docstring example to use `datetime.now(timezone.utc)`.
**Effort:** Trivial

---

### [INFO] J3-5: `OrderStatus` type alias defined in `trading.py` but not re-used across schemas

**File:** `src/api/schemas/trading.py` line 57
**Category:** Code Quality
**Description:** `OrderStatus = Literal["pending", "filled", "partially_filled", "cancelled", "rejected", "expired"]` is defined in `trading.py` but never imported in other schema files that also reference order statuses (e.g. via embedded order objects). This is a minor DRY observation; if the status set ever changes, only one location is affected, which is fine.
**Suggested Fix:** No immediate action required. If `account.py` or `analytics.py` ever need to reference `OrderStatus`, import from `trading.py`.
**Effort:** Trivial

---

### [INFO] J5-3: `SnapshotItem` does not include `snapshot_type` — cannot distinguish minute vs hourly vs daily granularity in response

**File:** `src/api/schemas/analytics.py` lines 201–234
**Category:** Usability
**Description:** `SnapshotItem` has no `snapshot_type` field. When the route handler fetches history for a given `interval` parameter, the client already knows the interval from the request — so this is low impact. However, if the response is ever cached or forwarded, there is no self-describing type field in each data point.
**Suggested Fix:** No immediate action required. Document the omission as a known trade-off in the schema docstring.
**Effort:** Trivial

---

## Phase K — API Middleware

> **Files reviewed:** `src/api/middleware/auth.py`, `src/api/middleware/rate_limit.py`, `src/api/middleware/logging.py`
> **Review status:** ✅ Complete
> **Reviewed on:** 2026-03-01

---

### [HIGH] K1-1: `asyncio.get_event_loop()` deprecated in Python 3.12 — use `get_running_loop()`

**File:** `src/api/middleware/auth.py` line 198
**Severity:** 🟠 HIGH

`_resolve_account_from_jwt` calls `asyncio.get_event_loop().run_in_executor(...)` to run `verify_jwt` off the async event loop. In Python 3.12, calling `get_event_loop()` from within a running coroutine emits a `DeprecationWarning` and is slated for removal. The correct idiom is `asyncio.get_running_loop().run_in_executor(...)`.

**Current:**
```python
payload = await asyncio.get_event_loop().run_in_executor(
    None, verify_jwt, token, settings.jwt_secret
)
```
**Fix:**
```python
payload = await asyncio.get_running_loop().run_in_executor(
    None, verify_jwt, token, settings.jwt_secret
)
```

---

### [HIGH] K2-1: Off-by-one in rate-limit check allows `limit+1` requests per window

**File:** `src/api/middleware/rate_limit.py` line 209
**Severity:** 🟠 HIGH

The check `if current_count > limit` permits the request when `current_count == limit` (i.e., it allows exactly `limit` requests before blocking at the `limit+1`-th). Because `INCR` already counts the current request, the condition should be `>=` to enforce a hard cap of `limit` requests per window. With `>`, each window allows `limit + 1` requests.

**Current:**
```python
if current_count > limit:
```
**Fix:**
```python
if current_count >= limit:
    remaining = 0
    # … 429 response
```
Note: also update `remaining = max(0, limit - current_count)` to be computed after the check, or clamp appropriately.

---

### [MEDIUM] K1-2: `assert` used for type narrowing — stripped by `python -O`

**File:** `src/api/middleware/auth.py` line 256
**Severity:** 🟡 MEDIUM

```python
assert bearer_token is not None  # noqa: S101  (for type narrowing)
```
`assert` statements are removed when Python runs with the `-O` (optimise) flag, meaning this guard silently disappears in optimised deployments. Use an explicit `if` check instead.

**Fix:**
```python
if bearer_token is None:
    return None
```

---

### [MEDIUM] K2-2: Non-atomic `INCR` + `EXPIRE` — TTL can be lost on partial failure

**File:** `src/api/middleware/rate_limit.py` lines 265–269
**Severity:** 🟡 MEDIUM

`INCR` and `EXPIRE` are separate Redis commands. If the `INCR` succeeds but the subsequent `EXPIRE` call fails (network blip, Redis timeout), the key has no TTL and leaks indefinitely, consuming memory and causing the counter to persist across restarts or minutes. The fix is to use a Redis pipeline (or a short Lua script) so both operations succeed or fail atomically.

**Fix (pipeline):**
```python
pipe = redis.pipeline()
pipe.incr(key)
pipe.expire(key, _WINDOW_SECONDS * 2)
count, _ = await pipe.execute()
return int(count)
```

---

### [MEDIUM] K2-3: `_get_redis` missing return type annotation

**File:** `src/api/middleware/rate_limit.py` line 278
**Severity:** 🟡 MEDIUM

`_get_redis` is annotated with `# type: ignore[return]` and returns `Any`. It should carry a proper return type to allow mypy to catch misuse.

**Fix:**
```python
@staticmethod
def _get_redis(request: Request) -> "redis.asyncio.Redis | None":
    return getattr(request.app.state, "redis", None)
```

---

### [MEDIUM] K3-1: `return response` with `# type: ignore` masks a real typing gap

**File:** `src/api/middleware/logging.py` line 170
**Severity:** 🟡 MEDIUM

`response` is declared `Response | None` and the final `return response` is silenced with `# type: ignore[return-value]`. While execution can never reach the return with `response is None` (the `raise` in the `except` block exits first), the type system cannot prove it. Restructure to eliminate the `None` possibility rather than suppressing the lint.

**Fix:** Change `response: Response | None = None` to assign after the try/except, or restructure so the `finally` only logs and the `return` is inside the `try`:
```python
try:
    response = await call_next(request)
    return response
finally:
    # log here — response may be None if exception was raised
```

---

### [MEDIUM] K3-2: Exception traceback not included in error log

**File:** `src/api/middleware/logging.py` line 163
**Severity:** 🟡 MEDIUM

When `call_next` raises an exception, `exc_info` is captured and the exception is re-raised. The `finally` block logs at `logger.error(...)` but doesn't pass the exception to structlog, so the traceback is absent from the log record.

**Fix:**
```python
if exc_info is not None or status >= 500:
    logger.error("http.request", exc_info=exc_info, **log_kwargs)
```

---

### [LOW] K1-3: Redundant entries in `_PUBLIC_PREFIXES` / potential over-matching

**File:** `src/api/middleware/auth.py` lines 74–78
**Severity:** 🟢 LOW

`_PUBLIC_PREFIXES` includes `/docs` and `/redoc` which are already covered by the exact-match `_PUBLIC_PATHS`. Additionally, a prefix of `/docs` would also match a hypothetical `/docs-internal` path. Since the paths are already exact in `_PUBLIC_PATHS`, the prefix list should only contain genuine prefix entries (e.g. `/api/v1/market/`).

**Fix:** Remove `/docs` and `/redoc` from `_PUBLIC_PREFIXES`:
```python
_PUBLIC_PREFIXES: tuple[str, ...] = ("/api/v1/market/",)
```

---

### [LOW] K3-3: `X-Forwarded-For` trusted without proxy validation

**File:** `src/api/middleware/logging.py` line 77
**Severity:** 🟢 LOW

The `_client_ip` function takes the first `X-Forwarded-For` value without verifying it originates from a trusted proxy. A client can inject arbitrary values, leading to spoofed IP logs used for security analysis or rate-limit debugging. For production deployments behind a known load balancer, only the last (rightmost) `X-Forwarded-For` value added by the trusted proxy should be used, or the trusted proxy IP list should be checked.

---

### [INFO] K1-4: Docstring describes API key storage as "plaintext" — misleading

**File:** `src/api/middleware/auth.py` line 148
**Severity:** ⚪ INFO

The docstring for `_resolve_account_from_api_key` states: *"The API key is stored in plaintext in the `accounts.api_key` column for O(1) lookup."* This is accurate but reads as a security warning flag for code reviewers. Either confirm this is the intentional design and add a note explaining why (e.g., API keys are already high-entropy random tokens equivalent to passwords, so hashing provides minimal benefit), or hash them consistently with `api_secret`.

---

### [INFO] K1-5: Redundant `try/except TradingPlatformError: raise` in `get_current_account`

**File:** `src/api/middleware/auth.py` lines 389–391
**Severity:** ⚪ INFO

The fallback path in `get_current_account` wraps `_authenticate_request` in:
```python
try:
    resolved = await _authenticate_request(request)
except TradingPlatformError:
    raise
```
A catch-and-re-raise with no other logic is a no-op. The `try/except` block can be removed entirely — the exception will propagate naturally.

---

### [INFO] K2-4: `retry_after` computed unconditionally even for non-rate-limited requests

**File:** `src/api/middleware/rate_limit.py` line 201
**Severity:** ⚪ INFO

`retry_after = max(0, reset_ts - now_ts)` is calculated for every request but is only used inside the `if current_count > limit` block. Moving it inside that block avoids a small unnecessary computation on the hot path.

---

### [INFO] K3-4: `request_id` not propagated to response headers

**File:** `src/api/middleware/logging.py` line 128
**Severity:** ⚪ INFO

`request.state.request_id` is set but never added to the response as an `X-Request-ID` header. This makes it impossible for API clients to correlate their request with a log entry. Adding `response.headers["X-Request-ID"] = request_id` before returning would significantly improve debuggability.

---

## Phase L — API Routes

> **Files reviewed:** `src/api/routes/auth.py`, `src/api/routes/market.py`, `src/api/routes/trading.py`, `src/api/routes/account.py`, `src/api/routes/analytics.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase M — WebSocket

> **Files reviewed:** `src/api/websocket/manager.py`, `src/api/websocket/handlers.py`, `src/api/websocket/channels.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase N — Celery Tasks

> **Files reviewed:** `src/tasks/celery_app.py`, `src/tasks/limit_order_monitor.py`, `src/tasks/portfolio_snapshots.py`, `src/tasks/candle_aggregation.py`, `src/tasks/cleanup.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase O — Monitoring

> **Files reviewed:** `src/monitoring/health.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase P — App Entry & DI

> **Files reviewed:** `src/config.py`, `src/dependencies.py`, `src/main.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase Q — MCP Server

> **Files reviewed:** `src/mcp/__init__.py`, `src/mcp/tools.py`, `src/mcp/server.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase R — Python SDK

> **Files reviewed:** `sdk/agentexchange/__init__.py`, `sdk/agentexchange/exceptions.py`, `sdk/agentexchange/models.py`, `sdk/agentexchange/client.py`, `sdk/agentexchange/async_client.py`, `sdk/agentexchange/ws_client.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase S — Migrations

> **Files reviewed:** `alembic/env.py`, `alembic/versions/001_initial_schema.py`, `alembic/versions/002_trading_tables.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase T — Scripts

> **Files reviewed:** `scripts/seed_pairs.py`, `scripts/validate_phase1.py`, `scripts/stability_test_24h.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase U — Test Suite

> **Files reviewed:** `tests/conftest.py`, `tests/unit/*.py`, `tests/integration/*.py`
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

## Phase V — Cross-Cutting Concerns

> **Scope:** Dependency direction, import cycles, Decimal consistency, async safety, logging, config completeness, missing implementations
> **Review status:** Not Started
> **Reviewed on:** —

*(Issues will be added here after review)*

---

*Update this file after each review phase. Bump the Summary Dashboard counts as issues are discovered and fixed.*
