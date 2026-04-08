# Database Layer

<!-- last-updated: 2026-04-07 (task-15) -->

> SQLAlchemy ORM models, async session management, and repository pattern for TimescaleDB/PostgreSQL.

## What This Module Does

This module defines the entire data layer for the AI Agent Crypto Trading Platform. It contains:

1. **ORM models** (`models.py`) -- all 27 table definitions using SQLAlchemy 2.0 mapped columns (18 original + 6 strategy/training tables + 3 agent ecosystem tables)
2. **Session management** (`session.py`) -- async engine, session factory, and raw asyncpg pool as lazy singletons
3. **Repository classes** (`repositories/`) -- data access layer with one repository per domain entity (covered in `repositories/CLAUDE.md`)

The database is **TimescaleDB** (PostgreSQL extension). Four tables are hypertables partitioned by time: `ticks`, `portfolio_snapshots`, `backtest_snapshots`, and `battle_snapshots`.

## Key Files

| File | Purpose |
|------|---------|
| `models.py` | All 27 ORM model classes inheriting from shared `Base` |
| `session.py` | Async engine, `async_sessionmaker`, raw `asyncpg` pool, `init_db()`/`close_db()` lifecycle |
| `__init__.py` | Empty (package marker only) |
| `repositories/` | One repository class per domain entity (has its own CLAUDE.md) |

## Architecture & Patterns

### Dual Database Handles

`session.py` provides two independent database connections:

- **SQLAlchemy `AsyncSession`** -- used by all FastAPI routes and services via `get_async_session()` dependency. Configured with `expire_on_commit=False`, `autoflush=False`.
- **Raw `asyncpg` pool** -- used exclusively by `TickBuffer` for high-throughput `COPY` bulk inserts. Requires `init_db()` to be called at startup; accessing before init raises `RuntimeError`.

Both are module-level singletons, lazily initialized on first access (engine/session factory) or explicitly via `init_db()` (asyncpg pool).

### Model Hierarchy

All models inherit from `Base` (a plain `DeclarativeBase`). No mixins or abstract base classes. `Base.metadata` is passed to Alembic's `target_metadata`.

### Table Groups

**Core trading (agent-scoped via `agent_id` FK):**
- `Account` -- top-level user account (owns agents)
- `Agent` -- trading agent with own API key, balance, risk profile
- `Balance` -- per-asset available/locked amounts (unique per agent+asset)
- `Order` -- full order lifecycle (pending -> filled/cancelled/rejected/expired)
- `Trade` -- executed fills with realized PnL
- `Position` -- aggregated holdings per agent+symbol (unique per agent+symbol)
- `TradingSession` -- session tracking for account resets
- `PortfolioSnapshot` -- periodic equity snapshots (hypertable, 1-day chunks)
- `AgentApiCall` -- per-tool API call log: trace_id, endpoint, latency, tokens, cost (migration 018)
- `AgentStrategySignal` -- per-step strategy signal log: source, action, confidence (migration 018)
- `AgentDecision.trace_id` -- new column on existing model linking decisions to distributed traces (migration 018)
- `AgentFeedback.status`/`.resolution` -- feedback lifecycle columns with CHECK constraint (migration 019)
- `AgentAuditLog` -- durable audit trail for all permission check outcomes (allow + deny): `agent_id`, `action`, `outcome`, `reason`, `capability`, `timestamp` (migration 020)

**Backtesting:**
- `BacktestSession` -- run config, progress, and final metrics (JSONB)
- `BacktestTrade` -- simulated fills (uses `simulated_at` instead of `created_at`)
- `BacktestSnapshot` -- equity curve data points (hypertable, 1-day chunks)

**Battles:**
- `Battle` -- competition config and state machine (draft/pending/active/completed/cancelled)
- `BattleParticipant` -- agent enrollment with starting balance and final rank
- `BattleSnapshot` -- time-series equity during battle (hypertable, BIGSERIAL + timestamp composite PK)

