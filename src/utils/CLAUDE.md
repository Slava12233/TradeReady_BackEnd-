# Utils Module

<!-- last-updated: 2026-03-20 -->

> Shared exception hierarchy and utility functions used across the entire platform.

## What This Module Does

Provides two core pieces of infrastructure that every other module depends on:

1. **Exception hierarchy** (`exceptions.py`) -- A single base class `TradingPlatformError` with ~27 domain-specific subclasses. Each exception carries a machine-readable `code`, an HTTP status, and an optional `details` dict. The global exception handler in `src/main.py` catches `TradingPlatformError` and auto-serializes it to the standard `{"error": {"code": ..., "message": ..., "details": ...}}` JSON envelope.

2. **Helper functions** (`helpers.py`) -- Small, stateless utilities for time, pagination, decimal formatting, and symbol parsing that are used across services, repositories, and API routes.

## Key Files

| File | Purpose |
|------|---------|
| `exceptions.py` | Exception hierarchy: base `TradingPlatformError` + all domain subclasses |
| `helpers.py` | Shared utility functions: `utc_now`, `parse_period`, `paginate`, `format_decimal`, `symbol_to_base_quote`, `clamp`, `parse_interval` |
| `__init__.py` | Empty (no re-exports; consumers import from submodules directly) |

## Architecture & Patterns

### Exception hierarchy

```
TradingPlatformError (500)
  |
  +-- Auth (4xx)
  |     AuthenticationError (401, INVALID_API_KEY)
  |     InvalidTokenError (401, INVALID_TOKEN)
  |     AccountSuspendedError (403, ACCOUNT_SUSPENDED)
  |     PermissionDeniedError (403, PERMISSION_DENIED)
  |
  +-- Rate limiting
  |     RateLimitExceededError (429, RATE_LIMIT_EXCEEDED)
  |
  +-- Balance
  |     InsufficientBalanceError (400, INSUFFICIENT_BALANCE)
  |
  +-- Orders
  |     OrderRejectedError (400, ORDER_REJECTED)
  |     InvalidOrderTypeError (400, INVALID_ORDER_TYPE)
  |     InvalidQuantityError (400, INVALID_QUANTITY)
  |     OrderNotFoundError (404, ORDER_NOT_FOUND)
  |     OrderNotCancellableError (400, ORDER_NOT_CANCELLABLE)
  |     TradeNotFoundError (404, TRADE_NOT_FOUND)
  |
  +-- Market
  |     InvalidSymbolError (400, INVALID_SYMBOL)
  |     PriceNotAvailableError (503, PRICE_NOT_AVAILABLE)
  |
  +-- Risk
  |     RiskLimitExceededError (400, RISK_LIMIT_EXCEEDED)
  |     DailyLossLimitError (403, DAILY_LOSS_LIMIT)
  |
  +-- Accounts
  |     AccountNotFoundError (404, ACCOUNT_NOT_FOUND)
  |     DuplicateAccountError (409, DUPLICATE_ACCOUNT)
  |
  +-- Validation
  |     InputValidationError (422, VALIDATION_ERROR)
  |
  +-- Infrastructure
  |     DatabaseError (500, DATABASE_ERROR)
  |     CacheError (500, CACHE_ERROR)
  |     ServiceUnavailableError (503, SERVICE_UNAVAILABLE)
  |
  +-- Backtesting
  |     BacktestNotFoundError (404, BACKTEST_NOT_FOUND)
  |     BacktestInvalidStateError (409, BACKTEST_INVALID_STATE)
  |     BacktestNoDataError (400, BACKTEST_NO_DATA)
  |
  +-- Battles
  |     BattleNotFoundError (404, BATTLE_NOT_FOUND)
  |     BattleInvalidStateError (409, BATTLE_INVALID_STATE)
  |
  +-- Strategies
  |     StrategyNotFoundError (404, STRATEGY_NOT_FOUND)
  |     StrategyInvalidStateError (409, STRATEGY_INVALID_STATE)
  |
  +-- Training
        TrainingRunNotFoundError (404, TRAINING_RUN_NOT_FOUND)
```

