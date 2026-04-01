# Accounts Module

<!-- last-updated: 2026-04-01 -->

> Authentication, balance management, and account lifecycle for the AI trading platform.

## What This Module Does

This module handles three core responsibilities: (1) cryptographic operations for API key generation, password hashing, and JWT token management; (2) all balance mutations including credit, debit, lock/unlock for limit orders, and atomic trade settlement with fee calculation; (3) account lifecycle operations such as registration, authentication (API key and password), account reset, and suspend/unsuspend. All operations are transaction-safe and never call `session.commit()` themselves -- the caller controls the transaction boundary.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Module docstring only; no re-exports |
| `auth.py` | API key/secret generation (`ak_live_`/`sk_live_` prefixes), bcrypt hashing (12 rounds), password verify, HS256 JWT create/verify |
| `balance_manager.py` | `BalanceManager` -- single entry-point for all balance mutations: credit, debit, lock, unlock, pre-flight checks, atomic buy/sell settlement with fee deduction |
| `service.py` | `AccountService` -- registration (atomic: Account + TradingSession + credentials), API key auth, password auth, get/list accounts, reset, suspend/unsuspend |

## Architecture & Patterns

- **Thread-pool offloading**: All bcrypt operations (CPU-bound) are dispatched via `asyncio.get_event_loop().run_in_executor(None, ...)` to avoid blocking the event loop.
- **Transaction participation**: Neither `BalanceManager` nor `AccountService` calls `session.commit()`. They participate in the caller's transaction, enabling composition of multiple operations atomically.
- **Agent-scoped balances**: All `BalanceManager` methods accept an optional `agent_id: UUID | None` parameter. When provided, they delegate to agent-scoped repository methods (`get_by_agent`, `update_available_by_agent`, etc.). When `None`, they fall back to legacy account-scoped methods.
- **Frozen dataclasses with slots**: Return types (`ApiCredentials`, `JwtPayload`, `TradeSettlement`, `AccountCredentials`) are immutable `@dataclass(frozen=True, slots=True)` for safety and performance.
- **Dependency direction**: `Routes -> AccountService/BalanceManager -> AccountRepository/BalanceRepository -> DB models`

## Public API / Interfaces

### `auth.py` — Stateless Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `generate_api_credentials()` | `-> ApiCredentials` | Fresh `ak_live_`/`sk_live_` pair with bcrypt hashes |
| `hash_password(plaintext)` | `-> str` | Bcrypt hash for user passwords (12 rounds) |
| `verify_password(plaintext, stored_hash)` | `-> bool` | Check password against stored bcrypt hash |
| `verify_api_key(plaintext, stored_hash)` | `-> bool` | Check API key against stored bcrypt hash |
| `verify_api_secret(plaintext, stored_hash)` | `-> bool` | Check API secret for HMAC-signed requests |
| `create_jwt(account_id, jwt_secret, expiry_hours=1)` | `-> str` | HS256 JWT with `sub`, `iat`, `exp` claims |
| `verify_jwt(token, jwt_secret)` | `-> JwtPayload` | Decode/verify JWT; raises `InvalidTokenError` on failure |
| `authenticate_api_key(raw_key, stored_hash)` | `-> None` | Verify key format + bcrypt hash; raises `AuthenticationError` |

### `balance_manager.py` — `BalanceManager`

| Method | Purpose |
|--------|---------|
| `credit(account_id, asset, amount, agent_id=None)` | Add to available balance |
| `debit(account_id, asset, amount, agent_id=None)` | Subtract from available balance |
| `lock(account_id, asset, amount, agent_id=None)` | Move available -> locked (limit order reserve) |
| `unlock(account_id, asset, amount, agent_id=None)` | Move locked -> available (order cancellation) |
| `has_sufficient_balance(account_id, asset, amount, use_locked=False, agent_id=None)` | Non-mutating pre-flight check |
| `get_balance(account_id, asset, agent_id=None)` | Single balance row or `None` |
| `get_all_balances(account_id, agent_id=None)` | All balance rows for account/agent |
| `execute_trade(account_id, symbol, side, base_asset, quote_asset, quantity, execution_price, from_locked=False, agent_id=None)` | Atomic buy/sell settlement with fee deduction; returns `TradeSettlement` |

### `service.py` — `AccountService`

| Method | Purpose |
|--------|---------|
| `register(display_name, email=None, starting_balance=None, password=None)` | Registration: Account + credentials only (does NOT create TradingSession — agent_id required for that) |
| `authenticate(api_key)` | API key auth; checks active status |
| `authenticate_with_password(email, password)` | Email/password auth; checks active status |
| `get_account(account_id)` | Fetch account by UUID |
| `list_accounts(status="active", limit=100, offset=0)` | Paginated account list |
| `reset_account(account_id)` | Cancel pending orders, close session, wipe balances, re-credit starting USDT, open new session |
| `suspend_account(account_id)` | Set status to "suspended" |
| `unsuspend_account(account_id)` | Set status back to "active" |

