# Order Engine

<!-- last-updated: 2026-03-19 -->

> Handles order placement, execution, slippage simulation, limit/stop order matching, and pre-flight validation for the AI agent trading platform.

## What This Module Does

The order engine is the single authoritative path for placing, executing, and cancelling orders. It supports four order types (market, limit, stop_loss, take_profit), applies a size-proportional slippage model against real Binance volume data, manages fund locking for queued orders, maintains position tracking with weighted-average entry prices and realized PnL, and runs a background sweeper that matches pending orders against live Redis prices.

**Order lifecycle:**
1. Agent calls `OrderEngine.place_order()`.
2. `OrderValidator` runs pre-flight checks (side, type, quantity, price, symbol existence/active status, pair min_qty/min_notional).
3. Current price is fetched from Redis via `PriceCache`.
4. **Market orders**: slippage calculated, balances settled atomically via `BalanceManager`, Trade row created, Order set to `filled`, `OrderResult` returned immediately.
5. **Limit/stop_loss/take_profit orders**: required funds locked via `BalanceManager.lock()`, Order persisted as `pending`, `OrderResult` with `status="pending"` returned.
6. Background `LimitOrderMatcher` sweeps pending orders every 1s (via Celery beat), checks price conditions against Redis, and calls `OrderEngine.execute_pending_order()` when conditions are met.

## Key Files

| File | Purpose |
|------|---------|
| `engine.py` | `OrderEngine` class -- central coordinator for place, cancel, execute operations. `OrderResult` frozen dataclass. Position upsert logic (weighted-average entry, realized PnL). |
| `matching.py` | `LimitOrderMatcher` -- background sweeper with keyset pagination, per-order session isolation, exponential backoff on failures. `MatcherStats` dataclass. `run_matcher_once()` Celery entry point. |
| `slippage.py` | `SlippageCalculator` -- size-proportional slippage model using 24h Redis ticker volume. `SlippageResult` frozen dataclass. Includes 0.1% trading fee calculation. |
| `validators.py` | `OrderValidator` -- pre-flight validation chain (side, type, quantity, price, symbol/pair). `OrderRequest` lightweight descriptor class (not Pydantic). |
| `__init__.py` | Re-exports: `OrderEngine`, `OrderResult`, `LimitOrderMatcher`, `SlippageCalculator`, `OrderRequest`, `OrderValidator`. |

## Architecture & Patterns

- **Dependency injection**: `OrderEngine` takes all collaborators via constructor (session, price_cache, balance_manager, slippage_calculator, order_repo, trade_repo). No module-level singletons.
- **Per-request lifecycle**: A new `OrderEngine` and `OrderValidator` are created per request, sharing the same `AsyncSession`.
- **Transaction ownership**: `OrderEngine` owns the commit/rollback boundary. Each public method (`place_order`, `cancel_order`, `cancel_all_orders`, `execute_pending_order`) commits its own transaction.
- **Session isolation in matcher**: `LimitOrderMatcher` opens a fresh DB session per order execution so one failure never rolls back others.
- **Keyset pagination**: The matcher uses `WHERE id > last_seen_id` (not OFFSET) to avoid the shifting-offset problem when orders are inserted mid-sweep.
- **Fund locking**: Queued buy orders lock `quantity * limit_price * 1.001` (including 0.1% fee estimate) in the quote asset. Sell orders lock the base asset quantity. Cancellation mirrors this exactly.
- **Position tracking**: `_upsert_position()` maintains a single `Position` row per (account, symbol, agent). Buys recalculate weighted-average entry price using the fee-inclusive cost basis (`fill_qty * fill_price + fee`) so `avg_entry_price` represents the true per-unit cost. Sells compute net realized PnL as `(fill_price - avg_entry) * fill_qty - sell_fee`. Positions are zeroed out (not deleted) to preserve PnL history.

## Public API / Interfaces

### OrderEngine