### Exception design conventions

- `code` and `http_status` are **class-level defaults** that subclasses override. They can also be overridden per-instance via constructor kwargs.
- `details` is always a `dict[str, Any]` (never `None` on the instance). Subclass constructors build it from domain-specific kwargs (e.g., `asset`, `required`, `available` for `InsufficientBalanceError`).
- `.to_dict()` returns the standard API error envelope: `{"error": {"code": ..., "message": ..., "details": ...}}`.
- Raise the **most specific** subclass; never raise `TradingPlatformError` directly in application code.

### Helpers design conventions

- All helpers are **pure functions** (no side effects, no state).
- Lazy imports of `InputValidationError` inside `parse_period`, `paginate`, and `clamp` to avoid any circular import risk (same package but belt-and-suspenders).
- `_KNOWN_QUOTES` and `_PERIOD_DAYS` are module-level constants to avoid re-allocation on every call.

## Public API / Interfaces

### exceptions.py

| Class | Code | HTTP | Key kwargs |
|-------|------|------|------------|
| `TradingPlatformError` | `INTERNAL_ERROR` | 500 | `message`, `code`, `http_status`, `details` |
| `AuthenticationError` | `INVALID_API_KEY` | 401 | `details` |
| `InvalidTokenError` | `INVALID_TOKEN` | 401 | -- |
| `AccountSuspendedError` | `ACCOUNT_SUSPENDED` | 403 | `account_id` |
| `PermissionDeniedError` | `PERMISSION_DENIED` | 403 | `details` |
| `RateLimitExceededError` | `RATE_LIMIT_EXCEEDED` | 429 | `limit`, `window_seconds`, `retry_after` |
| `InsufficientBalanceError` | `INSUFFICIENT_BALANCE` | 400 | `asset`, `required`, `available` |
| `OrderRejectedError` | `ORDER_REJECTED` | 400 | `reason` |
| `InvalidOrderTypeError` | `INVALID_ORDER_TYPE` | 400 | `order_type` |
| `InvalidQuantityError` | `INVALID_QUANTITY` | 400 | `quantity`, `min_qty`, `max_qty` |
| `OrderNotFoundError` | `ORDER_NOT_FOUND` | 404 | `order_id` |
| `OrderNotCancellableError` | `ORDER_NOT_CANCELLABLE` | 400 | `order_id`, `current_status` |
| `TradeNotFoundError` | `TRADE_NOT_FOUND` | 404 | `trade_id` |
| `InvalidSymbolError` | `INVALID_SYMBOL` | 400 | `symbol` |
| `PriceNotAvailableError` | `PRICE_NOT_AVAILABLE` | 503 | `symbol` |
| `RiskLimitExceededError` | `RISK_LIMIT_EXCEEDED` | 400 | `limit_type`, `current_value`, `max_value` |
| `DailyLossLimitError` | `DAILY_LOSS_LIMIT` | 403 | `account_id`, `daily_pnl`, `loss_limit_pct` |
| `AccountNotFoundError` | `ACCOUNT_NOT_FOUND` | 404 | `account_id` |
| `DuplicateAccountError` | `DUPLICATE_ACCOUNT` | 409 | `email` |
| `InputValidationError` | `VALIDATION_ERROR` | 422 | `field`, `details` |
| `DatabaseError` | `DATABASE_ERROR` | 500 | `details` |
| `CacheError` | `CACHE_ERROR` | 500 | `details` |
| `ServiceUnavailableError` | `SERVICE_UNAVAILABLE` | 503 | `details` |
| `BacktestNotFoundError` | `BACKTEST_NOT_FOUND` | 404 | `session_id` |
| `BacktestInvalidStateError` | `BACKTEST_INVALID_STATE` | 409 | `current_status`, `required_status` |
| `BacktestNoDataError` | `BACKTEST_NO_DATA` | 400 | `details` |
| `BattleNotFoundError` | `BATTLE_NOT_FOUND` | 404 | `battle_id` |
| `BattleInvalidStateError` | `BATTLE_INVALID_STATE` | 409 | `current_status`, `required_status` |
| `StrategyNotFoundError` | `STRATEGY_NOT_FOUND` | 404 | `strategy_id` |
| `StrategyInvalidStateError` | `STRATEGY_INVALID_STATE` | 409 | `current_status`, `required_status` |
| `TrainingRunNotFoundError` | `TRAINING_RUN_NOT_FOUND` | 404 | `run_id` |

