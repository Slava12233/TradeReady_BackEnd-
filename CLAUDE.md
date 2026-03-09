# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mandatory Pre/Post Task Protocol

Before starting ANY task, read these files in order:
1. `context.md` — architecture, stack, design decisions (single source of truth for architecture)
2. `tasks.md` — full task breakdown with statuses
3. `developmentprogress.md` — current phase, progress, blockers
4. `developmantPlan.md` — the relevant section(s) for the component you are implementing

`developmantPlan.md` is the absolute authority. ALL implementation — file names, class names, method signatures, DB schema, API endpoints — MUST match what it specifies. Do not deviate or "improve" without explicit user approval.

After completing any task, update:
- `tasks.md` — mark task `[x]` Done
- `developmentprogress.md` — update progress %, add changelog entry
- `context.md` — only if architecture/stack decisions changed

**One file at a time:** Create exactly ONE source file per step, explain its purpose and connections, then wait for user confirmation before proceeding.

## Running the Platform

```bash
# Start all services (requires Docker)
docker compose up -d

# API server (local dev, no Docker)
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Price ingestion service
python -m src.price_ingestion.service

# MCP server (stdio transport — for Claude Desktop / MCP clients)
MCP_API_KEY=ak_live_... python -m src.mcp.server
# With JWT for authenticated endpoints:
MCP_API_KEY=ak_live_... MCP_JWT_TOKEN=eyJ... python -m src.mcp.server

# Celery worker
celery -A src.tasks.celery_app worker --loglevel=info

# Celery beat (scheduler)
celery -A src.tasks.celery_app beat --loglevel=info
```

Access points: API `http://localhost:8000`, Swagger docs `http://localhost:8000/docs`, Prometheus metrics `http://localhost:8000/metrics`, Grafana `http://localhost:3000`, Prometheus `http://localhost:9090`, WebSocket `ws://localhost:8000/ws/v1?api_key=...`

## Testing

```bash
pytest --cov=src --cov-report=html      # All tests with coverage
pytest tests/unit/                       # Unit tests only (mock external deps)
pytest tests/integration/                # Integration tests (requires Docker services)
pytest tests/unit/test_order_engine.py  # Single test file
pytest tests/unit/test_order_engine.py::test_market_buy_fills  # Single test
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

In tests, instantiate the app via `from src.main import create_app; app = create_app()` — do not import `app` directly, as the factory is the testable surface.

## Linting, Type Checking, Migrations

```bash
ruff check src/ tests/     # Lint (line-length=120, Python 3.12, selects E/W/F/I/B/C4/UP/ANN/S/N)
mypy src/                  # Type check (strict mode)

alembic revision --autogenerate -m "description"   # Create migration
alembic upgrade head                                # Apply migrations
alembic downgrade -1                                # Rollback one

