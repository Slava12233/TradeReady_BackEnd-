# Project Context — AI Agent Crypto Trading Platform

> **Last Updated:** 2026-02-24
> **Plan Version:** 1.0
> **Status:** Phase 3 — API Layer (Phase 2 complete)

---

## What This Project Is

A simulated crypto exchange platform powered by **real-time Binance market data**. AI agents connect via API, trade with virtual funds against live prices, and developers can train/test/benchmark their trading strategies risk-free.

**One-liner:** Universal training playground where any AI agent trades crypto against real-time Binance data with virtual funds.

---

## Core Principles

| Principle | Detail |
|---|---|
| **1:1 Market Mirror** | All 600+ Binance USDT trading pairs, tick-by-tick, 24/7 |
| **Universal Agent Access** | Any framework (OpenClaw, Agent Zero, LangChain, CrewAI, raw Python) connects in <5 min |
| **Realistic Simulation** | Slippage modeling, risk controls, proper order lifecycle |
| **Five Integration Layers** | REST API, WebSocket, MCP Server, Python SDK, skill.md file |

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Language | Python 3.12+ | Async support, agent framework compatibility |
| Web Framework | FastAPI | Async, auto OpenAPI docs, Pydantic v2 validation |
| Real-Time Cache | Redis 7+ | Sub-ms price lookups, rate limiting, pub/sub |
| Historical DB | TimescaleDB (PostgreSQL) | Time-series optimized, compression, continuous aggregates |
| ORM | SQLAlchemy 2.0 + asyncpg | Async database access |
| Migrations | Alembic | Schema versioning |
| Task Queue | Celery + Redis broker | Background jobs (candle aggregation, snapshots, cleanup) |
| Auth | JWT (PyJWT) + API Keys (bcrypt) | Stateless authentication |
| Containers | Docker + Docker Compose | Reproducible environments |
| Monitoring | Prometheus + Grafana | Metrics collection + dashboards |
| Logging | structlog + Loki | Structured JSON logging |
| Testing | pytest + pytest-asyncio + locust | Unit/integration + load testing |
| Linting | ruff + mypy | Fast linting + type checking |

---

## System Architecture (9 Components)

```
1. Price Ingestion Service   — Binance WS → Redis + TimescaleDB
2. Redis Real-Time Cache     — Sub-ms price lookups, agent state, rate limits
3. TimescaleDB Storage       — Full tick history, OHLCV candles, trade ledger
4. Order Execution Engine    — Market / Limit / Stop-Loss / Take-Profit orders
5. Account Management        — Registration, auth, balances, sessions
6. Portfolio Tracker         — Real-time PnL, Sharpe ratio, drawdown
7. Risk Management Engine    — Position limits, daily loss circuit breaker
8. API Gateway (FastAPI)     — REST + WebSocket + middleware
9. Monitoring & Logging      — Prometheus, Grafana, structured logs
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
  → Execute trade (update balances in DB)
  → Record in trades table
  → Update order status → filled
  → Notify agent via WebSocket
  → Portfolio Tracker recalculates equity
```

---

## Agent Connectivity Layer

| Layer | Description | Use Case |
|---|---|---|
| **REST API** | Standard HTTP endpoints | Any language, any framework |
| **WebSocket** | Real-time streaming | Live price feeds, order notifications |
| **MCP Server** | Model Context Protocol tools | Claude-based agents, MCP frameworks |
| **Python SDK** | `pip install agentexchange` | Python agents with typed client |
| **skill.md** | LLM-readable instruction file | Drop-in for any LLM agent |

---

## Project Structure (Key Directories)