### helpers.py

| Function | Signature | Returns |
|----------|-----------|---------|
| `utc_now()` | `() -> datetime` | Timezone-aware UTC datetime |
| `parse_period(period)` | `(str) -> timedelta \| None` | `timedelta` for bounded periods, `None` for `"all"` |
| `period_to_since(period)` | `(str) -> datetime \| None` | Absolute UTC start-of-window, or `None` for `"all"` |
| `paginate(stmt, *, limit, offset)` | `(Select, int, int) -> Select` | Statement with `.limit()` and `.offset()` applied |
| `format_decimal(value, places=8)` | `(Decimal, int) -> str` | String with `ROUND_HALF_UP`, e.g. `"1.23456789"` |
| `symbol_to_base_quote(symbol)` | `(str) -> tuple[str, str]` | `("BTC", "USDT")` from `"BTCUSDT"` |
| `clamp(value, lo, hi)` | `(Decimal, Decimal, Decimal) -> Decimal` | Value clamped to `[lo, hi]` |
| `parse_interval(interval)` | `(str \| int) -> int` | Normalise a candle interval to seconds; accepts `"1h"`, `"5m"`, `3600`, `"3600"`; raises `InputValidationError` on unknown strings |

## Dependencies

- **Standard library only**: `datetime`, `decimal`, `typing`, `uuid`
- **SQLAlchemy** (TYPE_CHECKING only in `helpers.py` for the `Select` type hint)
- No external runtime dependencies -- this module sits at the bottom of the import graph

## Common Tasks

### Adding a new exception

1. Pick the correct category section in `exceptions.py` (auth, order, market, risk, etc.)
2. Subclass `TradingPlatformError` and set `code` and `http_status` as class attributes
3. Accept domain-specific kwargs in `__init__` and build a `details` dict from them
4. Add the class name to the `__all__` list
5. No registration needed -- the global exception handler in `src/main.py` catches all `TradingPlatformError` subclasses automatically

### Adding a new helper

1. Add the function to `helpers.py`
2. Keep it pure (no I/O, no state)
3. Use lazy imports for anything from `src.utils.exceptions` to avoid circular imports
4. Add a Google-style docstring with Args/Returns/Raises/Example sections

## Gotchas & Pitfalls

- **`__all__` is defined before the Battle exceptions** at the bottom of `exceptions.py`. The battle classes are listed in `__all__` but defined after it. This works in Python but can confuse readers -- if adding new exceptions, place them in the correct category section and ensure they appear in `__all__`.
- **Lazy imports in helpers**: `parse_period`, `paginate`, and `clamp` import `InputValidationError` inside the function body. This is intentional to prevent any circular import risk. Do not move these to module level.
- **`symbol_to_base_quote` fallback**: If no known quote suffix matches, it splits the symbol at the midpoint. This can produce wrong results for unusual symbols -- only Binance USDT-pair symbols are reliably supported.
- **`format_decimal` uses `ROUND_HALF_UP`**: This is standard financial rounding, not Python's default `ROUND_HALF_EVEN` (banker's rounding). Do not change this without understanding the downstream impact on balance calculations.
- **`parse_period` raises `InputValidationError`** (HTTP 422) for unknown period strings -- callers should not catch and silently default.

## Recent Changes

- `2026-03-20` -- Added `parse_interval()` to `helpers.py`; normalises backtest interval parameter to seconds, accepting both string shorthand (`"1h"`, `"5m"`) and integer/string-integer forms. Used by `src/api/routes/backtest.py`.
- `2026-03-18` -- Added StrategyNotFoundError, StrategyInvalidStateError, TrainingRunNotFoundError to exception hierarchy and public API table
- `2026-03-17` -- Initial CLAUDE.md created
