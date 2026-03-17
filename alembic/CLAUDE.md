# Alembic Migrations

<!-- last-updated: 2026-03-17 -->

> Async Alembic migrations for TimescaleDB/PostgreSQL schema management.

## What This Module Does

Manages all database schema changes for the AI Agent Crypto Trading Platform. Migrations run against an async `postgresql+asyncpg://` connection using `NullPool`. TimescaleDB-specific DDL (hypertables, continuous aggregates, compression/retention policies) is executed via raw `op.execute()` calls since Alembic has no native support for these.

## Key Files

| File | Purpose |
|------|---------|
| `alembic.ini` (project root) | Alembic config: script location, file template, post-write ruff hook |
| `alembic/env.py` | Async migration runner: `asyncio.run(run_migrations_online())` with `NullPool` |
| `alembic/versions/` | All migration scripts (sequential `001`..`015` numeric revisions) |
| `src/database/models.py` | SQLAlchemy ORM models (`Base.metadata` used for autogenerate) |
| `src/config.py` | `get_settings().database_url` provides the connection string |

## Migration Inventory

| # | Migration | Description |
|---|-----------|-------------|
| 001 | `001_initial_schema.py` | TimescaleDB extension, `ticks` hypertable, continuous aggregates (1m/5m/1h/1d candles), `trading_pairs` |
| 002 | `002_trading_tables.py` | `accounts`, `balances`, `trading_sessions`, `orders`, `trades`, `positions`, `portfolio_snapshots` (hypertable), `audit_log` |
| 003 | `003_add_password_hash.py` | Add `password_hash` column to `accounts`, unique index on `email` |
| 004 | `004_add_waitlist_table.py` | `waitlist_entries` table for landing-page email collection |
| 005 | `005_backtesting_tables.py` | `backtest_sessions`, `backtest_trades`, `backtest_snapshots` (hypertable), `current_mode`/`active_strategy_label` on `accounts` |
| 006 | `006_candles_backfill.py` | `candles_backfill` hypertable for historical Binance kline data |
| 007 | `007_create_agents_table.py` | `agents` table (additive only, no existing tables modified) |
| 008 | `008_add_agent_id_to_trading_tables.py` | Nullable `agent_id` FK on `balances`, `orders`, `trades`, `positions`, `trading_sessions`, `portfolio_snapshots` |
| 009 | `009_enforce_agent_id_not_null.py` | Set `agent_id` NOT NULL on trading tables (run after backfill script) |
| 010 | `010_create_battle_tables.py` | `battles`, `battle_participants`, `battle_snapshots` (hypertable) |
| 012 | `012_agent_scoped_unique_constraints.py` | Change unique constraints from account-scoped to agent-scoped on `balances`/`positions` |
| 013 | `013_add_agent_id_to_backtest_sessions.py` | Nullable `agent_id` FK on `backtest_sessions` |
| 014 | `014_enforce_backtest_agent_id_not_null.py` | Set `agent_id` NOT NULL on `backtest_sessions` (run after backfill) |
| 015 | `015_add_historical_battle_support.py` | `battle_mode`, `backtest_config` on `battles`; `backtest_session_id` FK on `battle_participants` |

**Current head:** `015`

**Note:** Migration `011` (drop legacy account trading columns) is missing from the versions directory but is referenced in the chain. The chain skips from `010` directly to `012` via `down_revision`.

## Architecture & Patterns

### Async Engine Setup (`env.py`)

The environment uses an async-first pattern:
- `asyncio.run(run_migrations_online())` at module level
- Creates an `AsyncEngine` with `NullPool` (no persistent connections)
- Acquires a sync connection via `conn.run_sync(_run_migrations_sync)` for Alembic's synchronous migration context
- Database URL comes from `get_settings().database_url`, never hardcoded in `alembic.ini`
- `target_metadata = Base.metadata` enables autogenerate to detect model diffs

### Revision ID Convention

Revisions use zero-padded sequential integers (`001`, `002`, ..., `015`) rather than Alembic's default random hex hashes. The `down_revision` chain is strictly linear (no branches).

### File Naming

