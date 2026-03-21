# deploy-checker — Persistent Memory

<!-- last-updated: 2026-03-21 -->

## Docker Services (docker-compose.yml)

**Core services (always up):**
- `db` — TimescaleDB (PostgreSQL extension, port 5432)
- `redis` — Redis (port 6379)
- `api` — FastAPI app via uvicorn (port 8000)
- `worker` — Celery worker
- `beat` — Celery beat scheduler
- `price_ingestion` — Price ingestion service
- `prometheus` — Prometheus metrics scraper (port 9090)
- `grafana` — Grafana dashboards (port 3000)

**Profile-gated (opt-in):**
- `agent` — Platform testing agent; started with `--profile agent`; reads `agent/.env`

**Dev overrides:** `docker-compose.dev.yml` adds hot reload and debug ports.

## Environment Variables

**Required (no default):**
- `DATABASE_URL` — must use `postgresql+asyncpg://` scheme (enforced by config validator)
- `REDIS_URL` — Redis connection string
- `JWT_SECRET` — must be 32+ chars (enforced by config validator)

**Optional with defaults:**
- `EXCHANGE_ID` — default `binance`; supports any CCXT exchange ID
- `TRADING_FEE_PCT` — default 0.1%
- `DEFAULT_STARTING_BALANCE` — default 10000 USDT
- `DEFAULT_SLIPPAGE_FACTOR` — default 0.1
- `TICK_FLUSH_INTERVAL` — default 1.0s
- `TICK_BUFFER_MAX_SIZE` — default 5000
- `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` — both default to `REDIS_URL`

**Frontend (NEXT_PUBLIC_*):**
- `NEXT_PUBLIC_API_BASE_URL` — default `http://localhost:8000/api/v1`
- `NEXT_PUBLIC_WS_URL` — default `ws://localhost:8000/ws/v1`

**Agent (in `agent/.env`, not root `.env`):**
- `OPENROUTER_API_KEY` — required for agent workflows
- `AGENT_MODEL` — default `openrouter:anthropic/claude-sonnet-4-5`
- `AGENT_CHEAP_MODEL` — default `openrouter:google/gemini-2.0-flash-001`

## CI/CD Structure

- GitHub Actions defined in `.github/workflows/`
- Branch: `V.0.0.2` is active development; `main` is production
- All PRs must pass: ruff lint, mypy type check, pytest unit tests, frontend `pnpm build`
- Zero TS/lint errors required for frontend build

## Deployment Gotchas

- `DATABASE_URL` scheme is validated at startup — `postgresql://` (without asyncpg) fails immediately
- `get_settings()` uses `lru_cache` — env var changes require process restart
- TimescaleDB extension must be pre-installed in the DB container before migrations run
- `alembic upgrade head` must run before first API start; current head is migration `019`
- Frontend build requires `NEXT_PUBLIC_*` vars at build time (not just runtime)
- No migration 011 in chain — gap is intentional (010 → 012)

## Access Points

| Service | URL |
|---------|-----|
| API | `http://localhost:8000` |
| Swagger | `http://localhost:8000/docs` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3000` |
| Frontend | `http://localhost:3000` (pnpm dev) |
| WebSocket | `ws://localhost:8000/ws/v1?api_key=...` |
