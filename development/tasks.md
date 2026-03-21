---
type: task-list
title: "Tasks — AI Agent Crypto Trading Platform !"
status: archived
phase: platform-foundation
tags:
  - task
  - platform-foundation
---

# Tasks — AI Agent Crypto Trading Platform !

> **Last Updated:** 2026-03-12
> **Status Legend:** `[ ]` To Do · `[~]` In Progress · `[x]` Done · `[-]` Blocked · `[!]` Needs Review

---

## Phase 1: Foundation (Weeks 1–3)

**Goal:** All Binance pairs streaming to Redis + TimescaleDB 24/7

### 1.1 Project Setup

- [x] Initialize project repository and directory structure per plan (Section 4)
- [x] Create `requirements.txt` with pinned dependency versions
- [x] Create `requirements-dev.txt` (pytest, ruff, mypy, locust, etc.)
- [x] Create `.env.example` with all required environment variables
- [x] Set up `ruff` + `mypy` configuration files
- [x] Create `.gitignore` for Python/Docker/IDE artifacts

### 1.2 Docker & Infrastructure

- [x] Write `Dockerfile` for API service
- [x] Write `Dockerfile.ingestion` for price ingestion service
- [x] Write `docker-compose.yml` with TimescaleDB, Redis, API services
- [x] Write `docker-compose.dev.yml` with dev overrides (hot reload, debug ports)
- [x] Verify all services start and connect to each other
- [x] Add healthchecks for all services

### 1.3 Configuration

- [x] Implement `src/config.py` — pydantic-settings for all env vars
- [x] Implement `src/dependencies.py` — FastAPI dependency injection setup

### 1.4 Database Foundation

- [x] Create TimescaleDB schema: `ticks` hypertable + indexes
- [x] Add compression policy on `ticks` (7-day chunks)
- [x] Add retention policy on `ticks` (90-day raw data)
- [x] Create continuous aggregates: `candles_1m`, `candles_5m`, `candles_1h`, `candles_1d`
- [x] Add refresh policies for each continuous aggregate
- [x] Create `trading_pairs` reference table
- [x] Set up Alembic with initial migration
- [x] Implement `src/database/session.py` — async SQLAlchemy session factory
- [x] Implement `src/database/models.py` — ORM models (ticks, trading_pairs)

### 1.5 Redis Cache

- [x] Implement `src/cache/redis_client.py` — connection pool manager
- [x] Implement `src/cache/price_cache.py` — HSET/HGET for current prices, ticker stats, stale pair detection

### 1.6 Price Ingestion Service

- [x] Implement `src/price_ingestion/binance_ws.py` — fetch all USDT pairs, build combined stream URL, connect
- [x] Implement `src/price_ingestion/tick_buffer.py` — in-memory buffer with timed/size flush via asyncpg COPY
- [x] Implement `src/price_ingestion/service.py` — main loop: receive tick → update Redis + buffer → flush to DB
- [x] Implement `src/price_ingestion/broadcaster.py` — Redis pub/sub for price updates
- [x] Handle reconnection with exponential backoff (1s → 60s max)
- [x] Handle >1024 pairs via multiple WebSocket connections

### 1.7 Scripts

- [x] Write `scripts/seed_pairs.py` — fetch all pairs from Binance REST, seed `trading_pairs` table

### 1.8 Health & Monitoring (Phase 1 basics)

- [x] Implement tick freshness health check (alert if pair has no tick for 60s)
- [x] Basic `/health` endpoint returning ingestion status

### 1.9 Phase 1 Testing

- [x] Unit tests: `tick_buffer` (flush logic, size/time thresholds, failure retention)
- [x] Unit tests: `price_cache` (set/get price, ticker updates, stale detection)
- [x] Integration test: ticks flowing Binance → Redis → TimescaleDB
- [x] 24h stability test — verify zero data loss on major pairs

---

## Phase 2: Trading Engine (Weeks 4–6)

**Goal:** Complete trading engine executing orders against live prices

### 2.1 Database Schema (Trading)

- [x] Create `accounts` table with API key hashing
- [x] Create `balances` table with available/locked per asset
- [x] Create `trading_sessions` table
- [x] Create `orders` table with all order types and statuses
- [x] Create `trades` table (executed fills)
- [x] Create `positions` table (aggregated holdings)
- [x] Create `portfolio_snapshots` hypertable
- [x] Create `audit_log` table
- [x] Write Alembic migration for all trading tables
- [x] Implement ORM models for all new tables in `src/database/models.py`