**Strategies/Training:**
- `Strategy` -- strategy metadata, versioning, lifecycle (draft/testing/validated/deployed/archived)
- `StrategyVersion` -- immutable versioned strategy definitions (JSONB)
- `StrategyTestRun` -- multi-episode test run orchestration
- `StrategyTestEpisode` -- individual test episode results (FK to backtest_sessions)
- `TrainingRun` -- RL training run tracking
- `TrainingEpisode` -- individual training episode results (FK to backtest_sessions)

**Webhooks:**
- `WebhookSubscription` -- per-account outbound webhook endpoint registrations (FK → accounts.id, cascade delete)

**Reference/utility:**
- `Tick` -- raw Binance trade ticks (hypertable, 1-hour chunks; composite PK: time+symbol+trade_id)
- `TradingPair` -- Binance USDT pair reference data (symbol is PK)
- `AuditLog` -- immutable request audit trail (BIGSERIAL PK)
- `WaitlistEntry` -- landing page email signups

### Column Conventions

- All monetary values: `Numeric(20, 8)` -- never `float`
- All timestamps: `TIMESTAMP(timezone=True)` -- always UTC
- All UUIDs: `PG_UUID(as_uuid=True)` with `server_default=func.gen_random_uuid()`
- Status fields: `VARCHAR(20)` with `CheckConstraint` enforcing valid values
- JSON data: `JSONB` (risk_profile, metrics, positions, config, strategy_tags)
- `created_at`/`updated_at` patterns: `server_default=func.now()`, `onupdate=func.now()`

### Relationship Pattern

All parent-child relationships use `cascade="all, delete-orphan"` on the parent side. Foreign keys use `ondelete="CASCADE"` (or `SET NULL` for optional references like `session_id` on orders/trades).

### Agent Scoping

Trading tables (`balances`, `orders`, `trades`, `positions`, `portfolio_snapshots`, `trading_sessions`) carry both `account_id` and `agent_id` FKs. The `agent_id` is the primary scoping key for all trading operations. Unique constraints enforce one balance per (agent, asset) and one position per (agent, symbol).

## Public API / Interfaces

### session.py exports

| Function | Description |
|----------|-------------|
| `init_db()` | Call once at startup. Creates SQLAlchemy engine + asyncpg pool. |
| `close_db()` | Call on shutdown. Disposes engine and closes asyncpg pool. Resets all singletons to `None`. |
| `get_engine()` | Returns singleton `AsyncEngine` (lazy-created). |
| `get_session_factory()` | Returns singleton `async_sessionmaker[AsyncSession]` (lazy-created). |
| `get_async_session()` | Async generator yielding one `AsyncSession` per request. Used as FastAPI dependency. |
| `get_asyncpg_pool()` | Returns raw `asyncpg.Pool`. Raises `RuntimeError` if `init_db()` not called. |

### models.py exports

| Export | Description |
|--------|-------------|
| `Base` | Declarative base for Alembic `target_metadata` |
| 28 model classes | `Tick`, `TradingPair`, `Account`, `Agent`, `Balance`, `TradingSession`, `Order`, `Trade`, `Position`, `PortfolioSnapshot`, `AuditLog`, `WaitlistEntry`, `BacktestSession`, `BacktestTrade`, `BacktestSnapshot`, `Battle`, `BattleParticipant`, `BattleSnapshot`, `Strategy`, `StrategyVersion`, `StrategyTestRun`, `StrategyTestEpisode`, `TrainingRun`, `TrainingEpisode`, `AgentApiCall`, `AgentStrategySignal`, `AgentAuditLog`, `WebhookSubscription` |

## Dependencies

- **SQLAlchemy 2.0** (async) -- `AsyncEngine`, `AsyncSession`, `async_sessionmaker`, `mapped_column`, `Mapped`
- **asyncpg** -- raw pool for bulk COPY operations
- **src.config.get_settings()** -- reads `DATABASE_URL` (must be `postgresql+asyncpg://` scheme)
- **TimescaleDB** -- hypertable creation happens in Alembic migrations, not in model definitions

