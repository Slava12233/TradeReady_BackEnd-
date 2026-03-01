---
name: Phase 2 Trading Engine
overview: "Implement the complete trading engine: database schema for trading tables, repository layer, account management with auth/balance operations, order execution engine with slippage simulation, risk management with circuit breaker, portfolio tracking with performance metrics, and full unit/integration tests -- totaling ~33 tasks across 7 components, following the one-file-at-a-time rule."
todos:
  - id: 2.1-utils-exceptions
    content: Create `src/utils/exceptions.py` with custom exception classes (InsufficientBalance, OrderRejected, AccountSuspended, RiskLimitExceeded, etc.) -- needed by all subsequent components
    status: pending
  - id: 2.1-db-models
    content: "Add ORM models to `src/database/models.py`: Account, Balance, TradingSession, Order, Trade, Position, PortfolioSnapshot, AuditLog -- all per Section 14 schema"
    status: pending
  - id: 2.1-alembic-migration
    content: "Create `alembic/versions/002_trading_tables.py` migration: accounts, balances, trading_sessions, orders, trades, positions, portfolio_snapshots (hypertable), audit_log -- exact columns/constraints/indexes from plan"
    status: pending
  - id: 2.1-fix-deps
    content: Fix `src/dependencies.py` import of `async_session_factory` -> `get_session_factory()` from session.py
    status: pending
  - id: 2.2-account-repo
    content: "Create `src/database/repositories/account_repo.py` -- AccountRepository: create, get_by_id, get_by_api_key, update_status, list_by_status"
    status: pending
  - id: 2.2-balance-repo
    content: "Create `src/database/repositories/balance_repo.py` -- BalanceRepository: get, get_all, create, update_available, update_locked, atomic trade ops"
    status: pending
  - id: 2.2-order-repo
    content: "Create `src/database/repositories/order_repo.py` -- OrderRepository: create, get_by_id, list_by_account, list_pending, update_status, cancel"
    status: pending
  - id: 2.2-trade-repo
    content: "Create `src/database/repositories/trade_repo.py` -- TradeRepository: create, list_by_account, list_by_symbol, get_daily_trades"
    status: pending
  - id: 2.2-tick-repo
    content: "Create `src/database/repositories/tick_repo.py` -- TickRepository: query ticks by symbol/time range (used by analytics)"
    status: pending
  - id: 2.2-snapshot-repo
    content: "Create `src/database/repositories/snapshot_repo.py` -- SnapshotRepository: create, get_history by type/account"
    status: pending
  - id: 2.3-auth
    content: Create `src/accounts/auth.py` -- API key generation (ak_live_ prefix, secrets.token_urlsafe(48)), bcrypt hashing, JWT creation/verification with PyJWT
    status: pending
  - id: 2.3-account-service
    content: "Create `src/accounts/service.py` -- AccountService: register (create account + initial USDT balance + session), authenticate, get_account, reset_account, suspend_account"
    status: pending
  - id: 2.3-balance-manager
    content: "Create `src/accounts/balance_manager.py` -- BalanceManager: credit, debit, lock, unlock, has_sufficient_balance, execute_trade (atomic buy/sell with fee deduction)"
    status: pending
  - id: 2.4-slippage
    content: "Create `src/order_engine/slippage.py` -- SlippageCalculator: size-proportional slippage formula using PriceCache ticker volume, 0.1% trading fee"
    status: pending
  - id: 2.4-validators
    content: Create `src/order_engine/validators.py` -- validate symbol exists, side is buy/sell, type is valid, quantity > 0, price required for limit/stop/tp, pair is active
    status: pending
  - id: 2.4-engine
    content: "Create `src/order_engine/engine.py` -- OrderEngine: place_order (market/limit/stop_loss/take_profit), cancel_order, cancel_all_orders; market orders execute immediately, limit orders lock funds and queue"
    status: pending
  - id: 2.4-matching
    content: "Create `src/order_engine/matching.py` -- LimitOrderMatcher: check_all_pending every 1s, compare pending order prices vs Redis current price, trigger execution on match"
    status: pending
  - id: 2.5-risk-manager
    content: "Create `src/risk/manager.py` -- RiskManager: 8-step validate_order chain (account active, daily loss, rate limit, min size, max size %, max position %, max open orders, sufficient balance)"
    status: pending
  - id: 2.5-circuit-breaker
    content: "Create `src/risk/circuit_breaker.py` -- CircuitBreaker: record_trade_pnl, is_tripped, get_daily_pnl, reset_all; uses Redis hash circuit_breaker:{account_id} with TTL"
    status: pending
  - id: 2.6-tracker
    content: "Create `src/portfolio/tracker.py` -- PortfolioTracker: get_portfolio (total equity, positions at market price, unrealized/realized PnL, ROI), get_positions, get_pnl"
    status: pending
  - id: 2.6-metrics
    content: "Create `src/portfolio/metrics.py` -- PerformanceMetrics: calculate Sharpe, Sortino, max drawdown, win rate, profit factor, avg win/loss from snapshot/trade history"
    status: pending
  - id: 2.6-snapshots
    content: "Create `src/portfolio/snapshots.py` -- SnapshotService: capture_minute_snapshot, capture_hourly_snapshot, capture_daily_snapshot, get_snapshot_history"
    status: pending
  - id: 2.7-update-deps
    content: "Update `src/dependencies.py` to add DI providers for all new services: AccountService, BalanceManager, OrderEngine, RiskManager, CircuitBreaker, PortfolioTracker, PerformanceMetrics, SnapshotService + all repositories"
    status: completed
  - id: 2.8-test-slippage
    content: Create `tests/unit/test_slippage.py` -- test small/medium/large orders, buy vs sell direction, fee calculation, zero-volume edge case
    status: completed
  - id: 2.8-test-balance-mgr
    content: Create `tests/unit/test_balance_manager.py` -- test credit, debit, lock, unlock, atomic trade execution, insufficient balance rejection
    status: completed
  - id: 2.8-test-order-engine
    content: Create `tests/unit/test_order_engine.py` -- test market buy/sell, limit order queue, stop-loss trigger, take-profit trigger, order cancellation
    status: completed
  - id: 2.8-test-risk-mgr
    content: Create `tests/unit/test_risk_manager.py` -- test all 8 validation checks individually, custom risk profiles, circuit breaker integration
    status: completed
  - id: 2.8-test-portfolio
    content: Create `tests/unit/test_portfolio_metrics.py` -- test Sharpe ratio, drawdown, win rate, empty portfolio edge case, single-trade case
    status: completed
  - id: 2.8-test-integration
    content: "Create `tests/integration/test_full_trade_flow.py` -- end-to-end: register account -> fund balance -> place market buy -> verify fill + slippage -> place sell -> verify PnL"
    status: completed
  - id: 2.9-update-tracking
    content: Update tasks.md (mark Phase 2 tasks done) and developmentprogress.md (Phase 2 complete, changelog entries)
    status: completed
