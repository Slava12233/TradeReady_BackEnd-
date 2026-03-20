# Portfolio Module

<!-- last-updated: 2026-03-19 -->

> Real-time portfolio valuation, PnL calculation, performance metrics, and periodic snapshot capture for AI trading agents.

## What This Module Does

This module (Component 6) provides three core capabilities:

1. **Portfolio Tracking** (`tracker.py`) -- Combines live Redis prices with DB position/balance data to produce on-demand equity snapshots, position valuations, and PnL breakdowns for any account or agent.

2. **Performance Metrics** (`metrics.py`) -- Computes advanced trading analytics (Sharpe, Sortino, max drawdown, win rate, profit factor, streaks) from trade history and equity-curve snapshots. All heavy computation is pure (no I/O) after the initial data load.

3. **Snapshot Capture** (`snapshots.py`) -- Periodic background service that persists portfolio state at three granularities (minute, hourly, daily) into a TimescaleDB hypertable for charting and historical analysis.

## Key Files

| File | Purpose |
|------|---------|
| `tracker.py` | `PortfolioTracker` service -- real-time equity, position valuation, PnL breakdown. Dataclasses: `PositionView`, `PnLBreakdown`, `PortfolioSummary`. |
| `metrics.py` | `PerformanceMetrics` service -- Sharpe, Sortino, drawdown, win rate, profit factor, streak. Dataclass: `Metrics`. Pure computation helpers at module level. |
| `snapshots.py` | `SnapshotService` -- captures minute/hourly/daily snapshots, queries snapshot history. Dataclass: `Snapshot`. |
| `__init__.py` | Package docstring only (no re-exports). |

## Architecture & Patterns

**Dependency direction** (strict):
```
API routes / Celery tasks
  -> SnapshotService
       -> PortfolioTracker  (equity, positions, PnL)
       -> PerformanceMetrics (metrics for daily snapshots)
       -> SnapshotRepository (DB writes)
  -> PortfolioTracker
       -> BalanceRepository, TradeRepository, Position ORM rows
       -> PriceCache (Redis)
  -> PerformanceMetrics
       -> TradeRepository, SnapshotRepository
```

**Key patterns:**
- All services accept an injected `AsyncSession` and participate in the caller's unit of work (no internal commits).
- All monetary values use `Decimal` (never `float`) for exact arithmetic. ORM numeric columns are cast via `Decimal(str(value))`.
- Frozen dataclasses (`slots=True, frozen=True`) for all return types -- callers receive immutable, typed objects instead of raw ORM rows.
- Agent scoping: every public method accepts `agent_id: UUID | None = None`. When provided, queries are filtered by agent; when `None`, falls back to account-level scope.
- Snapshot capture methods flush but do **not** commit -- the caller is responsible for `session.commit()`.

## Public API / Interfaces

### PortfolioTracker (tracker.py)

```python
class PortfolioTracker:
    def __init__(self, session: AsyncSession, price_cache: PriceCache, settings: Settings) -> None: ...

    async def get_portfolio(self, account_id: UUID, *, agent_id: UUID | None = None) -> PortfolioSummary
    async def get_positions(self, account_id: UUID, *, agent_id: UUID | None = None) -> list[PositionView]
    async def get_pnl(self, account_id: UUID, *, agent_id: UUID | None = None) -> PnLBreakdown
```

