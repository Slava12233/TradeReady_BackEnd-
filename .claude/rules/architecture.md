---
paths:
  - "src/**/*.py"
  - "agent/**/*.py"
---

# Architecture Overview

Simulated crypto exchange: AI agents trade **virtual USDT** against **real Binance market data**. 600+ USDT pairs, real-time feeds, order execution, risk controls, portfolio tracking.

## Core Components

| Component | Module |
|-----------|--------|
| Exchange Abstraction (CCXT, 110+ exchanges) | `src/exchange/` |
| Price Ingestion (WS → Redis + TimescaleDB) | `src/price_ingestion/` |
| Redis Cache (sub-ms lookups, rate limiting, pub/sub) | `src/cache/` |
| TimescaleDB (ticks, OHLCV, trades) | `src/database/` |
| Order Engine (Market/Limit/Stop-Loss/Take-Profit) | `src/order_engine/` |
| Account Management (auth, API keys, balances) | `src/accounts/` |
| Portfolio Tracker (PnL, Sharpe, drawdown) | `src/portfolio/` |
| Risk Management (position limits, circuit breaker) | `src/risk/` |
| API Gateway (REST + WebSocket, middleware) | `src/api/` |
| Monitoring (Prometheus, health checks) | `src/monitoring/` |
| Backtesting (historical replay, sandbox) | `src/backtesting/` |
| Agent Management (multi-agent, per-agent wallets) | `src/agents/` |
| Battle System (agent vs agent, rankings) | `src/battles/` |
| Unified Metrics (shared calculator) | `src/metrics/` |

## Multi-Agent Architecture

Each account owns multiple **agents** with own API key, balance, risk profile, trading history. Trading tables keyed by `agent_id`.

- **API key auth** (`X-API-Key`): agents table first, fallback to accounts table
- **JWT auth** (`Authorization: Bearer`): account from JWT, agent via `X-Agent-Id` header

## Dependency Direction (strict)
```
Routes → Schemas + Services
Services → Repositories + Cache + External clients
Repositories → Models + Session
```
Never import upward.

## Middleware Execution Order
Starlette adds LIFO. Registration order:
```
RateLimitMiddleware → AuthMiddleware → LoggingMiddleware → route handler
```

## Key Data Flows

**Price ingestion:** Exchange WS (CCXT/Binance) → Redis HSET → buffer ticks → flush to TimescaleDB via asyncpg COPY → Redis pub/sub broadcast.

**Order execution:** `POST /api/v1/trade/order` → RiskManager (8-step) → Redis price → market fills with slippage; limit/stop queue as pending, matched by Celery task.

**Backtesting:** `POST /backtest/create` → `/start` → agent loops `/step` → auto-complete → `GET /results`. Critical: `DataReplayer` filters `WHERE bucket <= virtual_clock` (no look-ahead bias).

## API Authentication

REST: `X-API-Key: ak_live_...` or `Authorization: Bearer <jwt>`.
WebSocket: `?api_key=ak_live_...` (close 4401 on failure).

## Database

- Repository pattern in `src/database/repositories/`
- Atomic writes (SQLAlchemy transactions)
- `NUMERIC(20,8)` for prices/quantities/balances
- TimescaleDB hypertables: `ticks`, `portfolio_snapshots`, `backtest_snapshots`

## Redis Key Patterns

- Prices: `HSET prices {SYMBOL} {price}`
- Rate limits: `INCR rate_limit:{api_key}:{endpoint}:{minute}` + `EXPIRE 60`
- Circuit breaker: `HSET circuit_breaker:{account_id} daily_pnl {value}`
