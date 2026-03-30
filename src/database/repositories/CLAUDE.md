# Database Repositories

<!-- last-updated: 2026-03-24 -->

> Async repository layer providing typed CRUD methods for all database models; the sole interface between service code and SQLAlchemy/TimescaleDB.

## What This Module Does

Every database table has a corresponding repository class that encapsulates all SQL queries behind typed async methods. Services and routes never call `session.execute()` directly -- they go through these repositories. All repositories follow a shared contract: they accept an `AsyncSession` at construction, they flush but **never commit** (the caller owns the transaction boundary), and they raise domain exceptions from `src.utils.exceptions` on failure.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports the 6 original repositories (`AccountRepository`, `BalanceRepository`, `OrderRepository`, `SnapshotRepository`, `TickRepository`, `TradeRepository`) |
| `account_repo.py` | CRUD for the `accounts` table -- create, lookup by ID/API key/email, update status and risk profile, list by status |
| `agent_repo.py` | CRUD for the `agents` table -- create, update fields, archive (soft delete), hard delete, lookup by ID/API key, list/count by account |
| `backtest_repo.py` | CRUD for `backtest_sessions`, `backtest_trades`, `backtest_snapshots` -- session lifecycle, bulk trade/snapshot persistence, analytics queries, cleanup |
| `balance_repo.py` | CRUD + atomic trade settlement for the `balances` table -- credit/debit available/locked columns, atomic lock/unlock funds, atomic buy/sell execution across two balance rows |
| `battle_repo.py` | CRUD for `battles`, `battle_participants`, `battle_snapshots` -- battle lifecycle, participant management, time-series snapshot storage |
| `order_repo.py` | CRUD for the `orders` table -- create, update status with extra fields, cancel (with state machine enforcement), list by account/agent/pending, keyset pagination |
| `snapshot_repo.py` | CRUD for the `portfolio_snapshots` hypertable -- create, time-range history queries, latest snapshot, pruning old data |
| `tick_repo.py` | **Read-only** repository for the `ticks` hypertable -- latest tick, time-range queries, price-at-time lookup, tick count, VWAP calculation |
| `trade_repo.py` | Insert + read for the `trades` table -- create, list by account/agent/symbol, daily trades, daily realized PnL aggregation |
| `strategy_repo.py` | CRUD for `strategies`, `strategy_versions`, `strategy_test_runs`, `strategy_test_episodes` -- strategy lifecycle, versioning, test runs, deploy/undeploy |
| `test_run_repo.py` | `TestRunRepository` (extends `StrategyRepository`) -- focused interface for test orchestrator and Celery tasks |
| `training_repo.py` | `TrainingRunRepository` -- CRUD for `training_runs` and `training_episodes`, episode tracking, run comparison |
| `waitlist_repo.py` | Single-method repository for the `waitlist_entries` table -- add email to waitlist with duplicate detection |
| `agent_api_call_repo.py` | `AgentApiCallRepository` -- insert and query `agent_api_calls` rows: bulk save, list by agent/trace_id, aggregate latency/cost stats |
| `agent_strategy_signal_repo.py` | `AgentStrategySignalRepository` -- insert and query `agent_strategy_signals` rows: bulk save, list by agent/source/action, daily attribution query |
| `agent_audit_log_repo.py` | `AgentAuditLogRepository` -- insert and query `agent_audit_log` rows: permission check outcomes (allow + deny), by agent/action/time range |

## Architecture & Patterns

### Session Injection
Every repository takes `AsyncSession` in `__init__` and stores it as `self._session`. Repositories are instantiated per-request via FastAPI dependency injection (`src/dependencies.py`).

### Transaction Ownership
Repositories **never call `session.commit()`**. They call `flush()` to obtain server-generated defaults (IDs, timestamps) and to detect constraint violations early, but the caller is responsible for committing. This allows multiple repository operations to participate in a single atomic transaction.

### Error Handling Pattern
All methods follow the same exception structure:
1. Catch domain-specific exceptions (e.g., `AccountNotFoundError`, `OrderNotFoundError`) and re-raise them.
2. Catch `IntegrityError` for constraint violations (unique keys, CHECK constraints, foreign keys) and translate to domain exceptions (`DuplicateAccountError`, `InsufficientBalanceError`).
3. Catch `SQLAlchemyError` as the broadest fallback and wrap in `DatabaseError`.
4. Rollback the session on write-path errors.