## Common Tasks

### Adding a new model

1. Define the class in `models.py` inheriting from `Base`
2. Use `Numeric(20, 8)` for money, `PG_UUID(as_uuid=True)` for IDs, `TIMESTAMP(timezone=True)` for times
3. Add `CheckConstraint` for status enums, appropriate indexes
4. Create an Alembic migration: `alembic revision --autogenerate -m "description"`
5. If time-series, add hypertable creation in the migration's `upgrade()` function

### Adding a column to an existing model

1. Add the `mapped_column` to the model class
2. Generate migration: `alembic revision --autogenerate -m "add column_name to table"`
3. If NOT NULL on existing data, use a two-step migration (add nullable -> backfill -> enforce NOT NULL)

### Using sessions in tests

Tests use mocked sessions from `tests/conftest.py`. The `get_async_session` dependency is overridden via FastAPI dependency injection. Never import the raw singletons in tests.

## Gotchas & Pitfalls

- **`get_settings()` is `lru_cache`d** -- in tests, patch `src.config.get_settings` before any database module is imported, or you get the real config.
- **`expire_on_commit=False`** -- ORM objects remain usable after commit without extra SELECTs, but this means stale data is possible if another session modifies the same row.
- **`autoflush=False`** -- you must explicitly call `session.flush()` if you need generated values (like server-default UUIDs) before commit.
- **asyncpg pool requires `init_db()`** -- accessing `get_asyncpg_pool()` before startup raises `RuntimeError`. The SQLAlchemy engine/session factory are lazy and do not need explicit init.
- **Hypertable composite PKs** -- `Tick` (time+symbol+trade_id), `PortfolioSnapshot` (id+created_at), `BacktestSnapshot` (id+simulated_at), `BattleSnapshot` (id+timestamp) all have composite primary keys required by TimescaleDB.
- **`BacktestSession.agent_id` is nullable** -- migration 013 added it as nullable; migration 014 enforces NOT NULL after backfill. Check which migration has been applied.
- **No `__init__.py` re-exports** -- import directly from `src.database.models` and `src.database.session`, not from `src.database`.
- **Engine pool settings** -- `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=3600`. Do not change without load testing.
- **DSN stripping for asyncpg** -- `init_db()` strips `postgresql+asyncpg://` to `postgresql://` for the raw pool. If the DATABASE_URL scheme changes, this will break.

## Recent Changes

- `2026-04-07` — Migration 023: added `WebhookSubscription` model (`webhook_subscriptions` table). Per-account outbound webhook endpoint registrations with JSONB events array, HMAC-SHA256 secret, active flag, failure_count, and last_triggered_at. FK → accounts.id with CASCADE delete. Two indexes: account_id and active. Model count: 27 → 28. Alembic head: 022 → 023.
- `2026-04-07` — Migration 022: added `stop_price NUMERIC(20,8)` nullable column to `BacktestTrade` model and `backtest_trades` table. Persists trigger price for stop-loss and take-profit sandbox trades. Alembic head: 021 → 022.
- `2026-04-02` — Migration 021: fixed CASCADE DELETE on agent foreign keys (`orders`, `trades`, `positions`, `balances`, `trading_sessions`, `portfolio_snapshots`). No new tables; enforces correct cascade behavior so deleting an agent removes all associated rows. Alembic head: 020 → 021.
- `2026-03-23` — Migration 020: added `AgentAuditLog` model (`agent_audit_log` table) for durable, complete permission audit trail (all outcomes, not just denials). 3 indexes on `agent_id`, `created_at`, and `(agent_id, created_at)` composite. Model count: 26 → 27. Alembic head: 020.
- `2026-03-21` — Migration 018: added `AgentApiCall` and `AgentStrategySignal` tables; added `trace_id` column to `agent_decisions`. Migration 019: added `status`/`resolution` lifecycle columns to `agent_feedback` with CHECK constraint. Model count: 24 → 26.
- `2026-03-17` -- Initial CLAUDE.md created
