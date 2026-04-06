# Risk Management

<!-- last-updated: 2026-04-02 -->

> Enforces trading limits and daily-loss circuit-breaker logic to prevent agents from unrealistic or destructive trading behaviour.

## What This Module Does

Every order placed through the Order Engine passes through an 8-step validation chain in `RiskManager.validate_order()` before execution. The chain short-circuits on the first failure, returning a machine-readable rejection code. Separately, `CircuitBreaker` tracks daily realized PnL per account/agent in Redis and halts trading when cumulative losses exceed a configurable threshold.

The two classes are read-only with respect to balances and orders -- they never mutate trading state. `RiskManager` reads account data, balances, open-order counts, daily PnL, and current prices. `CircuitBreaker` reads and writes only its own Redis hash keys.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports `RiskManager`, `RiskLimits`, `RiskCheckResult`, `CircuitBreaker` |
| `manager.py` | `RiskManager` class -- 8-step order validation chain, risk limit merging, equity computation |
| `circuit_breaker.py` | `CircuitBreaker` class -- Redis-backed daily PnL tracker with auto-trip and midnight TTL |

## Architecture & Patterns

### 8-Step Validation Chain (`RiskManager.validate_order`)

| Step | Check | Rejection Code |
|------|-------|----------------|
| 1 | Account is active (not suspended/archived) | `account_not_active` |
| 2 | Daily realized PnL within loss limit | `daily_loss_limit` |
| 3 | Order rate limit not exceeded (Redis sliding window) | `rate_limit_exceeded` |
| 4 | Order value >= minimum USD threshold | `order_too_small` |
| 5 | Order value <= max % of total portfolio equity | `order_too_large` |
| 6 | Resulting position <= max % of total equity | `position_limit_exceeded` |
| 7 | Open order count < maximum | `max_open_orders_exceeded` |
| 8 | Sufficient balance (USDT for buys, base asset for sells) | `insufficient_balance` |

The chain fetches the current price once and computes total equity once, reusing both across steps 4-8 to minimize DB/cache round-trips.

Rate-limit tokens are consumed only after all 8 checks pass -- rejected orders do not count against the rate limit.

### Default Risk Limits

| Limit | Default | Description |
|-------|---------|-------------|
| `max_position_size_pct` | 25% | Single position max % of total equity |
| `max_open_orders` | 50 | Max concurrent pending orders |
| `daily_loss_limit_pct` | 20% | Halt if daily loss > % of starting balance |
| `min_order_size_usd` | $1.00 | Minimum order value |
| `max_order_size_pct` | 50% | Single order max % of total equity |
| `order_rate_limit` | 100 | Max orders per minute |

Defaults are overridden per-account via the `risk_profile` JSONB column on `accounts`, or per-agent via the `risk_profile` JSONB on `agents`. Agent profile takes precedence over account profile when present.

### Circuit Breaker Redis Schema

Each account gets a Redis hash at `circuit_breaker:{account_id}`:
- `daily_pnl` -- running sum of realized PnL (Decimal string)
- `tripped` -- `"1"` when breaker is tripped
- `tripped_at` -- ISO-8601 timestamp of trip event

Keys auto-expire at midnight UTC via TTL set on every write. A Celery beat task calls `reset_all()` at 00:00 UTC as a belt-and-suspenders cleanup using batched `SCAN` (1000 keys per page).

### Risk Limit Merging

`_build_risk_limits()` merges platform defaults with per-account or per-agent overrides. Invalid profile values (unparseable strings) fall back to defaults with a warning log -- they never crash the validation chain.

### Total Equity Computation

`_compute_total_equity()` sums USDT balance + all non-USDT holdings priced via `PriceCache`. Assets whose price cannot be resolved are excluded (conservative: lower equity means stricter limits, never looser). Steps 5 and 6 both use this value.

## Public API / Interfaces

### `RiskManager`

```python
# Constructor
RiskManager(
    redis, price_cache, balance_manager,
    account_repo, order_repo, trade_repo, settings
)

# Primary method -- called by OrderEngine before every order
await manager.validate_order(account_id, order, agent=None) -> RiskCheckResult

# Standalone daily-loss check
await manager.check_daily_loss(account_id, agent=None) -> bool

# Read/write effective limits
await manager.get_risk_limits(account_id, agent=None) -> RiskLimits
await manager.update_risk_limits(account_id, limits) -> None
```

### `RiskCheckResult`