- `get_portfolio` -- full snapshot: equity = available_cash + locked_cash + total_position_value. ROI = total_pnl / starting_balance * 100.
- `get_positions` -- all open positions (quantity > 0) valued at current Redis price. Falls back to cost-basis when price unavailable (`price_available=False`).
- `get_pnl` -- unrealized (from open positions at market price) + realized (SUM of `trades.realized_pnl`) + daily realized (today's UTC trades).

### PerformanceMetrics (metrics.py)

```python
class PerformanceMetrics:
    def __init__(self, session: AsyncSession) -> None: ...

    async def calculate(self, account_id: UUID, period: str = "all", *, agent_id: UUID | None = None) -> Metrics
```

- Supported periods: `"1d"`, `"7d"`, `"30d"`, `"90d"`, `"all"`.
- Returns `Metrics.empty(period)` when no trades and no snapshots exist.
- Sharpe/Sortino assume hourly snapshot intervals; annualisation factor is `sqrt(8760)`.
- Risk-free rate: 4% annualised (`_RISK_FREE_RATE = 0.04`).
- Max snapshots loaded for `"all"` period: 5000.

### SnapshotService (snapshots.py)

```python
class SnapshotService:
    def __init__(self, session: AsyncSession, price_cache: PriceCache, settings: Settings) -> None: ...

    async def capture_minute_snapshot(self, account_id: UUID, *, agent_id: UUID | None = None) -> None
    async def capture_hourly_snapshot(self, account_id: UUID, *, agent_id: UUID | None = None) -> None
    async def capture_daily_snapshot(self, account_id: UUID, *, agent_id: UUID | None = None) -> None
    async def get_snapshot_history(self, account_id: UUID, snapshot_type: str, limit: int = 100, *, agent_id: UUID | None = None) -> list[Snapshot]
```

**Snapshot tiers:**

| Tier | Frequency | positions JSONB | metrics JSONB |
|------|-----------|-----------------|---------------|
| `minute` | Every 1 min | `None` | `None` |
| `hourly` | Every 1 hour | Serialised positions | `None` |
| `daily` | Once per UTC day | Serialised positions | Full `Metrics` output |

## Dependencies

**Internal:**
- `src.cache.price_cache.PriceCache` -- Redis price lookups for position valuation.
- `src.config.Settings` -- `default_starting_balance` fallback.
- `src.database.models` -- `Account`, `Agent`, `Balance`, `Position`, `Trade`, `PortfolioSnapshot` ORM models.
- `src.database.repositories.balance_repo.BalanceRepository` -- USDT balance queries.
- `src.database.repositories.trade_repo.TradeRepository` -- realized PnL sums, daily PnL.
- `src.database.repositories.snapshot_repo.SnapshotRepository` -- snapshot CRUD and history.
- `src.utils.exceptions` -- `AccountNotFoundError`, `CacheError`, `DatabaseError`.

**External:**
- `sqlalchemy` (async session, select, func).
- `math` (sqrt for annualisation, isfinite for profit factor clamping).

## Common Tasks

**Add a new metric to `Metrics`:**
1. Add the field to the `Metrics` frozen dataclass and to `Metrics.empty()`.
2. Implement a pure module-level helper function (prefix with `_`, no I/O).
3. Call it in `PerformanceMetrics.calculate()` and wire to the `Metrics` constructor.
4. Add it to `_serialise_metrics()` in `snapshots.py` if it should appear in daily snapshot JSONB.

**Change snapshot frequency:**
Snapshot capture is triggered by Celery beat tasks (not by this module). Adjust the Celery beat schedule, not this code.

**Add a new snapshot tier:**
1. Add a `capture_<tier>_snapshot` method to `SnapshotService`.
2. Create a corresponding Celery beat task.
3. The `snapshot_type` string column is free-form, no migration needed.

## Gotchas & Pitfalls

- **Price unavailable fallback**: When Redis has no price for a symbol, `PositionView.market_value` falls back to cost basis (not zero), and `price_available` is set to `False`. This means equity may be stale but not artificially deflated.
- **`CacheError` vs cache miss**: A missing price in Redis is a warning (returns `(Decimal("0"), False)`). A Redis connectivity failure raises `CacheError`. These are different code paths in `_get_price_safe`.
- **Starting balance resolution**: `_get_starting_balance` checks the `Agent` table first when `agent_id` is provided, then falls back to `Account`. If neither exists, raises `AccountNotFoundError`.
- **Snapshot commit responsibility**: All `capture_*` methods flush but do NOT commit. Forgetting `await session.commit()` after capture means the snapshot is lost on session close.
- **Sharpe/Sortino hourly assumption**: The annualisation uses `sqrt(8760)` assuming hourly equity snapshots. If snapshot frequency changes, these ratios become incorrect.
- **Profit factor edge case**: When there are no losing trades, `_profit_factor` returns `0.0` (not infinity) for clean JSON serialisation.
- **`_std` is population std**: Uses N (not N-1) as the denominator because the window is treated as the complete sample, not an estimate.
- **Decimal/float boundary**: ORM numeric fields are cast to `Decimal(str(value))` on read. Snapshot writes convert back to `float()` for the `PortfolioSnapshot` model columns. This is intentional -- the hypertable stores `float`, but all in-process arithmetic uses `Decimal`.
- **Lazy imports**: `Agent` model and `Trade` model are imported inside methods (not at module top) to avoid circular import chains. Do not move these to module level.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