python scripts/seed_pairs.py       # Seed Binance USDT pairs
python scripts/validate_phase1.py  # Validate Phase 1 health
```

## Architecture Overview

This is a simulated crypto exchange where AI agents trade **virtual USDT** against **real Binance market data**. Supports 600+ USDT pairs with real-time price feeds, order execution, risk controls, and portfolio tracking.

### Nine Core Components

| # | Component | Key Files |
|---|-----------|-----------|
| 1 | **Price Ingestion** — Binance WS → Redis + TimescaleDB | `src/price_ingestion/` |
| 2 | **Redis Cache** — sub-ms price lookups, rate limiting, pub/sub | `src/cache/` |
| 3 | **TimescaleDB** — tick history, OHLCV candles, trades | `src/database/` |
| 4 | **Order Engine** — Market/Limit/Stop-Loss/Take-Profit | `src/order_engine/` |
| 5 | **Account Management** — registration, auth, API keys, balances | `src/accounts/` |
| 6 | **Portfolio Tracker** — real-time PnL, Sharpe, drawdown | `src/portfolio/` |
| 7 | **Risk Management** — position limits, daily loss circuit breaker | `src/risk/` |
| 8 | **API Gateway** — REST + WebSocket, middleware | `src/api/` |
| 9 | **Monitoring** — Prometheus metrics, health checks, structured logs | `src/monitoring/` |

### Dependency Direction (strict)
```
Routes → Schemas + Services
Services → Repositories + Cache + External clients
Repositories → Models + Session
```
Never import upward in this chain.

### Middleware Execution Order
Starlette adds middleware LIFO. Registration order in `create_app()`:
```
RateLimitMiddleware → AuthMiddleware → LoggingMiddleware → route handler
```
`AuthMiddleware` must run before `RateLimitMiddleware` so `request.state.account` is populated before rate-limit checks.

### Key Data Flows

**Price ingestion:** Binance WebSocket → update Redis `HSET prices {SYMBOL} {price}` → buffer ticks in memory → periodic flush to TimescaleDB via asyncpg COPY → broadcast on Redis pub/sub for WebSocket clients.

**Order execution:** `POST /api/v1/trade/order` → RiskManager (8-step validation) → fetch price from Redis → market orders fill immediately with slippage; limit/stop orders queue as pending and are matched by background Celery task.

### Redis Key Patterns
- Current prices: `HSET prices {SYMBOL} {price}`
- Rate limits: `INCR rate_limit:{api_key}:{endpoint}:{minute}` + `EXPIRE 60`
- Circuit breaker: `HSET circuit_breaker:{account_id} daily_pnl {value}`

### Database
- All DB access through repository classes in `src/database/repositories/`
- All write operations must be atomic (SQLAlchemy transactions)
- `NUMERIC(20,8)` for all price/quantity/balance columns
- TimescaleDB hypertables for time-series only (`ticks`, `portfolio_snapshots`)

### API Authentication
All REST endpoints accept either:
- `X-API-Key: ak_live_...` header
- `Authorization: Bearer <jwt>` header

WebSocket authenticates via `?api_key=ak_live_...` query param (close code 4401 on failure).

### WebSocket Protocol
After connecting, send JSON messages to subscribe/unsubscribe:
```json
{"action": "subscribe",   "channel": "ticker", "symbol": "BTCUSDT"}
{"action": "unsubscribe", "channel": "ticker", "symbol": "BTCUSDT"}
{"action": "subscribe",   "channel": "orders"}
```

## Code Standards

- **Python 3.12+**, fully typed, `async/await` for all I/O
- **Pydantic v2** for all data models; **`Decimal`** (never `float`) for money/prices
- **Google-style docstrings** on every public class and function
- Custom exceptions from `src/utils/exceptions.py`; never bare `except:`
- All external calls (Redis, DB, Binance WS) wrapped in try/except with logging; fail closed on errors

### Naming
- Files: `snake_case.py`, Classes: `PascalCase`, Functions: `snake_case`, Constants: `UPPER_SNAKE_CASE`, Private: `_prefix`

### API Design
- All routes under `/api/v1/` prefix
- Error format: `{"error": {"code": "...", "message": "..."}}`
- Rate limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

## Git Commit Format

```
type(scope): description
```
Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
Scope: component name (e.g., `ingestion`, `order-engine`, `api`)

## Current Phase Status

| Phase | Status |
|-------|--------|
| Phase 1: Foundation (price feed, Redis, TimescaleDB) | ✅ Complete |
| Phase 2: Trading Engine (orders, accounts, risk, portfolio) | ✅ Complete |
| Phase 3: API Layer (REST, WebSocket, Celery) | 🔄 ~85% done |
| Phase 4: Agent Connectivity (MCP server, SDK, framework guides) | 🔄 In progress |
| Phase 5: Polish & Launch | ⬜ Not started |

## SDK & Frontend

**Python SDK** (`sdk/`): `AgentExchangeClient` (sync), `AsyncAgentExchangeClient` (async), `AgentExchangeWS` (streaming). Install locally: `pip install -e sdk/`

**MCP Server** (`src/mcp/`): 12 trading tools over stdio transport. Env vars: `MCP_API_KEY` (required), `API_BASE_URL` (default `http://localhost:8000`), `MCP_JWT_TOKEN` (optional).

**Frontend** (`Frontend/`): Next.js 16, React 19, TypeScript, Tailwind CSS 4.2, pnpm. Development plans in `UiDevelopmentPlan.md` and `UIdevelopmentProgress.md`.

### Frontend Commands

```bash
cd Frontend
pnpm dev              # Dev server at http://localhost:3000
pnpm build            # Production build (zero TS/lint errors required)
pnpm test             # Unit tests (vitest)
pnpm test:e2e         # Playwright E2E tests
pnpm dlx shadcn@latest add <component-name>  # Add shadcn/ui component
```

Frontend has its own `CLAUDE.md` at `Frontend/CLAUDE.md` with full UI conventions. Key points:
- `UiDevelopmentPlan.md` is the authority for frontend (like `developmantPlan.md` is for backend)
- Read `UIcontext.md`, `UItasks.md`, `UIdevelopmentProgress.md` before frontend tasks
- Tailwind v4 configured via `@theme inline` in `src/app/globals.css` (no `tailwind.config.ts`)
- State: Zustand (WS/streaming), TanStack Query (REST), React state (local UI)
- `@/*` path alias maps to `./src/*`

## Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | TimescaleDB async connection string |
| `REDIS_URL` | Redis connection string |
| `BINANCE_WS_URL` | Binance WebSocket base URL |
| `JWT_SECRET` | JWT signing secret (64+ chars) |
| `TRADING_FEE_PCT` | Simulated fee (default 0.1%) |
| `DEFAULT_STARTING_BALANCE` | New account balance (default 10000 USDT) |
| `DEFAULT_SLIPPAGE_FACTOR` | Base slippage factor (default 0.1) |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend: backend REST API base URL |
| `NEXT_PUBLIC_WS_URL` | Frontend: backend WebSocket URL |