```python
RiskCheckResult(approved=True)                         # all checks passed
RiskCheckResult(approved=False, rejection_reason="..") # first failure
RiskCheckResult.ok()                                   # factory for approved
RiskCheckResult.reject("reason", key=value)            # factory for rejected
```

### `RiskLimits`

Frozen dataclass with six fields. Constructed by `_build_risk_limits()` from account/agent `risk_profile` JSONB merged with platform defaults.

### `CircuitBreaker`

```python
CircuitBreaker(redis=redis_client)

await cb.record_trade_pnl(account_id, pnl, starting_balance=..., daily_loss_limit_pct=...)
await cb.is_tripped(account_id) -> bool
await cb.get_daily_pnl(account_id) -> Decimal
await cb.reset_all()  # deletes all circuit_breaker:* keys
```

## Dependencies

**Upstream (this module depends on):**
- `src.cache.price_cache.PriceCache` -- live prices for equity computation and order valuation
- `src.accounts.balance_manager.BalanceManager` -- balance reads (available, locked)
- `src.database.repositories.account_repo.AccountRepository` -- account status and `risk_profile`
- `src.database.repositories.order_repo.OrderRepository` -- open order counts
- `src.database.repositories.trade_repo.TradeRepository` -- daily realized PnL sum
- `src.config.Settings` -- `trading_fee_pct` for balance check fee buffer
- `src.order_engine.validators.OrderRequest` -- validated order input
- `src.database.models.Account`, `Agent` -- account/agent models
- `redis.asyncio` -- rate limiting (RiskManager) and PnL tracking (CircuitBreaker)

**Downstream (depends on this module):**
- `src.order_engine` -- calls `validate_order()` before every execution
- `src.dependencies` -- wires `RiskManager` via `get_risk_manager()`
- `src.backtesting.sandbox` -- enforces a subset of risk limits (`max_order_size_pct`, `max_position_size_pct`, `daily_loss_limit_pct`) independently via `_check_risk_limits()`

## Common Tasks

**Adding a new risk check:** Add a private `_check_*` method, call it in `validate_order()` at the appropriate position in the chain, and add a corresponding rejection code string. Update `RiskCheckResult` docstring with the new code.

**Changing a default limit:** Update the `_DEFAULT_*` module-level constant in `manager.py`. Existing accounts with explicit overrides in `risk_profile` will not be affected.

**Per-agent risk profiles:** Set `risk_profile` JSONB on the `agents` table row. The keys match the `RiskLimits` field names (e.g., `"max_open_orders": 20`). Agent profiles fully override account profiles when present.

**Testing:** Mock `redis`, `price_cache`, `balance_manager`, and all repo dependencies. The `RiskCheckResult.reject()`/`.ok()` factories make assertion easy. For CircuitBreaker, mock the Redis pipeline's `__aenter__`/`__aexit__`.

## Gotchas & Pitfalls

- **Rate-limit token is consumed last:** The Redis INCR for rate limiting happens only after all 8 checks pass. If you add a check after step 3, rejected orders still will not consume tokens (this is intentional).
- **Sell orders skip position-limit check:** Step 6 returns `ok()` immediately for sells since selling shrinks the position. Do not change this without considering short-selling implications.
- **CircuitBreaker uses `hincrbyfloat`:** Redis `HINCRBYFLOAT` operates on floats internally, which introduces minor precision drift. The result is quantized to 8 decimal places on read. This is acceptable for a safety threshold but not for exact accounting.
- **`price_unavailable` rejection:** If `PriceCache` returns `None` for the order's symbol, the order is rejected conservatively. This can happen during startup before the first price tick arrives.
- **Equity computation excludes unpriced assets:** Assets without a price in the cache are omitted from total equity. This makes limits stricter (lower equity denominator), never looser.
- **`CircuitBreaker` is not account-scoped in constructor:** A single instance serves all accounts. The per-account state lives entirely in Redis hashes. Do not try to make it a singleton-per-account.
- **BacktestSandbox has its own risk enforcement:** The sandbox in `src/backtesting/sandbox.py` implements `_check_risk_limits()` independently using the same limit keys but without Redis or live services. Changes to risk logic here do not automatically propagate to the sandbox.

## Recent Changes

- `2026-04-02` (BUG-016) — `manager.py`: Step 6 (`position_limit_exceeded`) rejection message now includes the full calculation: current position value, projected position value, max allowed value (% of equity), and current total equity. Previously returned a bare rejection code with no numbers, making it hard for agents to calibrate order sizes.
- `2026-03-17` -- Initial CLAUDE.md created