### Agent Scoping
Most repositories support dual scoping: legacy `account_id`-based queries and newer `agent_id`-based queries. The balance, order, and trade repos have dedicated `*_by_agent` methods. During the multi-agent transition, `agent_id` parameters are often `UUID | None`.

### Custom Exceptions Defined in Repos
- `agent_repo.py` defines `AgentNotFoundError` locally (not in `src/utils/exceptions.py`).
- `battle_repo.py` defines `BattleNotFoundError` locally.

### Keyset Pagination
`OrderRepository.list_pending()` uses keyset pagination (`WHERE id > after_id`) instead of OFFSET to avoid skipping rows during concurrent inserts. Other list methods use traditional OFFSET/LIMIT.

### Auto-Creation (Upsert-Style)
`BalanceRepository._get_or_create_zero()` creates a zero-balance row if one does not exist for an asset. Uses a savepoint (`begin_nested()`) to handle race conditions where a concurrent request creates the row first.

## Public API / Interfaces

### AccountRepository
- `create(account) -> Account` -- persist new account
- `update_risk_profile(account_id, profile)` -- update JSONB risk profile
- `update_status(account_id, status) -> Account` -- change account status
- `get_by_id(account_id) -> Account` -- lookup by UUID
- `get_by_api_key(api_key) -> Account` -- lookup by plaintext API key (O(1) via unique index)
- `get_by_email(email) -> Account` -- lookup by email (O(1) via unique index)
- `list_by_status(status, limit, offset) -> Sequence[Account]` -- paginated list filtered by status

### AgentRepository
- `create(agent) -> Agent` -- persist new agent
- `update(agent_id, **fields) -> Agent` -- update arbitrary fields via `setattr`
- `archive(agent_id) -> Agent` -- soft delete (sets status to "archived")
- `hard_delete(agent_id)` -- permanent deletion
- `get_by_id(agent_id) -> Agent` -- lookup by UUID
- `get_by_api_key(api_key) -> Agent` -- lookup by plaintext API key
- `list_by_account(account_id, include_archived, limit, offset) -> Sequence[Agent]` -- list with optional archived filter
- `count_by_account(account_id) -> int` -- count non-archived agents

### BacktestRepository
- `create_session(bt_session) -> BacktestSession` -- persist new session
- `get_session(session_id, account_id?, agent_id?) -> BacktestSession | None` -- lookup with optional scope filters
- `update_session(session_id, **fields)` -- update session fields (auto-sets `updated_at`)
- `list_sessions(account_id, agent_id?, strategy_label?, status?, sort_by, limit) -> Sequence[BacktestSession]` -- filtered listing with dynamic sort column
- `save_trades(session_id, trades)` -- bulk insert backtest trades
- `get_trades(session_id, limit, offset) -> Sequence[BacktestTrade]` -- ordered by `simulated_at`
- `save_snapshots(session_id, snapshots)` -- bulk insert equity snapshots
- `get_snapshots(session_id) -> Sequence[BacktestSnapshot]` -- all snapshots ordered by time
- `get_best_session(account_id, metric, strategy_label?, agent_id?) -> BacktestSession | None` -- best completed session by dynamic metric column
- `get_sessions_for_compare(session_ids, agent_id?) -> Sequence[BacktestSession]` -- multi-session comparison
- `delete_old_detail_data(days=90) -> int` -- prune trades/snapshots from completed sessions older than N days

### BalanceRepository
- `get(account_id, asset) -> Balance | None` -- single balance by account + asset
- `get_all(account_id) -> Sequence[Balance]` -- all balances for account (ordered by asset)
- `get_by_agent(agent_id, asset) -> Balance | None` -- single balance by agent + asset
- `get_all_by_agent(agent_id) -> Sequence[Balance]` -- all balances for agent
- `create(balance) -> Balance` -- persist new balance row
- `update_available(account_id, asset, delta) -> Balance` -- add/subtract from `available` column
- `update_available_by_agent(agent_id, asset, delta) -> Balance` -- agent-scoped variant
- `update_locked(account_id, asset, delta) -> Balance` -- add/subtract from `locked` column
- `atomic_lock_funds(account_id, asset, amount) -> Balance` -- move available -> locked in one UPDATE
- `atomic_unlock_funds(account_id, asset, amount) -> Balance` -- move locked -> available in one UPDATE
- `atomic_lock_funds_by_agent(agent_id, asset, amount) -> Balance` -- agent-scoped lock
- `atomic_unlock_funds_by_agent(agent_id, asset, amount) -> Balance` -- agent-scoped unlock
- `atomic_execute_buy(account_id, ..., agent_id?) -> (Balance, Balance)` -- settle a buy across quote + base balances
- `atomic_execute_sell(account_id, ..., agent_id?) -> (Balance, Balance)` -- settle a sell across base + quote balances

