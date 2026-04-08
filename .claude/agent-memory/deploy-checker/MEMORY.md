# deploy-checker — Persistent Memory

<!-- last-updated: 2026-04-07 -->

## Docker Services (docker-compose.yml)

**Core services (always up) — 9 total:**
- `timescaledb` — TimescaleDB (PostgreSQL 16 + TimescaleDB extension, port 5432)
- `redis` — Redis 7 (port 6379)
- `api` — FastAPI app via uvicorn (port 8000)
- `ingestion` — Price ingestion service (no external port)
- `celery` — Celery worker (queues: default, high_priority)
- `celery-beat` — Celery beat scheduler
- `pgadmin` — pgAdmin 4 web UI (port 5050)
- `prometheus` — Prometheus metrics scraper (port 9090)
- `grafana` — Grafana dashboards (port **3001**, mapped from container 3000)

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
- Branch: `main` is production and active development (V.0.0.3 work merged to main)
- All PRs must pass: ruff lint, mypy type check, pytest unit tests, frontend `pnpm build`
- Zero TS/lint errors required for frontend build

## Deployment Gotchas

- `DATABASE_URL` scheme is validated at startup — `postgresql://` (without asyncpg) fails immediately
- `get_settings()` uses `lru_cache` — env var changes require process restart
- TimescaleDB extension must be pre-installed in the DB container before migrations run
- `alembic upgrade head` must run before first API start; current head is migration `023`
- Frontend build requires `NEXT_PUBLIC_*` vars at build time (not just runtime)
- No migration 011 in chain — gap is intentional (010 → 012)
- **DB volume password mismatch:** If `timescaledb_data` volume existed before `.env` was updated, the stored password hash won't match. Fix: `docker exec <container> psql -U agentexchange -d agentexchange -c "ALTER USER agentexchange WITH PASSWORD '<new_pw>';"` — peer auth via docker exec bypasses password check.
- **API health "degraded" on startup is normal:** `/health` returns `degraded` with stale pair list when ingestion just started. `ingestion_active: true` + Redis/DB connected confirms healthy state. Prices populate within minutes.
- **`docker exec psql` uses peer/Unix socket auth** — does NOT test TCP password auth. Use `psql postgresql://user:pass@localhost:5432/db` to test real auth path.
- **`alembic` CLI broken in venv** — `alembic history` fails with `ModuleNotFoundError`. Verify migration chain by reading files in `alembic/versions/` directly (check `revision` and `down_revision` fields). The Python API also fails (`No module named alembic.__main__`).
- **mypy known issue in `src/api/routes/indicators.py`** — 11 type errors: `RedisDep` missing type params (line 149), `row` object attribute access (lines 253-256), stale `type: ignore` comments on lines 353/381/416. These are pre-existing and not new regressions. The file was committed in HEAD — not a working-copy issue.
- **Untracked test file `tests/unit/test_webhook_ssrf.py`** — written by security fixes commit but not staged/committed. Must be committed before push.

## Access Points

| Service | URL |
|---------|-----|
| API | `http://localhost:8000` |
| Swagger | `http://localhost:8000/docs` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3001` (host port 3001 → container 3000) |
| pgAdmin | `http://localhost:5050` |
| Frontend | `http://localhost:3000` (pnpm dev, not in compose) |
| WebSocket | `ws://localhost:8000/ws/v1?api_key=...` |

- [project_monitoring_stack.md](project_monitoring_stack.md) — Prometheus + Grafana monitoring config patterns and common issues
