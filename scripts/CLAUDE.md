# Scripts

<!-- last-updated: 2026-03-18 -->

> Standalone scripts for database seeding, data migration, backfill operations, testing, and platform validation.

## What This Module Does

This directory contains one-off and repeatable scripts that operate directly against the database, Binance API, or the platform's REST API. They handle data seeding, schema migrations (data-layer, not Alembic DDL), backfill of missing columns, end-to-end testing, and infrastructure validation. All async scripts use `asyncio.run()` as their entry point.

## Script Inventory

| Script | Purpose | When to Run |
|--------|---------|-------------|
| `seed_pairs.py` | Fetches all active USDT trading pairs from Binance or any CCXT exchange (`--exchange okx`) and upserts them into `trading_pairs` table. Extracts LOT_SIZE and MIN_NOTIONAL filters. | **First setup** and periodically to pick up new listings. Run before `backfill_history.py`. |
| `seed_test_user.py` | Creates a test account (`slava@test.com` / `TestPass123!`) with 3 agents (Alpha Scalper, Beta Swing, Gamma HODL), each with pre-populated balances, trades, orders, and positions. Idempotent. | **Development/demo** — to get a ready-made user with realistic multi-agent data. |
| `backfill_history.py` | Fetches historical OHLCV klines from Binance or any CCXT exchange (`--exchange okx`) and batch-inserts into `candles_backfill` hypertable. Supports `--daily`, `--hourly`, custom `--symbols`, `--resume`, `--dry-run`, and `--exchange`. | **After `seed_pairs.py`** — to populate historical candle data for backtesting. Long-running (hours for full backfill). |
| `migrate_accounts_to_agents.py` | Creates one `Agent` row per existing `Account`, copying API key, starting balance, and risk profile. | **Once**, after Alembic migration 007 (`create_agents_table`) and before migration 009 (`enforce_agent_id_not_null`). |
| `backfill_agent_ids.py` | Sets `agent_id` on all rows in `balances`, `orders`, `trades`, `positions`, `trading_sessions`, and `portfolio_snapshots` where it is NULL, using the account-to-agent mapping. Verifies zero NULLs remain. | **Once**, after `migrate_accounts_to_agents.py` and before Alembic migration 009. |
| `backfill_backtest_agent_ids.py` | Sets `agent_id` on `backtest_sessions` rows where it is NULL, assigning the earliest agent for the session's account. | **Once**, after Alembic migration 013 and before migration 014 (`enforce_backtest_agent_id_not_null`). |
| `backfill_positions.py` | Replays all trade history per account to reconstruct the `positions` table (quantity + weighted-average entry price). Deletes existing positions first, so it is safe to re-run. | **Once**, after deploying position-tracking. Can re-run if positions get out of sync. |
| `backfill_realized_pnl.py` | Backfills `realized_pnl` on existing `Trade` rows by replaying trade history and computing PnL for sell trades. Supports `--dry-run`. Uses synchronous `psycopg2`. | **Once**, after deploying realized PnL tracking to the order engine. |
| `backfill_rpnl.sql` | Pure SQL (PL/pgSQL) equivalent of `backfill_realized_pnl.py`. Replays trades in a single `DO` block and updates sell trades with computed `realized_pnl`. | **Alternative** to the Python script — run directly via `psql` if you prefer a single SQL transaction. |
| `e2e_multi_agent_test.py` | End-to-end test: registers an account, creates 3 agents with distinct risk profiles, places live trades per agent, runs a backtest, and verifies agent isolation (different balances, positions, trade counts). | **After deployment** or during development to validate the full multi-agent stack. Requires API at `localhost:8000` with live prices. |
| `e2e_full_scenario_live.py` | Full 8-phase E2E scenario against a live backend: registers account, creates 3 agents (AlphaBot, BetaBot, GammaBot), places 25 trades, runs 6 backtests (2 per agent), creates and runs 1 historical battle, verifies analytics and account management. All data persists in DB and is visible in the UI. Supports `--skip-backtest`, `--skip-battle`, `--email`, `--base-url`. | **After deployment** or during UI development — to populate a realistic full-stack dataset visible in the frontend. Requires API at `localhost:8000` with live prices. |
| `validate_phase1.py` | Validates Phase 1 infrastructure: Redis connectivity and price freshness, TimescaleDB tick ingestion and growth, `trading_pairs` seeding, continuous aggregates, and `/health` endpoint. Prints pass/fail summary. | **After `docker compose up`** — to confirm all services are healthy. |
| `stability_test_24h.py` | Monitors the price ingestion pipeline for 24 hours (configurable via `DURATION_SECONDS`), sampling tick throughput, stale pair counts, Redis freshness, and API health every 60 seconds. Writes a JSON report to `reports/`. | **Production readiness** — run before go-live or after infrastructure changes. Use `DURATION_SECONDS=600` for a 10-minute smoke test. |

## Common Tasks