### BattleRepository
- `create_battle(battle) -> Battle` -- persist new battle
- `get_battle(battle_id) -> Battle` -- lookup by UUID (raises `BattleNotFoundError`)
- `list_battles(account_id, status?, limit, offset) -> Sequence[Battle]` -- filtered listing
- `update_status(battle_id, status, **extra_fields) -> Battle` -- update status + optional fields
- `update_battle(battle_id, **fields) -> Battle` -- update arbitrary fields
- `delete_battle(battle_id)` -- permanent delete with cascade
- `add_participant(participant) -> BattleParticipant` -- add agent to battle (enforces unique constraint `uq_bp_battle_agent`)
- `remove_participant(battle_id, agent_id)` -- remove agent from battle
- `get_participants(battle_id) -> Sequence[BattleParticipant]` -- list participants ordered by `joined_at`
- `get_participant(battle_id, agent_id) -> BattleParticipant` -- single participant lookup
- `update_participant(battle_id, agent_id, **fields) -> BattleParticipant` -- update participant fields
- `insert_snapshot(snapshot) -> BattleSnapshot` -- single snapshot insert
- `insert_snapshots_bulk(snapshots)` -- batch insert via `add_all`
- `get_snapshots(battle_id, agent_id?, since?, until?, limit, offset) -> Sequence[BattleSnapshot]` -- time-series query with filters
- `count_snapshots(battle_id) -> int` -- total snapshot count

### OrderRepository
- `create(order) -> Order` -- persist new order
- `update_status(order_id, status, extra_fields?) -> Order` -- transition order state with optional execution data
- `cancel(order_id, account_id) -> Order` -- cancel with ownership check and state machine enforcement (only `pending`/`partially_filled`)
- `get_by_id(order_id, account_id?) -> Order` -- lookup with optional ownership filter
- `list_by_account(account_id, agent_id?, status?, symbol?, limit, offset) -> Sequence[Order]` -- filtered list (newest first)
- `list_pending(symbol?, limit, after_id?) -> Sequence[Order]` -- keyset-paginated pending orders for the limit-order matcher
- `list_open_by_account(account_id, agent_id?, limit, offset) -> Sequence[Order]` -- pending + partially_filled
- `count_open_by_account(account_id) -> int` -- for risk manager's `max_open_orders` check
- `list_by_agent(agent_id, limit, offset) -> Sequence[Order]` -- agent-scoped listing
- `list_open_by_agent(agent_id) -> Sequence[Order]` -- agent-scoped open orders
- `count_open_by_agent(agent_id) -> int` -- agent-scoped open order count

### SnapshotRepository
- `create(snapshot) -> PortfolioSnapshot` -- persist new equity snapshot
- `get_history(account_id, snapshot_type, limit, since?, until?, agent_id?) -> Sequence[PortfolioSnapshot]` -- time-range query (newest first)
- `get_latest(account_id, snapshot_type) -> PortfolioSnapshot | None` -- most recent snapshot
- `list_by_account(account_id, limit, offset) -> Sequence[PortfolioSnapshot]` -- all types, paginated
- `delete_before(account_id, snapshot_type, cutoff) -> int` -- prune old snapshots

### TickRepository (read-only)
- `get_latest(symbol) -> Tick | None` -- most recent tick
- `get_range(symbol, since, until?, limit?) -> Sequence[Tick]` -- time-range ticks (oldest first)
- `get_price_at(symbol, at) -> Tick | None` -- last tick at or before a timestamp
- `count_in_range(symbol, since, until?) -> int` -- tick count for health checks
- `get_vwap(symbol, since, until?) -> Decimal | None` -- volume-weighted average price

### WaitlistRepository
- `create(email, source="landing") -> WaitlistEntry` -- add email to waitlist

## Dependencies

All repositories depend on:
- `sqlalchemy.ext.asyncio.AsyncSession` -- injected at construction
- `src.database.models` -- ORM model classes (`Account`, `Agent`, `Balance`, `Order`, `Trade`, `Tick`, `PortfolioSnapshot`, `BacktestSession`, `BacktestTrade`, `BacktestSnapshot`, `Battle`, `BattleParticipant`, `BattleSnapshot`, `WaitlistEntry`)
- `src.utils.exceptions` -- domain exception classes (`DatabaseError`, `AccountNotFoundError`, `InsufficientBalanceError`, `OrderNotFoundError`, `OrderNotCancellableError`, `TradeNotFoundError`, `DuplicateAccountError`)
- `structlog` -- structured logging