```python
class OrderEngine:
    def __init__(self, session, price_cache, balance_manager, slippage_calculator, order_repo, trade_repo)
    async def place_order(self, account_id: UUID, order: OrderRequest, *, agent_id: UUID | None = None) -> OrderResult
    async def cancel_order(self, account_id: UUID, order_id: UUID, *, agent_id: UUID | None = None) -> bool
    async def cancel_all_orders(self, account_id: UUID, *, agent_id: UUID | None = None) -> int
    async def execute_pending_order(self, order_id: UUID, current_price: Decimal) -> OrderResult
```

### OrderResult

```python
@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: UUID
    status: str              # "filled", "pending", or "cancelled"
    executed_price: Decimal | None
    executed_quantity: Decimal | None
    slippage_pct: Decimal | None
    fee: Decimal | None
    timestamp: datetime
    rejection_reason: str | None = None
```

### OrderRequest

```python
class OrderRequest:
    symbol: str              # auto-uppercased
    side: str                # auto-lowercased ("buy" | "sell")
    type: str                # auto-lowercased ("market" | "limit" | "stop_loss" | "take_profit")
    quantity: Decimal
    price: Decimal | None    # required for limit/stop_loss/take_profit; None for market
```

### OrderValidator

```python
class OrderValidator:
    def __init__(self, session: AsyncSession)
    async def validate(self, order: OrderRequest) -> TradingPair  # returns pair metadata on success
```

### SlippageCalculator

```python
class SlippageCalculator:
    def __init__(self, price_cache: PriceCache, default_factor: Decimal = Decimal("0.1"))
    async def calculate(self, symbol: str, side: str, quantity: Decimal, reference_price: Decimal) -> SlippageResult
```

### LimitOrderMatcher

```python
class LimitOrderMatcher:
    def __init__(self, session_factory, price_cache, balance_manager_factory, slippage_calculator, page_size=500)
    async def check_all_pending(self) -> MatcherStats
    async def check_order(self, order: Order) -> OrderResult | None
    async def start(self, interval_seconds: float = 1.0) -> None  # dev loop; production uses Celery

async def run_matcher_once(session_factory, price_cache, settings) -> MatcherStats  # Celery entry point
```

### Matching Rules

| Order Type | Side | Condition |
|------------|------|-----------|
| `limit` | `buy` | `current_price <= order.price` |
| `limit` | `sell` | `current_price >= order.price` |
| `stop_loss` | any | `current_price <= order.price` |
| `take_profit` | any | `current_price >= order.price` |

### Slippage Formula

```
slippage_fraction = clamp(factor * order_size_usd / avg_daily_volume_usd, 0.0001, 0.10)
execution_price = reference_price * (1 + direction * slippage_fraction)
fee = order_size_usd * 0.001
```

- `direction`: +1 for buy, -1 for sell
- `factor`: default 0.1, from `settings.default_slippage_factor`
- Falls back to minimum slippage (0.01%) when Redis ticker volume is unavailable
- Fee is 0.1% of order notional (simulated Binance taker fee)

## Dependencies

**Upstream (this module depends on):**
- `src.cache.price_cache.PriceCache` -- live price and 24h ticker volume from Redis
- `src.accounts.balance_manager.BalanceManager` -- balance checks, trade settlement, fund locking/unlocking
- `src.database.repositories.order_repo.OrderRepository` -- Order CRUD, status updates, pending/open queries
- `src.database.repositories.trade_repo.TradeRepository` -- Trade row creation
- `src.database.models` -- `Order`, `Trade`, `Position`, `TradingPair` ORM models
- `src.config.Settings` -- `default_slippage_factor` setting
- `src.utils.exceptions` -- domain exceptions (`InsufficientBalanceError`, `PriceNotAvailableError`, etc.)