## Dependencies

### This module depends on
- `src.config.Settings` -- `trading_fee_pct`, `default_starting_balance`, `jwt_secret`
- `src.database.models` -- `Account`, `Balance`, `Order`, `TradingSession`
- `src.database.repositories.account_repo.AccountRepository` -- account CRUD
- `src.database.repositories.balance_repo.BalanceRepository` -- balance CRUD, atomic lock/unlock/buy/sell
- `src.utils.exceptions` -- `AuthenticationError`, `InvalidTokenError`, `InsufficientBalanceError`, `DatabaseError`, `AccountNotFoundError`, `AccountSuspendedError`, `DuplicateAccountError`, `InputValidationError`
- Third-party: `bcrypt`, `PyJWT`, `sqlalchemy`, `structlog`

### What depends on this module
- `src.api.routes` -- auth endpoints, account endpoints
- `src.api.middleware.auth` -- `AuthMiddleware` uses `auth.verify_jwt` and `AccountService.authenticate`
- `src.order_engine` -- `BalanceManager` for trade settlement
- `src.risk` -- `BalanceManager.has_sufficient_balance` for pre-flight checks
- `src.agents.service` -- `AccountService` for account lookups during agent creation
- `src.portfolio` -- `BalanceManager` for balance reads
- `src.dependencies` -- wires `BalanceManagerDep`, `AccountServiceDep` via FastAPI `Depends()`

## Common Tasks

### Adding a new balance operation
1. Add the method to `BalanceManager` with both `account_id` and optional `agent_id` parameters.
2. Delegate to the appropriate `BalanceRepository` method (create one if needed).
3. Validate inputs (amount > 0) and raise `InputValidationError` for bad input.
4. Add structured logging with `structlog`.
5. Never call `session.commit()` -- let the caller handle it.

### Adding a new auth mechanism
1. Add the cryptographic helper as a stateless function in `auth.py`.
2. If CPU-bound, document that callers must use `run_in_executor`.
3. Add it to the `__all__` list in `auth.py`.
4. Wire it into `AccountService` if it needs DB access.

### Adding a new account lifecycle operation
1. Add the method to `AccountService`.
2. Wrap DB operations in `try/except SQLAlchemyError` and raise `DatabaseError`.
3. Call `self._session.rollback()` on unexpected errors.
4. Add structured logging with account_id context.

## Gotchas & Pitfalls

- **CPU-bound bcrypt in async context**: All bcrypt calls (`generate_api_credentials`, `hash_password`, `verify_password`, `authenticate_api_key`) MUST be offloaded to a thread pool via `run_in_executor`. Calling them directly in an async handler will block the event loop.
- **API key stored in plaintext**: The `api_key` column stores the plaintext key for O(1) lookup. The `api_key_hash` column stores the bcrypt hash for verification. The `api_secret` is NEVER stored -- only its hash.
- **Fee calculation precision**: Fees are quantized to 8 decimal places (`Decimal("0.00000001")`) to match the `NUMERIC(20,8)` column type. Using `float` anywhere in this chain will introduce rounding errors.
- **`execute_trade` sell guard**: If the fee exceeds gross proceeds on a sell, the method raises `InputValidationError` rather than crediting a negative amount.
- **`reset_account` cancels pending orders**: The reset flow cancels all `pending` and `partially_filled` orders before wiping balances. Without this, the Celery `LimitOrderMonitor` could execute stale orders against the freshly-credited balance.
- **Balance row auto-creation**: The `BalanceRepository` auto-creates a zero-balance row if one doesn't exist when `credit` is called. But `debit`/`lock` on a non-existent row will fail.
- **`lru_cache` on `get_settings()`**: In tests, you must patch `src.config.get_settings` BEFORE the cached instance is created, or the real config will be used.
- **Agent ID transition**: All `BalanceManager` methods have `agent_id=None` as optional. When `None`, they use legacy `account_id`-scoped repo methods. New code should always pass `agent_id`.
- **Registration no longer creates balances**: `AccountService.register()` does NOT create the initial USDT balance row. Balance creation is handled by `AgentService.create_agent()`, which creates agent-scoped balances (`Balance.agent_id` is NOT NULL).
- **Registration does NOT create TradingSession**: As of 2026-04-01, `register()` no longer creates a `TradingSession`. `TradingSession.agent_id` is `NOT NULL`, but registration has no `agent_id` yet. Creating it in `register()` caused every registration to fail with `IntegrityError` (misreported as `DuplicateAccountError`). TradingSession is created later, when an agent is assigned.

## Recent Changes

- `2026-04-01` -- Removed TradingSession creation from `register()` to fix registration IntegrityError bug; updated `register()` docstring/signature entry above
- `2026-03-17` -- Initial CLAUDE.md created