Configured in `alembic.ini` as `file_template = %%(rev)s_%%(slug)s`, producing filenames like `005_backtesting_tables.py`. Slug is truncated to 40 characters.

### Post-Write Hook

Every generated migration file is auto-formatted by `ruff format` via the `[post_write_hooks]` section in `alembic.ini`.

### Migration Patterns Used

- **Table creation:** `op.create_table()` with SQLAlchemy column definitions; UUIDs use `PG_UUID(as_uuid=True)` with `server_default=sa.text("gen_random_uuid()")`
- **TimescaleDB hypertables:** Created via `op.execute("SELECT create_hypertable(...)")` immediately after `op.create_table()`; partition column must be part of the primary key (composite PK)
- **CHECK constraints:** Either inline via `sa.CheckConstraint()` or via `op.execute("ALTER TABLE ... ADD CONSTRAINT ...")`
- **Two-phase NOT NULL migrations:** Nullable column added first (e.g., 008/013), backfill script run, then NOT NULL enforced in a follow-up migration (e.g., 009/014)
- **JSONB columns:** Used for flexible config storage (`config`, `metrics`, `pairs`, `backtest_config`)
- **Cascade deletes:** `ondelete="CASCADE"` on all child FKs; `ondelete="SET NULL"` for optional references
- **Additive-only preference:** Most migrations add columns/tables without modifying existing data, keeping them safe for zero-downtime deployment
- **All timestamps:** Use `sa.TIMESTAMP(timezone=True)` (always timezone-aware)
- **All monetary values:** Use `sa.Numeric(20, 8)` (never float)

### Downgrade Pattern

Every migration includes a `downgrade()` that reverses all changes in reverse dependency order (indexes first, then tables/columns). Continuous aggregates must be dropped before the underlying hypertable.

## Common Tasks

### Creating a new migration

```bash
# Autogenerate from model changes (preferred)
alembic revision --autogenerate -m "description of change"

# Manual (when autogenerate can't detect the change, e.g., TimescaleDB DDL)
alembic revision -m "description of change"
```

After generating, you must:
1. Set `revision` to the next sequential number (e.g., `"016"`)
2. Set `down_revision` to the current head (e.g., `"015"`)
3. Write both `upgrade()` and `downgrade()` functions
4. Run `ruff check` on the generated file (post-write hook handles formatting)

### Applying migrations

```bash
alembic upgrade head       # Apply all pending migrations
alembic upgrade +1         # Apply next one migration
alembic current            # Show current revision
alembic history            # Show full migration history
```

### Rolling back

```bash
alembic downgrade -1       # Roll back one migration
alembic downgrade 010      # Roll back to specific revision
```

**Warning:** Rolling back hypertable or continuous aggregate migrations may lose data. Test downgrades against a staging database first.

## Gotchas & Pitfalls

- **`prepend_sys_path = .`** in `alembic.ini` is required for `src` module imports to work. Do not remove it.
- **`get_settings()` uses `lru_cache`** -- the database URL is read from `.env` once per process. If you change `.env`, restart the Alembic process.
- **Database URL must use `postgresql+asyncpg://`** scheme (enforced by a validator in `src/config.py`). Standard `postgresql://` will fail.
- **TimescaleDB hypertable partition columns must be in the primary key.** This is why `backtest_snapshots` and `battle_snapshots` use composite PKs like `PrimaryKeyConstraint("id", "simulated_at")`.
- **Two-phase NOT NULL pattern:** When adding a NOT NULL FK column to a table with existing data, always split into two migrations with a backfill script between them (see migrations 008/009 and 013/014).
- **No migration 011** in the versions directory -- the chain goes `010 -> 012`. If you see revision errors, this gap is intentional.
- **Continuous aggregates must be dropped before their source hypertable** in downgrade functions.
- **`op.execute()` for TimescaleDB DDL** -- there is no SQLAlchemy/Alembic native support for hypertables, continuous aggregates, compression, or retention policies.
- **Offline mode** (`alembic upgrade --sql`) will include `op.execute()` calls verbatim -- review the output before handing to a DBA.

## Recent Changes

- `2026-03-17` -- Migrations 013-015 added: agent-scoped backtests and historical battle support
- `2026-03-17` -- Initial CLAUDE.md created