**Downstream (depends on this module):**
- `src.api.routes.trading` -- REST endpoints call `OrderEngine.place_order()` / `cancel_order()`
- `src.tasks.limit_order_monitor` -- Celery beat task calls `run_matcher_once()` every 1s
- `src.backtesting.sandbox` -- backtesting sandbox has its own in-memory order engine (does NOT use this module)
- `src.dependencies` -- FastAPI DI wiring (`OrderEngineDep`, `SlippageCalcDep`)

## Common Tasks

**Adding a new order type:**
1. Add the type string to `VALID_ORDER_TYPES` in `validators.py`.
2. If it requires a price, add it to `PRICE_REQUIRED_TYPES`.
3. Add the matching condition in `_condition_met()` in `matching.py`.
4. Handle any special execution logic in `OrderEngine.place_order()` (market-like vs queued).

**Changing the fee model:**
- `_FEE_FRACTION` in `slippage.py` controls the fee rate (currently `0.001` = 0.1%).
- Fee estimate for fund locking uses a hardcoded `Decimal("0.001")` in `engine.py` (`_place_queued_order` and `_release_locked_funds`). These must stay in sync.

**Adjusting slippage behavior:**
- `_MIN_SLIPPAGE_FRACTION` (0.01%) and `_MAX_SLIPPAGE_FRACTION` (10%) in `slippage.py` are the clamp bounds.
- `default_factor` is configurable via `Settings.default_slippage_factor`.

**Running the matcher standalone (dev):**
```python
await matcher.start(interval_seconds=1.0)  # loops forever with exponential backoff on errors
```

## Gotchas & Pitfalls

- **Fee fraction duplication**: The `0.001` fee fraction appears in three places: `_FEE_FRACTION` in `slippage.py`, and hardcoded `Decimal("0.001")` in `_place_queued_order()` and `_release_locked_funds()` in `engine.py`. Changing the fee requires updating all three.
- **Symbol parsing heuristic**: `_base_asset_from_order()` and `_quote_asset_from_order()` in `engine.py` strip known suffixes (`USDT`, `BTC`, `ETH`, `BNB`). Non-standard quote assets will fall through to a 4-char strip or default to `"USDT"`. These are only used in `execute_pending_order()` where the `TradingPair` object is not available.
- **OrderRequest is not Pydantic**: `OrderRequest` in `validators.py` is a plain `__slots__` class, not a Pydantic model. The API layer's Pydantic schema is separate (`src.api.schemas`). Do not confuse the two.
- **Validator returns TradingPair**: `OrderValidator.validate()` returns the `TradingPair` ORM object (not `None`). Callers should use it for `base_asset`/`quote_asset` to avoid the symbol-parsing heuristic.
- **Position zeroing**: Selling more than the held quantity clamps to zero (not negative). No short selling is supported.
- **agent_id is optional**: All public methods accept `agent_id: UUID | None = None` for backward compatibility during migration. When `None`, positions are scoped by `(account_id, symbol)` only.
- **Matcher page size**: Default 500 rows per page. If the platform has thousands of pending orders, the sweep may take multiple pages. Keyset pagination ensures correctness even if new orders arrive mid-sweep.
- **Matcher backoff**: The `start()` loop uses exponential backoff (1s, 2s, 4s... capped at 60s) on unhandled errors. Consecutive failure count resets after any successful sweep.

## Recent Changes

- `2026-04-01` (BUG-011) -- Fixed `realized_pnl` calculation in `_upsert_position()`. Buy fills now include the trading fee in `total_cost` so `avg_entry_price` is the true fee-inclusive cost basis. Sell fills now subtract the sell fee from `realised_increment` before setting `trade.realized_pnl`. This ensures win/loss classification in `PerformanceMetrics` reflects true economic P&L, not just gross price movement. Both callers (`execute_pending_order` and `_execute_market_order`) pass `settlement.fee_charged` to `_upsert_position`.
- `2026-03-17` -- Initial CLAUDE.md created