### 2.2 Repositories

- [x] Implement `src/database/repositories/account_repo.py`
- [x] Implement `src/database/repositories/balance_repo.py`
- [x] Implement `src/database/repositories/order_repo.py`
- [x] Implement `src/database/repositories/trade_repo.py`
- [x] Implement `src/database/repositories/tick_repo.py`
- [x] Implement `src/database/repositories/snapshot_repo.py`

### 2.3 Account Management (Component 5)

- [x] Implement `src/accounts/auth.py` — API key generation (`ak_live_` prefix), bcrypt hashing, JWT creation/verification
- [x] Implement `src/accounts/service.py` — register, authenticate, get_account, reset_account, suspend
- [x] Implement `src/accounts/balance_manager.py` — credit, debit, lock, unlock, execute_trade (atomic)

### 2.4 Order Execution Engine (Component 4)

- [x] Implement `src/order_engine/slippage.py` — size-proportional slippage + 0.1% fee
- [x] Implement `src/order_engine/validators.py` — order validation rules
- [x] Implement `src/order_engine/engine.py` — market order execution flow
- [x] Add limit order support to `engine.py` (queue + lock funds)
- [x] Add stop-loss order type
- [x] Add take-profit order type
- [x] Implement `src/order_engine/matching.py` — background limit order matcher (1s interval)

### 2.5 Risk Management (Component 7)

- [x] Implement `src/risk/manager.py` — 8-step validation chain (balance, position size, daily loss, rate, etc.)
- [x] Implement `src/risk/circuit_breaker.py` — daily PnL tracking, trip/reset via Redis

### 2.6 Portfolio Tracking (Component 6)

- [x] Implement `src/portfolio/tracker.py` — real-time equity, positions, unrealized PnL
- [x] Implement `src/portfolio/metrics.py` — Sharpe, Sortino, drawdown, win rate, profit factor
- [x] Implement `src/portfolio/snapshots.py` — minute/hourly/daily snapshot capture

### 2.7 Phase 2 Testing

- [x] Unit tests: order engine (market buy/sell, limit queue, stop-loss trigger, take-profit trigger)
- [x] Unit tests: slippage calculator (small/large orders, buy/sell direction, fees)
- [x] Unit tests: risk manager (all 8 validation checks, custom risk profiles)
- [x] Unit tests: balance manager (credit, debit, lock, unlock, atomic trade execution)
- [x] Unit tests: portfolio metrics (Sharpe, drawdown, win rate, empty portfolio)
- [x] Integration test: full trade lifecycle (register → fund → buy → sell → check PnL)

---

## Phase 3: API Layer (Weeks 7–9)

**Goal:** Fully functional REST + WebSocket API

### 3.1 FastAPI Core

- [x] Implement `src/main.py` — app factory, middleware registration, router includes, startup/shutdown events
- [x] Implement `src/api/middleware/auth.py` — API key + JWT authentication middleware
- [x] Implement `src/api/middleware/rate_limit.py` — Redis sliding window rate limiter
- [x] Implement `src/api/middleware/logging.py` — structlog request/response logging

### 3.2 Pydantic Schemas

- [x] Implement `src/api/schemas/auth.py` — RegisterRequest, LoginRequest, TokenResponse, RegisterResponse
- [x] Implement `src/api/schemas/market.py` — PriceResponse, TickerResponse, CandleResponse, etc.
- [x] Implement `src/api/schemas/trading.py` — OrderRequest, OrderResponse, TradeResponse, etc.
- [x] Implement `src/api/schemas/account.py` — BalanceResponse, PositionResponse, PortfolioResponse, etc.
- [x] Implement `src/api/schemas/analytics.py` — PerformanceResponse, SnapshotResponse, LeaderboardResponse

### 3.3 REST Routes

- [x] Implement `src/api/routes/auth.py` — POST /auth/register, POST /auth/login
- [x] Implement `src/api/routes/market.py` — GET /market/pairs, /price/{symbol}, /prices, /ticker/{symbol}, /candles/{symbol}, /trades/{symbol}, /orderbook/{symbol}
- [x] Implement `src/api/routes/trading.py` — POST /trade/order, GET /trade/order/{id}, GET /trade/orders, GET /trade/orders/open, DELETE /trade/order/{id}, DELETE /trade/orders/open, GET /trade/history
- [x] Implement `src/api/routes/account.py` — GET /account/info, /balance, /positions, /portfolio, /pnl, POST /account/reset
- [x] Implement `src/api/routes/analytics.py` — GET /analytics/performance, /portfolio/history, /leaderboard

