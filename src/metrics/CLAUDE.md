# Unified Metrics

<!-- last-updated: 2026-03-17 -->

> Single source of truth for all performance metrics across backtesting and battles, ensuring consistent and comparable results.

## What This Module Does

The `src/metrics/` module computes trading performance metrics (ROI, Sharpe, Sortino, drawdown, win rate, profit factor, etc.) from normalised inputs. It decouples metric calculation from any specific domain (backtests, live trading, battles) by defining two normalised input dataclasses (`MetricTradeInput`, `MetricSnapshotInput`) and four adapter functions that convert domain-specific types into those inputs. All arithmetic uses `Decimal` for precision.

## Key Files

| File | Purpose |
|------|---------|
| `calculator.py` | Core metrics engine: `calculate_unified_metrics()`, input/output dataclasses, Sharpe/Sortino helpers |
| `adapters.py` | Four adapter functions converting domain types into `MetricTradeInput` / `MetricSnapshotInput` |
| `__init__.py` | Package marker with module docstring |

## Architecture & Patterns

- **Normalisation pattern**: Domain types never reach the calculator. Adapters convert them into `MetricTradeInput` / `MetricSnapshotInput` first. This keeps the calculator pure and testable.
- **Frozen dataclasses with slots**: All data containers (`MetricTradeInput`, `MetricSnapshotInput`, `UnifiedMetrics`) are `@dataclass(frozen=True, slots=True)` for immutability and memory efficiency.
- **Decimal everywhere**: All monetary and ratio values use `Decimal`. Float is only used transiently inside `math.sqrt` calls, immediately converted back to `Decimal`.
- **Quantisation constants**: `_QUANT2` (0.01), `_QUANT4` (0.0001), `_QUANT8` (0.00000001) control rounding precision at output boundaries.

## Public API / Interfaces

### Dataclasses (calculator.py)

| Class | Fields | Usage |
|-------|--------|-------|
| `MetricTradeInput` | `realized_pnl: Decimal \| None`, `quote_amount: Decimal`, `symbol: str`, `timestamp: datetime` | Normalised trade fed into calculator |
| `MetricSnapshotInput` | `timestamp: datetime`, `equity: Decimal` | Normalised equity snapshot fed into calculator |
| `UnifiedMetrics` | `roi_pct`, `total_pnl`, `sharpe_ratio`, `sortino_ratio`, `max_drawdown_pct`, `max_drawdown_duration_days`, `win_rate`, `profit_factor`, `total_trades`, `trades_per_day`, `avg_win`, `avg_loss`, `best_trade`, `worst_trade` | Output of `calculate_unified_metrics()` |

### Functions

**calculator.py:**

```python
calculate_unified_metrics(
    trades: list[MetricTradeInput],
    snapshots: list[MetricSnapshotInput],
    starting_balance: Decimal,
    duration_days: Decimal,
    snapshot_interval_seconds: int = 86400,
) -> UnifiedMetrics
```

- `snapshot_interval_seconds` controls Sharpe/Sortino annualisation: `86400` for daily snapshots, `5` for battle 5-second snapshots.
- Returns `None` for `sharpe_ratio`/`sortino_ratio` when fewer than 2 return periods exist, or when standard deviation is zero.
- Returns `None` for `profit_factor` when there are no losing trades.

**adapters.py:**

| Function | Source Type | Target |
|----------|------------|--------|
| `from_sandbox_trades(trades)` | `list[SandboxTrade]` | `list[MetricTradeInput]` |
| `from_sandbox_snapshots(snapshots)` | `list[SandboxSnapshot]` | `list[MetricSnapshotInput]` |
| `from_db_trades(trades)` | `Sequence[Trade]` (DB model) | `list[MetricTradeInput]` |
| `from_battle_snapshots(snapshots)` | `Sequence[BattleSnapshot]` (DB model) | `list[MetricSnapshotInput]` |

## Dependencies

**Internal:**
- `src.database.models` — `BattleSnapshot`, `Trade` (used by adapters)
- `src.backtesting.sandbox` — `SandboxTrade`, `SandboxSnapshot` (TYPE_CHECKING only, avoids circular import)

**External:**
- Python stdlib only: `dataclasses`, `datetime`, `decimal`, `math`, `collections.abc`

**Consumed by:**
- `src.backtesting.results` — delegates to `calculate_unified_metrics` via sandbox adapters
- `src.battles.ranking` — delegates to `calculate_unified_metrics` via battle/DB adapters
- `src.battles.historical_engine` — uses sandbox adapters for historical battle results

## Common Tasks

**Adding a new metric to the output:**
1. Add the field to `UnifiedMetrics` in `calculator.py`
2. Compute the value inside `calculate_unified_metrics()`
3. Update tests in `tests/unit/test_unified_metrics.py` and `tests/unit/test_metrics_consistency.py`

**Adding a new source domain (e.g., paper trading):**
1. Create a new adapter function in `adapters.py` that maps the domain type to `MetricTradeInput` / `MetricSnapshotInput`
2. Call `calculate_unified_metrics()` with the adapted inputs from the new domain's service layer

## Gotchas & Pitfalls

- **`snapshot_interval_seconds` matters**: The annualisation factor for Sharpe/Sortino is `sqrt(365.25 * 86400 / interval)`. Passing the wrong interval (e.g., 86400 for 5-second battle snapshots) will produce wildly incorrect ratios.
- **Sortino returns `None` when all returns are non-negative**: If there are no negative return periods, downside deviation is zero and Sortino cannot be computed.
- **`from_battle_snapshots` handles mixed types**: The equity field on `BattleSnapshot` may arrive as `float` from JSON deserialization, so the adapter explicitly wraps non-Decimal values with `Decimal(str(s.equity))`.
- **Trades with `realized_pnl=None` are counted in `total_trades` but excluded from win/loss classification**: Only trades with a non-None `realized_pnl` contribute to win rate, profit factor, avg win/loss, and best/worst trade.
- **`SandboxTrade`/`SandboxSnapshot` are TYPE_CHECKING imports**: This avoids a circular dependency with `src.backtesting.sandbox`. Do not move them to runtime imports.

## Recent Changes

- `2026-03-17` — Initial CLAUDE.md created