isProject: false
---

# Phase 2: Trading Engine Implementation Plan

## Current State

Phase 1 is **100% complete**: Binance WS streaming to Redis + TimescaleDB, 441 pairs seeded, all tests passing. The existing codebase provides:

- **ORM base**: `DeclarativeBase` in [src/database/models.py](src/database/models.py) with `Tick` and `TradingPair` models
- **Async sessions**: [src/database/session.py](src/database/session.py) with asyncpg pool + SQLAlchemy 2.0
- **Config**: [src/config.py](src/config.py) with trading settings (`trading_fee_pct`, `default_slippage_factor`, `default_starting_balance`, `jwt_secret`)
- **Redis cache**: [src/cache/price_cache.py](src/cache/price_cache.py) with `PriceCache.get_price()`, `get_ticker()` (needed by slippage calculator)
- **Dependencies**: [src/dependencies.py](src/dependencies.py) with `DbSessionDep`, `RedisDep`, `PriceCacheDep`
- **Migration baseline**: [alembic/versions/001_initial_schema.py](alembic/versions/001_initial_schema.py) (ticks hypertable + trading_pairs)

**Known issue**: `dependencies.py` imports `async_session_factory` but `session.py` exports `get_session_factory()` -- fix during this phase.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph phaseTwo [Phase 2 Components]
        DB["Database Schema\n(Alembic migration 002)"]
        Repos["Repository Layer\n(6 repo classes)"]
        Auth["accounts/auth.py\n(API keys + JWT)"]
        AccSvc["accounts/service.py\n(register, auth, reset)"]
        BalMgr["accounts/balance_manager.py\n(credit, debit, lock, unlock)"]
        Slip["order_engine/slippage.py\n(size-proportional model)"]
        Val["order_engine/validators.py\n(order validation rules)"]
        Eng["order_engine/engine.py\n(market + limit + stop/TP)"]
        Match["order_engine/matching.py\n(background limit matcher)"]
        Risk["risk/manager.py\n(8-step validation chain)"]
        CB["risk/circuit_breaker.py\n(daily PnL + halt)"]
        Track["portfolio/tracker.py\n(real-time equity + PnL)"]
        Metrics["portfolio/metrics.py\n(Sharpe, drawdown, etc.)"]
        Snap["portfolio/snapshots.py\n(minute/hourly/daily)"]
    end

    subgraph phaseOne [Phase 1 - Existing]
        Redis["Redis PriceCache"]
        TSDB["TimescaleDB"]
        Cfg["config.py Settings"]
    end

    DB --> Repos
    Repos --> AccSvc
    Repos --> BalMgr
    Repos --> Eng
    Auth --> AccSvc
    Redis --> Slip
    Redis --> Match
    Redis --> Track
    Slip --> Eng
    Val --> Eng
    Risk --> Eng
    BalMgr --> Eng
    CB --> Risk
    Track --> Snap
    Track --> Metrics
    Cfg --> Risk
    Cfg --> Slip
```



