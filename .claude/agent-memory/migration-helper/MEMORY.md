# migration-helper — Persistent Memory

<!-- last-updated: 2026-03-21 -->

## Current State

- **Head migration:** `019` (feedback lifecycle columns)
- **Next revision number:** `020`
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
| 008 | Nullable `agent_id` FK on trading tables (phase 1 of 2-phase NOT NULL) |
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
