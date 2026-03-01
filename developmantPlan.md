# AI Agent Crypto Trading Platform — Complete Development Plan

> **Version:** 1.0 | **Date:** February 2026
> **Stack:** Python 3.12+ | FastAPI | Redis | TimescaleDB | Docker
> **Goal:** Build a universal training playground where any AI agent can trade crypto against real-time Binance data with virtual funds.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Project Structure](#4-project-structure)
5. [Component 1: Price Ingestion Service](#5-component-1-price-ingestion-service)
6. [Component 2: Redis Real-Time Cache](#6-component-2-redis-real-time-cache)
7. [Component 3: TimescaleDB Historical Storage](#7-component-3-timescaledb-historical-storage)
8. [Component 4: Order Execution Engine](#8-component-4-order-execution-engine)
9. [Component 5: Account Management System](#9-component-5-account-management-system)
10. [Component 6: Portfolio Tracker](#10-component-6-portfolio-tracker)
11. [Component 7: Risk Management Engine](#11-component-7-risk-management-engine)
12. [Component 8: API Gateway (FastAPI)](#12-component-8-api-gateway-fastapi)
13. [Component 9: Monitoring & Logging](#13-component-9-monitoring--logging)
14. [Database Schema](#14-database-schema)
15. [REST API Specification](#15-rest-api-specification)
16. [WebSocket API Specification](#16-websocket-api-specification)
17. [MCP Server Integration](#17-mcp-server-integration)
18. [Python SDK](#18-python-sdk)
19. [skill.md Agent Connectivity File](#19-skillmd-agent-connectivity-file)
20. [Security & Authentication](#20-security--authentication)
21. [Docker Compose Configuration](#21-docker-compose-configuration)
22. [Development Phases & Tasks](#22-development-phases--tasks)
23. [Testing Strategy](#23-testing-strategy)
24. [Future Roadmap](#24-future-roadmap)

---

## 1. Project Overview

### What We Are Building

A simulated crypto exchange platform powered by real-time Binance market data. AI agents connect via API, trade with virtual funds against live prices, and developers can train/test/benchmark their trading strategies risk-free.

### Core Principles

- **1:1 Market Mirror:** All 600+ Binance trading pairs, full tick-by-tick data, 24/7
- **Universal Agent Access:** Any framework (OpenClaw, Agent Zero, LangChain, CrewAI, raw Python) connects in under 5 minutes
- **Realistic Simulation:** Slippage modeling, risk controls, proper order lifecycle
- **Five Integration Layers:** REST API, WebSocket, MCP Server, Python SDK, skill.md file

### Key User Flow

```
Developer registers → Gets API key + skill.md → Feeds to agent → Agent trades in 5 minutes
```

---

## 2. System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXTERNAL DATA                             │
│                   Binance WebSocket Streams                      │
│                  (All 600+ trading pairs)                        │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              COMPONENT 1: PRICE INGESTION SERVICE                │
│   - Connects to Binance Combined WebSocket Stream                │
│   - Parses every tick for all pairs                              │
│   - Writes to Redis (current) + TimescaleDB (history)            │
│   - Broadcasts to WebSocket subscribers                          │
└──────┬──────────────────────────────┬───────────────────────────┘
       │                              │
       ▼                              ▼
┌──────────────┐          ┌───────────────────────┐
│  COMPONENT 2 │          │     COMPONENT 3       │
│    REDIS     │          │     TIMESCALEDB       │
│              │          │                       │
│ Current      │          │ Full tick history     │
│ prices for   │          │ for all pairs.        │
│ all pairs.   │          │ OHLCV candles.        │
│ Agent state. │          │ Trade ledger.         │
│ Rate limits. │          │ Account data.         │
└──────┬───────┘          └───────────┬───────────┘
       │                              │
       ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              COMPONENT 8: API GATEWAY (FastAPI)                  │
│                                                                  │
│   REST Endpoints    WebSocket Server    Authentication           │
│   Rate Limiting     Request Validation  CORS                     │
└──────┬──────────────────┬───────────────────┬───────────────────┘
       │                  │                   │
       ▼                  ▼                   ▼
┌──────────────┐  ┌──────────────┐   ┌──────────────────┐
│ COMPONENT 4  │  │ COMPONENT 5  │   │   COMPONENT 6    │
│ ORDER ENGINE │  │ ACCOUNT MGR  │   │ PORTFOLIO TRACKER│
│              │  │              │   │                  │
│ Market orders│  │ Registration │   │ Real-time PnL    │
│ Limit orders │  │ Balances     │   │ Sharpe ratio     │
│ Stop-loss    │  │ Positions    │   │ Max drawdown     │
│ Take-profit  │  │ Trade history│   │ Snapshots        │
│ Slippage sim │  │ Account reset│   │                  │
└──────────────┘  └──────────────┘   └──────────────────┘
       │
       ▼
┌──────────────┐          ┌───────────────────────┐
│ COMPONENT 7  │          │     COMPONENT 9       │
│ RISK MANAGER │          │   MONITORING/LOGGING  │
│              │          │                       │
│ Position lim │          │ Prometheus + Grafana   │
│ Daily loss   │          │ Agent dashboards       │
│ Circuit break│          │ Alerting               │
└──────────────┘          └───────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                 AGENT CONNECTIVITY LAYER                          │
│                                                                  │
│  ┌─────────┐  ┌───────────┐  ┌─────┐  ┌──────┐  ┌──────────┐  │
│  │REST API │  │WebSocket  │  │ MCP │  │Python│  │ skill.md │  │
│  │         │  │Streaming  │  │Server│  │ SDK  │  │          │  │
│  └─────────┘  └───────────┘  └─────┘  └──────┘  └──────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow: Price Ingestion

```
Binance WS → Price Ingestion Service → Redis (current price overwrite)
                                     → Write Buffer (in-memory)
                                     → Flush every 1s → TimescaleDB
                                     → Broadcast → WebSocket clients
```

### Data Flow: Order Execution

```
Agent POST /trade/order
  → API Gateway (auth + validate)
  → Order Engine (check balance + risk limits)
  → Fetch current price from Redis
  → Calculate slippage
  → Execute trade (update balances in PostgreSQL)
  → Record in trades table
  → Update order status → filled
  → Notify agent via WebSocket
  → Portfolio Tracker recalculates equity
```

---

## 3. Technology Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.12+ | Ecosystem, async support, agent framework compatibility |
| Web Framework | FastAPI | Async, auto OpenAPI docs, Pydantic validation |
| Real-Time Cache | Redis 7+ | Sub-ms price lookups, rate limiting, pub/sub |
| Historical DB | TimescaleDB (PostgreSQL) | Time-series optimized, compression, continuous aggregates |
| ORM | SQLAlchemy 2.0 + asyncpg | Async database access, migration support |
| Migrations | Alembic | Database schema versioning |
| WebSocket | FastAPI WebSocket + websockets lib | Native async WebSocket support |
| Task Queue | Celery + Redis broker | Background jobs (candle aggregation, snapshots, cleanup) |
| Auth | JWT (PyJWT) + API Keys (bcrypt) | Industry standard, stateless |
| Containerization | Docker + Docker Compose | Reproducible environments |
| Monitoring | Prometheus + Grafana | Metrics collection + dashboards |
| Logging | structlog + Loki (or ELK) | Structured JSON logging, centralized search |
| Testing | pytest + pytest-asyncio + locust | Unit/integration + load testing |
| CI/CD | GitHub Actions | Automated test + deploy pipeline |
| Linting | ruff + mypy | Fast linting + type checking |

---

## 4. Project Structure

```
agent-exchange/
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── .github/
│   └── workflows/
│       ├── test.yml
│       └── deploy.yml
├── alembic/
│   ├── alembic.ini
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app entry point
│   ├── config.py                        # Settings via pydantic-settings
│   ├── dependencies.py                  # Dependency injection
│   │
│   ├── price_ingestion/                 # COMPONENT 1
│   │   ├── __init__.py
│   │   ├── service.py                   # Main ingestion loop
│   │   ├── binance_ws.py                # Binance WebSocket client
│   │   ├── tick_buffer.py               # In-memory buffer + flush logic
│   │   └── broadcaster.py               # Push prices to WS subscribers
│   │
│   ├── cache/                           # COMPONENT 2
│   │   ├── __init__.py
│   │   ├── redis_client.py              # Redis connection manager
│   │   └── price_cache.py              # Price read/write operations
│   │
│   ├── database/                        # COMPONENT 3
│   │   ├── __init__.py
│   │   ├── session.py                   # Async SQLAlchemy session
│   │   ├── models.py                    # All SQLAlchemy ORM models
│   │   └── repositories/
│   │       ├── tick_repo.py             # Tick data CRUD
│   │       ├── account_repo.py          # Account CRUD
│   │       ├── order_repo.py            # Order CRUD
│   │       ├── trade_repo.py            # Trade CRUD
│   │       ├── balance_repo.py          # Balance CRUD
│   │       └── snapshot_repo.py         # Portfolio snapshot CRUD
│   │
│   ├── order_engine/                    # COMPONENT 4
│   │   ├── __init__.py
│   │   ├── engine.py                    # Main order processing logic
│   │   ├── slippage.py                  # Slippage calculation model
│   │   ├── matching.py                  # Price matching for limit orders
│   │   └── validators.py               # Order validation rules
│   │
│   ├── accounts/                        # COMPONENT 5
│   │   ├── __init__.py
│   │   ├── service.py                   # Account business logic
│   │   ├── auth.py                      # API key generation, JWT logic
│   │   └── balance_manager.py           # Balance update operations
│   │
│   ├── portfolio/                       # COMPONENT 6
│   │   ├── __init__.py
│   │   ├── tracker.py                   # Real-time portfolio valuation
│   │   ├── metrics.py                   # Sharpe, drawdown, win rate calcs
│   │   └── snapshots.py                # Periodic snapshot service
│   │
│   ├── risk/                            # COMPONENT 7
│   │   ├── __init__.py
│   │   ├── manager.py                   # Risk limit enforcement
│   │   └── circuit_breaker.py           # Daily loss circuit breaker
│   │
│   ├── api/                             # COMPONENT 8
│   │   ├── __init__.py
│   │   ├── middleware/
│   │   │   ├── auth.py                  # Authentication middleware
│   │   │   ├── rate_limit.py            # Rate limiting middleware
│   │   │   └── logging.py              # Request/response logging
│   │   ├── routes/
│   │   │   ├── auth.py                  # POST /auth/register, /auth/login
│   │   │   ├── market.py               # GET /market/price, /market/candles
│   │   │   ├── trading.py              # POST /trade/order, DELETE /trade/order
│   │   │   ├── account.py              # GET /account/balance, /account/positions
│   │   │   └── analytics.py            # GET /analytics/performance
│   │   ├── websocket/
│   │   │   ├── manager.py              # WebSocket connection manager
│   │   │   ├── handlers.py             # Subscribe/unsubscribe logic
│   │   │   └── channels.py             # Channel definitions (ticker, orders, etc.)
│   │   └── schemas/
│   │       ├── auth.py                  # Pydantic models for auth
│   │       ├── market.py               # Pydantic models for market data
│   │       ├── trading.py              # Pydantic models for orders/trades
│   │       ├── account.py              # Pydantic models for account data
│   │       └── analytics.py            # Pydantic models for analytics
│   │
│   ├── monitoring/                      # COMPONENT 9
│   │   ├── __init__.py
│   │   ├── prometheus_metrics.py        # Custom Prometheus metrics
│   │   └── health.py                   # Health check endpoints
│   │
│   ├── mcp/                             # MCP SERVER
│   │   ├── __init__.py
│   │   ├── server.py                    # MCP server implementation
│   │   └── tools.py                    # Tool definitions for agents
│   │
│   ├── tasks/                           # CELERY BACKGROUND TASKS
│   │   ├── __init__.py
│   │   ├── celery_app.py               # Celery configuration
│   │   ├── candle_aggregation.py        # Aggregate ticks → candles
│   │   ├── portfolio_snapshots.py       # Periodic snapshot capture
│   │   ├── limit_order_monitor.py       # Check pending orders vs prices
│   │   └── cleanup.py                  # Old data archival
│   │
│   └── utils/
│       ├── __init__.py
│       ├── exceptions.py               # Custom exception classes
│       └── helpers.py                  # Shared utility functions
│
├── sdk/                                 # PYTHON SDK (separate package)
│   ├── setup.py
│   ├── agentexchange/
│   │   ├── __init__.py
│   │   ├── client.py                   # Sync REST client
│   │   ├── async_client.py             # Async REST client
│   │   ├── ws_client.py                # WebSocket client
│   │   ├── models.py                   # Response models
│   │   └── exceptions.py              # SDK exception classes
│   └── tests/
│
├── docs/
│   ├── skill.md                        # Agent connectivity file
│   ├── quickstart.md
│   ├── api_reference.md
│   └── framework_guides/
│       ├── openclaw.md
│       ├── langchain.md
│       ├── agent_zero.md
│       └── crewai.md
│
├── tests/
│   ├── conftest.py                     # Shared fixtures
│   ├── unit/
│   │   ├── test_order_engine.py
│   │   ├── test_slippage.py
│   │   ├── test_risk_manager.py
│   │   ├── test_balance_manager.py
│   │   ├── test_portfolio_metrics.py
│   │   └── test_auth.py
│   ├── integration/
│   │   ├── test_full_trade_flow.py
│   │   ├── test_price_ingestion.py
│   │   ├── test_websocket.py
│   │   └── test_api_endpoints.py
│   └── load/
│       └── locustfile.py               # Load testing scenarios
│
├── scripts/
│   ├── seed_pairs.py                   # Fetch all Binance pairs and seed DB
│   ├── backfill_history.py             # Backfill historical candle data
│   └── create_test_agent.py            # Create a test agent account
│
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
├── Dockerfile.ingestion
├── Dockerfile.celery
└── README.md
```

---

## 5. Component 1: Price Ingestion Service

### Purpose
Connects to Binance WebSocket, receives every trade tick for all 600+ pairs, updates Redis with current prices, stores full tick history in TimescaleDB.

### Implementation: `src/price_ingestion/service.py`

```python
"""
Price Ingestion Service

Responsibilities:
1. Connect to Binance Combined WebSocket Stream for ALL trading pairs
2. Parse each incoming tick: symbol, price, quantity, timestamp, is_buyer_maker
3. Update Redis hash 'prices' with latest price per pair (overwrite)
4. Buffer ticks in memory, flush to TimescaleDB every 1 second or 5000 ticks
5. Broadcast price updates to subscribed WebSocket clients
6. Auto-reconnect on connection drop with exponential backoff
7. Health monitoring: alert if any pair has no tick for 60 seconds

Binance WebSocket URL:
  wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/...

Tick data fields from Binance:
  - s: symbol (e.g., "BTCUSDT")
  - p: price (string, e.g., "64521.30000000")
  - q: quantity (string, e.g., "0.01200000")
  - T: trade time (int, milliseconds since epoch)
  - m: is buyer maker (boolean)
  - t: trade ID (int)

Implementation notes:
- Use asyncio + websockets library for the connection
- Binance allows max 1024 streams per connection; if >1024 pairs, use multiple connections
- Buffer ticks in a list, use asyncio.create_task for periodic flush
- Use PostgreSQL COPY command (via asyncpg copy_to_table) for bulk inserts
- On flush failure, retain buffer and retry next cycle
- Run as standalone process via: python -m src.price_ingestion.service
"""
```

### Implementation: `src/price_ingestion/binance_ws.py`

```python
"""
Binance WebSocket Client

Responsibilities:
1. Fetch all USDT trading pairs from Binance REST API: GET https://api.binance.com/api/v3/exchangeInfo
2. Filter for pairs with status="TRADING" and quoteAsset="USDT"
3. Build combined stream URL with all pairs
4. Manage WebSocket connection lifecycle
5. Parse incoming messages and yield Tick objects
6. Handle reconnection with exponential backoff (1s, 2s, 4s, 8s, max 60s)

Class: BinanceWebSocketClient
  - __init__(self) → fetch pairs, build stream URL
  - async connect(self) → establish WebSocket connection
  - async listen(self) → async generator yielding Tick namedtuples
  - async reconnect(self) → close and re-establish connection
  - get_all_pairs(self) → list of all active USDT trading pair symbols

Tick namedtuple fields:
  symbol: str
  price: Decimal
  quantity: Decimal
  timestamp: datetime (from millisecond epoch)
  is_buyer_maker: bool
  trade_id: int
"""
```

### Implementation: `src/price_ingestion/tick_buffer.py`

```python
"""
Tick Buffer

Responsibilities:
1. Accept Tick objects and accumulate in an in-memory list
2. Flush to TimescaleDB when either:
   - Buffer size >= 5000 ticks
   - 1 second has elapsed since last flush
3. Use asyncpg COPY command for bulk insert (fastest method)
4. On flush failure: log error, retain buffer, retry on next cycle
5. On graceful shutdown: flush remaining buffer before exit

Class: TickBuffer
  - __init__(self, db_pool: asyncpg.Pool, flush_interval: float = 1.0, max_size: int = 5000)
  - async add(self, tick: Tick) → None
  - async flush(self) → int (number of ticks flushed)
  - async start_periodic_flush(self) → None (background task)
  - async shutdown(self) → None (final flush)

Performance target: Handle 10,000+ ticks/second without dropping
"""
```

### Implementation: `src/price_ingestion/broadcaster.py`

```python
"""
Price Broadcaster

Responsibilities:
1. Receive price updates from the ingestion service
2. Publish to Redis pub/sub channel "price_updates"
3. WebSocket manager subscribes to this channel and forwards to connected agents
4. Message format: JSON {"symbol": "BTCUSDT", "price": "64521.30", "timestamp": 1708000000000}

Class: PriceBroadcaster
  - __init__(self, redis_client: Redis)
  - async broadcast(self, tick: Tick) → None
  - async broadcast_batch(self, ticks: list[Tick]) → None
"""
```

---

## 6. Component 2: Redis Real-Time Cache

### Purpose
Sub-millisecond current price lookups for all trading pairs. Also handles agent session state and rate limiting.

### Implementation: `src/cache/price_cache.py`

```python
"""
Price Cache

Redis data structures:
1. Hash "prices" → field per pair → current price
   SET: HSET prices BTCUSDT 64521.30
   GET: HGET prices BTCUSDT → "64521.30"
   GET ALL: HGETALL prices → {"BTCUSDT": "64521.30", "ETHUSDT": "3421.50", ...}

2. Hash "prices:meta" → field per pair → last update timestamp
   Used to detect stale pairs (no update in 60s → alert)

3. Hash "ticker:{symbol}" → 24h stats
   Fields: open, high, low, close, volume, change_pct, last_update
   Updated every tick by comparing with stored open/high/low

4. String "rate_limit:{api_key}" → sliding window counter
   INCR + EXPIRE for rate limiting

Class: PriceCache
  - __init__(self, redis: Redis)
  - async set_price(self, symbol: str, price: Decimal, timestamp: datetime) → None
  - async get_price(self, symbol: str) → Decimal | None
  - async get_all_prices(self) → dict[str, Decimal]
  - async get_ticker(self, symbol: str) → TickerData
  - async update_ticker(self, tick: Tick) → None
  - async get_stale_pairs(self, threshold_seconds: int = 60) → list[str]

Redis configuration:
  - Persistence: RDB snapshots every 60s + AOF
  - Memory: ~50-100 MB for all pairs + state
  - Eviction: noeviction (all data essential)
  - Connection pool: max 50 connections
"""
```

---

## 7. Component 3: TimescaleDB Historical Storage

### Purpose
Permanent storage for every trade tick from Binance. Supports backtesting, candle generation, and historical analysis.

### Schema: Ticks Hypertable

```sql
-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Main tick storage table
CREATE TABLE ticks (
    time        TIMESTAMPTZ     NOT NULL,
    symbol      TEXT            NOT NULL,
    price       NUMERIC(20,8)   NOT NULL,
    quantity    NUMERIC(20,8)   NOT NULL,
    is_buyer_maker BOOLEAN      NOT NULL DEFAULT FALSE,
    trade_id    BIGINT          NOT NULL
);

-- Convert to hypertable (partition by time, 1-hour chunks)
SELECT create_hypertable('ticks', 'time', chunk_time_interval => INTERVAL '1 hour');

-- Create indexes
CREATE INDEX idx_ticks_symbol_time ON ticks (symbol, time DESC);
CREATE INDEX idx_ticks_trade_id ON ticks (symbol, trade_id);

-- Enable compression on chunks older than 7 days
ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);

-- Auto-compress chunks older than 7 days
SELECT add_compression_policy('ticks', INTERVAL '7 days');

-- Retention: drop raw ticks older than 90 days (candles retained indefinitely)
SELECT add_retention_policy('ticks', INTERVAL '90 days');
```

### Schema: Pre-Aggregated Candles

```sql
-- 1-minute candles (continuous aggregate)
CREATE MATERIALIZED VIEW candles_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    symbol,
    FIRST(price, time) AS open,
    MAX(price) AS high,
    MIN(price) AS low,
    LAST(price, time) AS close,
    SUM(quantity) AS volume,
    COUNT(*) AS trade_count
FROM ticks
GROUP BY bucket, symbol
WITH NO DATA;

-- Refresh policy: refresh every 1 minute, cover last 10 minutes
SELECT add_continuous_aggregate_policy('candles_1m',
    start_offset => INTERVAL '10 minutes',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute'
);

-- 5-minute candles
CREATE MATERIALIZED VIEW candles_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time) AS bucket,
    symbol,
    FIRST(price, time) AS open,
    MAX(price) AS high,
    MIN(price) AS low,
    LAST(price, time) AS close,
    SUM(quantity) AS volume,
    COUNT(*) AS trade_count
FROM ticks
GROUP BY bucket, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('candles_5m',
    start_offset => INTERVAL '30 minutes',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes'
);

-- 1-hour candles
CREATE MATERIALIZED VIEW candles_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    symbol,
    FIRST(price, time) AS open,
    MAX(price) AS high,
    MIN(price) AS low,
    LAST(price, time) AS close,
    SUM(quantity) AS volume,
    COUNT(*) AS trade_count
FROM ticks
GROUP BY bucket, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('candles_1h',
    start_offset => INTERVAL '4 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- 1-day candles
CREATE MATERIALIZED VIEW candles_1d
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    symbol,
    FIRST(price, time) AS open,
    MAX(price) AS high,
    MIN(price) AS low,
    LAST(price, time) AS close,
    SUM(quantity) AS volume,
    COUNT(*) AS trade_count
FROM ticks
GROUP BY bucket, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('candles_1d',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day'
);
```

### Storage Estimates

| Timeframe | Estimated Ticks | Raw Size | Compressed Size |
|---|---|---|---|
| Per Day | 50-100M | 5-10 GB | 500MB - 1GB |
| Per Month | 1.5-3B | 150-300 GB | 15-30 GB |
| Per Year | 18-36B | 1.8-3.6 TB | 180-360 GB |

---

## 8. Component 4: Order Execution Engine

### Purpose
Process all buy/sell orders from agents against live market prices with realistic slippage simulation.

### Implementation: `src/order_engine/engine.py`

```python
"""
Order Execution Engine

Supported order types:
1. MARKET  → Execute immediately at current price + slippage
2. LIMIT   → Queue until price reaches target, then execute
3. STOP_LOSS → Convert to market when price drops below trigger
4. TAKE_PROFIT → Convert to market when price rises above trigger

Order lifecycle:
1. Agent submits order via API
2. Validate: sufficient balance, valid pair, within risk limits
3. For MARKET: fetch price from Redis, calculate slippage, execute
4. For LIMIT: lock required funds, add to pending_orders table, monitor
5. On execution: update balances (debit quote asset, credit base asset for buy)
6. Record trade in trades table
7. Send WebSocket notification to agent
8. Return OrderResult with execution details

Class: OrderEngine
  - __init__(self, price_cache, balance_manager, risk_manager, trade_repo, order_repo)
  - async place_order(self, account_id: UUID, order: OrderRequest) → OrderResult
  - async cancel_order(self, account_id: UUID, order_id: UUID) → bool
  - async cancel_all_orders(self, account_id: UUID) → int
  - async check_pending_orders(self) → list[OrderResult]  # called by background task

OrderRequest fields:
  symbol: str          # e.g., "BTCUSDT"
  side: str            # "buy" or "sell"
  type: str            # "market", "limit", "stop_loss", "take_profit"
  quantity: Decimal     # amount of base asset
  price: Decimal | None # required for limit, stop_loss, take_profit

OrderResult fields:
  order_id: UUID
  status: str          # "filled", "pending", "rejected"
  executed_price: Decimal | None
  executed_quantity: Decimal | None
  slippage: Decimal | None
  fee: Decimal          # simulated trading fee (0.1%)
  timestamp: datetime
  rejection_reason: str | None
"""
```

### Implementation: `src/order_engine/slippage.py`

```python
"""
Slippage Calculation Model

Simulates realistic price impact based on order size.

Formula:
  execution_price = reference_price * (1 + direction * slippage_factor * order_size_usd / avg_daily_volume_usd)

Where:
  - direction: +1 for buy (price goes up), -1 for sell (price goes down)
  - slippage_factor: base factor per pair (default 0.1, calibrated from spread data)
  - order_size_usd: order quantity * reference_price
  - avg_daily_volume_usd: 24h volume from ticker data

Small orders (<0.01% of daily volume): negligible slippage (~0.01%)
Medium orders (0.01-0.1%): moderate slippage (~0.05-0.1%)
Large orders (>0.1%): significant slippage (~0.1-0.5%)

Trading fee: 0.1% of order value (simulates Binance standard fee)

Class: SlippageCalculator
  - __init__(self, price_cache: PriceCache, default_factor: float = 0.1)
  - async calculate(self, symbol: str, side: str, quantity: Decimal, reference_price: Decimal) → SlippageResult

SlippageResult:
  execution_price: Decimal
  slippage_amount: Decimal
  slippage_pct: Decimal
  fee: Decimal
"""
```

### Implementation: `src/order_engine/matching.py`

```python
"""
Limit Order Matcher

Background task that runs every 1 second:
1. Fetch all pending limit/stop_loss/take_profit orders from database
2. For each order, check current price from Redis
3. Limit buy: execute if current_price <= order.price
4. Limit sell: execute if current_price >= order.price
5. Stop loss: execute as market if current_price <= order.trigger_price
6. Take profit: execute as market if current_price >= order.trigger_price
7. On match: execute order through OrderEngine, update status

Class: LimitOrderMatcher
  - __init__(self, order_engine, price_cache, order_repo)
  - async check_all_pending(self) → list[OrderResult]
  - async check_order(self, order: Order) → OrderResult | None

Run as Celery beat task every 1 second
"""
```

---

## 9. Component 5: Account Management System

### Purpose
Handle agent registration, authentication, virtual wallets, and balance tracking.

### Database Schema

```sql
-- Agent accounts
CREATE TABLE accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key         VARCHAR(64) UNIQUE NOT NULL,       -- plaintext for lookup
    api_key_hash    VARCHAR(128) NOT NULL,              -- bcrypt hash for verification
    api_secret_hash VARCHAR(128) NOT NULL,              -- bcrypt hash
    display_name    VARCHAR(100) NOT NULL,
    email           VARCHAR(255),
    starting_balance NUMERIC(20,8) NOT NULL DEFAULT 10000.00,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, suspended, archived
    risk_profile    JSONB DEFAULT '{}',                 -- custom risk limits
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Per-asset balances
CREATE TABLE balances (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID NOT NULL REFERENCES accounts(id),
    asset       VARCHAR(20) NOT NULL,                   -- e.g., "USDT", "BTC", "ETH"
    available   NUMERIC(20,8) NOT NULL DEFAULT 0,       -- free to trade
    locked      NUMERIC(20,8) NOT NULL DEFAULT 0,       -- locked in pending orders
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, asset)
);

CREATE INDEX idx_balances_account ON balances(account_id);

-- Trading sessions (for account reset tracking)
CREATE TABLE trading_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id),
    starting_balance NUMERIC(20,8) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    ending_equity   NUMERIC(20,8),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'  -- active, closed
);
```

### Implementation: `src/accounts/service.py`

```python
"""
Account Service

Responsibilities:
1. Register new agent accounts
2. Authenticate API keys
3. Manage account lifecycle (activate, suspend, archive)
4. Handle account reset (close current session, start new one)

Class: AccountService
  - async register(self, display_name: str, email: str | None, starting_balance: Decimal = 10000) → AccountCredentials
  - async authenticate(self, api_key: str) → Account | None
  - async get_account(self, account_id: UUID) → Account
  - async reset_account(self, account_id: UUID) → TradingSession
  - async suspend_account(self, account_id: UUID) → None
  - async list_accounts(self, status: str = "active") → list[Account]

AccountCredentials (returned on registration):
  account_id: UUID
  api_key: str          # shown once, stored as hash
  api_secret: str       # shown once, stored as hash
  display_name: str
  starting_balance: Decimal
"""
```

### Implementation: `src/accounts/balance_manager.py`

```python
"""
Balance Manager

Handles all balance modifications with strict consistency.
All operations are atomic (database transactions).

Class: BalanceManager
  - async get_balance(self, account_id: UUID, asset: str) → Balance
  - async get_all_balances(self, account_id: UUID) → list[Balance]
  - async credit(self, account_id: UUID, asset: str, amount: Decimal, reason: str) → Balance
  - async debit(self, account_id: UUID, asset: str, amount: Decimal, reason: str) → Balance
  - async lock(self, account_id: UUID, asset: str, amount: Decimal) → Balance  # for pending orders
  - async unlock(self, account_id: UUID, asset: str, amount: Decimal) → Balance
  - async has_sufficient_balance(self, account_id: UUID, asset: str, amount: Decimal) → bool
  - async execute_trade(self, account_id: UUID, base_asset: str, quote_asset: str, side: str, base_amount: Decimal, quote_amount: Decimal, fee: Decimal) → None

Trade execution example (buy 0.5 BTC at 64000 USDT):
  - Debit USDT: 32000 (0.5 * 64000) + fee
  - Credit BTC: 0.5
  Both in same transaction → atomic

Balance invariant: available >= 0 AND locked >= 0 ALWAYS
"""
```

---

## 10. Component 6: Portfolio Tracker

### Purpose
Real-time portfolio valuation and performance metrics for every agent.

### Implementation: `src/portfolio/tracker.py`

```python
"""
Portfolio Tracker

Continuously calculates the real-time value of every agent's holdings.

Class: PortfolioTracker
  - async get_portfolio(self, account_id: UUID) → PortfolioSummary
  - async get_positions(self, account_id: UUID) → list[Position]
  - async get_pnl(self, account_id: UUID) → PnLBreakdown

PortfolioSummary:
  total_equity: Decimal          # cash + all positions at current market price
  available_cash: Decimal        # USDT available balance
  locked_cash: Decimal           # USDT locked in pending orders
  total_position_value: Decimal  # sum of all non-USDT holdings at market price
  unrealized_pnl: Decimal        # current positions vs entry price
  realized_pnl: Decimal          # from closed trades
  total_pnl: Decimal             # unrealized + realized
  roi_pct: Decimal               # total return on starting balance
  positions: list[Position]

Position:
  symbol: str                    # e.g., "BTCUSDT"
  asset: str                     # e.g., "BTC"
  quantity: Decimal
  avg_entry_price: Decimal       # weighted average entry
  current_price: Decimal         # from Redis
  market_value: Decimal          # quantity * current_price
  unrealized_pnl: Decimal        # market_value - (quantity * avg_entry_price)
  unrealized_pnl_pct: Decimal
"""
```

### Implementation: `src/portfolio/metrics.py`

```python
"""
Portfolio Performance Metrics

Calculates advanced trading performance metrics from snapshot history.

Class: PerformanceMetrics
  - async calculate(self, account_id: UUID, period: str = "all") → Metrics

Metrics:
  sharpe_ratio: float            # risk-adjusted return (annualized)
  sortino_ratio: float           # downside risk-adjusted return
  max_drawdown: float            # largest peak-to-trough decline (%)
  max_drawdown_duration: int     # days in longest drawdown
  win_rate: float                # % of profitable trades
  profit_factor: float           # gross profit / gross loss
  avg_win: Decimal               # average winning trade size
  avg_loss: Decimal              # average losing trade size
  total_trades: int
  avg_trades_per_day: float
  best_trade: Decimal
  worst_trade: Decimal
  current_streak: int            # positive = win streak, negative = loss streak

Periods: "1d", "7d", "30d", "90d", "all"
"""
```

### Implementation: `src/portfolio/snapshots.py`

```python
"""
Portfolio Snapshots

Background service that captures periodic snapshots for charting and analysis.

Schedule (Celery beat):
  - Every 1 minute:  quick snapshot (portfolio value, top 5 positions)
  - Every 1 hour:    detailed snapshot (full position breakdown, all metrics)
  - Every 24 hours:  daily summary with comprehensive performance report

Table: portfolio_snapshots
  id: UUID
  account_id: UUID
  snapshot_type: str       # "minute", "hourly", "daily"
  total_equity: Decimal
  positions: JSONB         # serialized position data
  metrics: JSONB           # serialized metrics (for hourly/daily)
  created_at: TIMESTAMPTZ

Class: SnapshotService
  - async capture_minute_snapshot(self, account_id: UUID) → None
  - async capture_hourly_snapshot(self, account_id: UUID) → None
  - async capture_daily_snapshot(self, account_id: UUID) → None
  - async get_snapshot_history(self, account_id: UUID, type: str, limit: int) → list[Snapshot]
"""
```

---

## 11. Component 7: Risk Management Engine

### Purpose
Prevent agents from unrealistic or destructive trading behavior. Configurable per agent.

### Implementation: `src/risk/manager.py`

```python
"""
Risk Manager

Enforces trading limits. Called by Order Engine before every order execution.

Default limits (configurable per account via risk_profile JSON):
  MAX_POSITION_SIZE_PCT: 25      # single position max % of total equity
  MAX_OPEN_ORDERS: 50            # max concurrent pending orders
  DAILY_LOSS_LIMIT_PCT: 20       # halt trading if daily loss exceeds % of starting balance
  MAX_LEVERAGE: 1.0              # no leverage (future: configurable)
  MIN_ORDER_SIZE_USD: 1.0        # minimum order value
  MAX_ORDER_SIZE_PCT: 50         # single order max % of available balance
  ORDER_RATE_LIMIT: 100          # max orders per minute

Class: RiskManager
  - __init__(self, price_cache, balance_manager, account_repo)
  - async validate_order(self, account_id: UUID, order: OrderRequest) → RiskCheckResult
  - async check_daily_loss(self, account_id: UUID) → bool  # True if within limit
  - async get_risk_limits(self, account_id: UUID) → RiskLimits
  - async update_risk_limits(self, account_id: UUID, limits: RiskLimits) → None

RiskCheckResult:
  approved: bool
  rejection_reason: str | None    # "insufficient_balance", "position_limit", "daily_loss_limit", etc.

Validation chain (short-circuit on first failure):
1. Account is active (not suspended)
2. Daily loss limit not exceeded
3. Order rate limit not exceeded
4. Order size >= minimum
5. Order size <= maximum % of available balance
6. Resulting position <= maximum % of total equity
7. Open orders count <= maximum
8. Sufficient available balance for the trade
"""
```

### Implementation: `src/risk/circuit_breaker.py`

```python
"""
Circuit Breaker

Tracks daily PnL per agent and halts trading when daily loss limit is hit.

Logic:
1. On each trade execution, calculate running daily PnL
2. Daily PnL = sum of all realized trades today + unrealized PnL change
3. If daily_loss > starting_balance * DAILY_LOSS_LIMIT_PCT / 100 → trip breaker
4. When breaker is tripped: agent can read data but cannot place orders
5. Breaker resets at 00:00 UTC daily

Class: CircuitBreaker
  - async record_trade_pnl(self, account_id: UUID, pnl: Decimal) → None
  - async is_tripped(self, account_id: UUID) → bool
  - async get_daily_pnl(self, account_id: UUID) → Decimal
  - async reset_all(self) → None  # called by daily Celery task at 00:00 UTC

Storage: Redis hash "circuit_breaker:{account_id}" with fields:
  daily_pnl: Decimal
  tripped: bool
  tripped_at: datetime | None
TTL: auto-expire at midnight UTC
"""
```

---

## 12. Component 8: API Gateway (FastAPI)

### Purpose
Single entry point for all agent communication. Handles routing, auth, rate limiting, validation.

### Implementation: `src/main.py`

```python
"""
FastAPI Application Entry Point

Setup:
1. Create FastAPI app with metadata (title, version, description)
2. Add middleware: CORS, authentication, rate limiting, request logging
3. Include routers: auth, market, trading, account, analytics
4. Mount WebSocket endpoint at /ws/v1
5. Add startup event: connect Redis, connect DB, start health checks
6. Add shutdown event: close connections gracefully
7. Mount Prometheus metrics endpoint at /metrics
8. Mount health check at /health

CORS: Allow all origins for development, restrict in production
Docs: Available at /docs (Swagger) and /redoc (ReDoc)
"""
```

### Implementation: `src/api/middleware/auth.py`

```python
"""
Authentication Middleware

Two authentication methods:
1. API Key: Header "X-API-Key: {key}" → lookup in database → attach account to request
2. JWT Token: Header "Authorization: Bearer {token}" → decode → verify → attach account

Public endpoints (no auth required):
  - POST /api/v1/auth/register
  - POST /api/v1/auth/login
  - GET /health
  - GET /docs, /redoc, /openapi.json

All other endpoints require valid authentication.

Class: AuthMiddleware(BaseHTTPMiddleware)
  - async dispatch(self, request, call_next) → Response

Helper functions:
  - verify_api_key(key: str) → Account | None
  - create_jwt_token(account_id: UUID) → str
  - verify_jwt_token(token: str) → UUID | None
  - get_current_account(request: Request) → Account  # FastAPI dependency
"""
```

### Implementation: `src/api/middleware/rate_limit.py`

```python
"""
Rate Limiting Middleware

Uses Redis sliding window algorithm.

Limits:
  - General API: 600 requests/minute per API key
  - Order placement: 100 orders/minute per API key
  - Market data: 1200 requests/minute per API key (higher limit)
  - WebSocket: 10 subscriptions per connection

Implementation:
  - Key: "rate_limit:{api_key}:{endpoint_group}:{minute_bucket}"
  - INCR key on each request
  - EXPIRE key after 60 seconds
  - If count > limit → return 429 Too Many Requests

Response headers:
  X-RateLimit-Limit: 600
  X-RateLimit-Remaining: 423
  X-RateLimit-Reset: 1708000060  # Unix timestamp when window resets
"""
```

---

## 13. Component 9: Monitoring & Logging

### Implementation: `src/monitoring/prometheus_metrics.py`

```python
"""
Prometheus Custom Metrics

Metrics to track:
  # Price Ingestion
  price_ticks_received_total (Counter, labels: symbol)
  price_ticks_per_second (Gauge)
  tick_buffer_size (Gauge)
  tick_flush_duration_seconds (Histogram)
  tick_flush_failures_total (Counter)
  stale_pairs_count (Gauge)

  # API
  api_requests_total (Counter, labels: method, endpoint, status)
  api_request_duration_seconds (Histogram, labels: method, endpoint)
  websocket_connections_active (Gauge)

  # Trading
  orders_placed_total (Counter, labels: type, side, status)
  order_execution_duration_seconds (Histogram)
  trades_executed_total (Counter, labels: symbol, side)
  trade_volume_usd_total (Counter, labels: symbol)

  # Accounts
  active_agents_count (Gauge)
  circuit_breakers_tripped_total (Counter)

  # Infrastructure
  redis_memory_bytes (Gauge)
  redis_hit_rate (Gauge)
  db_connection_pool_size (Gauge)
  db_query_duration_seconds (Histogram, labels: query_type)
"""
```

### Grafana Dashboards to Create

```
1. System Overview Dashboard
   - Ticks/second ingestion rate
   - API requests/second
   - Active WebSocket connections
   - Redis memory usage
   - Database query latency (p50, p95, p99)
   - Error rate

2. Agent Activity Dashboard
   - Active agents count
   - Orders placed per hour (by agent)
   - Trade volume per hour
   - Agent PnL leaderboard (real-time)
   - Most traded pairs
   - Circuit breaker events

3. Price Feed Health Dashboard
   - Ticks received per pair per minute
   - Stale pair alerts
   - Buffer flush latency
   - WebSocket connection stability
```

---

## 14. Database Schema

### Complete Schema (PostgreSQL + TimescaleDB)

```sql
-- ============================================
-- EXTENSIONS
-- ============================================
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================
-- ACCOUNTS
-- ============================================
CREATE TABLE accounts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key           VARCHAR(64) UNIQUE NOT NULL,
    api_key_hash      VARCHAR(128) NOT NULL,
    api_secret_hash   VARCHAR(128) NOT NULL,
    display_name      VARCHAR(100) NOT NULL,
    email             VARCHAR(255),
    starting_balance  NUMERIC(20,8) NOT NULL DEFAULT 10000.00,
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    risk_profile      JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- BALANCES
-- ============================================
CREATE TABLE balances (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    asset       VARCHAR(20) NOT NULL,
    available   NUMERIC(20,8) NOT NULL DEFAULT 0 CHECK (available >= 0),
    locked      NUMERIC(20,8) NOT NULL DEFAULT 0 CHECK (locked >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, asset)
);
CREATE INDEX idx_balances_account ON balances(account_id);

-- ============================================
-- TRADING SESSIONS
-- ============================================
CREATE TABLE trading_sessions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    starting_balance  NUMERIC(20,8) NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMPTZ,
    ending_equity     NUMERIC(20,8),
    status            VARCHAR(20) NOT NULL DEFAULT 'active'
);
CREATE INDEX idx_sessions_account ON trading_sessions(account_id);

-- ============================================
-- ORDERS
-- ============================================
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES trading_sessions(id),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL CHECK (side IN ('buy', 'sell')),
    type            VARCHAR(20) NOT NULL CHECK (type IN ('market', 'limit', 'stop_loss', 'take_profit')),
    quantity        NUMERIC(20,8) NOT NULL CHECK (quantity > 0),
    price           NUMERIC(20,8),            -- target price for limit/stop/tp
    executed_price  NUMERIC(20,8),            -- actual execution price
    executed_qty    NUMERIC(20,8),            -- actual executed quantity
    slippage_pct    NUMERIC(10,6),
    fee             NUMERIC(20,8),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'filled', 'partially_filled', 'cancelled', 'rejected', 'expired')),
    rejection_reason VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at       TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ               -- for limit orders with TTL
);
CREATE INDEX idx_orders_account ON orders(account_id);
CREATE INDEX idx_orders_account_status ON orders(account_id, status);
CREATE INDEX idx_orders_symbol_status ON orders(symbol, status) WHERE status = 'pending';

-- ============================================
-- TRADES (executed order fills)
-- ============================================
CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id        UUID NOT NULL REFERENCES orders(id),
    session_id      UUID REFERENCES trading_sessions(id),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL,
    quantity        NUMERIC(20,8) NOT NULL,
    price           NUMERIC(20,8) NOT NULL,
    quote_amount    NUMERIC(20,8) NOT NULL,   -- quantity * price
    fee             NUMERIC(20,8) NOT NULL,
    realized_pnl    NUMERIC(20,8),            -- PnL if closing a position
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_trades_account ON trades(account_id);
CREATE INDEX idx_trades_account_time ON trades(account_id, created_at DESC);
CREATE INDEX idx_trades_symbol ON trades(symbol, created_at DESC);

-- ============================================
-- POSITIONS (aggregated view of current holdings)
-- ============================================
CREATE TABLE positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL DEFAULT 'long',
    quantity        NUMERIC(20,8) NOT NULL DEFAULT 0,
    avg_entry_price NUMERIC(20,8) NOT NULL,
    total_cost      NUMERIC(20,8) NOT NULL,   -- quantity * avg_entry_price
    realized_pnl    NUMERIC(20,8) NOT NULL DEFAULT 0,
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, symbol)
);
CREATE INDEX idx_positions_account ON positions(account_id);

-- ============================================
-- TICKS (TimescaleDB hypertable)
-- ============================================
CREATE TABLE ticks (
    time            TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    price           NUMERIC(20,8) NOT NULL,
    quantity        NUMERIC(20,8) NOT NULL,
    is_buyer_maker  BOOLEAN NOT NULL DEFAULT FALSE,
    trade_id        BIGINT NOT NULL
);

SELECT create_hypertable('ticks', 'time', chunk_time_interval => INTERVAL '1 hour');
CREATE INDEX idx_ticks_symbol_time ON ticks (symbol, time DESC);

ALTER TABLE ticks SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('ticks', INTERVAL '7 days');
SELECT add_retention_policy('ticks', INTERVAL '90 days');

-- ============================================
-- PORTFOLIO SNAPSHOTS
-- ============================================
CREATE TABLE portfolio_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    snapshot_type   VARCHAR(10) NOT NULL CHECK (snapshot_type IN ('minute', 'hourly', 'daily')),
    total_equity    NUMERIC(20,8) NOT NULL,
    available_cash  NUMERIC(20,8) NOT NULL,
    position_value  NUMERIC(20,8) NOT NULL,
    unrealized_pnl  NUMERIC(20,8) NOT NULL,
    realized_pnl    NUMERIC(20,8) NOT NULL,
    positions       JSONB,
    metrics         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_snapshots_account_type ON portfolio_snapshots(account_id, snapshot_type, created_at DESC);

-- Convert to hypertable for automatic partition management
SELECT create_hypertable('portfolio_snapshots', 'created_at', chunk_time_interval => INTERVAL '1 day');

-- ============================================
-- TRADING PAIRS (reference data)
-- ============================================
CREATE TABLE trading_pairs (
    symbol          VARCHAR(20) PRIMARY KEY,
    base_asset      VARCHAR(10) NOT NULL,
    quote_asset     VARCHAR(10) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    min_qty         NUMERIC(20,8),
    max_qty         NUMERIC(20,8),
    step_size       NUMERIC(20,8),
    min_notional    NUMERIC(20,8),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- AUDIT LOG
-- ============================================
CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    account_id  UUID REFERENCES accounts(id),
    action      VARCHAR(50) NOT NULL,
    details     JSONB,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_account ON audit_log(account_id, created_at DESC);
```

---

## 15. REST API Specification

### Base URL
```
https://api.agentexchange.com/api/v1
```

### Authentication
All requests (except register/login) require header:
```
X-API-Key: {your_api_key}
```

### Error Response Format
```json
{
    "error": {
        "code": "INSUFFICIENT_BALANCE",
        "message": "Not enough USDT. Required: 5000.00, Available: 3241.50",
        "details": {
            "required": "5000.00",
            "available": "3241.50",
            "asset": "USDT"
        }
    }
}
```

### Error Codes
| Code | HTTP Status | Description |
|---|---|---|
| `INVALID_API_KEY` | 401 | API key not found or inactive |
| `INVALID_TOKEN` | 401 | JWT token invalid or expired |
| `PERMISSION_DENIED` | 403 | Action not authorised for this account |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INSUFFICIENT_BALANCE` | 400 | Not enough funds |
| `INVALID_SYMBOL` | 400 | Trading pair not found |
| `INVALID_ORDER_TYPE` | 400 | Unsupported order type |
| `INVALID_QUANTITY` | 400 | Quantity below minimum or above maximum |
| `VALIDATION_ERROR` | 422 | Generic request payload validation failure |
| `RISK_LIMIT_EXCEEDED` | 400 | Would exceed a risk limit (position size, max open orders, etc.) |
| `DAILY_LOSS_LIMIT` | 403 | Daily loss limit reached, trading halted |
| `ORDER_NOT_FOUND` | 404 | Order ID not found |
| `ORDER_NOT_CANCELLABLE` | 400 | Order already filled or cancelled |
| `ORDER_REJECTED` | 400 | Order rejected by the engine or risk manager |
| `TRADE_NOT_FOUND` | 404 | Trade ID not found |
| `ACCOUNT_SUSPENDED` | 403 | Account is suspended |
| `DUPLICATE_ACCOUNT` | 409 | Email already registered |
| `ACCOUNT_NOT_FOUND` | 404 | Account ID not found |
| `PRICE_NOT_AVAILABLE` | 503 | Real-time price not available for the symbol |
| `DATABASE_ERROR` | 500 | Unexpected database failure |
| `CACHE_ERROR` | 500 | Unexpected Redis/cache failure |
| `SERVICE_UNAVAILABLE` | 503 | Required downstream service is unavailable |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

### 15.1 Authentication Endpoints

#### POST /auth/register
Register a new agent account.

**Request:**
```json
{
    "display_name": "MyTradingBot",
    "email": "dev@example.com",
    "starting_balance": 10000.00
}
```

**Response (201):**
```json
{
    "account_id": "550e8400-e29b-41d4-a716-446655440000",
    "api_key": "ak_live_xJ3kF9mN2pQ7wR4tY8uI1oA5sD6fG0hL",
    "api_secret": "sk_live_bV3cX9mN2pQ7wR4tY8uI1oA5sD6fG0hK",
    "display_name": "MyTradingBot",
    "starting_balance": "10000.00",
    "message": "Save your API secret now. It will not be shown again."
}
```

#### POST /auth/login
Get JWT token for session-based auth.

**Request:**
```json
{
    "api_key": "ak_live_xJ3kF9mN2pQ7wR4tY8uI1oA5sD6fG0hL",
    "api_secret": "sk_live_bV3cX9mN2pQ7wR4tY8uI1oA5sD6fG0hK"
}
```

**Response (200):**
```json
{
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "expires_at": "2026-02-24T12:00:00Z",
    "token_type": "Bearer"
}
```

---

### 15.2 Market Data Endpoints

#### GET /market/pairs
List all available trading pairs.

**Response (200):**
```json
{
    "pairs": [
        {
            "symbol": "BTCUSDT",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "status": "active",
            "min_qty": "0.00001",
            "step_size": "0.00001",
            "min_notional": "10.00"
        }
    ],
    "total": 647
}
```

#### GET /market/price/{symbol}
Get current price for a trading pair.

**Response (200):**
```json
{
    "symbol": "BTCUSDT",
    "price": "64521.30000000",
    "timestamp": "2026-02-23T15:30:45.123Z"
}
```

#### GET /market/prices
Get current prices for all pairs.

**Query params:** `symbols` (optional, comma-separated filter)

**Response (200):**
```json
{
    "prices": {
        "BTCUSDT": "64521.30",
        "ETHUSDT": "3421.50",
        "SOLUSDT": "142.80"
    },
    "timestamp": "2026-02-23T15:30:45.123Z",
    "count": 647
}
```

#### GET /market/ticker/{symbol}
Get 24h ticker statistics.

**Response (200):**
```json
{
    "symbol": "BTCUSDT",
    "open": "63800.00",
    "high": "65200.00",
    "low": "63500.00",
    "close": "64521.30",
    "volume": "24531.456",
    "quote_volume": "1582345678.90",
    "change": "721.30",
    "change_pct": "1.13",
    "trade_count": 1456789,
    "timestamp": "2026-02-23T15:30:45.123Z"
}
```

#### GET /market/candles/{symbol}
Get OHLCV candle data.

**Query params:**
- `interval`: "1m", "5m", "15m", "1h", "4h", "1d" (required)
- `limit`: 1-1000, default 100
- `start_time`: ISO timestamp (optional)
- `end_time`: ISO timestamp (optional)

**Response (200):**
```json
{
    "symbol": "BTCUSDT",
    "interval": "1h",
    "candles": [
        {
            "time": "2026-02-23T14:00:00Z",
            "open": "64200.00",
            "high": "64600.00",
            "low": "64100.00",
            "close": "64521.30",
            "volume": "1234.567",
            "trade_count": 45678
        }
    ],
    "count": 100
}
```

#### GET /market/trades/{symbol}
Get recent trades for a pair.

**Query params:** `limit`: 1-500, default 100

**Response (200):**
```json
{
    "symbol": "BTCUSDT",
    "trades": [
        {
            "trade_id": 123456789,
            "price": "64521.30",
            "quantity": "0.01200",
            "time": "2026-02-23T15:30:45.123Z",
            "is_buyer_maker": false
        }
    ]
}
```

#### GET /market/orderbook/{symbol}
Get simulated order book snapshot.

**Query params:** `depth`: 5, 10, 20 (default 10)

**Response (200):**
```json
{
    "symbol": "BTCUSDT",
    "bids": [
        ["64520.00", "1.234"],
        ["64519.00", "2.567"]
    ],
    "asks": [
        ["64522.00", "0.987"],
        ["64523.00", "1.456"]
    ],
    "timestamp": "2026-02-23T15:30:45.123Z"
}
```

---

### 15.3 Trading Endpoints

#### POST /trade/order
Place a new order.

**Request (Market Order):**
```json
{
    "symbol": "BTCUSDT",
    "side": "buy",
    "type": "market",
    "quantity": 0.5
}
```

**Request (Limit Order):**
```json
{
    "symbol": "BTCUSDT",
    "side": "buy",
    "type": "limit",
    "quantity": 0.5,
    "price": 63000.00
}
```

**Request (Stop Loss):**
```json
{
    "symbol": "BTCUSDT",
    "side": "sell",
    "type": "stop_loss",
    "quantity": 0.5,
    "price": 62000.00
}
```

**Request (Take Profit):**
```json
{
    "symbol": "BTCUSDT",
    "side": "sell",
    "type": "take_profit",
    "quantity": 0.5,
    "price": 70000.00
}
```

**Response (201 - Market Order Filled):**
```json
{
    "order_id": "660e8400-e29b-41d4-a716-446655440001",
    "status": "filled",
    "symbol": "BTCUSDT",
    "side": "buy",
    "type": "market",
    "requested_quantity": "0.50000000",
    "executed_quantity": "0.50000000",
    "executed_price": "64525.18",
    "slippage_pct": "0.006",
    "fee": "32.26",
    "total_cost": "32294.85",
    "filled_at": "2026-02-23T15:30:45.456Z"
}
```

**Response (201 - Limit Order Pending):**
```json
{
    "order_id": "660e8400-e29b-41d4-a716-446655440002",
    "status": "pending",
    "symbol": "BTCUSDT",
    "side": "buy",
    "type": "limit",
    "quantity": "0.50000000",
    "price": "63000.00",
    "locked_amount": "31515.00",
    "created_at": "2026-02-23T15:30:45.456Z"
}
```

#### GET /trade/order/{order_id}
Get order details.

**Response (200):**
```json
{
    "order_id": "660e8400-e29b-41d4-a716-446655440001",
    "status": "filled",
    "symbol": "BTCUSDT",
    "side": "buy",
    "type": "market",
    "quantity": "0.50000000",
    "executed_price": "64525.18",
    "executed_qty": "0.50000000",
    "slippage_pct": "0.006",
    "fee": "32.26",
    "created_at": "2026-02-23T15:30:45.456Z",
    "filled_at": "2026-02-23T15:30:45.456Z"
}
```

#### GET /trade/orders
List all orders with filters.

**Query params:**
- `status`: "pending", "filled", "cancelled", "all" (default "all")
- `symbol`: filter by pair (optional)
- `side`: "buy", "sell" (optional)
- `limit`: 1-500, default 50
- `offset`: pagination offset

#### GET /trade/orders/open
List only pending orders.

#### DELETE /trade/order/{order_id}
Cancel a pending order.

**Response (200):**
```json
{
    "order_id": "660e8400-e29b-41d4-a716-446655440002",
    "status": "cancelled",
    "unlocked_amount": "31515.00",
    "cancelled_at": "2026-02-23T15:35:00.000Z"
}
```

#### DELETE /trade/orders/open
Cancel all pending orders.

**Response (200):**
```json
{
    "cancelled_count": 5,
    "total_unlocked": "45230.00"
}
```

#### GET /trade/history
Get trade execution history.

**Query params:**
- `symbol`: filter by pair (optional)
- `side`: "buy", "sell" (optional)
- `start_time`: ISO timestamp (optional)
- `end_time`: ISO timestamp (optional)
- `limit`: 1-500, default 50
- `offset`: pagination offset

---

### 15.4 Account Endpoints

#### GET /account/info
Get account details.

**Response (200):**
```json
{
    "account_id": "550e8400-e29b-41d4-a716-446655440000",
    "display_name": "MyTradingBot",
    "status": "active",
    "starting_balance": "10000.00",
    "current_session": {
        "session_id": "770e8400-e29b-41d4-a716-446655440003",
        "started_at": "2026-02-20T00:00:00Z"
    },
    "risk_profile": {
        "max_position_size_pct": 25,
        "daily_loss_limit_pct": 20,
        "max_open_orders": 50
    },
    "created_at": "2026-02-20T00:00:00Z"
}
```

#### GET /account/balance
Get all asset balances.

**Response (200):**
```json
{
    "balances": [
        {
            "asset": "USDT",
            "available": "6741.50",
            "locked": "1500.00",
            "total": "8241.50"
        },
        {
            "asset": "BTC",
            "available": "0.50000000",
            "locked": "0.00000000",
            "total": "0.50000000"
        },
        {
            "asset": "ETH",
            "available": "2.00000000",
            "locked": "0.00000000",
            "total": "2.00000000"
        }
    ],
    "total_equity_usdt": "12458.30"
}
```

#### GET /account/positions
Get current open positions.

**Response (200):**
```json
{
    "positions": [
        {
            "symbol": "BTCUSDT",
            "asset": "BTC",
            "quantity": "0.50000000",
            "avg_entry_price": "63200.00",
            "current_price": "64521.30",
            "market_value": "32260.65",
            "unrealized_pnl": "660.65",
            "unrealized_pnl_pct": "2.09",
            "opened_at": "2026-02-21T10:15:00Z"
        }
    ],
    "total_unrealized_pnl": "660.65"
}
```

#### GET /account/portfolio
Full portfolio summary.

**Response (200):**
```json
{
    "total_equity": "12458.30",
    "available_cash": "6741.50",
    "locked_cash": "1500.00",
    "total_position_value": "4216.80",
    "unrealized_pnl": "660.65",
    "realized_pnl": "1241.30",
    "total_pnl": "1901.95",
    "roi_pct": "19.02",
    "starting_balance": "10000.00",
    "positions": [...],
    "timestamp": "2026-02-23T15:30:45Z"
}
```

#### GET /account/pnl
PnL breakdown.

**Query params:** `period`: "1d", "7d", "30d", "all" (default "all")

**Response (200):**
```json
{
    "period": "7d",
    "realized_pnl": "1241.30",
    "unrealized_pnl": "660.65",
    "total_pnl": "1901.95",
    "fees_paid": "156.20",
    "net_pnl": "1745.75",
    "winning_trades": 23,
    "losing_trades": 12,
    "win_rate": "65.71"
}
```

#### POST /account/reset
Reset account to starting balance.

**Request:**
```json
{
    "confirm": true,
    "new_starting_balance": 10000.00
}
```

**Response (200):**
```json
{
    "message": "Account reset successful",
    "previous_session": {
        "session_id": "770e8400-e29b-41d4-a716-446655440003",
        "ending_equity": "12458.30",
        "total_pnl": "2458.30",
        "duration_days": 3
    },
    "new_session": {
        "session_id": "770e8400-e29b-41d4-a716-446655440004",
        "starting_balance": "10000.00",
        "started_at": "2026-02-23T15:35:00Z"
    }
}
```

---

### 15.5 Analytics Endpoints

#### GET /analytics/performance
Get performance metrics.

**Query params:** `period`: "1d", "7d", "30d", "90d", "all"

**Response (200):**
```json
{
    "period": "30d",
    "sharpe_ratio": 1.85,
    "sortino_ratio": 2.31,
    "max_drawdown_pct": 8.5,
    "max_drawdown_duration_days": 3,
    "win_rate": 65.71,
    "profit_factor": 2.1,
    "avg_win": "156.30",
    "avg_loss": "-74.50",
    "total_trades": 35,
    "avg_trades_per_day": 1.17,
    "best_trade": "523.00",
    "worst_trade": "-210.00",
    "current_streak": 3
}
```

#### GET /analytics/portfolio/history
Historical portfolio value for charting.

**Query params:**
- `interval`: "1m", "1h", "1d" (default "1h")
- `start_time`: ISO timestamp
- `end_time`: ISO timestamp
- `limit`: 1-1000, default 100

**Response (200):**
```json
{
    "snapshots": [
        {
            "time": "2026-02-23T14:00:00Z",
            "total_equity": "12300.50",
            "unrealized_pnl": "600.20",
            "realized_pnl": "1200.30"
        }
    ]
}
```

#### GET /analytics/leaderboard
Agent performance rankings.

**Query params:** `period`: "1d", "7d", "30d", "all"

**Response (200):**
```json
{
    "period": "30d",
    "rankings": [
        {
            "rank": 1,
            "display_name": "AlphaBot",
            "roi_pct": 24.5,
            "sharpe_ratio": 2.1,
            "total_trades": 156,
            "win_rate": 68.2
        }
    ]
}
```

---

## 16. WebSocket API Specification

### Connection
```
wss://api.agentexchange.com/ws/v1?api_key={YOUR_API_KEY}
```

### Message Format
All messages are JSON. Client sends subscription requests, server pushes data.

### Subscribe to Channel
```json
{"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```

### Unsubscribe
```json
{"action": "unsubscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```

### Available Channels

#### ticker:{symbol}
Real-time price updates.
```json
{
    "channel": "ticker",
    "symbol": "BTCUSDT",
    "data": {
        "price": "64521.30",
        "quantity": "0.012",
        "timestamp": "2026-02-23T15:30:45.123Z",
        "is_buyer_maker": false
    }
}
```

#### ticker:all
Price updates for all pairs.
```json
{
    "channel": "ticker",
    "symbol": "ETHUSDT",
    "data": {
        "price": "3421.50",
        "timestamp": "2026-02-23T15:30:45.123Z"
    }
}
```

#### candles:{symbol}:{interval}
Live candle updates.
```json
{
    "channel": "candles",
    "symbol": "BTCUSDT",
    "interval": "1m",
    "data": {
        "time": "2026-02-23T15:30:00Z",
        "open": "64500.00",
        "high": "64550.00",
        "low": "64490.00",
        "close": "64521.30",
        "volume": "12.345",
        "is_closed": false
    }
}
```

#### orders
Your order status updates.
```json
{
    "channel": "orders",
    "data": {
        "order_id": "660e8400-...",
        "status": "filled",
        "symbol": "BTCUSDT",
        "side": "buy",
        "executed_price": "64521.30",
        "executed_quantity": "0.50",
        "fee": "32.26",
        "filled_at": "2026-02-23T15:30:45.456Z"
    }
}
```

#### portfolio
Real-time portfolio value updates (every 5 seconds).
```json
{
    "channel": "portfolio",
    "data": {
        "total_equity": "12458.30",
        "unrealized_pnl": "660.65",
        "realized_pnl": "1241.30",
        "timestamp": "2026-02-23T15:30:45Z"
    }
}
```

### Heartbeat
Server sends `{"type": "ping"}` every 30 seconds. Client must respond with `{"type": "pong"}` within 10 seconds.

---

## 17. MCP Server Integration

### Purpose
Expose platform capabilities as MCP tools for Claude-based agents and MCP-compatible frameworks.

### Implementation: `src/mcp/server.py`

```python
"""
MCP Server

Runs as a separate process. Exposes trading tools via Model Context Protocol.
Each tool maps to a REST API endpoint internally.

Tools:

1. get_price
   - description: "Get the current price of a cryptocurrency trading pair"
   - params: {"symbol": {"type": "string", "required": true}}
   - returns: {"symbol": str, "price": str, "timestamp": str}

2. get_all_prices
   - description: "Get current prices for all available trading pairs"
   - params: {}
   - returns: {"prices": dict, "count": int}

3. get_candles
   - description: "Get historical OHLCV candle data for a trading pair"
   - params: {"symbol": str (required), "interval": str (required, enum: 1m/5m/15m/1h/4h/1d), "limit": int (optional, default 100)}
   - returns: {"candles": list}

4. get_balance
   - description: "Get your current account balances for all assets"
   - params: {}
   - returns: {"balances": list, "total_equity_usdt": str}

5. get_positions
   - description: "Get your current open trading positions with unrealized PnL"
   - params: {}
   - returns: {"positions": list}

6. place_order
   - description: "Place a buy or sell order for a cryptocurrency"
   - params: {
       "symbol": str (required),
       "side": str (required, enum: buy/sell),
       "type": str (required, enum: market/limit/stop_loss/take_profit),
       "quantity": number (required),
       "price": number (optional, required for limit/stop/tp)
     }
   - returns: {"order_id": str, "status": str, "executed_price": str, ...}

7. cancel_order
   - description: "Cancel a pending order"
   - params: {"order_id": str (required)}
   - returns: {"status": "cancelled"}

8. get_order_status
   - description: "Check the status of an order"
   - params: {"order_id": str (required)}
   - returns: order details

9. get_portfolio
   - description: "Get complete portfolio summary including equity, PnL, and positions"
   - params: {}
   - returns: full portfolio summary

10. get_trade_history
    - description: "Get your historical trade executions"
    - params: {"symbol": str (optional), "limit": int (optional, default 50)}
    - returns: {"trades": list}

11. get_performance
    - description: "Get trading performance metrics like Sharpe ratio, win rate, drawdown"
    - params: {"period": str (optional, enum: 1d/7d/30d/90d/all, default all)}
    - returns: performance metrics

12. reset_account
    - description: "Reset your trading account to starting balance. All positions will be closed."
    - params: {"confirm": bool (required, must be true)}
    - returns: reset confirmation
"""
```

---

## 18. Python SDK

### Implementation: `sdk/agentexchange/client.py`

```python
"""
AgentExchange Python SDK

Sync client for easy integration. Wraps all REST endpoints.

Installation: pip install agentexchange

Usage:
    from agentexchange import AgentExchangeClient

    client = AgentExchangeClient(
        api_key="ak_live_...",
        api_secret="sk_live_...",
        base_url="https://api.agentexchange.com"  # default
    )

    # Market data
    price = client.get_price("BTCUSDT")
    all_prices = client.get_all_prices()
    candles = client.get_candles("BTCUSDT", interval="1h", limit=100)
    ticker = client.get_ticker("BTCUSDT")
    trades = client.get_recent_trades("BTCUSDT", limit=50)
    orderbook = client.get_orderbook("BTCUSDT", depth=10)

    # Trading
    order = client.place_market_order("BTCUSDT", "buy", 0.5)
    order = client.place_limit_order("BTCUSDT", "buy", 0.5, price=63000)
    order = client.place_stop_loss("BTCUSDT", "sell", 0.5, trigger_price=62000)
    order = client.place_take_profit("BTCUSDT", "sell", 0.5, trigger_price=70000)
    status = client.get_order("order_id")
    orders = client.get_open_orders()
    client.cancel_order("order_id")
    client.cancel_all_orders()
    history = client.get_trade_history(symbol="BTCUSDT", limit=100)

    # Account
    info = client.get_account_info()
    balance = client.get_balance()
    positions = client.get_positions()
    portfolio = client.get_portfolio()
    pnl = client.get_pnl(period="7d")
    client.reset_account(starting_balance=10000)

    # Analytics
    perf = client.get_performance(period="30d")
    portfolio_history = client.get_portfolio_history(interval="1h")
    leaderboard = client.get_leaderboard(period="7d")

Class: AgentExchangeClient
  - __init__(self, api_key, api_secret, base_url="https://api.agentexchange.com")
  - All methods return typed dataclass objects
  - Raises AgentExchangeError subclasses for each error code
  - Auto-retries on 5xx errors with exponential backoff (max 3 retries)
  - Logs all requests at DEBUG level via standard logging
"""
```

### Implementation: `sdk/agentexchange/async_client.py`

```python
"""
Async client using httpx.AsyncClient.
Same interface as sync client but all methods are async.

Usage:
    from agentexchange import AsyncAgentExchangeClient

    async with AsyncAgentExchangeClient(api_key="...", api_secret="...") as client:
        price = await client.get_price("BTCUSDT")
        order = await client.place_market_order("BTCUSDT", "buy", 0.5)
"""
```

### Implementation: `sdk/agentexchange/ws_client.py`

```python
"""
WebSocket client with auto-reconnect.

Usage:
    from agentexchange import AgentExchangeWS

    ws = AgentExchangeWS(api_key="...")

    @ws.on_ticker("BTCUSDT")
    async def handle_price(data):
        print(f"BTC price: {data['price']}")

    @ws.on_order_update()
    async def handle_order(data):
        print(f"Order {data['order_id']} is {data['status']}")

    @ws.on_portfolio()
    async def handle_portfolio(data):
        print(f"Equity: {data['total_equity']}")

    await ws.connect()  # blocks, auto-reconnects on disconnect

Class: AgentExchangeWS
  - __init__(self, api_key, base_url="wss://api.agentexchange.com")
  - async connect(self) → None (blocking, runs event loop)
  - async subscribe(self, channel: str, symbol: str = None) → None
  - async unsubscribe(self, channel: str, symbol: str = None) → None
  - on_ticker(symbol) → decorator
  - on_order_update() → decorator
  - on_portfolio() → decorator
  - Auto-reconnect with exponential backoff
  - Heartbeat handling built-in
"""
```

---

## 19. skill.md Agent Connectivity File

### Purpose
A structured instruction file that any LLM-based agent can read to immediately understand how to trade on the platform. Optimized for AI consumption, not human reading.

### Implementation: `docs/skill.md`

The skill.md file should contain:

```markdown
# AgentExchange Trading Platform — Agent Skill File

## Overview
You have access to a crypto trading platform where you can buy and sell
cryptocurrencies using virtual funds against real-time market prices.
Your account has a virtual USDT balance that you can use to trade any
of the 600+ available trading pairs.

## Authentication
Include this header in every HTTP request:
  X-API-Key: {YOUR_API_KEY}

Base URL: https://api.agentexchange.com/api/v1

## Available Actions

### Check a Price
GET /market/price/{symbol}
Example: GET /market/price/BTCUSDT
Returns: {"symbol": "BTCUSDT", "price": "64521.30", "timestamp": "..."}

### Check All Prices
GET /market/prices
Returns: {"prices": {"BTCUSDT": "64521.30", "ETHUSDT": "3421.50", ...}}

### Get Historical Candles
GET /market/candles/{symbol}?interval={interval}&limit={limit}
Intervals: 1m, 5m, 15m, 1h, 4h, 1d
Example: GET /market/candles/BTCUSDT?interval=1h&limit=24
Returns: list of {time, open, high, low, close, volume} objects

### Check Your Balance
GET /account/balance
Returns: list of assets with available and locked amounts

### Check Your Positions
GET /account/positions
Returns: list of open positions with entry price, current price, PnL

### Buy Crypto (Market Order)
POST /trade/order
Body: {"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.5}
Executes immediately at current market price.

### Sell Crypto (Market Order)
POST /trade/order
Body: {"symbol": "BTCUSDT", "side": "sell", "type": "market", "quantity": 0.5}

### Buy at Specific Price (Limit Order)
POST /trade/order
Body: {"symbol": "BTCUSDT", "side": "buy", "type": "limit", "quantity": 0.5, "price": 63000}
Order waits until price reaches 63000, then executes.

### Set Stop Loss
POST /trade/order
Body: {"symbol": "BTCUSDT", "side": "sell", "type": "stop_loss", "quantity": 0.5, "price": 62000}
Automatically sells if price drops to 62000.

### Set Take Profit
POST /trade/order
Body: {"symbol": "BTCUSDT", "side": "sell", "type": "take_profit", "quantity": 0.5, "price": 70000}
Automatically sells if price reaches 70000.

### Cancel an Order
DELETE /trade/order/{order_id}

### Cancel All Orders
DELETE /trade/orders/open

### Check Order Status
GET /trade/order/{order_id}

### Get Trade History
GET /trade/history?limit=50

### Get Portfolio Summary
GET /account/portfolio
Returns: total equity, cash, positions, unrealized PnL, realized PnL, ROI

### Get Performance Metrics
GET /analytics/performance?period=30d
Returns: Sharpe ratio, win rate, max drawdown, profit factor

### Reset Account
POST /account/reset
Body: {"confirm": true}
Resets balance to starting amount. Use when you want to start fresh.

## Error Handling
If a request fails, the response contains:
{"error": {"code": "ERROR_CODE", "message": "Human readable message"}}

Common errors:
- INSUFFICIENT_BALANCE: You don't have enough funds. Check balance first.
- INVALID_SYMBOL: The trading pair doesn't exist. Check /market/pairs.
- DAILY_LOSS_LIMIT: You've lost too much today. Trading resumes tomorrow UTC.
- RATE_LIMIT_EXCEEDED: Too many requests. Wait and retry.

## Best Practices
1. Always check your balance before placing an order.
2. Use limit orders when you want a specific entry price.
3. Set stop-loss orders to manage risk on every position.
4. Check /market/candles for historical data before making decisions.
5. Monitor your portfolio regularly with /account/portfolio.
6. Don't risk more than 25% of your equity on a single trade.

## WebSocket (Real-Time Data)
Connect to: wss://api.agentexchange.com/ws/v1?api_key={YOUR_API_KEY}
Send: {"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}
Receive: {"channel": "ticker", "symbol": "BTCUSDT", "data": {"price": "64521.30", ...}}
```

---

## 20. Security & Authentication

### Authentication Methods

1. **API Key** (primary): Header `X-API-Key: {key}` on every request
2. **JWT Token** (session): Header `Authorization: Bearer {token}` — 1h expiry
3. **HMAC Signing** (sensitive ops): Sign request body with API secret for order placement

### Security Implementation

```python
"""
Security checklist for implementation:

1. API keys: Generate with secrets.token_urlsafe(48), prefix "ak_live_"
2. API secrets: Generate with secrets.token_urlsafe(48), prefix "sk_live_"
3. Storage: bcrypt hash both key and secret in database
4. Lookup: Store plaintext API key for O(1) lookup, verify with hash
5. JWT: HS256 algorithm, 1h expiry, include account_id in payload
6. HTTPS: Enforce TLS 1.3 on all endpoints
7. Rate limiting: Redis sliding window, 429 on exceed
8. IP allowlist: Optional per-account IP whitelist
9. HMAC signing: SHA256(api_secret, request_body) for order endpoints
10. Audit log: Record every authenticated request
11. Input validation: Pydantic schemas on all endpoints
12. SQL injection: Parameterized queries only (SQLAlchemy handles this)
13. CORS: Restrict origins in production
"""
```

---

## 21. Docker Compose Configuration

### Implementation: `docker-compose.yml`

```yaml
# Docker Compose for AgentExchange Platform
#
# Services:
#   api          - FastAPI gateway (port 8000)
#   ingestion    - Price ingestion from Binance (no port, internal only)
#   celery       - Background task worker
#   celery-beat  - Task scheduler
#   redis        - Real-time cache (port 6379)
#   timescaledb  - Historical storage (port 5432)
#   prometheus   - Metrics collection (port 9090)
#   grafana      - Dashboards (port 3000)
#
# Volumes:
#   timescaledb_data - Persistent database storage
#   redis_data       - Redis persistence
#   grafana_data     - Dashboard configs
#
# Networks:
#   internal - All services communicate on this network
#
# Environment variables (from .env):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#   REDIS_URL
#   BINANCE_WS_URL
#   JWT_SECRET
#   API_HOST, API_PORT
#
# Resource limits:
#   api:         2 CPU, 2GB RAM
#   ingestion:   1 CPU, 1GB RAM
#   celery:      1 CPU, 1GB RAM
#   redis:       1 CPU, 512MB RAM
#   timescaledb: 2 CPU, 4GB RAM
#   prometheus:  0.5 CPU, 512MB RAM
#   grafana:     0.5 CPU, 512MB RAM
#
# Total minimum: 8 CPU, 10GB RAM
#
# Healthchecks on all services
# Restart policy: unless-stopped
# Logging: json-file driver, max 10MB, max 3 files
```

### Implementation: `.env.example`

```bash
# Database
POSTGRES_USER=agentexchange
POSTGRES_PASSWORD=change_me_in_production
POSTGRES_DB=agentexchange
DATABASE_URL=postgresql+asyncpg://agentexchange:change_me_in_production@timescaledb:5432/agentexchange

# Redis
REDIS_URL=redis://redis:6379/0

# Binance
BINANCE_WS_URL=wss://stream.binance.com:9443/stream

# API
API_HOST=0.0.0.0
API_PORT=8000
API_BASE_URL=https://api.agentexchange.com

# Auth
JWT_SECRET=change_me_to_random_64_char_string
JWT_EXPIRY_HOURS=1

# Trading defaults
DEFAULT_STARTING_BALANCE=10000
TRADING_FEE_PCT=0.1
DEFAULT_SLIPPAGE_FACTOR=0.1

# Monitoring
GRAFANA_ADMIN_PASSWORD=change_me
```

---

## 22. Development Phases & Tasks

### Phase 1: Foundation (Weeks 1-3)

**Goal:** All Binance pairs streaming to Redis + TimescaleDB 24/7

Tasks:
- [ ] Initialize project repository and structure per Section 4
- [ ] Create Docker Compose with TimescaleDB, Redis, and API service
- [ ] Write `src/config.py` using pydantic-settings for all env vars
- [ ] Implement `src/price_ingestion/binance_ws.py` — fetch all USDT pairs, connect to combined stream
- [ ] Implement `src/price_ingestion/tick_buffer.py` — in-memory buffer with periodic flush
- [ ] Implement `src/cache/redis_client.py` — Redis connection pool
- [ ] Implement `src/cache/price_cache.py` — HSET/HGET for current prices
- [ ] Implement `src/price_ingestion/service.py` — main loop: receive tick → update Redis + buffer
- [ ] Create TimescaleDB schema: ticks hypertable + indexes + compression policy
- [ ] Create continuous aggregates: candles_1m, candles_5m, candles_1h, candles_1d
- [ ] Write `scripts/seed_pairs.py` — fetch all pairs from Binance REST and seed trading_pairs table
- [ ] Implement health check: verify tick freshness per pair
- [ ] Write unit tests for tick_buffer and price_cache
- [ ] Write integration test: verify ticks flowing from Binance → Redis → TimescaleDB
- [ ] Run 24h stability test — verify zero data loss

**Deliverable:** Price feed running 24/7, all pairs in Redis, full tick history in TimescaleDB

---

### Phase 2: Trading Engine (Weeks 4-6)

**Goal:** Complete trading engine executing orders against live prices

Tasks:
- [ ] Create database schema: accounts, balances, trading_sessions, orders, trades, positions
- [ ] Set up Alembic migrations
- [ ] Implement `src/accounts/service.py` — register, authenticate, get_account
- [ ] Implement `src/accounts/auth.py` — API key generation, bcrypt hashing, JWT creation
- [ ] Implement `src/accounts/balance_manager.py` — credit, debit, lock, unlock, execute_trade
- [ ] Implement `src/order_engine/slippage.py` — slippage calculation model
- [ ] Implement `src/order_engine/validators.py` — order validation rules
- [ ] Implement `src/order_engine/engine.py` — market order execution
- [ ] Add limit order support in engine.py
- [ ] Implement `src/order_engine/matching.py` — background limit order matcher
- [ ] Add stop-loss and take-profit order types
- [ ] Implement `src/risk/manager.py` — all risk checks
- [ ] Implement `src/risk/circuit_breaker.py` — daily loss tracking + halt
- [ ] Implement `src/portfolio/tracker.py` — real-time portfolio valuation
- [ ] Implement `src/portfolio/metrics.py` — Sharpe, drawdown, win rate
- [ ] Implement `src/portfolio/snapshots.py` — periodic snapshot capture
- [ ] Write unit tests: order engine, slippage, risk manager, balance manager, portfolio metrics
- [ ] Write integration test: full trade lifecycle (register → fund → buy → sell → check PnL)

**Deliverable:** Working trading engine, accounts, risk management, portfolio tracking

---

### Phase 3: API Layer (Weeks 7-9)

**Goal:** Fully functional REST + WebSocket API

Tasks:
- [ ] Implement `src/main.py` — FastAPI app setup with middleware
- [ ] Implement `src/api/middleware/auth.py` — API key + JWT authentication
- [ ] Implement `src/api/middleware/rate_limit.py` — Redis-backed rate limiting
- [ ] Implement `src/api/middleware/logging.py` — structured request/response logging
- [ ] Create Pydantic schemas: `src/api/schemas/` — all request/response models
- [ ] Implement `src/api/routes/auth.py` — register, login, refresh, revoke
- [ ] Implement `src/api/routes/market.py` — pairs, price, prices, ticker, candles, trades, orderbook
- [ ] Implement `src/api/routes/trading.py` — place order, get order, list orders, cancel order
- [ ] Implement `src/api/routes/account.py` — info, balance, positions, portfolio, PnL, reset
- [ ] Implement `src/api/routes/analytics.py` — performance, portfolio history, leaderboard
- [ ] Implement `src/api/websocket/manager.py` — connection lifecycle management
- [ ] Implement `src/api/websocket/handlers.py` — subscribe/unsubscribe logic
- [ ] Implement `src/api/websocket/channels.py` — ticker, candles, orders, portfolio channels
- [ ] Implement `src/price_ingestion/broadcaster.py` — Redis pub/sub → WebSocket push
- [ ] Set up Celery: `src/tasks/celery_app.py` + all task files
- [ ] Configure celery beat schedule: limit order matching (1s), snapshots (1m/1h/1d), circuit breaker reset (daily)
- [ ] Verify auto-generated OpenAPI docs at /docs
- [ ] Write integration tests for all REST endpoints
- [ ] Write WebSocket integration tests
- [ ] Load test with locust: 50 concurrent agents, 10 req/s each

**Deliverable:** Complete API ready for agent connections

---

### Phase 4: Agent Connectivity (Weeks 10-11)

**Goal:** Any AI agent can connect and trade within 5 minutes

Tasks:
- [ ] Write `docs/skill.md` — comprehensive agent instruction file (see Section 19)
- [ ] Implement `src/mcp/server.py` — MCP server with all 12 tools (see Section 17)
- [ ] Implement `src/mcp/tools.py` — tool definitions and parameter schemas
- [ ] Build Python SDK: `sdk/agentexchange/client.py` — sync client
- [ ] Build Python SDK: `sdk/agentexchange/async_client.py` — async client
- [ ] Build Python SDK: `sdk/agentexchange/ws_client.py` — WebSocket client
- [ ] Build Python SDK: `sdk/agentexchange/models.py` — typed response objects
- [ ] Build Python SDK: `sdk/agentexchange/exceptions.py` — error classes
- [ ] Write SDK tests
- [ ] Create `docs/quickstart.md` — 5-minute getting started guide
- [ ] Create `docs/framework_guides/openclaw.md`
- [ ] Create `docs/framework_guides/langchain.md`
- [ ] Create `docs/framework_guides/agent_zero.md`
- [ ] Create `docs/framework_guides/crewai.md`
- [ ] Test: connect 10 agents from different frameworks simultaneously
- [ ] Test: verify skill.md works with Claude, GPT-4, and open-source LLMs
- [ ] Test: verify MCP server discovery and tool execution

**Deliverable:** Complete integration layer — any agent connects in 5 minutes

---

### Phase 5: Polish & Launch (Weeks 12-14)

**Goal:** Production-ready platform with monitoring

Tasks:
- [ ] Implement `src/monitoring/prometheus_metrics.py` — all custom metrics
- [ ] Implement `src/monitoring/health.py` — comprehensive health checks
- [ ] Create Grafana dashboards: System Overview, Agent Activity, Price Feed Health
- [ ] Set up alerting rules in Prometheus/Grafana
- [ ] Implement audit log table and write middleware
- [ ] Security audit: review all endpoints for auth bypass, injection, data leaks
- [ ] Implement IP allowlisting option
- [ ] Implement HMAC request signing for order endpoints
- [ ] Set up automated backups: TimescaleDB daily dump, Redis snapshots
- [ ] Write `README.md` — project overview, setup instructions, architecture
- [ ] Create developer documentation website (optional: MkDocs or Docusaurus)
- [ ] Create `scripts/create_test_agent.py` — easy test agent setup
- [ ] Create `scripts/backfill_history.py` — backfill historical candles from Binance REST
- [ ] Run 72h production stability test
- [ ] Fix all issues found during stability test
- [ ] Beta launch with 5-10 select developers

**Deliverable:** Production platform, monitoring, documentation, beta users

---

## 23. Testing Strategy

### Unit Tests (`tests/unit/`)

```python
"""
Coverage targets: 90%+ on business logic

test_order_engine.py:
  - test_market_buy_executes_at_current_price
  - test_market_sell_executes_at_current_price
  - test_limit_buy_queued_when_price_above_target
  - test_limit_buy_executes_when_price_at_target
  - test_stop_loss_triggers_when_price_drops
  - test_take_profit_triggers_when_price_rises
  - test_order_rejected_insufficient_balance
  - test_order_rejected_invalid_symbol
  - test_order_rejected_zero_quantity
  - test_order_rejected_account_suspended
  - test_cancel_pending_order_unlocks_funds
  - test_cancel_filled_order_fails

test_slippage.py:
  - test_small_order_minimal_slippage
  - test_large_order_significant_slippage
  - test_buy_slippage_increases_price
  - test_sell_slippage_decreases_price
  - test_fee_calculation_correct

test_risk_manager.py:
  - test_order_within_all_limits_approved
  - test_position_size_exceeded_rejected
  - test_daily_loss_limit_blocks_trading
  - test_max_open_orders_exceeded
  - test_min_order_size_rejected
  - test_rate_limit_exceeded
  - test_custom_risk_profile_applied

test_balance_manager.py:
  - test_credit_increases_available
  - test_debit_decreases_available
  - test_debit_below_zero_fails
  - test_lock_moves_from_available_to_locked
  - test_unlock_moves_from_locked_to_available
  - test_execute_trade_buy_updates_both_assets
  - test_execute_trade_sell_updates_both_assets
  - test_atomic_trade_execution

test_portfolio_metrics.py:
  - test_sharpe_ratio_calculation
  - test_max_drawdown_calculation
  - test_win_rate_calculation
  - test_profit_factor_calculation
  - test_empty_portfolio_returns_defaults

test_auth.py:
  - test_api_key_generation_format
  - test_api_key_verification_valid
  - test_api_key_verification_invalid
  - test_jwt_creation_and_verification
  - test_jwt_expired_token_rejected
"""
```

### Integration Tests (`tests/integration/`)

```python
"""
test_full_trade_flow.py:
  1. Register new agent account
  2. Verify starting balance is 10000 USDT
  3. Get BTC price
  4. Place market buy order for 0.1 BTC
  5. Verify order status is "filled"
  6. Verify USDT balance decreased by correct amount
  7. Verify BTC balance is 0.1
  8. Verify position exists with correct entry price
  9. Place market sell order for 0.1 BTC
  10. Verify USDT balance reflects PnL
  11. Verify position closed
  12. Check trade history has 2 trades
  13. Check portfolio shows correct realized PnL

test_price_ingestion.py:
  1. Start price ingestion service
  2. Wait 5 seconds
  3. Verify Redis has prices for 600+ pairs
  4. Verify TimescaleDB has ticks
  5. Verify no gaps in major pairs

test_websocket.py:
  1. Connect WebSocket with API key
  2. Subscribe to ticker:BTCUSDT
  3. Verify price updates received within 5 seconds
  4. Subscribe to orders channel
  5. Place an order via REST
  6. Verify order fill notification received via WebSocket
  7. Test heartbeat ping/pong
  8. Test reconnection after disconnect

test_api_endpoints.py:
  - Test every REST endpoint with valid and invalid inputs
  - Test auth: valid key, invalid key, expired JWT, no auth
  - Test rate limiting: exceed limit, verify 429
  - Test error responses match documented format
"""
```

### Load Tests (`tests/load/locustfile.py`)

```python
"""
Simulate 50 concurrent agents each doing:
  - GET /market/price/{random_pair} — 5 req/s
  - GET /account/balance — 1 req/s
  - GET /account/positions — 1 req/s
  - POST /trade/order (market) — 0.5 req/s
  - GET /trade/history — 0.5 req/s
  - GET /analytics/performance — 0.1 req/s

Total: ~400 req/s across all agents

Performance targets:
  - p50 latency < 50ms
  - p95 latency < 100ms
  - p99 latency < 200ms
  - Zero errors under sustained load
  - WebSocket: 500 concurrent connections, price updates < 100ms latency
"""
```

---

## 24. Future Roadmap

### Phase 6: Advanced Features (Post-Launch)
- [ ] Add Kafka to price pipeline for zero-data-loss guarantee
- [ ] Margin trading simulation with configurable leverage (2x, 5x, 10x)
- [ ] Multi-exchange data feeds: KuCoin, Bybit, OKX
- [ ] Futures/perpetuals simulation
- [ ] Advanced order types: OCO (one-cancels-other), trailing stop
- [ ] Agent-vs-agent mode: agents trade against each other's order book
- [ ] Historical backtesting API: replay any time period at accelerated speed
- [ ] Portfolio comparison: benchmark agent vs buy-and-hold vs market index

### Phase 7: Platform & Monetization
- [ ] Web dashboard for developers to monitor their agents
- [ ] Agent leaderboard with public rankings
- [ ] Tournament system: weekly/monthly competitions with prizes
- [ ] Free tier: 1 agent, 10 pairs, 7-day history
- [ ] Pro tier ($29/mo): Unlimited agents, all pairs, full history, priority API
- [ ] Enterprise tier: Dedicated infra, custom risk, SLA
- [ ] Strategy marketplace: developers sell proven agent strategies

### Phase 8: Real Trading Bridge
- [ ] Optional bridge to real Binance accounts for proven agents
- [ ] Graduated deployment: start with $100, scale based on simulated performance
- [ ] Paper-to-live transition wizard
- [ ] Real-time risk monitoring for live agents
- [ ] Kill switch: instant halt on live trading if agent misbehaves

---

## Quick Reference: Key Commands

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f api
docker compose logs -f ingestion

# Run migrations
docker compose exec api alembic upgrade head

# Create test agent
docker compose exec api python scripts/create_test_agent.py

# Run tests
docker compose exec api pytest tests/unit -v
docker compose exec api pytest tests/integration -v

# Load test
docker compose exec api locust -f tests/load/locustfile.py

# Check price feed health
curl http://localhost:8000/health

# API docs
open http://localhost:8000/docs
```

---

*End of Development Plan — Version 1.0*