Repositories are instantiated by FastAPI dependency functions in `src/dependencies.py` and injected into route handlers via typed aliases (`AccountRepoDep`, `BalanceRepoDep`, `OrderRepoDep`, etc.).

## Common Tasks

### Adding a new repository

1. Create `src/database/repositories/new_model_repo.py` following the established pattern:
   - Import `AsyncSession`, `select`/`update`/`delete` from SQLAlchemy, `structlog`, your ORM model, and relevant exceptions.
   - Define the class with `__init__(self, session: AsyncSession)`.
   - Implement methods that flush but never commit.
   - Wrap all DB calls in `try/except SQLAlchemyError` with structured logging and `DatabaseError` re-raise.
   - Catch `IntegrityError` separately for constraint violations.
2. If the model needs a "not found" exception, either add it to `src/utils/exceptions.py` or define it locally in the repo module (current codebase has mixed approaches).
3. Add the new repository to `__init__.py` exports if it should be part of the public package API.
4. Create a FastAPI dependency function in `src/dependencies.py` and add a typed `Annotated` alias (e.g., `NewModelRepoDep`).
5. Write unit tests in `tests/unit/test_new_model_repo.py` using `AsyncMock` for the session.

### Adding a method to an existing repository

1. Follow the existing error-handling pattern for that repository (check how sibling methods handle exceptions).
2. Use `flush()` after writes; use `refresh()` only when you need server-generated values back.
3. Add `agent_id: UUID | None = None` as an optional filter parameter if the query should support agent scoping.
4. Add structured log events with the `logger.info()` / `logger.exception()` convention used in the file.

## Gotchas & Pitfalls

- **Never commit in a repository.** The caller (typically a service or route handler) owns the transaction boundary. Committing inside a repo method would break atomicity when multiple repo calls need to happen in a single transaction.
- **`__init__.py` is incomplete.** It only re-exports the 6 original repositories. `AgentRepository`, `BacktestRepository`, `BattleRepository`, and `WaitlistRepository` are **not** in `__all__` and must be imported directly from their modules.
- **`AgentNotFoundError` and `BattleNotFoundError` are defined locally** in their respective repo modules, not in `src/utils/exceptions.py`. If you need to catch these in service code, import from the repo module (e.g., `from src.database.repositories.agent_repo import AgentNotFoundError`).
- **`BalanceRepository` uses CHECK constraints** (`available >= 0`, `locked >= 0`) to enforce non-negative balances. An `IntegrityError` from these constraints is caught and re-raised as `InsufficientBalanceError`. Do not rely on application-level validation alone.
- **`BalanceRepository._get_or_create_zero()` uses savepoints** (`begin_nested()`) to handle race conditions. This means nested transactions are in play during `atomic_execute_buy` and `atomic_execute_sell`.
- **`TickRepository` is read-only.** Ticks are written by the price ingestion service via raw asyncpg `COPY`, bypassing SQLAlchemy entirely. There are no write methods in this repo.
- **Dynamic column sorting** in `BacktestRepository.list_sessions()` and `get_best_session()` uses `getattr(BacktestSession, sort_by)`. If an invalid column name is passed, it silently falls back to `created_at` or `roi_pct`. Validate sort column names at the API schema level.
- **`OrderRepository.list_pending()` uses keyset pagination** (`after_id`), while all other list methods use OFFSET. Do not mix pagination strategies on the same endpoint.
- **Agent-scoped balance operations** (`update_available_by_agent`, `atomic_lock_funds_by_agent`, etc.) filter by `agent_id` only, not `account_id + agent_id`. This is correct because `agent_id` is globally unique, but be aware that ownership checks happen upstream in the service layer.
- **Rollback on write errors.** Repos call `self._session.rollback()` on caught exceptions in write paths. This rolls back the entire session, not just the failed operation. If you need partial failure handling, use savepoints explicitly.

## Recent Changes

- `2026-03-21` — Added `AgentApiCallRepository` (`agent_api_call_repo.py`) and `AgentStrategySignalRepository` (`agent_strategy_signal_repo.py`) for the Agent Logging System. Both support bulk save (used by `LogBatchWriter`) and analytics queries (used by Celery attribution tasks).
- `2026-03-17` -- Initial CLAUDE.md created