### 3.4 WebSocket Server

- [x] Implement `src/api/websocket/manager.py` — connection lifecycle (connect, disconnect, auth, heartbeat)
- [x] Implement `src/api/websocket/handlers.py` — subscribe/unsubscribe logic
- [x] Implement `src/api/websocket/channels.py` — ticker, candles, orders, portfolio channel definitions
- [x] Wire `src/price_ingestion/broadcaster.py` to push prices from Redis pub/sub → WebSocket clients

### 3.5 Background Tasks (Celery)

- [x] Implement `src/tasks/celery_app.py` — Celery config with Redis broker
- [x] Implement `src/tasks/limit_order_monitor.py` — check pending orders every 1s
- [x] Implement `src/tasks/candle_aggregation.py` — trigger continuous aggregate refreshes (if manual needed)
- [x] Implement `src/tasks/portfolio_snapshots.py` — 1m/1h/1d snapshot capture for all accounts
- [x] Implement `src/tasks/cleanup.py` — old data archival, expired order cleanup
- [x] Write `Dockerfile.celery` for Celery worker
- [x] Configure celery-beat schedule (1s matcher, 1m/1h/1d snapshots, daily circuit breaker reset)

### 3.6 Utilities

- [x] Implement `src/utils/exceptions.py` — custom exception classes matching error codes
- [x] Implement `src/utils/helpers.py` — shared utility functions

### 3.7 Phase 3 Testing

- [x] Integration tests: every REST endpoint with valid + invalid inputs
- [x] Integration tests: authentication (valid key, invalid key, expired JWT, no auth)
- [x] Integration tests: market data endpoints (pairs, price, prices, ticker, candles, trades, orderbook)
- [x] Integration tests: rate limiting (exceed limit → 429)
- [x] Integration tests: WebSocket (connect, subscribe, receive price, order notification, heartbeat)
- [ ] Verify OpenAPI docs auto-generated at `/docs` and `/redoc`
- [ ] Load test with locust: 50 concurrent agents, ~400 req/s, verify p95 < 100ms

### 3.8 Test Coverage Gap Analysis

- [x] Unit tests: `src/utils/exceptions.py` — 13 tests (TradingPlatformError hierarchy, to_dict, http_status, details)
- [x] Unit tests: `src/config.py` — 8 tests (Settings validation, field validators, DATABASE_URL scheme, JWT_SECRET length)
- [x] Unit tests: `src/accounts/auth.py` — 19 tests + 2 bonus (API key generation, bcrypt hash, JWT create/verify, expiry)
- [x] Unit tests: `src/order_engine/validators.py` — 15 tests (all validation rules, symbol format, quantity/price bounds)
- [x] Unit tests: `src/risk/circuit_breaker.py` — 12 tests (trip, reset, daily PnL tracking, Redis integration)
- [x] Unit tests: `src/accounts/service.py` — 12 tests (register, authenticate, get_account, reset_account, suspend)
- [x] Unit tests: `src/order_engine/matching.py` — 13 tests (limit order matching, stop-loss/take-profit triggers)
- [x] Unit tests: `src/portfolio/tracker.py` — 8 tests (real-time equity, unrealized PnL, positions)
- [x] Unit tests: `src/cache/redis_client.py` — 8 tests (connection pool, ping health check, pipeline)
- [x] Unit tests: `src/monitoring/health.py` — 10 tests (health check endpoint, Redis/DB/ingestion status)
- [x] Expanded `tests/unit/test_backtest_engine.py` — +8 tests (now 13 total; fixed AsyncMock for preload_range)
- [x] Expanded `tests/unit/test_backtest_sandbox.py` — +6 tests (now 20 total)
- [x] Expanded `tests/unit/test_backtest_results.py` — +5 tests (now 16 total)
- [x] Unit tests: `src/portfolio/snapshots.py` (snapshot_service) — 4 tests (new file)

---

## Phase 4: Agent Connectivity (Weeks 10–11)

**Goal:** Any AI agent connects and trades within 5 minutes

### 4.1 MCP Server

- [x] Implement `src/mcp/server.py` — MCP server process with all 12 tools
- [x] Implement `src/mcp/tools.py` — tool definitions, parameter schemas, internal API wiring
- [x] Test MCP tool discovery and execution

### 4.2 Python SDK

