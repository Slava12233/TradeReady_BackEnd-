# migration-helper — Persistent Memory

<!-- last-updated: 2026-03-23 -->

## Current State

- **Head migration:** `021` (fix cascade delete on agent FK constraints)
- **Next revision number:** `022`
- **Chain gap:** Migration `011` is missing (intentional). Chain goes `010 → 012`.
- **File naming:** `alembic.ini` template = `%%(rev)s_%%(slug)s` → e.g., `017_my_description.py`

## Migration Inventory Summary

| # | What it added |
|---|--------------|
| 001 | TimescaleDB extension, `ticks` hypertable, 4 continuous aggregates, `trading_pairs` |
| 002 | `accounts`, `balances`, `orders`, `trades`, `positions`, `portfolio_snapshots` (hypertable) |
| 003 | `password_hash` on accounts, unique index on email |
| 004 | `waitlist_entries` |
| 005 | Backtest tables, `current_mode`/`active_strategy_label` on accounts |
| 006 | `candles_backfill` hypertable |
| 007 | `agents` table |
| 008 | Nullable `agent_id` FK on trading tables with `SET NULL` (phase 1 of 2-phase NOT NULL) |
| 009 | `agent_id` NOT NULL enforcement on trading tables (phase 2) |
| 010 | Battle tables: `battles`, `battle_participants`, `battle_snapshots` (hypertable) |
| 012 | Agent-scoped unique constraints on `balances`/`positions` |
| 013 | Nullable `agent_id` FK on `backtest_sessions` (phase 1) |
| 014 | `agent_id` NOT NULL on `backtest_sessions` (phase 2) |
| 015 | `battle_mode`, `backtest_config` on battles; `backtest_session_id` on participants |
| 016 | Strategies/training tables (6 new tables) |
| 017 | Agent ecosystem tables (10 tables: sessions, messages, decisions, journal, learnings, feedback, permissions, budgets, performance, observations hypertable) |
| 018 | Agent logging tables: `agent_api_calls`, `agent_strategy_signals`; `trace_id` column on `agent_decisions` |
| 019 | Feedback lifecycle columns on agent tables |
| 020 | `agent_audit_log` table (no FK to agents — intentional, records outlive agents) |
| 021 | Fix BUG-004: change `agent_id` FK on 6 trading tables from SET NULL → CASCADE |

## Hypertable Rules

**TimescaleDB hypertable partition column must be in the primary key.** Composite PKs:
- `ticks` → `(time, symbol, trade_id)`
- `portfolio_snapshots` → `(id, created_at)`
- `backtest_snapshots` → `(id, simulated_at)`
- `battle_snapshots` → `(id, timestamp)`

If adding a new hypertable, always create with a composite PK including the time column.

## Column Conventions

- All monetary values: `sa.Numeric(20, 8)` — never float
- All timestamps: `sa.TIMESTAMP(timezone=True)` — always UTC
- All UUIDs: `PG_UUID(as_uuid=True)` + `server_default=sa.text("gen_random_uuid()")`
- Status fields: `VARCHAR(20)` + `CheckConstraint`
- JSON data: `JSONB`
- FKs: `ondelete="CASCADE"` for required references, `ondelete="SET NULL"` for optional

## Two-Phase NOT NULL Pattern

When adding a NOT NULL FK to a table that already has rows:
1. **Migration N:** Add column as `nullable=True`
2. **Run backfill script** (separate Python script to populate existing rows)
3. **Migration N+1:** `ALTER COLUMN ... SET NOT NULL`

Precedent: migrations 008/009 (agent_id on trading tables) and 013/014 (agent_id on backtest_sessions).

## Creating a New Migration

```bash
# Autogenerate from model diff
alembic revision --autogenerate -m "description"

# Then immediately:
# 1. Set revision = "017" (next sequential number)
# 2. Set down_revision = "016"
# 3. Write upgrade() and downgrade()
# 4. ruff check alembic/versions/017_*.py
```

## Running Alembic Against Docker

The `DATABASE_URL` uses `timescaledb` as the hostname (Docker service name), which only resolves inside the Docker network. Running `alembic` on the host machine will fail with `getaddrinfo failed`.

**Correct approach:** Run Alembic inside the API container:
```bash
docker exec aitradingagent-api-1 bash -c "cd /app && alembic upgrade head"
docker exec aitradingagent-api-1 bash -c "cd /app && alembic current"
```

**Watch out:** The Docker image is built at a point in time. New migration files added after the image was built will NOT be in the container. If `alembic upgrade head` shows no new migrations after adding files, copy them in first:
```bash
docker cp alembic/versions/017_*.py aitradingagent-api-1:/app/alembic/versions/
```

**Live database state as of 2026-04-01:** All 21 migrations applied, head at `021`.

## FK CASCADE vs SET NULL — Agent Scoping History

Migration 008 added `agent_id` with `ondelete="SET NULL"` to trading tables. Migration 009 later enforced NOT NULL. This created an impossible constraint (PostgreSQL can't SET NULL on a NOT NULL column) which caused `DELETE /agents/{id}` to fail with DATABASE_ERROR. Fixed in migration 021.

**Constraint names for the 6 affected trading tables:**
- `balances_agent_id_fkey` — was SET NULL, now CASCADE
- `orders_agent_id_fkey` — was SET NULL, now CASCADE
- `trades_agent_id_fkey` — was SET NULL, now CASCADE
- `positions_agent_id_fkey` — was SET NULL, now CASCADE
- `trading_sessions_agent_id_fkey` — was SET NULL, now CASCADE
- `portfolio_snapshots_agent_id_fkey` — was SET NULL, now CASCADE (hypertable: use `DROP CONSTRAINT … CASCADE` to also drop from chunks)

**All agent ecosystem tables (017/018) already had CASCADE — no change needed.**

## Critical Gotchas

- `DATABASE_URL` must use `postgresql+asyncpg://` scheme (validator in `src/config.py` enforces this)
- `prepend_sys_path = .` in `alembic.ini` required for `src` imports — do not remove
- `get_settings()` is `lru_cache`d — changing `.env` requires restarting the Alembic process
- Continuous aggregates must be dropped BEFORE their source hypertable in `downgrade()`
- `op.execute()` required for all TimescaleDB DDL (hypertables, continuous aggregates, compression)
- Rolling back hypertable migrations may lose data — always test against staging first
- `--sql` offline mode includes `op.execute()` verbatim — review before handing to DBA
- Post-write hook: `ruff format` runs automatically on generated files via `[post_write_hooks]`
- `BacktestSession.agent_id` was nullable until migration 014 — check which migration is applied
