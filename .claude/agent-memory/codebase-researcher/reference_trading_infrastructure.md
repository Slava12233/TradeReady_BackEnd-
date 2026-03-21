---
name: trading_infrastructure_reference
description: Full map of the 13-module trading infrastructure (order engine, price ingestion, risk, portfolio, backtesting, battles, strategies, training, metrics, exchange, database, cache, tasks) and how the agent uses each
type: reference
---

# Trading Infrastructure Reference

**Why:** Comprehensive research request 2026-03-22 covering all core platform modules and the agent↔platform closed loop.

## Module Quick-Reference

| Module | Key class | How agent uses it |
|--------|-----------|-------------------|
| `src/order_engine/` | `OrderEngine.place_order()` | POST `/api/v1/trade/order` via SDK `place_market_order()` |
| `src/price_ingestion/` | `BinanceWebSocketClient`, `TickBuffer` | Read-only via Redis (`PriceCache`) and REST `/market/prices` |
| `src/risk/` | `RiskManager.validate_order()` | Transparent gate — 8 steps run before every order |
| `src/portfolio/` | `PortfolioTracker`, `PerformanceMetrics` | SDK `get_positions()`, `get_performance()`, REST `/account/portfolio` |
| `src/backtesting/` | `BacktestEngine` (singleton) | REST `PlatformRESTClient` — create/start/step/trade/results |
| `src/battles/` | `BattleService`, `HistoricalBattleEngine` | REST `/battles/` — 20 endpoints (JWT only) |
| `src/strategies/` | `StrategyService`, `StrategyExecutor` | REST `/strategies/` — CRUD, versioning, deploy, test |
| `src/training/` | `TrainingRunService` | REST `/training/runs` — register/episodes/complete/learning-curve |
| `src/metrics/` | `calculate_unified_metrics()` | Output of backtest/battle results (Sharpe, drawdown, etc.) |
| `src/exchange/` | `CCXTAdapter` | Used by ingestion pipeline; not directly agent-callable |
| `src/database/models.py` | 26 ORM models | Repositories, never direct |
| `src/cache/` | `PriceCache`, `RedisClient` | SDK `get_price()` → REST → Redis HGET prices {symbol} |
| `src/tasks/` | 14 Celery beat tasks | Background automation; agent benefits indirectly |

## Critical Paths for the Agent

### Place a trade (live)
`agent.trading.TradeExecutor.execute()` → `sdk_client.place_market_order(symbol, side, qty)` → `POST /api/v1/trade/order` → `RiskManager.validate_order()` (8 steps) → `PriceCache.get_price()` → `SlippageCalculator.calculate()` → `BalanceManager` atomic settle → Trade row created → `OrderResult` returned

### Read price
`sdk_client.get_price(symbol)` → `GET /api/v1/market/prices/{symbol}` → `PriceCache.get_price()` → Redis HGET prices {symbol}

### Run a backtest (agent-driven)
`PlatformRESTClient.create_backtest()` → `POST /api/v1/backtest/create` → `BacktestEngine.create_session()` → `start_backtest()` → `DataReplayer.preload_range()` (bulk SQL) → trading loop with `step_backtest_batch()` + `backtest_trade()` → `get_backtest_results()` → metrics via `calculate_unified_metrics()`

### Get performance metrics
`sdk_client.get_performance(period)` → `GET /api/v1/analytics/performance?period=X` → `PerformanceMetrics.calculate()` (loads trades + snapshots, Sharpe/Sortino/drawdown from `Decimal` arithmetic)

## Key Invariants to Remember
- Slippage: `clamp(factor * order_size_usd / avg_daily_volume, 0.01%, 10%)` + 0.1% fee
- Matching conditions: limit-buy fills when price <= order.price; stop_loss fills when price <= trigger; take_profit when price >= trigger
- Backtest look-ahead: `DataReplayer` enforces `WHERE bucket <= virtual_clock` always
- Risk defaults: 25% max position, 50% max single order, 100 orders/min, 20% daily loss limit, $1 min order
- `BacktestEngine` is a singleton; `CircuitBreaker` is NOT (per-account)
- Circuit breaker uses `hincrbyfloat` — float precision drift, but acceptable for safety threshold
- Portfolio Sharpe annualisation uses `sqrt(8760)` assuming hourly snapshots
- Strategy lifecycle: `draft → testing → validated → deployed → archived`
- Battle state machine: `draft → pending → active → completed` (also cancelled, paused)
- Unified metrics adapter: pass `snapshot_interval_seconds=5` for battles, `86400` for backtests

## How to apply
When tracing any agent→platform interaction, use this table to find which module handles it and which class/method is the entry point.