- [x] Implement `sdk/agentexchange/client.py` — sync REST client with all methods
- [x] Implement `sdk/agentexchange/async_client.py` — async REST client (httpx)
- [x] Implement `sdk/agentexchange/ws_client.py` — WebSocket client with auto-reconnect, decorators
- [x] Implement `sdk/agentexchange/models.py` — typed response dataclasses
- [x] Implement `sdk/agentexchange/exceptions.py` — error class hierarchy
- [x] Write `sdk/setup.py` (or `pyproject.toml`) for `pip install agentexchange`
- [x] Write SDK unit tests

### 4.3 Documentation

- [x] Write `docs/skill.md` — comprehensive agent instruction file (Section 19)
- [x] Write `docs/quickstart.md` — 5-minute getting started guide
- [x] Write `docs/api_reference.md` — full REST API reference
- [x] Write `docs/framework_guides/openclaw.md`
- [x] Write `docs/framework_guides/langchain.md`
- [x] Write `docs/framework_guides/agent_zero.md`
- [x] Write `docs/framework_guides/crewai.md`

### 4.4 Phase 4 Testing

- [x] Test: 10 agents from different frameworks connected simultaneously
- [ ] Test: skill.md works with Claude, GPT-4, and open-source LLMs
- [x] Test: MCP server discovery and tool execution end-to-end

---

## Phase 5: Polish & Launch (Weeks 12–14)

**Goal:** Production-ready platform with monitoring and documentation

### 5.1 Monitoring (Component 9)

- [ ] Implement `src/monitoring/prometheus_metrics.py` — all custom metrics (ingestion, API, trading, infra)
- [ ] Implement `src/monitoring/health.py` — comprehensive health checks (Redis, DB, ingestion, Celery)
- [ ] Create Grafana dashboard: System Overview
- [ ] Create Grafana dashboard: Agent Activity
- [ ] Create Grafana dashboard: Price Feed Health
- [ ] Set up Prometheus alerting rules (stale pairs, error rate, latency spikes)

### 5.2 Security Hardening

- [ ] Security audit: review all endpoints for auth bypass, injection, data leaks
- [ ] Implement audit log middleware (write every request to `audit_log` table)
- [ ] Implement optional IP allowlisting per account
- [ ] Implement HMAC request signing for order endpoints
- [ ] Enforce HTTPS / TLS 1.3 in production config

### 5.3 Operations

- [ ] Set up automated backups: TimescaleDB daily dump
- [ ] Set up automated backups: Redis RDB snapshots
- [ ] Write `scripts/create_test_agent.py` — easy test agent setup
- [x] Write `scripts/backfill_history.py` — backfill historical candles from Binance REST
- [x] Create `alembic/versions/006_candles_backfill.py` — candles_backfill hypertable migration
- [x] Update `src/backtesting/data_replayer.py` — UNION with candles_backfill for historical data
- [x] Update `src/backtesting/engine.py` — pass step_interval to DataReplayer

### 5.4 Documentation & README

- [ ] Write `README.md` — project overview, setup instructions, architecture diagram
- [ ] Ensure all public functions have docstrings/JSDoc

### 5.5 Phase 5 Testing & Launch

- [ ] Run 72h production stability test
- [ ] Fix all issues found during stability test
- [ ] Beta launch with 5–10 select developers
- [ ] Collect feedback and create follow-up task list

---

## Future Phases (Post-Launch)

### Phase 6: Advanced Features

- [ ] Add Kafka to price pipeline for zero-data-loss guarantee
- [ ] Margin trading simulation (2x, 5x, 10x leverage)
- [ ] Multi-exchange data feeds (KuCoin, Bybit, OKX)
- [ ] Futures/perpetuals simulation
- [ ] Advanced order types: OCO, trailing stop
- [ ] Agent-vs-agent order book mode
- [ ] Historical backtesting API (replay at accelerated speed)
- [ ] Portfolio comparison: agent vs. buy-and-hold vs. market index

### Phase 7: Platform & Monetization

- [ ] Web dashboard for developers
- [ ] Public agent leaderboard
- [ ] Tournament system (weekly/monthly competitions)
- [ ] Tiered pricing (Free / Pro $29/mo / Enterprise)
- [ ] Strategy marketplace

### Phase 8: Real Trading Bridge

- [ ] Optional bridge to real Binance accounts
- [ ] Graduated deployment ($100 start, scale on performance)
- [ ] Paper-to-live transition wizard
- [ ] Real-time risk monitoring for live agents
- [ ] Kill switch for live trading halt

---

*Update this file as tasks are started, completed, or reprioritized. Use `[~]` for in-progress and `[x]` for done.*
