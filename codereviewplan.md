# Code Review Plan — AI Agent Crypto Trading Platform (Backend)

> **Created:** 2026-03-01
> **Scope:** All backend code (`src/`, `sdk/`, `tests/`, `scripts/`, `alembic/`, root configs)
> **Excluded:** `Frontend/` folder (separate review)
> **Codebase size:** ~41,600 lines across 110 files
> **Review methodology:** Folder-by-folder, bottom-up (foundations → business logic → API surface → tests)

---

## Table of Contents

1. [Review Principles & Checklist](#1-review-principles--checklist)
2. [Review Phases Overview](#2-review-phases-overview)
3. [Phase A: Root Configuration & Infrastructure](#3-phase-a-root-configuration--infrastructure)
4. [Phase B: Database Layer](#4-phase-b-database-layer)
5. [Phase C: Cache Layer](#5-phase-c-cache-layer)
6. [Phase D: Utility Layer](#6-phase-d-utility-layer)
7. [Phase E: Price Ingestion Service](#7-phase-e-price-ingestion-service)
8. [Phase F: Account Management](#8-phase-f-account-management)
9. [Phase G: Order Execution Engine](#9-phase-g-order-execution-engine)
10. [Phase H: Risk Management](#10-phase-h-risk-management)
11. [Phase I: Portfolio Tracking](#11-phase-i-portfolio-tracking)
12. [Phase J: API Layer — Schemas](#12-phase-j-api-layer--schemas)
13. [Phase K: API Layer — Middleware](#13-phase-k-api-layer--middleware)
14. [Phase L: API Layer — Routes](#14-phase-l-api-layer--routes)
15. [Phase M: API Layer — WebSocket](#15-phase-m-api-layer--websocket)
16. [Phase N: Background Tasks (Celery)](#16-phase-n-background-tasks-celery)
17. [Phase O: Monitoring & Health](#17-phase-o-monitoring--health)
18. [Phase P: App Entry Point & DI](#18-phase-p-app-entry-point--di)
19. [Phase Q: MCP Server](#19-phase-q-mcp-server)
20. [Phase R: Python SDK](#20-phase-r-python-sdk)
21. [Phase S: Database Migrations](#21-phase-s-database-migrations)
22. [Phase T: Scripts](#22-phase-t-scripts)
23. [Phase U: Test Suite](#23-phase-u-test-suite)
24. [Phase V: Cross-Cutting Concerns](#24-phase-v-cross-cutting-concerns)
25. [Issue Tracking Template](#25-issue-tracking-template)
26. [Severity Definitions](#26-severity-definitions)

---

## 1. Review Principles & Checklist

Every file reviewed will be checked against this universal checklist. Not every item applies to every file — use judgment.

### 1.1 Correctness
- [ ] Logic matches the `developmantPlan.md` specification exactly
- [ ] Edge cases handled (empty inputs, zero values, None, boundary conditions)
- [ ] Race conditions considered in concurrent/async code
- [ ] Error paths return correct HTTP status codes and error envelopes
- [ ] Decimal precision maintained — no float used for money/prices
- [ ] All Decimal operations use `ROUND_HALF_UP` or explicit rounding

### 1.2 Security
- [ ] No hardcoded secrets, tokens, passwords, or API keys
- [ ] No bare `except:` — always catch specific exceptions
- [ ] SQL injection prevented (parameterized queries only)
- [ ] Authentication checks on all non-public endpoints
- [ ] Sensitive data (api_secret, passwords) never logged or returned after creation
- [ ] Input validation on all external-facing boundaries
- [ ] Rate limiting enforced on mutating endpoints
- [ ] No path traversal, SSRF, or injection vulnerabilities

### 1.3 Type Safety & Python Standards
- [ ] Full type annotations on all function signatures
- [ ] Pydantic v2 models used for all external data boundaries
- [ ] `async/await` used correctly — no blocking calls in async context
- [ ] No `asyncio.run()` inside an already-running event loop
- [ ] Imports follow the dependency direction: Routes → Services → Repositories → Models
- [ ] No circular imports
- [ ] `__all__` exports defined where appropriate
- [ ] Python 3.12+ features used correctly

### 1.4 Error Handling
- [ ] Custom exceptions from `src/utils/exceptions.py` used (not generic Exception)
- [ ] All external calls (Redis, DB, Binance WS) wrapped in try/except with logging
- [ ] Error responses follow the standard envelope: `{"error": {"code": "...", "message": "..."}}`
- [ ] Fail closed on errors (deny access, reject order) rather than fail open
- [ ] Resource cleanup in `finally` blocks where needed

### 1.5 Performance
- [ ] Database queries use proper indexes (check against migration indexes)
- [ ] N+1 query patterns avoided
- [ ] Redis operations use pipelines for batch operations
- [ ] Large result sets paginated
- [ ] No unbounded loops or unbounded memory growth
- [ ] Connection pools properly sized and released

### 1.6 Code Quality
- [ ] Google-style docstrings on all public classes and functions
- [ ] No dead code, commented-out code, or TODO/FIXME/HACK left unaddressed
- [ ] DRY — no significant duplicated logic
- [ ] Single Responsibility — each class/function does one thing
- [ ] Naming follows convention: files=`snake_case`, classes=`PascalCase`, funcs=`snake_case`, constants=`UPPER_SNAKE`
- [ ] No magic numbers — constants extracted and named
- [ ] File length reasonable (<1000 lines preferred; refactor if larger)

### 1.7 Testing (when reviewing test files)
- [ ] Tests cover happy path, error paths, and edge cases
- [ ] Mocks/patches are correctly scoped and cleaned up
- [ ] No test interdependency (each test runs independently)
- [ ] Assertions are specific (not just `assert result`)
- [ ] Test names describe the scenario being tested
- [ ] Integration tests don't require live infrastructure (proper mocking)

---

## 2. Review Phases Overview

The review follows a **bottom-up dependency order**: we start with foundations that everything depends on, then work up through business logic, API surface, and finally tests.

| Phase | Folder/Area | Files | ~Lines | Priority |
|-------|------------|-------|--------|----------|
| **A** | Root configs & Docker | 13 files | 796 | High |
| **B** | `src/database/` | 10 files | 4,148 | Critical |
| **C** | `src/cache/` | 2 files | 395 | High |
| **D** | `src/utils/` | 2 files | 1,044 | High |
| **E** | `src/price_ingestion/` | 4 files | 706 | High |
| **F** | `src/accounts/` | 3 files | 1,414 | Critical |
| **G** | `src/order_engine/` | 4 files | 1,888 | Critical |
| **H** | `src/risk/` | 2 files | 1,277 | Critical | ✅ |
| **I** | `src/portfolio/` | 3 files | 1,805 | High | ✅ |
| **J** | `src/api/schemas/` | 5 files | 2,093 | Medium |
| **K** | `src/api/middleware/` | 3 files | 861 | Critical |
| **L** | `src/api/routes/` | 5 files | 2,946 | High |
| **M** | `src/api/websocket/` | 3 files | 1,674 | High |
| **N** | `src/tasks/` | 5 files | 1,307 | Medium |
| **O** | `src/monitoring/` | 1 file | 184 | Medium |
| **P** | `src/main.py` + `src/dependencies.py` + `src/config.py` | 3 files | 981 | Critical |
| **Q** | `src/mcp/` | 3 files | 718 | Medium |
| **R** | `sdk/agentexchange/` | 6 files | 3,608 | High |
| **S** | `alembic/` | 3 files | 836 | High |
| **T** | `scripts/` | 3 files | 916 | Low |
| **U** | `tests/` | 18 files | 11,168 | Medium |
| **V** | Cross-cutting concerns | N/A | N/A | High |

**Estimated review time:** 6–10 hours total (can be spread across sessions)

---

## 3. Phase A: Root Configuration & Infrastructure ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 10 (0 Critical · 3 High · 4 Medium · 1 Low · 2 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase A section

**Goal:** Verify the foundation is solid — Docker, dependencies, env vars, linting config.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| A1 | `requirements.txt` | 37 | Pinned versions, no vulnerable packages, all deps needed | ✅ |
| A2 | `requirements-dev.txt` | 28 | Test/lint deps complete, no prod deps leaked | ✅ |
| A3 | `pyproject.toml` | 65 | ruff + mypy config correct, line-length=120, Python 3.12 target | ✅ |
| A4 | `.env.example` | 37 | All required vars documented, no real secrets, sensible defaults | ✅ |
| A5 | `Dockerfile` | 28 | Multi-stage build, non-root user, minimal image, HEALTHCHECK | ✅ |
| A6 | `Dockerfile.ingestion` | 17 | Same Docker best practices | ✅ |
| A7 | `Dockerfile.celery` | 52 | Worker + beat support, HEALTHCHECK | ✅ |
| A8 | `docker-compose.yml` | 280 | All services, healthchecks, resource limits, restart policies, volume persistence | ✅ |
| A9 | `docker-compose.dev.yml` | 88 | Hot reload, debug ports, dev overrides | ✅ |
| A10 | `docker-compose.phase1.yml` | 16 | Phase 1 subset correctness | ✅ |
| A11 | `prometheus.yml` | 25 | Scrape targets match services, intervals reasonable | ✅ |
| A12 | `alembic.ini` | 67 | Correct DB URL template, script location | ✅ |
| A13 | `sdk/pyproject.toml` | 66 | SDK packaging, deps, version, py.typed marker | ✅ |

### Specific Checks
- [x] `requirements.txt` — All deps pinned to exact versions; no obvious CVEs in pinned set
- [x] Docker images use `python:3.12-slim` ✅ — but third-party images (timescaledb, prometheus, grafana) use unpinned `latest` tags ⚠️ → **A8-1, A8-2, A8-3**
- [ ] `docker-compose.yml` — All services have `healthcheck`, `restart: unless-stopped`, `logging` config → **ingestion** missing healthcheck (**A8-5**); **celery-beat** missing healthcheck + restart + limits (**A8-4**)
- [x] No port conflicts between services
- [x] Volumes for `timescaledb_data` and `redis_data` are persistent (named volumes) ✅
- [x] `.env.example` includes core vars; Celery broker vars not documented (**A4-1** INFO)
- [x] `pyproject.toml` ruff selects match CLAUDE.md spec: `E, W, F, I, B, C4, UP, ANN, S, N` ✅

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| A8-1 | 🟠 HIGH | `timescaledb` image unpinned (`latest-pg16`) |
| A8-2 | 🟠 HIGH | `prometheus` image unpinned (`latest`) |
| A8-3 | 🟠 HIGH | `grafana` image unpinned (`latest`) |
| A8-4 | 🟡 MEDIUM | `celery-beat` missing healthcheck, restart policy, resource limits |
| A8-5 | 🟡 MEDIUM | `ingestion` service missing healthcheck |
| A8-6 | 🟡 MEDIUM | `celery-beat` depends_on only `celery`, not healthy DB/Redis |
| A5-1 | 🟡 MEDIUM | `Dockerfile` (API): no HEALTHCHECK, runs as root |
| A6-1 | 🟡 MEDIUM | `Dockerfile.ingestion`: no HEALTHCHECK, runs as root, no curl |
| A13-1 | 🟢 LOW | SDK `line-length=100` inconsistent with main project `line-length=120` |
| A11-1 | ⚪ INFO | `prometheus.yml` scrapes `ingestion:9100` — endpoint does not exist |
| A4-1 | ⚪ INFO | `.env.example` missing Celery broker/backend var documentation |

---

## 4. Phase B: Database Layer ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 11 (1 Critical · 3 High · 3 Medium · 2 Low · 2 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase B section

**Goal:** Verify ORM models match the schema, repositories are correct and atomic, session lifecycle is safe.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| B1 | `src/database/session.py` | 171 | Engine creation, pool config, session factory, lifecycle | ✅ |
| B2 | `src/database/models.py` | 936 | All 10+ ORM models, column types, relationships, constraints | ✅ |
| B3 | `src/database/repositories/__init__.py` | 6 | Exports | ✅ |
| B4 | `src/database/repositories/account_repo.py` | 279 | CRUD, error handling, typed exceptions | ✅ |
| B5 | `src/database/repositories/balance_repo.py` | 857 | Atomic ops, CHECK constraint handling, lock/unlock | ✅ |
| B6 | `src/database/repositories/order_repo.py` | 533 | State machine guards, pagination, pending query | ✅ |
| B7 | `src/database/repositories/trade_repo.py` | 428 | Insert-only, daily PnL aggregation, filtering | ✅ |
| B8 | `src/database/repositories/tick_repo.py` | 363 | Read-only, time-series queries, VWAP | ✅ |
| B9 | `src/database/repositories/snapshot_repo.py` | 395 | Create, history, cleanup | ✅ |

### Specific Checks
- [x] **models.py** — DB column types are all `NUMERIC(20,8)` ✅ — but Python-side `Mapped[float]` annotations are wrong throughout → **B2-1 CRITICAL**
- [x] **models.py** — CHECK constraints present: `ck_orders_side`, `ck_orders_type`, `ck_orders_status`, `ck_balances_available_non_negative`, `ck_balances_locked_non_negative`, `ck_snapshots_type` ✅ — `Trade.side` has no CHECK constraint → **B2-4 INFO**
- [x] **models.py** — Foreign keys: `Balance → accounts` CASCADE ✅, `Order → accounts` CASCADE ✅ — `Order.session_id`, `Trade.order_id`, `Trade.session_id` missing `ondelete` → **B2-2 HIGH**
- [x] **models.py** — Indexes present and match migration patterns ✅
- [x] **models.py** — `Tick` and `PortfolioSnapshot` noted as hypertables in docstrings ✅
- [x] **session.py** — Uses `asyncpg` driver, `pool_size=10`, `max_overflow=20` ✅ — `expire_on_commit=False` ✅ — `close_db()` doesn't reset `_session_factory` → **B1-1 MEDIUM**
- [x] **All repos** — No raw SQL, all SQLAlchemy ORM queries ✅
- [x] **All repos** — No `session.commit()` called — caller responsible ✅
- [x] **balance_repo.py** — `atomic_lock_funds`: single UPDATE (available-amount, locked+amount) — truly atomic ✅ — `_get_or_create_zero()` race condition savepoint problem → **B5-1 MEDIUM**
- [x] **balance_repo.py** — IntegrityError caught and re-raised as `InsufficientBalanceError` ✅
- [x] **order_repo.py** — `_CANCELLABLE_STATUSES = frozenset({"pending", "partially_filled"})` ✅
- [x] **order_repo.py** — `list_pending` has `limit=500`, paginated ✅ — deferred local import → **B6-1 MEDIUM**
- [x] **trade_repo.py** — `sum_daily_realized_pnl` uses `COALESCE(SUM(...), 0)` ✅ — returns `float` not `Decimal` → **B7-1 HIGH**
- [x] **tick_repo.py** — All queries filter `symbol` first ✅ — `get_vwap()` returns `float` → **B8-1 HIGH**
- [x] **All repos** — Use `logging.getLogger()` instead of `structlog.get_logger()` → **B2-3 MEDIUM**

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| B2-1 | 🔴 CRITICAL | All financial model columns use `Mapped[float]` instead of `Mapped[Decimal]` |
| B2-2 | 🟠 HIGH | `Order.session_id`, `Trade.order_id`, `Trade.session_id` FKs missing `ondelete` |
| B7-1 | 🟠 HIGH | `sum_daily_realized_pnl()` returns `float` — financial precision lost |
| B8-1 | 🟠 HIGH | `get_vwap()` converts Decimal→float for financial calculation |
| B1-1 | 🟡 MEDIUM | `close_db()` doesn't reset `_session_factory = None` |
| B2-3 | 🟡 MEDIUM | All 6 repo files use `logging.getLogger()` instead of `structlog.get_logger()` |
| B5-1 | 🟡 MEDIUM | `_get_or_create_zero()` rollback aborts parent transaction instead of savepoint |
| B6-1 | 🟢 LOW | `count_open_by_account()` has deferred local import for `sa_func` |
| B7-2 | 🟢 LOW | `get_daily_trades()` uses `time.max` upper bound — use half-open interval instead |
| B3-1 | ⚪ INFO | `repositories/__init__.py` has no `__all__` exports |
| B2-4 | ⚪ INFO | `Trade` model missing `CHECK` constraint on `side` column |
| B2-5 | ⚪ INFO | `Order.session_id` FK `ondelete` behaviour is undefined (undocumented intent) |

---

## 5. Phase C: Cache Layer

**Goal:** Verify Redis operations are correct, connection pool managed, failure handling graceful.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| C1 | `src/cache/redis_client.py` | 141 | Pool config, health check, connect/disconnect | ✅ |
| C2 | `src/cache/price_cache.py` | 254 | HSET/HGET, ticker, stale detection, Decimal handling | ✅ |

### Specific Checks
- [x] Connection pool uses `max_connections=50`, `decode_responses=True` ✅ — both `get_redis_client()` singleton and `RedisClient.connect()` correctly set both params
- [x] `get_price()` returns `Decimal` (not string or float) ✅ — `return Decimal(raw)` on line 140
- [x] `set_price()` stores as string representation of Decimal ✅ — `str(price)` on line 124
- [x] `get_all_prices()` returns dict with Decimal values ✅ — dict comprehension with `Decimal(price_str)` on line 149
- [x] `update_ticker()` atomically updates all ticker fields (pipeline or HMSET) ❌ — does HGETALL + HSET as two separate commands; no pipeline; TOCTOU race condition → **C2-1 HIGH**
- [x] `get_stale_pairs()` — threshold comparison is correct (compares timestamps properly) ✅ — `datetime.fromisoformat()` + UTC-aware `datetime.now(UTC)` + `total_seconds()` comparison is correct; corrupt timestamps handled
- [x] All Redis calls wrapped in try/except `RedisError` with logging ❌ — **no** Redis call in either file is wrapped in try/except `RedisError`; `ping()` in `RedisClient` only catches `RedisConnectionError` / `RedisTimeoutError`, missing `ResponseError`; all `PriceCache` methods are completely unprotected → **C1-2 HIGH**, **C2-2 HIGH**
- [x] Graceful degradation when Redis is unavailable (don't crash the app) ❌ — any Redis failure in `PriceCache` propagates as an uncaught exception, crashing the caller → **C2-2 HIGH**

### Additional Issues Found
- [x] **redis_client.py** — Uses `logging.getLogger()` instead of `structlog.get_logger()` → **C1-1 MEDIUM**
- [x] **price_cache.py** — Uses `logging.getLogger()` instead of `structlog.get_logger()` → **C2-3 MEDIUM**
- [x] **redis_client.py** — `get_redis_client()` singleton has no async-safe init guard; concurrent startup can create two pools → **C1-3 MEDIUM**
- [x] **redis_client.py** — `get_redis_client()` module-level singleton has no corresponding `close_redis_client()` — the singleton pool is never explicitly closed on app shutdown → **C1-4 MEDIUM**
- [x] **redis_client.py** — `connect()` has no try/except; if `_ping()` raises after pool creation, `_pool` and `_redis` are left dangling (partially initialized) → **C1-5 MEDIUM**
- [x] **redis_client.py** — `disconnect()` calls `self._redis.aclose()` then `self._pool.aclose()` — double-close: closing a `Redis` instance already drains its pool; calling `pool.aclose()` again is redundant and may log spurious errors → **C1-6 LOW**
- [x] **price_cache.py** — `get_ticker()` does unchecked `raw["open"]` etc. on the hash; a partially-written ticker hash (e.g. after a crash mid-write) raises `KeyError` → **C2-4 MEDIUM**
- [x] **price_cache.py** — `Tick` NamedTuple is defined in `price_cache.py` but is the canonical shared type used by ingestion, broadcaster, and tick buffer — should live in a dedicated module (e.g. `src/cache/types.py`) → **C2-5 LOW**
- [x] **price_cache.py** — `set_price()` docstring says "atomically" but uses `transaction=False` pipeline (non-MULTI/EXEC); the two HSET calls are pipelined but not truly atomic → **C2-6 INFO**
- [x] **cache/** — No `__init__.py` exists; the cache package has no `__all__`, making public API opaque → **C0-1 INFO**

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| C2-1 | 🟠 HIGH | `update_ticker()` TOCTOU race: HGETALL + HSET are not atomic; concurrent ticks for same symbol corrupt high/low/volume |
| C1-2 | 🟠 HIGH | `RedisClient.ping()` only catches `ConnectionError`/`TimeoutError`; misses `ResponseError` and other `RedisError` subtypes |
| C2-2 | 🟠 HIGH | All `PriceCache` methods have zero error handling; any Redis failure propagates as uncaught exception |
| C1-1 | 🟡 MEDIUM | `redis_client.py` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| C2-3 | 🟡 MEDIUM | `price_cache.py` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| C1-3 | 🟡 MEDIUM | `get_redis_client()` singleton not async-safe on first call; concurrent coroutines can create duplicate pools |
| C1-4 | 🟡 MEDIUM | `get_redis_client()` singleton has no `close_redis_client()` counterpart; pool leaks on shutdown |
| C1-5 | 🟡 MEDIUM | `connect()` leaves `_pool`/`_redis` dangling if `_ping()` raises after pool creation |
| C2-4 | 🟡 MEDIUM | `get_ticker()` does unchecked field access on hash; partial hash raises `KeyError` |
| C1-6 | 🟢 LOW | `disconnect()` double-closes pool (via `_redis.aclose()` then `_pool.aclose()`) |
| C2-5 | 🟢 LOW | `Tick` NamedTuple defined in `price_cache.py` but is a shared cross-module type |
| C2-6 | ⚪ INFO | `set_price()` docstring says "atomically" but pipeline uses `transaction=False` (not MULTI/EXEC) |
| C0-1 | ⚪ INFO | `src/cache/` has no `__init__.py`; package public API is opaque |

---

## 6. Phase D: Utility Layer ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 9 (0 Critical · 0 High · 4 Medium · 2 Low · 3 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase D section

**Goal:** Verify shared exceptions and helpers are consistent, complete, and correctly structured.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| D1 | `src/utils/exceptions.py` | 792 | Exception hierarchy, error codes, HTTP status mapping | ✅ |
| D2 | `src/utils/helpers.py` | 252 | Utility functions, Decimal formatting, pagination | ✅ |

### Specific Checks
- [x] **exceptions.py** — All 12 plan Section 15 error codes covered ✅
- [x] **exceptions.py** — Each exception has correct `http_status`, `error_code`, `to_dict()` ✅ — `ValidationError` name shadows `pydantic.ValidationError` → **D1-1 MEDIUM**
- [x] **exceptions.py** — No duplicate error codes ✅
- [x] **exceptions.py** — Base `TradingPlatformError` carries structured `details` dict ✅ — 5 subclasses drop `details` kwarg entirely → **D1-2 MEDIUM**
- [x] **exceptions.py** — `RiskLimitExceededError` uses code `POSITION_LIMIT_EXCEEDED` for all risk types → **D1-3 LOW**
- [x] **exceptions.py** — 9 extra exceptions beyond plan's Section 15 table (undocumented extensions) → **D1-4 INFO**
- [x] **helpers.py** — `format_decimal()` uses `ROUND_HALF_UP` ✅
- [x] **helpers.py** — `paginate()` validates `limit ≥ 1` and `offset ≥ 0` ✅ — raises stdlib `ValueError` not platform `ValidationError` → **D2-3 LOW**
- [x] **helpers.py** — `symbol_to_base_quote()` handles non-USDT pairs ✅ — `_KNOWN_QUOTES` allocated on every call → **D2-1 MEDIUM**
- [x] **helpers.py** — `utc_now()` returns timezone-aware datetime ✅
- [x] **helpers.py** — `parse_period()` silently treats unknown strings as "all time" → **D2-2 MEDIUM**
- [x] **helpers.py** — `clamp()` raises stdlib `ValueError` not platform `ValidationError` → **D2-4 LOW**
- [x] **helpers.py** — Module-level `from sqlalchemy import Select` couples utility layer to ORM → **D2-6 INFO**
- [x] **helpers.py** — `_PERIOD_DAYS` sentinel ambiguity between `"all"` and unknown keys → **D2-5 INFO**

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| D1-1 | 🟡 MEDIUM | `ValidationError` name shadows `pydantic.ValidationError` — causes silent mismatch in routes |
| D2-2 | 🟡 MEDIUM | `parse_period()` silently returns `None` for unknown periods (same as "all time") |
| D2-1 | 🟡 MEDIUM | `_KNOWN_QUOTES` tuple defined inside function body — re-allocated on every call |
| D1-2 | 🟡 MEDIUM | `AuthenticationError`, `PermissionDeniedError`, `DatabaseError`, `CacheError`, `ServiceUnavailableError` drop `details` kwarg |
| D1-3 | 🟢 LOW | `RiskLimitExceededError` hardcodes code `POSITION_LIMIT_EXCEEDED` for all risk limit types |
| D2-3 | 🟢 LOW | `paginate()` raises stdlib `ValueError` instead of platform `ValidationError` |
| D2-4 | 🟢 LOW | `clamp()` raises stdlib `ValueError` instead of platform `ValidationError` |
| D1-4 | ⚪ INFO | 9 extra error codes not documented in `developmantPlan.md` Section 15 |
| D2-5 | ⚪ INFO | `_PERIOD_DAYS` dict uses `None` for both `"all"` and unknown-key sentinel — ambiguous |
| D2-6 | ⚪ INFO | `helpers.py` imports `sqlalchemy.Select` at module level — couples utility layer to ORM |

---

## 7. Phase E: Price Ingestion Service

**Goal:** Verify Binance connection, tick parsing, buffer flush, and broadcast are robust.

**Status:** ✅ Complete — Reviewed 2026-03-01 — 10 issues found (0 critical, 1 high, 3 medium, 2 low, 4 info)

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| E1 | `src/price_ingestion/binance_ws.py` | 239 | WS connection, pair fetching, reconnection logic |
| E2 | `src/price_ingestion/tick_buffer.py` | 192 | Buffer size/time flush, asyncpg COPY, failure retention |
| E3 | `src/price_ingestion/service.py` | 165 | Main loop, signal handling, graceful shutdown |
| E4 | `src/price_ingestion/broadcaster.py` | 110 | Redis pub/sub publish, batch pipeline |

### Specific Checks
- [x] **binance_ws.py** — Handles >1024 streams via multiple connections
- [x] **binance_ws.py** — Exponential backoff: 1s→2s→4s→...→60s max, resets on successful connect
- [x] **binance_ws.py** — Tick parsing: `Decimal(p)` not `float(p)` for price
- [x] **binance_ws.py** — Handles malformed messages gracefully (JSON decode errors)
- [x] **tick_buffer.py** — Size flush at 5000 ticks AND time flush at 1s
- [x] **tick_buffer.py** — On flush failure: buffer retained, retry next cycle
- [x] **tick_buffer.py** — `shutdown()` performs final flush
- [x] **tick_buffer.py** — Uses `COPY` command (asyncpg) for bulk insert, not individual INSERTs
- [x] **service.py** — SIGINT/SIGTERM handlers call graceful shutdown
- [x] **service.py** — Main loop doesn't swallow exceptions silently
- [~] **broadcaster.py** — Uses Redis pipeline for batch publish (not individual PUBLISH per tick) — `broadcast_batch()` exists but hot path calls `broadcast()` per tick (see E4-1)
- [x] **broadcaster.py** — Publish failures logged but don't crash the ingestion service

### Issues Found

| ID | Severity | File | Summary |
|----|----------|------|---------|
| E3-1 | 🟠 HIGH | `service.py` | Fatal exception bypasses graceful shutdown — Redis and DB connections leaked |
| E4-1 | 🟡 MEDIUM | `service.py` + `broadcaster.py` | Hot path calls `broadcast()` (one PUBLISH per tick) instead of `broadcast_batch()` |
| E3-2 | 🟡 MEDIUM | `service.py` | `structlog.configure()` at module level pollutes global state in tests |
| E2-1 | 🟡 MEDIUM | `tick_buffer.py` | Lock held across async DB COPY call — `add()` stalls all callers during flush |
| E1-1 | 🟢 LOW | `binance_ws.py` | `listen()` declared `-> None` but is an async generator — misleading type signature |
| E1-2 | 🟢 LOW | `binance_ws.py` | `json.JSONDecodeError` not explicitly caught — relies on implicit `ValueError` inheritance |
| E1-3 | ⚪ INFO | `binance_ws.py` | Uses `logging.getLogger` instead of `structlog.get_logger` |
| E2-2 | ⚪ INFO | `tick_buffer.py` | Uses `logging.getLogger` instead of `structlog.get_logger` |
| E4-2 | ⚪ INFO | `broadcaster.py` | Uses `logging.getLogger` instead of `structlog.get_logger` |
| E3-3 | ⚪ INFO | `service.py` | Dead `if TYPE_CHECKING: pass` block |

---

## 8. Phase F: Account Management ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 13 (1 Critical · 3 High · 4 Medium · 3 Low · 2 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase F section

**Goal:** Verify auth security, balance atomicity, and account lifecycle correctness.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| F1 | `src/accounts/auth.py` | 323 | Key generation, bcrypt hashing, JWT create/verify | ✅ |
| F2 | `src/accounts/service.py` | 495 | Register, authenticate, reset, suspend | ✅ |
| F3 | `src/accounts/balance_manager.py` | 596 | Credit/debit/lock/unlock, atomic trade execution | ✅ |

### Specific Checks
- [x] **auth.py** — API key prefix `ak_live_`, secret prefix `sk_live_` ✅
- [x] **auth.py** — Uses `secrets.token_urlsafe(48)` (not random or uuid) ✅
- [x] **auth.py** — bcrypt rounds >= 12 ✅ (`_BCRYPT_ROUNDS = 12`)
- [x] **auth.py** — JWT uses HS256, includes `sub` (account_id), `iat`, `exp` ✅
- [x] **auth.py** — `verify_jwt` catches `DecodeError` AND `ExpiredSignatureError` ✅ — also catches `InvalidTokenError` base ✅
- [x] **auth.py** — API secret is NEVER returned after initial registration ✅ — only `api_key_hash` and `api_secret_hash` persisted; plaintext secret travels only in `ApiCredentials` returned once
- [x] **service.py** — `register()` creates Account + initial USDT Balance + TradingSession atomically ✅ — BUT has no `SQLAlchemyError` wrapping → **F2-2 HIGH**
- [x] **service.py** — `authenticate()` verifies bcrypt hash AND checks `status == 'active'` ✅ — BUT bcrypt called synchronously, blocking event loop → **F2-1 CRITICAL**
- [x] **service.py** — `reset_account()` closes session + deletes balances + re-credits USDT atomically ✅ — BUT does NOT cancel pending orders first → **F2-7 LOW**
- [x] **service.py** — Raises `AccountSuspendedError` on suspended accounts ✅
- [x] **balance_manager.py** — `execute_trade()` is truly atomic (single transaction via `atomic_execute_buy`/`atomic_execute_sell`) ✅
- [x] **balance_manager.py** — Fee deduction correct: buy = gross+fee, sell = gross-fee ✅
- [x] **balance_manager.py** — `lock()` moves from available→locked, `unlock()` reverses ✅
- [x] **balance_manager.py** — `has_sufficient_balance()` doesn't mutate state ✅
- [x] **balance_manager.py** — Handles `from_locked=True` path for limit order fills ✅

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| F2-1 | 🔴 CRITICAL | `register()` and `authenticate()` call bcrypt synchronously — blocks event loop ~200–400ms |
| F2-2 | 🟠 HIGH | `register()` has no try/except — raw `SQLAlchemyError`/`IntegrityError` leaks to route handler |
| F2-3 | 🟠 HIGH | `suspend_account()` and `unsuspend_account()` have no error handling |
| F1-1 | 🟠 HIGH | `verify_api_key()` and `verify_api_secret()` use bare `except Exception:` |
| F2-4 | 🟡 MEDIUM | `starting_balance or default` silently ignores explicit `Decimal("0")` input |
| F2-5 | 🟡 MEDIUM | `AccountService` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| F3-1 | 🟡 MEDIUM | `BalanceManager` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| F3-2 | 🟡 MEDIUM | `execute_trade()` does not wrap DB errors as `DatabaseError` |
| F2-6 | 🟡 MEDIUM | `_get_active_session()` is dead private method — never called internally |
| F1-2 | 🟢 LOW | `verify_jwt()` redundantly re-validates `iat`/`exp` after PyJWT already enforced them |
| F2-7 | 🟢 LOW | `reset_account()` does not cancel pending/open orders before wiping balances |
| F1-3 | 🟢 LOW | `authenticate_api_key()` performs full bcrypt on every request — no cheap prefix pre-check |
| F2-8 | ⚪ INFO | `register()` commits inside service method — inconsistent with `BalanceManager`'s caller-commits pattern |
| F1-4 | ⚪ INFO | `auth.py` has no `__all__` export definition |

---

## 9. Phase G: Order Execution Engine ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 16 (1 Critical · 3 High · 6 Medium · 3 Low · 3 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase G section

**Goal:** Verify order lifecycle, slippage model, validation chain, and limit order matching.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| G1 | `src/order_engine/slippage.py` | 246 | Slippage formula, fee calculation, edge cases | ✅ |
| G2 | `src/order_engine/validators.py` | 266 | 5-step validation chain, OrderRequest | ✅ |
| G3 | `src/order_engine/engine.py` | 824 | Market/limit/stop/TP execution, cancel logic | ✅ |
| G4 | `src/order_engine/matching.py` | 552 | Background matcher, condition evaluation, 1s cadence | ✅ |

### Specific Checks
- [x] **slippage.py** — Formula: `exec_price = ref_price * (1 + direction * factor * size/volume)` ✅
- [x] **slippage.py** — Direction: +1 for buy (price up), -1 for sell (price down) ✅
- [x] **slippage.py** — Fee: 0.1% of order value ✅ (`_FEE_FRACTION = Decimal("0.001")`)
- [x] **slippage.py** — Handles zero daily volume gracefully (minimum slippage fallback) ✅ — but no upper cap on slippage fraction → **G1-2 MEDIUM**
- [x] **slippage.py** — All prices quantized to 8 decimal places ✅ (`_PRICE_QUANT = Decimal("0.00000001")`)
- [x] **slippage.py** — Uses `logging.getLogger` instead of `structlog.get_logger` → **G1-3 LOW**
- [x] **slippage.py** — `calculate()` raises `ValueError` for bad side instead of `ValidationError` → **G1-1 MEDIUM**
- [x] **validators.py** — Validates: side, type, quantity (>0), price (required for limit/stop/tp), symbol (DB lookup) ✅ — BUT does NOT check `pair.min_qty` or `pair.min_notional` → **G2-1 HIGH**
- [x] **validators.py** — Returns `TradingPair` on success ✅
- [x] **validators.py** — DB error wrapped as `DatabaseError` ✅ — uses `logging.getLogger` → **G1-3 LOW**
- [x] **validators.py** — `_check_quantity` passes `min_qty=Decimal("0")` — misleading error detail → **G2-2 LOW**
- [x] **engine.py** — Market: fetch price → slippage → settle → fill → record trade ✅
- [x] **engine.py** — Limit: lock funds → queue as pending (no immediate execution) ✅
- [x] **engine.py** — Stop-loss/take-profit: same as limit (lock + queue) ✅
- [x] **engine.py** — `cancel_order()` unlocks funds AND sets status to cancelled ✅ — but TOCTOU race with matcher → **G3-4 MEDIUM**
- [x] **engine.py** — `execute_pending_order()` settles from locked funds (`from_locked=True`) ✅
- [x] **engine.py** — All operations commit via injected session ✅
- [x] **engine.py** — `Trade` and `Order` created with `float()` conversions — destroys Decimal precision → **G3-1 CRITICAL**
- [x] **engine.py** — `cancel_all_orders` uses bare `except Exception:` → **G3-2 HIGH**
- [x] **engine.py** — `place_order` `get_price()` call unguarded for `RedisError` → **G3-3 HIGH**
- [x] **engine.py** — `_release_locked_funds` silently returns on `order.price is None` → **G3-5 MEDIUM**
- [x] **engine.py** — `_base_asset_from_order` / `_quote_asset_from_order` fragile symbol splitting → **G3-6 MEDIUM**
- [x] **matching.py** — Condition: limit buy ≤ price, limit sell ≥ price, stop ≤ price, TP ≥ price ✅
- [x] **matching.py** — Per-order isolated sessions (one failure doesn't cascade) ✅
- [x] **matching.py** — Paginated sweep (no SELECT * from all pending orders) ✅ — offset-based pagination has cursor drift caveat → **G4-4 INFO**
- [x] **matching.py** — 1s cadence driven by Celery beat ✅ — `asyncio.get_event_loop()` deprecated → **G4-2 MEDIUM**
- [x] **matching.py** — `_was_execution_error()` permanently stubbed — `orders_errored` always 0 → **G4-1 MEDIUM**
- [x] **matching.py** — `start()` has no backoff on repeated failures → **G4-3 INFO**

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| G3-1 | 🔴 CRITICAL | `Trade` and `Order` rows created with `float()` conversions — financial precision destroyed |
| G3-2 | 🟠 HIGH | `cancel_all_orders` uses bare `except Exception:` — swallows errors silently |
| G3-3 | 🟠 HIGH | `place_order` `get_price()` call unguarded — `RedisError` bypasses `PriceNotAvailableError` guard |
| G2-1 | 🟠 HIGH | Validator ignores `min_qty` and `min_notional` from `TradingPair` — plan-required checks omitted |
| G3-4 | 🟡 MEDIUM | TOCTOU race between `get_by_id` and `cancel` in `cancel_order` — double-fund-release risk |
| G3-5 | 🟡 MEDIUM | `_release_locked_funds` silently no-ops on `order.price is None` — locked funds may never release |
| G3-6 | 🟡 MEDIUM | `_base_asset_from_order` / `_quote_asset_from_order` fragile — wrong assets for non-USDT pairs |
| G4-1 | 🟡 MEDIUM | `_was_execution_error()` always returns `False` — `orders_errored` counter is permanently 0 |
| G4-2 | 🟡 MEDIUM | `asyncio.get_event_loop()` deprecated in Python 3.10+ — should use `asyncio.get_running_loop()` |
| G1-1 | 🟡 MEDIUM | `calculate()` raises `ValueError` for bad side — should raise platform `ValidationError` |
| G1-2 | 🟡 MEDIUM | Slippage fraction has no upper cap — extreme orders can produce negative execution price on sell |
| G3-7 | 🟢 LOW | `reference_price` parameter name in `_place_queued_order` misleading — only used for logging |
| G2-2 | 🟢 LOW | `_check_quantity` passes `min_qty=Decimal("0")` to error — misleading client message |
| G1-3 | 🟢 LOW | All 4 order engine files use `logging.getLogger()` instead of `structlog.get_logger()` |
| G4-3 | ⚪ INFO | `start()` loop has no exponential backoff on repeated sweep failures |
| G4-4 | ⚪ INFO | Offset-based pagination in `check_all_pending` can skip orders inserted mid-sweep |
| G0-1 | ⚪ INFO | `src/order_engine/` has no `__init__.py` — public API is opaque |

---

## 10. Phase H: Risk Management ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 14 (0 Critical · 3 High · 5 Medium · 3 Low · 3 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase H section

**Goal:** Verify 8-step validation chain and circuit breaker are correct and cannot be bypassed.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| H1 | `src/risk/manager.py` | 884 | 8-step validation chain, risk limits, per-account overrides | ✅ |
| H2 | `src/risk/circuit_breaker.py` | 393 | Daily PnL tracking, trip/reset, Redis TTL | ✅ |

### Specific Checks
- [x] **manager.py** — All 8 steps in correct order (short-circuit on first failure) ✅
  1. Account active ✅
  2. Daily loss limit ✅
  3. Rate limit ✅
  4. Min order size ✅
  5. Max order size % of balance ✅ — sell orders with zero USDT balance bypass the cap → **H1-3 MEDIUM**
  6. Position limit % of equity ✅
  7. Max open orders ✅
  8. Sufficient balance ✅
- [x] **manager.py** — Default limits match plan: 25% position, 50 open orders, 20% daily loss, 1.0 USD min, 50% max order, 100 orders/min ✅
- [x] **manager.py** — Per-account overrides from `risk_profile` JSONB applied correctly ✅
- [x] **manager.py** — Decimal comparisons (not float comparisons) for money values ✅ — wraps float return from `sum_daily_realized_pnl()` with `Decimal(str(...))` as workaround for B7-1
- [x] **circuit_breaker.py** — `HINCRBYFLOAT` used for PnL accumulation ✅ — but passes `float(pnl)` losing Decimal precision → **H2-2 HIGH**
- [x] **circuit_breaker.py** — Trips when `abs(daily_pnl) >= threshold` AND `daily_pnl < 0` ✅
- [x] **circuit_breaker.py** — Redis key TTL set to seconds until next midnight UTC ✅
- [x] **circuit_breaker.py** — `reset_all()` uses SCAN+DELETE (not KEYS command) ✅ — but deletes one key per round-trip → **H2-4 LOW**
- [x] **circuit_breaker.py** — All Redis errors wrapped as `CacheError` ✅

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| H2-1 | 🟠 HIGH | `CircuitBreaker` computes `_loss_threshold` at init-time from a single account's balance — cannot function as a shared singleton across accounts |
| H2-2 | 🟠 HIGH | `HINCRBYFLOAT` called with `float(pnl)` — Decimal precision lost before Redis write |
| H1-1 | 🟠 HIGH | `update_risk_limits` accesses private `_session` attribute of `AccountRepository` — breaks encapsulation |
| H1-2 | 🟡 MEDIUM | `validate_order` has pointless no-op try/except that only re-raises both exceptions |
| H1-3 | 🟡 MEDIUM | `_check_max_order_size` skips cap enforcement for sell orders when USDT balance is zero |
| H1-4 | 🟡 MEDIUM | `_check_daily_loss` only catches `DatabaseError` — other exceptions from trade repo propagate unhandled |
| H1-5 | 🟡 MEDIUM | `_check_position_limit` uses fragile `symbol.replace("USDT", "")` — same bug as G3-6 |
| H2-3 | 🟡 MEDIUM | Both files use `logging.getLogger()` instead of `structlog.get_logger()` |
| H1-6 | 🟡 MEDIUM | `update_risk_limits` uses bare `except Exception:` — prohibited by CLAUDE.md |
| H2-4 | 🟢 LOW | `reset_all()` deletes keys one-by-one — N Redis round-trips for N keys |
| H2-5 | 🟢 LOW | `_seconds_until_midnight_utc()` uses deferred local import of `timedelta` |
| H1-7 | 🟢 LOW | `check_daily_loss()` fetches account twice — redundant DB round-trip |
| H1-8 | ⚪ INFO | Rate-limit counter incremented before order passes all validation steps — rejected orders consume tokens |
| H0-1 | ⚪ INFO | `src/risk/` has no `__init__.py` — package public API is opaque |

---

## 11. Phase I: Portfolio Tracking ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 19 (0 Critical · 2 High · 8 Medium · 6 Low · 3 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase I section

**Goal:** Verify portfolio calculations, metrics math, and snapshot capture correctness.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| I1 | `src/portfolio/tracker.py` | 563 | Real-time equity, positions, unrealized PnL | ✅ |
| I2 | `src/portfolio/metrics.py` | 799 | Sharpe, Sortino, drawdown, win rate, profit factor | ✅ |
| I3 | `src/portfolio/snapshots.py` | 443 | Minute/hourly/daily capture, serialization | ✅ |

### Specific Checks
- [x] **tracker.py** — `total_equity = available_cash + locked_cash + position_value` ✅ (line 239)
- [x] **tracker.py** — `unrealized_pnl = market_value - cost_basis` per position ✅ (line 306)
- [x] **tracker.py** — `roi_pct = total_pnl / starting_balance * 100` ✅ (lines 241–244)
- [x] **tracker.py** — Graceful fallback when price not in cache (mark `price_available=False`) ✅ — BUT `_get_price_safe` uses bare `except Exception:` → **I1-3 MEDIUM**
- [x] **tracker.py** — Uses live prices from Redis (not stale DB prices) ✅
- [x] **metrics.py** — Sharpe: `(mean_return - risk_free) / std_return * sqrt(annualization_factor)` ✅ — BUT `_std` uses population std dev, not sample std dev → **I2-8 MEDIUM**
- [x] **metrics.py** — Sortino: uses downside deviation only (negative returns) ✅
- [x] **metrics.py** — Max drawdown: peak-to-trough as percentage (not absolute) ✅
- [x] **metrics.py** — Win rate: `profitable_trades / total_trades * 100` ✅
- [x] **metrics.py** — Profit factor: `gross_profit / gross_loss` — ZERO loss case returns `0.0` instead of `inf` → **I2-4 MEDIUM**
- [x] **metrics.py** — `Metrics.empty()` returns safe defaults for zero-data ✅
- [x] **metrics.py** — All period filters ("1d", "7d", "30d", "90d", "all") work correctly ✅ — unknown period silently remaps to "all" → **I2-7 LOW**
- [x] **snapshots.py** — Minute snapshot: equity only (no JSONB positions) ✅
- [x] **snapshots.py** — Hourly snapshot: equity + serialized positions ✅
- [x] **snapshots.py** — Daily snapshot: equity + positions + full metrics ✅
- [x] **snapshots.py** — Caller responsible for commit (not committed internally) ✅

### Additional Issues Found
- [x] **snapshots.py** — All three `capture_*` methods write `float()` conversions to `NUMERIC(20,8)` columns → **I3-2 HIGH**
- [x] **metrics.py** — `_extract_equity` converts `Decimal` → `float` for entire equity curve → **I2-3 HIGH** (acceptable if I3-2 fixed; requires documentation)
- [x] **tracker.py** — Uses `logging.getLogger()` instead of `structlog.get_logger()` → **I1-1 MEDIUM**
- [x] **metrics.py** — Uses `logging.getLogger()` instead of `structlog.get_logger()` → **I2-1 MEDIUM**
- [x] **snapshots.py** — Uses `logging.getLogger()` instead of `structlog.get_logger()` → **I3-1 MEDIUM**
- [x] **metrics.py** — `_RISK_FREE_RATE` hardcoded, not from `Settings` → **I2-2 MEDIUM**
- [x] **snapshots.py** — `get_snapshot_history` accepts any string for `snapshot_type` silently → **I3-5 MEDIUM**
- [x] **metrics.py** — `_load_closed_trades` + `_load_snapshots` catch bare `except Exception:` → **I2-5 MEDIUM**
- [x] **tracker.py** — `_sum_realized_pnl` is a one-line dead passthrough → **I1-2 LOW**
- [x] **tracker.py** — `_symbol_to_asset` re-implements the same suffix-strip as G3-6 / H1-5 → **I1-4 LOW**
- [x] **tracker.py** — `_sum_all_realized_pnl` has deferred local imports → **I1-6 LOW**
- [x] **metrics.py** — `_period_to_since` / `_PERIOD_DAYS` duplicate `src/utils/helpers.py` → **I2-6 LOW**
- [x] **metrics.py** — `calculate` silently remaps unknown period to "all" → **I2-7 LOW**
- [x] **snapshots.py** — `_serialise_positions` typed as bare `list` not `list[PositionView]` → **I3-3 LOW**
- [x] **snapshots.py** — `_serialise_metrics` typed as `Any` not `Metrics` → **I3-4 LOW**
- [x] **portfolio/** — No `__init__.py` → **I0-1 INFO**
- [x] **tracker.py** — `get_portfolio` + `get_pnl` would double-fetch positions if called in sequence → **I1-7 INFO**
- [x] **metrics.py** — `_PERIOD_DAYS` / `_RISK_FREE_RATE` undocumented rationale → **I2-9 INFO**

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| I3-2 | 🟠 HIGH | All `capture_*` methods write `float()` to `NUMERIC(20,8)` snapshot columns — precision destroyed |
| I2-3 | 🟠 HIGH | `_extract_equity` converts Decimal→float — acceptable for ratio metrics but requires documentation + I3-2 fix |
| I1-3 | 🟡 MEDIUM | `_get_price_safe` catches bare `except Exception:` instead of `redis.exceptions.RedisError` |
| I2-8 | 🟡 MEDIUM | `_std` uses population std dev (÷N) — Sharpe/Sortino should use sample std dev (÷N−1) |
| I2-4 | 🟡 MEDIUM | `_profit_factor` returns `0.0` when no losing trades — should return `inf` or `None` |
| I2-1 | 🟡 MEDIUM | `metrics.py` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| I1-1 | 🟡 MEDIUM | `tracker.py` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| I3-1 | 🟡 MEDIUM | `snapshots.py` uses `logging.getLogger()` instead of `structlog.get_logger()` |
| I2-2 | 🟡 MEDIUM | `_RISK_FREE_RATE` hardcoded — should come from `Settings` |
| I3-5 | 🟡 MEDIUM | `get_snapshot_history` does not validate `snapshot_type` — silently returns `[]` for invalid types |
| I2-5 | 🟡 MEDIUM | `_load_closed_trades` + `_load_snapshots` catch bare `except Exception:` |
| I1-2 | 🟢 LOW | `_sum_realized_pnl` is a dead one-line passthrough to `_sum_all_realized_pnl` |
| I1-4 | 🟢 LOW | `_symbol_to_asset` re-implements suffix-stripping already in `src/utils/helpers.py` |
| I1-6 | 🟢 LOW | `_sum_all_realized_pnl` uses deferred local imports |
| I2-6 | 🟢 LOW | `_period_to_since` / `_PERIOD_DAYS` duplicate `src/utils/helpers.py` |
| I2-7 | 🟢 LOW | `calculate` silently remaps unknown period to `"all"` — returned `Metrics.period` does not reflect input |
| I3-3 | 🟢 LOW | `_serialise_positions` typed as bare `list` instead of `list[PositionView]` |
| I3-4 | 🟢 LOW | `_serialise_metrics` typed as `Any` instead of `Metrics` |
| I0-1 | ⚪ INFO | `src/portfolio/` has no `__init__.py` — package public API is opaque |
| I1-7 | ⚪ INFO | `get_portfolio` + `get_pnl` would double-fetch positions if called sequentially |
| I2-9 | ⚪ INFO | `_PERIOD_DAYS` / `_RISK_FREE_RATE` constants lack rationale documentation |

---

## 12. Phase J: API Layer — Schemas ✅ COMPLETE

> **Reviewed:** 2026-03-01 · **Issues:** 15 (0 Critical · 3 High · 6 Medium · 3 Low · 3 Info) · **Fixed:** 0
> **Details:** See `codereviewtasks.md` → Phase J section

**Goal:** Verify Pydantic v2 schemas match API spec, Decimal serialization, validation rules.

### Files to Review

| # | File | Lines | Focus | Status |
|---|------|-------|-------|--------|
| J1 | `src/api/schemas/auth.py` | 181 | Register, login, token response | ✅ |
| J2 | `src/api/schemas/market.py` | 334 | Price, ticker, candle, orderbook responses | ✅ |
| J3 | `src/api/schemas/trading.py` | 582 | Order request validation, order/trade responses | ✅ |
| J4 | `src/api/schemas/account.py` | 648 | Balance, position, portfolio, PnL, reset | ✅ |
| J5 | `src/api/schemas/analytics.py` | 348 | Performance, snapshots, leaderboard | ✅ |

### Specific Checks
- [x] All Decimal fields serialized as strings via `field_serializer` ✅ — every Decimal field has a `@field_serializer` returning `str(value)`
- [x] `OrderRequest` — `model_validator` enforces price presence for limit/stop/tp types ✅ — `_validate_price_requirement` covers all cases; also rejects price on market orders
- [x] `OrderRequest` — Validates `side` ∈ {"buy", "sell"}, `type` ∈ {"market", "limit", "stop_loss", "take_profit"} ✅ — `Literal` types enforce this
- [x] `RegisterRequest` — `starting_balance` defaults to 10000, validated `gt=Decimal("0")` ✅
- [x] All response models have `ConfigDict(from_attributes=True)` where needed ❌ — None of the response schemas have `from_attributes=True`; they all use the `_BaseSchema` mixin which does NOT include it → **J1-3 MEDIUM** (however, if routes construct schemas manually rather than via ORM object, this may be fine; must verify in Phase L)
- [x] No `Optional` fields that should be required ❌ — `OrderResponse` has 14 optional fields with no enforcement of which set must be populated for a given `status` → **J3-1 HIGH**
- [x] Schema field names match REST API spec ❌ — `OrderDetailResponse.executed_qty` vs `OrderResponse.executed_quantity` inconsistency → **J3-2 HIGH**; `PnLPeriod` missing `"90d"` → **J4-3 MEDIUM**
- [x] Email validation uses `EmailStr` from pydantic ✅ — `auth.py` line 63 uses `EmailStr`
- [x] `ResetRequest.confirm` must be `True` — no schema-level enforcement ❌ → **J4-1 HIGH**

### Issues Found
| ID | Severity | Description |
|----|----------|-------------|
| J3-1 | 🟠 HIGH | `OrderResponse` flat model — no discriminated union or validator enforcing filled vs pending field sets |
| J3-2 | 🟠 HIGH | `OrderDetailResponse.executed_qty` vs `OrderResponse.executed_quantity` — wire-format field name inconsistency |
| J4-1 | 🟠 HIGH | `ResetRequest.confirm` accepts `False` silently — no schema-level guard requiring `True` |
| J1-1 | 🟡 MEDIUM | `_BaseSchema` duplicated across all 5 files — should be in a shared `_base.py` module |
| J2-1 | 🟡 MEDIUM | `CandlesListResponse.interval` typed as `str` — allows invalid intervals; description erroneously lists `"4h"` |
| J3-3 | 🟡 MEDIUM | `OrderRequest.symbol` not uppercased by validator — case-sensitive downstream DB lookups |
| J4-2 | 🟡 MEDIUM | `RiskProfileInfo` percentage fields typed as `int` — loses fractional precision vs `Decimal` in `RiskManager` |
| J5-1 | 🟡 MEDIUM | `PerformanceResponse.profit_factor` should be `Decimal \| None` to represent infinite profit factor correctly |
| J4-3 | 🟡 MEDIUM | `PnLPeriod` missing `"90d"` — inconsistent with `AnalyticsPeriod` which includes `"90d"` |
| J5-2 | 🟡 MEDIUM | `PortfolioHistoryResponse` has no pagination fields — unbounded snapshot list |
| J0-1 | 🟢 LOW | `src/api/schemas/__init__.py` has no `__all__` or re-exports — public API is opaque |
| J3-4 | 🟢 LOW | `TradeHistoryItem` missing `realized_pnl` field — agents cannot determine per-trade profitability |
| J2-2 | 🟢 LOW | `BatchTickersResponse` references undocumented `GET /market/tickers` endpoint |
| J1-2 | 🟢 LOW | `RegisterRequest.starting_balance` example uses float literal `10000.00` instead of string `"10000.00"` |
| J4-4 | ⚪ INFO | `account.py` docstring uses deprecated `datetime.utcnow()` — should be `datetime.now(timezone.utc)` |
| J3-5 | ⚪ INFO | `OrderStatus` type alias defined in `trading.py` — not exported from `__init__.py` for reuse |
| J5-3 | ⚪ INFO | `SnapshotItem` lacks `snapshot_type` field — cannot distinguish interval granularity in response body |

---

## 13. Phase K: API Layer — Middleware

**Goal:** Verify auth, rate limiting, and logging middleware are secure, performant, and correctly ordered.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| K1 | `src/api/middleware/auth.py` | 400 | API key + JWT auth, public path whitelist |
| K2 | `src/api/middleware/rate_limit.py` | 291 | Sliding window, 3 tiers, Redis-backed |
| K3 | `src/api/middleware/logging.py` | 170 | structlog, request_id, latency |

### Specific Checks
- [x] **auth.py** — Public paths: `/api/v1/auth/register`, `/api/v1/auth/login`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`
- [x] **auth.py** — Tries API key first, then Bearer token
- [x] **auth.py** — Sets `request.state.account` on success
- [x] **auth.py** — Returns 401 with standard error envelope on failure
- [x] **auth.py** — Owns its own DB session (not shared with route)
- [x] **auth.py** — `get_current_account()` FastAPI dependency reads from `request.state`
- [x] **rate_limit.py** — Three tiers: orders 100/min, market 1200/min, general 600/min
- [x] **rate_limit.py** — Redis key: `rate_limit:{api_key}:{group}:{minute_bucket}`
- [x] **rate_limit.py** — INCR + EXPIRE(120s) — expire is 120s not 60s (covers bucket overlap)
- [x] **rate_limit.py** — Fail-open on Redis errors (don't block requests)
- [x] **rate_limit.py** — Injects `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers
- [x] **logging.py** — Excludes `/health` and `/metrics` from logging (noise reduction)
- [x] **logging.py** — Logs `account_id` when available
- [x] **logging.py** — Does not log request/response bodies (data leak risk)
- [x] **Middleware order** — In `create_app()`: LoggingMiddleware → AuthMiddleware → RateLimitMiddleware (LIFO means RateLimit→Auth→Logging execution order)

### Issues Found
| ID | Severity | Summary |
|----|----------|---------|
| K1-1 | 🟠 HIGH | `asyncio.get_event_loop()` deprecated in Python 3.12 — use `get_running_loop()` |
| K2-1 | 🟠 HIGH | Off-by-one in rate-limit check: `> limit` should be `>= limit` |
| K1-2 | 🟡 MEDIUM | `assert bearer_token is not None` stripped by `python -O` — use `if` check |
| K2-2 | 🟡 MEDIUM | Non-atomic `INCR` + `EXPIRE` — TTL lost on partial Redis failure; use pipeline |
| K2-3 | 🟡 MEDIUM | `_get_redis` missing return type annotation (`# type: ignore[return]`) |
| K3-1 | 🟡 MEDIUM | `return response` suppresses real `Response \| None` typing gap with `type: ignore` |
| K3-2 | 🟡 MEDIUM | Exception traceback not passed to structlog `error` call — traceback absent from logs |
| K1-3 | 🟢 LOW | Redundant `/docs` and `/redoc` in `_PUBLIC_PREFIXES`; prefix `/docs` can over-match |
| K3-3 | 🟢 LOW | `X-Forwarded-For` trusted without proxy validation — spoofable by clients |
| K1-4 | ⚪ INFO | Docstring describes API key as "plaintext" — misleading without security rationale |
| K1-5 | ⚪ INFO | Redundant `try/except TradingPlatformError: raise` no-op in `get_current_account` |
| K2-4 | ⚪ INFO | `retry_after` computed unconditionally even for non-rate-limited requests |
| K3-4 | ⚪ INFO | `request_id` not propagated to `X-Request-ID` response header |

---

## 14. Phase L: API Layer — Routes

**Goal:** Verify all 22 REST endpoints match the spec, have correct auth, validation, and responses.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| L1 | `src/api/routes/auth.py` | 221 | Register (201), login (JWT) |
| L2 | `src/api/routes/market.py` | 751 | 7 endpoints, no auth required, symbol validation |
| L3 | `src/api/routes/trading.py` | 675 | 7 endpoints, all authed, risk check → engine |
| L4 | `src/api/routes/account.py` | 765 | 6 endpoints, all authed, portfolio integration |
| L5 | `src/api/routes/analytics.py` | 534 | 3 endpoints, all authed, metrics/leaderboard |

### Specific Checks
- [ ] **auth.py** — `POST /register` returns 201 with `api_key` and `api_secret` (shown once)
- [ ] **auth.py** — `POST /login` returns JWT with correct expiry
- [ ] **market.py** — All 7 endpoints: `/pairs`, `/price/{symbol}`, `/prices`, `/ticker/{symbol}`, `/candles/{symbol}`, `/trades/{symbol}`, `/orderbook/{symbol}`
- [ ] **market.py** — Symbol validation: uppercase normalization, DB lookup
- [ ] **market.py** — Candle intervals: only `1m`, `5m`, `1h`, `1d` accepted (maps to correct view)
- [ ] **market.py** — Orderbook is deterministic simulated (not real order book)
- [ ] **trading.py** — `POST /order` does: risk validate → engine.place_order → response
- [ ] **trading.py** — `DELETE /order/{id}` checks ownership
- [ ] **trading.py** — `DELETE /orders/open` returns `cancelled_count` + `total_unlocked`
- [ ] **trading.py** — All responses use correct schema classes
- [ ] **account.py** — `POST /reset` requires `confirm: true` guard
- [ ] **account.py** — `GET /pnl` accepts `period` query param
- [ ] **analytics.py** — Leaderboard filters out zero-trade accounts, caps at 50 entries
- [ ] **All routes** — Use `CurrentAccountDep` for authenticated endpoints
- [ ] **All routes** — Error responses match standard envelope format

---

## 15. Phase M: API Layer — WebSocket

**Goal:** Verify WebSocket connection lifecycle, channel subscriptions, and Redis bridge.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| M1 | `src/api/websocket/manager.py` | 595 | Connection lifecycle, auth, heartbeat, broadcast |
| M2 | `src/api/websocket/handlers.py` | 525 | Subscribe/unsubscribe, Redis pub/sub bridge |
| M3 | `src/api/websocket/channels.py` | 554 | Channel definitions, serialization |

### Specific Checks
- [ ] **manager.py** — Auth via `api_key` query param on connect
- [ ] **manager.py** — Close code 4401 on auth failure
- [ ] **manager.py** — Heartbeat: 30s ping, 10s pong timeout → disconnect
- [ ] **manager.py** — `asyncio.Lock` for thread-safe registry operations
- [ ] **manager.py** — Per-account connection index for fast `broadcast_to_account`
- [ ] **manager.py** — `disconnect_all()` for graceful shutdown
- [ ] **handlers.py** — Actions: `subscribe`, `unsubscribe`, `pong`
- [ ] **handlers.py** — Subscription limit enforced (prevent memory exhaustion)
- [ ] **handlers.py** — `RedisPubSubBridge` subscribes to `price_updates` channel
- [ ] **handlers.py** — Bridge auto-reconnects on Redis errors
- [ ] **channels.py** — 5 channels: `ticker:{symbol}`, `ticker:all`, `candles:{symbol}:{interval}`, `orders`, `portfolio`
- [ ] **channels.py** — `orders` and `portfolio` are private (per-account only)
- [ ] **channels.py** — Decimal serialized as string in wire format
- [ ] **channels.py** — `resolve_channel_name()` correctly parses client subscribe payloads

---

## 16. Phase N: Background Tasks (Celery)

**Goal:** Verify Celery configuration, task implementations, and beat schedule.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| N1 | `src/tasks/celery_app.py` | 145 | Celery config, queues, beat schedule |
| N2 | `src/tasks/limit_order_monitor.py` | 117 | Sync→async bridge, Redis lifecycle, 1s cadence |
| N3 | `src/tasks/portfolio_snapshots.py` | 380 | 3 tiers, per-account isolation, circuit breaker reset |
| N4 | `src/tasks/candle_aggregation.py` | 224 | Continuous aggregate refresh |
| N5 | `src/tasks/cleanup.py` | 441 | Expired orders, old snapshots, audit log pruning |

### Specific Checks
- [ ] **celery_app.py** — Broker + backend = `REDIS_URL`
- [ ] **celery_app.py** — `task_acks_late=True` (at-least-once delivery)
- [ ] **celery_app.py** — Beat schedule: limit monitor 1s, snapshots 60s/3600s/daily, candle refresh 60s, cleanup daily 01:00, circuit breaker reset 00:01
- [ ] **celery_app.py** — Two queues: `default` + `high_priority`
- [ ] **limit_order_monitor.py** — Uses `asyncio.run()` to bridge sync Celery → async matcher
- [ ] **limit_order_monitor.py** — Creates short-lived Redis + DB session per invocation (no stale connections)
- [ ] **limit_order_monitor.py** — `finally` block always disconnects Redis
- [ ] **portfolio_snapshots.py** — Pages through accounts in batches (1000 rows)
- [ ] **portfolio_snapshots.py** — Per-account failures isolated (don't abort remaining)
- [ ] **portfolio_snapshots.py** — Daily task has extended time limits (110s/120s)
- [ ] **candle_aggregation.py** — Refreshes all 4 views: `candles_1m`, `candles_5m`, `candles_1h`, `candles_1d`
- [ ] **candle_aggregation.py** — Per-view failure isolation
- [ ] **cleanup.py** — Expires orders older than 7 days
- [ ] **cleanup.py** — Deletes minute snapshots older than 7 days
- [ ] **cleanup.py** — Deletes audit log rows older than 30 days
- [ ] **All tasks** — Return serializable summary dicts (not ORM objects)

---

## 17. Phase O: Monitoring & Health

**Goal:** Verify health check is comprehensive and monitoring foundation is correct.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| O1 | `src/monitoring/health.py` | 184 | Health endpoint, Redis/DB/ingestion checks |

### Specific Checks
- [ ] Checks Redis ping, DB `SELECT 1`, and ingestion freshness in parallel
- [ ] Returns `ok` / `degraded` / `unhealthy` with correct HTTP status (200/200/503)
- [ ] Reports latency metrics per check
- [ ] Stale pair detection uses `PriceCache.get_stale_pairs(60)`
- [ ] Note: `prometheus_metrics.py` is NOT yet implemented (Phase 5 task) — flag as gap

---

## 18. Phase P: App Entry Point & DI

**Goal:** Verify the FastAPI app factory, middleware registration order, DI providers, and config.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| P1 | `src/config.py` | 120 | pydantic-settings, all env vars, validators |
| P2 | `src/dependencies.py` | 582 | DI providers for all services, repos, caches |
| P3 | `src/main.py` | 279 | App factory, middleware, routers, lifespan, error handlers |

### Specific Checks
- [ ] **config.py** — All env vars from `.env.example` have corresponding fields
- [ ] **config.py** — Sensitive defaults are NOT production-unsafe (JWT_SECRET must be set)
- [ ] **config.py** — Validators for DATABASE_URL, REDIS_URL format
- [ ] **dependencies.py** — DI providers for ALL services: AccountService, BalanceManager, OrderEngine, RiskManager, CircuitBreaker, PortfolioTracker, PerformanceMetrics, SnapshotService, + all 6 repositories
- [ ] **dependencies.py** — Session factory injected correctly (not global mutable state)
- [ ] **dependencies.py** — No circular dependency between providers
- [ ] **main.py** — Middleware registration order (LIFO): RateLimitMiddleware last added → runs first
- [ ] **main.py** — CORS configured: allows `["*"]` in dev (document production restriction)
- [ ] **main.py** — Exposes `X-RateLimit-*` headers in CORS
- [ ] **main.py** — All 6 routers included: health, auth, market, trading, account, analytics
- [ ] **main.py** — WebSocket endpoint at `/ws/v1`
- [ ] **main.py** — Prometheus metrics at `/metrics`
- [ ] **main.py** — Lifespan: startup (DB init → Redis → ConnectionManager → pub/sub bridge), shutdown (reverse)
- [ ] **main.py** — Global exception handlers: `TradingPlatformError` → structured JSON, catch-all → 500
- [ ] **main.py** — structlog configured for JSON output

---

## 19. Phase Q: MCP Server

**Goal:** Verify all 12 MCP tools, schema definitions, dispatch routing, and server lifecycle.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| Q1 | `src/mcp/__init__.py` | 15 | Package stub |
| Q2 | `src/mcp/tools.py` | 487 | 12 tool definitions, dispatch, API wiring |
| Q3 | `src/mcp/server.py` | 216 | Server process, stdio transport, env vars |

### Specific Checks
- [ ] **tools.py** — All 12 tools defined: get_price, get_all_prices, get_candles, get_balance, get_positions, place_order, cancel_order, get_order_status, get_portfolio, get_trade_history, get_performance, reset_account
- [ ] **tools.py** — Each tool has correct JSON schema with required/optional params
- [ ] **tools.py** — `_dispatch()` routes each tool to correct REST endpoint via httpx
- [ ] **tools.py** — `reset_account` requires `confirm: true` guard
- [ ] **tools.py** — Symbol params are uppercased
- [ ] **tools.py** — Error propagation: 4xx/5xx from API → clear error content in MCP response
- [ ] **server.py** — Reads `MCP_API_KEY` from env (exits with CRITICAL if missing)
- [ ] **server.py** — `API_BASE_URL` defaults to `http://localhost:8000`
- [ ] **server.py** — Uses stdio transport (not HTTP)
- [ ] **server.py** — httpx client sends auth headers (API key + optional JWT)

---

## 20. Phase R: Python SDK

**Goal:** Verify both sync/async clients, WebSocket client, models, and exception mapping.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| R1 | `sdk/agentexchange/__init__.py` | 110 | Public exports, `__all__`, `__version__` |
| R2 | `sdk/agentexchange/exceptions.py` | 452 | Error hierarchy, status→exception mapping |
| R3 | `sdk/agentexchange/models.py` | 865 | 13 response dataclasses, `from_dict()` |
| R4 | `sdk/agentexchange/client.py` | 846 | Sync client, 22 methods, retry logic, JWT lifecycle |
| R5 | `sdk/agentexchange/async_client.py` | 844 | Async client, mirrors sync exactly |
| R6 | `sdk/agentexchange/ws_client.py` | 491 | WebSocket, decorators, reconnect, heartbeat |

### Specific Checks
- [ ] **__init__.py** — `__all__` covers 3 clients + 13 models + 10 exceptions + `__version__`
- [ ] **exceptions.py** — `raise_for_response()` maps all 25 platform error codes to typed exceptions
- [ ] **exceptions.py** — HTTP status fallback when error code not recognized
- [ ] **models.py** — All 13 models have `from_dict()` classmethod
- [ ] **models.py** — Decimal used for all monetary fields (not float)
- [ ] **models.py** — `Order.from_dict()` handles both response shapes (OrderResponse + OrderDetailResponse)
- [ ] **client.py** — `_login()` exchanges api_key + api_secret for JWT
- [ ] **client.py** — `_ensure_auth()` refreshes JWT before expiry (30s buffer)
- [ ] **client.py** — Retry: 3 attempts, exponential backoff (1s/2s/4s), only on 5xx
- [ ] **client.py** — `_clean_params()` strips None values
- [ ] **client.py** — All 22 methods present and typed
- [ ] **async_client.py** — Exact mirror of sync client with `async/await`
- [ ] **async_client.py** — Context manager (`__aenter__`/`__aexit__`)
- [ ] **ws_client.py** — Decorators: `@on_ticker`, `@on_candles`, `@on_order_update`, `@on_portfolio`
- [ ] **ws_client.py** — Auto-reconnect with exponential backoff (1s→60s)
- [ ] **ws_client.py** — Stops only on `AuthenticationError`
- [ ] **ws_client.py** — Heartbeat: responds to server pings, closes on timeout
- [ ] **ws_client.py** — `ticker:all` fan-out doesn't double-fire for specific symbol handlers

---

## 21. Phase S: Database Migrations

**Goal:** Verify migrations match ORM models and plan spec exactly.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| S1 | `alembic/env.py` | 110 | Async migration runner, metadata import |
| S2 | `alembic/versions/001_initial_schema.py` | 246 | Ticks hypertable, continuous aggregates, trading_pairs |
| S3 | `alembic/versions/002_trading_tables.py` | 480 | Accounts, balances, orders, trades, positions, etc. |

### Specific Checks
- [ ] **env.py** — Uses async migration runner (`run_migrations_online` with asyncpg)
- [ ] **env.py** — Imports `Base.metadata` from `src.database.models`
- [ ] **001** — Creates `ticks` table with `NUMERIC(20,8)` for price/quantity
- [ ] **001** — Creates hypertable with 1-hour chunks
- [ ] **001** — Creates all 4 continuous aggregates with correct refresh policies
- [ ] **001** — Compression policy: 7 days, segmentby=symbol
- [ ] **001** — Retention policy: 90 days
- [ ] **001** — Creates `trading_pairs` table
- [ ] **002** — Creates all 7 tables: accounts, balances, trading_sessions, orders, trades, positions, portfolio_snapshots, audit_log
- [ ] **002** — All CHECK constraints match: `side IN ('buy','sell')`, `status IN (...)`, `quantity > 0`, `available >= 0`, `locked >= 0`
- [ ] **002** — All indexes created: `idx_balances_account`, `idx_orders_account_status`, `idx_trades_account_time`, etc.
- [ ] **002** — `portfolio_snapshots` created as hypertable (1-day chunks)
- [ ] **002** — All FKs have `ON DELETE CASCADE`
- [ ] **Both** — `downgrade()` function correctly reverses all changes

---

## 22. Phase T: Scripts

**Goal:** Verify utility scripts are correct, safe, and properly handle errors.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| T1 | `scripts/seed_pairs.py` | 279 | Binance REST → trading_pairs upsert |
| T2 | `scripts/validate_phase1.py` | 338 | Phase 1 health validation |
| T3 | `scripts/stability_test_24h.py` | 299 | 24h stability monitoring |

### Specific Checks
- [ ] **seed_pairs.py** — Fetches from `https://api.binance.com/api/v3/exchangeInfo`
- [ ] **seed_pairs.py** — Filters `status="TRADING"` + `quoteAsset="USDT"`
- [ ] **seed_pairs.py** — Upserts (not just inserts) — handles re-runs gracefully
- [ ] **seed_pairs.py** — Extracts LOT_SIZE and MIN_NOTIONAL filters
- [ ] **validate_phase1.py** — Checks Docker services, Redis, DB, ingestion health
- [ ] **stability_test_24h.py** — Monitors data gaps, alerts on staleness

---

## 23. Phase U: Test Suite

**Goal:** Verify test coverage, mock correctness, assertion quality, and independence.

### Files to Review

| # | File | Lines | Focus |
|---|------|-------|-------|
| U1 | `tests/conftest.py` | 197 | Shared fixtures, factory helpers |
| U2 | `tests/unit/test_tick_buffer.py` | 289 | Buffer flush logic |
| U3 | `tests/unit/test_price_cache.py` | 429 | Redis cache operations |
| U4 | `tests/unit/test_slippage.py` | 272 | Slippage calculations |
| U5 | `tests/unit/test_balance_manager.py` | 468 | Balance operations |
| U6 | `tests/unit/test_order_engine.py` | 419 | Order lifecycle |
| U7 | `tests/unit/test_risk_manager.py` | 402 | Risk validation |
| U8 | `tests/unit/test_portfolio_metrics.py` | 325 | Metrics calculations |
| U9 | `tests/unit/test_mcp_tools.py` | 904 | MCP tool discovery + execution |
| U10 | `tests/unit/test_sdk_client.py` | 1733 | SDK sync/async/WS clients |
| U11 | `tests/integration/test_ingestion_flow.py` | 302 | Binance→Redis→DB pipeline |
| U12 | `tests/integration/test_full_trade_flow.py` | 394 | End-to-end trade lifecycle |
| U13 | `tests/integration/test_auth_endpoints.py` | 706 | Auth routes |
| U14 | `tests/integration/test_market_endpoints.py` | 1314 | Market data routes |
| U15 | `tests/integration/test_trading_endpoints.py` | 1719 | Trading routes |
| U16 | `tests/integration/test_websocket.py` | 1073 | WebSocket lifecycle |
| U17 | `tests/integration/test_rate_limiting.py` | 796 | Rate limit middleware |
| U18 | `tests/integration/test_agent_connectivity.py` | 642 | Multi-agent + MCP + skill.md |

### Specific Checks
- [ ] **conftest.py** — Fixtures are properly scoped (`function` scope default, `session` for expensive setup)
- [ ] **conftest.py** — Mock factories produce valid test objects
- [ ] **All unit tests** — No live infrastructure required (all mocked)
- [ ] **All integration tests** — Use `TestClient` / `AsyncClient` with app factory
- [ ] **All tests** — Independent (no test depends on another test's state)
- [ ] **All tests** — Assertions are specific (check exact values, not just truthy)
- [ ] **Missing tests** — Identify any gap: e.g., circuit breaker unit tests, WebSocket reconnection, cleanup task, candle aggregation task
- [ ] **Test count verification** — Confirm total matches reported: 45 (Phase 1) + Phase 2 + 303 (Phase 3) + Phase 4

---

## 24. Phase V: Cross-Cutting Concerns

**Goal:** After all phases complete, do a final sweep for systemic issues.

### V1: Dependency Direction Audit
- [ ] No route file imports from another route file
- [ ] No service imports from a route or middleware
- [ ] No repository imports from a service (except via DI)
- [ ] No model imports from a route (use schemas as boundary)
- [ ] Strict: Routes → Schemas + Services → Repositories + Cache → Models + Session

### V2: Import Cycle Detection
- [ ] Run static analysis or manual trace to confirm no circular imports
- [ ] Check `__init__.py` files don't re-export in ways that create cycles

### V3: Consistent Error Handling
- [ ] Every route that calls a service wraps errors in try/except and returns standard error envelope
- [ ] All custom exceptions inherit from `TradingPlatformError`
- [ ] No bare `except:` or `except Exception:` that swallows errors silently

### V4: Decimal Consistency
- [ ] `Decimal` used for ALL financial calculations (never `float`)
- [ ] `Decimal` to string conversion is consistent (8 decimal places for prices/quantities)
- [ ] API responses serialize Decimal as string (never as float JSON number)

### V5: Async Safety
- [ ] No `time.sleep()` in async code (use `asyncio.sleep()`)
- [ ] No blocking I/O in async code without `run_in_executor()`
- [ ] `asyncio.Lock` used where shared state is mutated
- [ ] No `asyncio.run()` called inside an already-running event loop (except Celery bridge)

### V6: Logging Consistency
- [ ] All modules use `structlog.get_logger()` (not `logging.getLogger()`)
- [ ] Log levels appropriate: DEBUG for internal ops, INFO for business events, WARNING for degraded, ERROR for failures
- [ ] No sensitive data in logs (passwords, API secrets, full JWT tokens)

### V7: Configuration Completeness
- [ ] Every configurable value reads from `Settings` (not hardcoded)
- [ ] Default values are sane for development
- [ ] Production-critical values have no default (force explicit setting)

### V8: Missing Implementation Gaps
- [ ] `src/monitoring/prometheus_metrics.py` — NOT YET IMPLEMENTED (Phase 5)
- [ ] `tests/load/locustfile.py` — NOT YET CREATED
- [ ] `scripts/create_test_agent.py` — NOT YET CREATED
- [ ] `scripts/backfill_history.py` — NOT YET CREATED
- [ ] Audit log middleware — NOT YET IMPLEMENTED
- [ ] IP allowlisting — NOT YET IMPLEMENTED
- [ ] HMAC request signing — NOT YET IMPLEMENTED

---

## 25. Issue Tracking Template

For each issue found during review, log it using this format:

```markdown
### [SEVERITY] PHASE-ID: Short description

**File:** `path/to/file.py` line XX
**Category:** Correctness | Security | Performance | Code Quality | Type Safety | Missing Feature
**Description:** What's wrong and why it matters.
**Suggested Fix:** How to fix it.
**Effort:** Trivial (< 5 min) | Small (< 30 min) | Medium (< 2 hrs) | Large (> 2 hrs)
```

**Example:**
```markdown
### [CRITICAL] B5-1: balance_repo.py uses float comparison for Decimal

**File:** `src/database/repositories/balance_repo.py` line 142
**Category:** Correctness
**Description:** Available balance comparison uses `>` operator on float-converted Decimal, which can produce floating-point precision errors on large values.
**Suggested Fix:** Keep both operands as `Decimal` and compare directly.
**Effort:** Trivial
```

---

## 26. Severity Definitions

| Severity | Meaning | Action Required |
|----------|---------|-----------------|
| **CRITICAL** | Security vulnerability, data corruption risk, financial calculation error | Must fix before production |
| **HIGH** | Logic bug, spec deviation, missing error handling, performance issue | Fix before beta launch |
| **MEDIUM** | Code quality, missing docstrings, minor spec mismatch | Fix when convenient |
| **LOW** | Style, naming, minor optimization | Nice to have |
| **INFO** | Observation, suggestion, or future consideration | Track for later |

---

## Execution Instructions

1. **Work phase by phase** in order (A → V). Each phase builds on the previous.
2. **Read every file** in the phase using the Read tool before commenting.
3. **Check against the plan** — `developmantPlan.md` is the authority for specs.
4. **Log issues** using the template in Section 25.
5. **Fix as you go** — for Trivial/Small issues, fix immediately. For Medium/Large, log and continue.
6. **After each phase**, summarize: files reviewed, issues found (by severity), issues fixed.
7. **Phase V (cross-cutting)** should be done LAST as it needs full codebase context.

---

*This plan covers ~41,600 lines across 110 files. Expected total review time: 6–10 hours.*