**Initial platform setup (in order):**
```bash
# 1. Start services
docker compose up -d

# 2. Run Alembic migrations
alembic upgrade head

# 3. Seed trading pairs from Binance
python scripts/seed_pairs.py

# 4. Validate infrastructure
python scripts/validate_phase1.py

# 5. (Optional) Backfill historical candles for backtesting
python scripts/backfill_history.py --daily --resume
python scripts/backfill_history.py --hourly --resume

# 6. (Optional) Seed a test user for development
python -m scripts.seed_test_user
```

**Agent migration (one-time, in order):**
```bash
alembic upgrade 007                              # Create agents table
python -m scripts.migrate_accounts_to_agents     # Create agent per account
python -m scripts.backfill_agent_ids             # Backfill agent_id on trading tables
alembic upgrade 009                              # Enforce NOT NULL on agent_id
```

**Backtest agent_id migration (one-time, in order):**
```bash
alembic upgrade 013                              # Add nullable agent_id to backtest_sessions
python -m scripts.backfill_backtest_agent_ids    # Backfill agent_id
alembic upgrade 014                              # Enforce NOT NULL
```

**Quick infrastructure health check:**
```bash
python scripts/validate_phase1.py
```

**Stability smoke test (10 minutes):**
```bash
DURATION_SECONDS=600 python scripts/stability_test_24h.py
```

## Gotchas & Pitfalls

- **Run order matters for migrations.** The backfill scripts must run between specific Alembic migrations. Running migration 009 or 014 before the corresponding backfill will fail if any NULL `agent_id` rows exist.
- **`backfill_realized_pnl.py` uses synchronous `psycopg2`**, not async `asyncpg` like the other scripts. It has a hardcoded `DB_URL` constant pointing to localhost — update it or use the SQL alternative (`backfill_rpnl.sql`) instead.
- **`backfill_positions.py` deletes all existing positions** before rebuilding. This is intentional but destructive — do not run on a live system without understanding the impact.
- **`backfill_history.py` is long-running.** A full daily backfill (all pairs from 2017) takes hours. Always use `--resume` to skip already-fetched ranges after an interruption. Use `--dry-run` to preview without writing.
- **`seed_pairs.py` requires Binance API access.** It fetches from the public endpoint (no API key needed) but will fail behind a firewall or if Binance is unreachable.
- **`seed_test_user.py` is idempotent** — it skips creation if `slava@test.com` already exists and prints existing agent API keys.
- **`e2e_multi_agent_test.py` requires live services** — the API must be running at `localhost:8000` with Binance WS connected for live price data. Each run creates a new account with a timestamp-based email.
- **`e2e_full_scenario_live.py` is idempotent for the account** — if the email already exists, it skips registration and logs in directly. Agents and trades are created fresh each run. Use `--email` to reuse a fixed account across runs.
- **`stability_test_24h.py` writes reports to `reports/`** in the repo root. The directory is auto-created. Default duration is 24 hours.
- **`validate_phase1.py` expects `seed_pairs.py` to have been run first** — it checks for 600+ rows in `trading_pairs`.
- **`__init__.py` is empty** — it exists so scripts can be invoked as `python -m scripts.<name>`.

## Dependencies

| Script | Python Packages | External Services |
|--------|----------------|-------------------|
| `seed_pairs.py` | `httpx`, `sqlalchemy[asyncpg]` | Binance API, TimescaleDB |
| `seed_test_user.py` | `sqlalchemy[asyncpg]`, `src.*` | TimescaleDB |
| `backfill_history.py` | `httpx`, `sqlalchemy[asyncpg]` | Binance API, TimescaleDB |
| `migrate_accounts_to_agents.py` | `sqlalchemy[asyncpg]`, `src.*` | TimescaleDB |
| `backfill_agent_ids.py` | `sqlalchemy[asyncpg]`, `src.*` | TimescaleDB |
| `backfill_backtest_agent_ids.py` | `sqlalchemy[asyncpg]`, `structlog`, `src.*` | TimescaleDB |
| `backfill_positions.py` | `sqlalchemy[asyncpg]`, `src.*` | TimescaleDB |
| `backfill_realized_pnl.py` | `psycopg2` (sync) | TimescaleDB |
| `backfill_rpnl.sql` | N/A (raw SQL) | TimescaleDB (`psql`) |
| `e2e_multi_agent_test.py` | `httpx` | API server, Binance WS (live prices) |
| `e2e_full_scenario_live.py` | `httpx` | API server, Binance WS (live prices) |
| `validate_phase1.py` | `httpx`, `asyncpg`, `redis` | API server, Redis, TimescaleDB |
| `stability_test_24h.py` | `httpx`, `asyncpg`, `redis` | API server, Redis, TimescaleDB |

## Recent Changes

- `2026-03-17` — Initial CLAUDE.md created
- `2026-03-18` — Added `e2e_full_scenario_live.py` to inventory
- `2026-03-18` — Added `--exchange` flag to `seed_pairs.py` and `backfill_history.py` for CCXT multi-exchange support