```
agent-exchange/
├── src/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # pydantic-settings
│   ├── price_ingestion/         # Component 1: Binance WS → Redis/DB
│   ├── cache/                   # Component 2: Redis operations
│   ├── database/                # Component 3: SQLAlchemy models + repos
│   ├── order_engine/            # Component 4: Order execution + slippage
│   ├── accounts/                # Component 5: Auth, balances, sessions
│   ├── portfolio/               # Component 6: Tracker, metrics, snapshots
│   ├── risk/                    # Component 7: Risk limits, circuit breaker
│   ├── api/                     # Component 8: Routes, middleware, WebSocket
│   ├── monitoring/              # Component 9: Prometheus, health checks
│   ├── mcp/                     # MCP Server for AI agents
│   ├── tasks/                   # Celery background jobs
│   └── utils/                   # Shared exceptions, helpers
├── sdk/                         # Python SDK (separate package)
├── docs/                        # skill.md, quickstart, framework guides
├── tests/                       # Unit, integration, load tests
├── scripts/                     # Seed data, backfill, test agent creation
├── alembic/                     # Database migrations
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Database Schema (Core Tables)

| Table | Purpose |
|---|---|
| `accounts` | Agent accounts with API keys, status, risk profile |
| `balances` | Per-asset balances (available + locked) per account |
| `trading_sessions` | Session tracking for account resets |
| `orders` | All orders (pending, filled, cancelled, rejected) |
| `trades` | Executed trade fills with PnL |
| `positions` | Aggregated current holdings per account/symbol |
| `ticks` | TimescaleDB hypertable — every trade tick from Binance |
| `candles_1m/5m/1h/1d` | Continuous aggregates for OHLCV data |
| `portfolio_snapshots` | Periodic equity snapshots for charting |
| `trading_pairs` | Reference data for all 600+ pairs |
| `audit_log` | Every authenticated request for security |

---

## Docker Services

| Service | Port | Resources |
|---|---|---|
| `api` (FastAPI) | 8000 | 2 CPU, 2 GB RAM |
| `ingestion` (Price feed) | internal | 1 CPU, 1 GB RAM |
| `celery` (Worker) | — | 1 CPU, 1 GB RAM |
| `celery-beat` (Scheduler) | — | — |
| `redis` | 6379 | 1 CPU, 512 MB RAM |
| `timescaledb` | 5432 | 2 CPU, 4 GB RAM |
| `prometheus` | 9090 | 0.5 CPU, 512 MB RAM |
| `grafana` | 3000 | 0.5 CPU, 512 MB RAM |

**Total minimum:** 8 CPU, 10 GB RAM

---

## Development Phases Overview

| Phase | Weeks | Focus |
|---|---|---|
| **Phase 1: Foundation** | 1–3 | Price ingestion pipeline (Binance → Redis → TimescaleDB) |
| **Phase 2: Trading Engine** | 4–6 | Orders, accounts, balances, risk, portfolio |
| **Phase 3: API Layer** | 7–9 | REST endpoints, WebSocket, middleware, Celery tasks |
| **Phase 4: Agent Connectivity** | 10–11 | MCP server, Python SDK, skill.md, framework guides |
| **Phase 5: Polish & Launch** | 12–14 | Monitoring, security audit, docs, beta launch |

---

## Key Design Decisions

1. **TimescaleDB over plain PostgreSQL** — native time-series compression, continuous aggregates, retention policies; avoids maintaining a separate TSDB.
2. **Redis for current prices** — sub-ms reads; all 600+ pairs fit in ~50–100 MB; also handles rate limiting and circuit breaker state.
3. **Celery for background tasks** — limit order matching (1s), snapshots (1m/1h/1d), circuit breaker reset (daily), cleanup.
4. **Slippage simulation** — proportional to order size vs. daily volume; makes the playground realistic without a full order book.
5. **Five connectivity layers** — ensures any agent framework can integrate, not just Python or MCP-aware ones.

---

## Environment Variables (Key)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | TimescaleDB async connection string |
| `REDIS_URL` | Redis connection string |
| `BINANCE_WS_URL` | Binance WebSocket base URL |
| `JWT_SECRET` | JWT signing secret (64+ chars) |
| `TRADING_FEE_PCT` | Simulated fee (default 0.1%) |
| `DEFAULT_STARTING_BALANCE` | New account balance (default 10000 USDT) |
| `DEFAULT_SLIPPAGE_FACTOR` | Base slippage factor (default 0.1) |

---

*This file is the single source of truth for project context. Update it whenever architecture, stack, or design decisions change.*
