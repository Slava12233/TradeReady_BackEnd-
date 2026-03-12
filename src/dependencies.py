"""FastAPI dependency-injection providers.

Every provider in this module is intended to be used with ``Depends()`` inside
route handlers and other FastAPI dependencies.  Each function returns (or
yields) a resource that is tied to the request lifetime where appropriate.

Dependency graph
----------------
Routes
  └── get_settings()          → Settings                   (singleton)
  └── get_db_session()        → AsyncSession               (per-request)
  └── get_redis()             → redis.asyncio.Redis        (shared pool)
  └── get_price_cache()       → PriceCache                 (per-request, depends on redis)
  └── get_account_repo()      → AccountRepository          (per-request, depends on db)
  └── get_balance_repo()      → BalanceRepository          (per-request, depends on db)
  └── get_order_repo()        → OrderRepository            (per-request, depends on db)
  └── get_trade_repo()        → TradeRepository            (per-request, depends on db)
  └── get_tick_repo()         → TickRepository             (per-request, depends on db)
  └── get_snapshot_repo()     → SnapshotRepository         (per-request, depends on db)
  └── get_balance_manager()   → BalanceManager             (per-request, depends on db + settings)
  └── get_account_service()   → AccountService             (per-request, depends on db + settings)
  └── get_slippage_calc()     → SlippageCalculator         (per-request, depends on price_cache + settings)
  └── get_order_engine()      → OrderEngine                (per-request, db + cache + balance + slippage)
  └── get_risk_manager()      → RiskManager                (per-request, redis + cache + balance + repos + settings)
  └── get_circuit_breaker()   → CircuitBreaker             (per-request, depends on redis + account_repo)
  └── get_portfolio_tracker() → PortfolioTracker           (per-request, depends on db + price_cache + settings)
  └── get_performance_metrics() → PerformanceMetrics       (per-request, depends on db)
  └── get_snapshot_service()  → SnapshotService            (per-request, depends on db + price_cache + settings)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Annotated, Any, TypeAlias

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.config import get_settings as _get_settings

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings() -> Settings:
    """Return the application settings singleton.

    Example::

        @router.get("/info")
        async def info(settings: Annotated[Settings, Depends(get_settings)]):
            return {"version": settings.api_base_url}
    """
    return _get_settings()


SettingsDep: TypeAlias = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a per-request async SQLAlchemy session.

    The session is committed automatically if the handler completes without
    raising, and rolled back + closed on any exception.

    Import ``get_session_factory`` lazily so that the database module is not
    imported until the first request — avoids circular-import issues during
    module loading.

    Example::

        @router.get("/pairs")
        async def list_pairs(db: Annotated[AsyncSession, Depends(get_db_session)]):
            result = await db.execute(select(TradingPair))
            return result.scalars().all()
    """
    from src.database.session import get_session_factory  # noqa: PLC0415

    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


DbSessionDep: TypeAlias = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------


async def get_redis() -> AsyncGenerator[Redis[Any], None]:
    """Yield a Redis client from the shared connection pool.

    The pool is created lazily on the first call and reused across requests.
    The yielded client is NOT closed after each request — it is returned to
    the pool automatically.

    Example::

        @router.get("/price/{symbol}")
        async def get_price(
            symbol: str,
            redis: Annotated[Redis, Depends(get_redis)],
        ):
            price = await redis.hget("prices", symbol)
            return {"symbol": symbol, "price": price}
    """
    from src.cache.redis_client import get_redis_client  # noqa: PLC0415

    client = await get_redis_client()
    try:
        yield client
    finally:
        pass  # pool manages connection lifecycle; do not close here


RedisDep: TypeAlias = Annotated[Redis[Any], Depends(get_redis)]


# ---------------------------------------------------------------------------
# Price cache
# ---------------------------------------------------------------------------


async def get_price_cache(
    redis: RedisDep,
) -> PriceCacheDep:
    """Return a ``PriceCache`` instance bound to the current Redis client.

    Example::

        @router.get("/prices")
        async def all_prices(
            cache: Annotated[PriceCache, Depends(get_price_cache)],
        ):
            return await cache.get_all_prices()
    """
    from src.cache.price_cache import PriceCache  # noqa: PLC0415

    return PriceCache(redis)


# Re-export a typed alias so callers can write the annotation concisely.
try:
    from src.cache.price_cache import PriceCache as _PriceCache

    PriceCacheDep: TypeAlias = Annotated[_PriceCache, Depends(get_price_cache)]
except ImportError:
    PriceCacheDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Repositories
# ---------------------------------------------------------------------------


async def get_account_repo(
    db: DbSessionDep,
) -> AccountRepoDep:
    """Return an ``AccountRepository`` wired to the current session."""
    from src.database.repositories.account_repo import AccountRepository  # noqa: PLC0415

    return AccountRepository(db)


async def get_balance_repo(
    db: DbSessionDep,
) -> BalanceRepoDep:
    """Return a ``BalanceRepository`` wired to the current session."""
    from src.database.repositories.balance_repo import BalanceRepository  # noqa: PLC0415

    return BalanceRepository(db)


async def get_order_repo(
    db: DbSessionDep,
) -> OrderRepoDep:
    """Return an ``OrderRepository`` wired to the current session."""
    from src.database.repositories.order_repo import OrderRepository  # noqa: PLC0415

    return OrderRepository(db)


async def get_trade_repo(
    db: DbSessionDep,
) -> TradeRepoDep:
    """Return a ``TradeRepository`` wired to the current session."""
    from src.database.repositories.trade_repo import TradeRepository  # noqa: PLC0415

    return TradeRepository(db)


async def get_tick_repo(
    db: DbSessionDep,
) -> TickRepoDep:
    """Return a ``TickRepository`` wired to the current session."""
    from src.database.repositories.tick_repo import TickRepository  # noqa: PLC0415

    return TickRepository(db)


async def get_snapshot_repo(
    db: DbSessionDep,
) -> SnapshotRepoDep:
    """Return a ``SnapshotRepository`` wired to the current session."""
    from src.database.repositories.snapshot_repo import SnapshotRepository  # noqa: PLC0415

    return SnapshotRepository(db)


# Typed aliases — resolved at import time with graceful fallback
try:
    from src.database.repositories.account_repo import AccountRepository as _AccountRepo
    from src.database.repositories.balance_repo import BalanceRepository as _BalanceRepo
    from src.database.repositories.order_repo import OrderRepository as _OrderRepo
    from src.database.repositories.snapshot_repo import SnapshotRepository as _SnapshotRepo
    from src.database.repositories.tick_repo import TickRepository as _TickRepo
    from src.database.repositories.trade_repo import TradeRepository as _TradeRepo

    AccountRepoDep: TypeAlias = Annotated[_AccountRepo, Depends(get_account_repo)]
    BalanceRepoDep: TypeAlias = Annotated[_BalanceRepo, Depends(get_balance_repo)]
    OrderRepoDep: TypeAlias = Annotated[_OrderRepo, Depends(get_order_repo)]
    TradeRepoDep: TypeAlias = Annotated[_TradeRepo, Depends(get_trade_repo)]
    TickRepoDep: TypeAlias = Annotated[_TickRepo, Depends(get_tick_repo)]
    SnapshotRepoDep: TypeAlias = Annotated[_SnapshotRepo, Depends(get_snapshot_repo)]
except ImportError:
    AccountRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]
    BalanceRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]
    OrderRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]
    TradeRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]
    TickRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]
    SnapshotRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Balance manager
# ---------------------------------------------------------------------------


async def get_balance_manager(
    db: DbSessionDep,
    settings: SettingsDep,
) -> BalanceManagerDep:
    """Return a ``BalanceManager`` wired to the current session and settings.

    Example::

        @router.get("/balance/{asset}")
        async def balance(
            asset: str,
            account_id: UUID,
            mgr: Annotated[BalanceManager, Depends(get_balance_manager)],
        ):
            return await mgr.get_balance(account_id, asset)
    """
    from src.accounts.balance_manager import BalanceManager  # noqa: PLC0415

    return BalanceManager(db, settings)


try:
    from src.accounts.balance_manager import BalanceManager as _BalanceManager

    BalanceManagerDep: TypeAlias = Annotated[_BalanceManager, Depends(get_balance_manager)]
except ImportError:
    BalanceManagerDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Account service
# ---------------------------------------------------------------------------


async def get_account_service(
    db: DbSessionDep,
    settings: SettingsDep,
) -> AccountServiceDep:
    """Return an ``AccountService`` wired to the current session and settings.

    Example::

        @router.post("/auth/register")
        async def register(
            body: RegisterRequest,
            svc: Annotated[AccountService, Depends(get_account_service)],
        ):
            creds = await svc.register(body.display_name, email=body.email)
            return {"api_key": creds.api_key, "api_secret": creds.api_secret}
    """
    from src.accounts.service import AccountService  # noqa: PLC0415

    return AccountService(db, settings)


try:
    from src.accounts.service import AccountService as _AccountService

    AccountServiceDep: TypeAlias = Annotated[_AccountService, Depends(get_account_service)]
except ImportError:
    AccountServiceDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Slippage calculator
# ---------------------------------------------------------------------------


async def get_slippage_calculator(
    price_cache: PriceCacheDep,
    settings: SettingsDep,
) -> SlippageCalcDep:
    """Return a ``SlippageCalculator`` wired to the current price cache.

    The ``default_factor`` is drawn from ``settings.default_slippage_factor``.
    """
    from src.order_engine.slippage import SlippageCalculator  # noqa: PLC0415

    return SlippageCalculator(
        price_cache,
        default_factor=Decimal(str(settings.default_slippage_factor)),
    )


try:
    from src.order_engine.slippage import SlippageCalculator as _SlippageCalc

    SlippageCalcDep: TypeAlias = Annotated[_SlippageCalc, Depends(get_slippage_calculator)]
except ImportError:
    SlippageCalcDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Order engine
# ---------------------------------------------------------------------------


async def get_order_engine(
    db: DbSessionDep,
    price_cache: PriceCacheDep,
    balance_manager: BalanceManagerDep,
    slippage_calc: SlippageCalcDep,
    order_repo: OrderRepoDep,
    trade_repo: TradeRepoDep,
) -> OrderEngineDep:
    """Return an ``OrderEngine`` wired to all required collaborators.

    Example::

        @router.post("/trade/order")
        async def place_order(
            body: OrderRequest,
            account_id: UUID,
            engine: Annotated[OrderEngine, Depends(get_order_engine)],
        ):
            return await engine.place_order(account_id, body)
    """
    from src.order_engine.engine import OrderEngine  # noqa: PLC0415

    return OrderEngine(
        session=db,
        price_cache=price_cache,
        balance_manager=balance_manager,
        slippage_calculator=slippage_calc,
        order_repo=order_repo,
        trade_repo=trade_repo,
    )


try:
    from src.order_engine.engine import OrderEngine as _OrderEngine

    OrderEngineDep: TypeAlias = Annotated[_OrderEngine, Depends(get_order_engine)]
except ImportError:
    OrderEngineDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Risk manager
# ---------------------------------------------------------------------------


async def get_risk_manager(
    redis: RedisDep,
    price_cache: PriceCacheDep,
    balance_manager: BalanceManagerDep,
    account_repo: AccountRepoDep,
    order_repo: OrderRepoDep,
    trade_repo: TradeRepoDep,
    settings: SettingsDep,
) -> RiskManagerDep:
    """Return a ``RiskManager`` wired to all required collaborators.

    Example::

        @router.post("/trade/order")
        async def place_order(
            body: OrderRequest,
            account_id: UUID,
            risk: Annotated[RiskManager, Depends(get_risk_manager)],
            engine: Annotated[OrderEngine, Depends(get_order_engine)],
        ):
            result = await risk.validate_order(account_id, body)
            if not result.approved:
                raise OrderRejectedError(reason=result.rejection_reason)
            return await engine.place_order(account_id, body)
    """
    from src.risk.manager import RiskManager  # noqa: PLC0415

    return RiskManager(
        redis=redis,
        price_cache=price_cache,
        balance_manager=balance_manager,
        account_repo=account_repo,
        order_repo=order_repo,
        trade_repo=trade_repo,
        settings=settings,
    )


try:
    from src.risk.manager import RiskManager as _RiskManager

    RiskManagerDep: TypeAlias = Annotated[_RiskManager, Depends(get_risk_manager)]
except ImportError:
    RiskManagerDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
#
# CircuitBreaker is account-scoped: it requires the account's starting_balance
# and daily_loss_limit_pct at construction time.  Route handlers that need it
# should build it on-the-fly after loading the account:
#
#     account = await account_repo.get_by_id(account_id)
#     limits = risk_manager._build_risk_limits(account)
#     cb = CircuitBreaker(
#         redis=redis,
#         starting_balance=Decimal(str(account.starting_balance)),
#         daily_loss_limit_pct=limits.daily_loss_limit_pct,
#     )
#
# A reset-all factory is provided for the Celery daily reset task.


async def get_circuit_breaker_redis(
    redis: RedisDep,
) -> CircuitBreakerRedisDep:
    """Return (redis,) tuple for use in Celery tasks that call reset_all.

    Routes that need a fully configured CircuitBreaker for a specific account
    should construct it directly (see module docstring above).

    Example::

        from src.risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(redis=redis, starting_balance=..., daily_loss_limit_pct=...)
        await cb.reset_all()
    """
    return redis


CircuitBreakerRedisDep: TypeAlias = Annotated[Redis[Any], Depends(get_circuit_breaker_redis)]


# ---------------------------------------------------------------------------
# Portfolio tracker
# ---------------------------------------------------------------------------


async def get_portfolio_tracker(
    db: DbSessionDep,
    price_cache: PriceCacheDep,
    settings: SettingsDep,
) -> PortfolioTrackerDep:
    """Return a ``PortfolioTracker`` wired to the current session.

    Example::

        @router.get("/account/portfolio")
        async def portfolio(
            account_id: UUID,
            tracker: Annotated[PortfolioTracker, Depends(get_portfolio_tracker)],
        ):
            return await tracker.get_portfolio(account_id)
    """
    from src.portfolio.tracker import PortfolioTracker  # noqa: PLC0415

    return PortfolioTracker(db, price_cache, settings)


try:
    from src.portfolio.tracker import PortfolioTracker as _PortfolioTracker

    PortfolioTrackerDep: TypeAlias = Annotated[_PortfolioTracker, Depends(get_portfolio_tracker)]
except ImportError:
    PortfolioTrackerDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------


async def get_performance_metrics(
    db: DbSessionDep,
) -> PerformanceMetricsDep:
    """Return a ``PerformanceMetrics`` instance wired to the current session.

    Example::

        @router.get("/analytics/performance")
        async def performance(
            account_id: UUID,
            period: str = "30d",
            metrics: Annotated[PerformanceMetrics, Depends(get_performance_metrics)],
        ):
            return await metrics.calculate(account_id, period=period)
    """
    from src.portfolio.metrics import PerformanceMetrics  # noqa: PLC0415

    return PerformanceMetrics(db)


try:
    from src.portfolio.metrics import PerformanceMetrics as _PerformanceMetrics

    PerformanceMetricsDep: TypeAlias = Annotated[_PerformanceMetrics, Depends(get_performance_metrics)]
except ImportError:
    PerformanceMetricsDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Snapshot service
# ---------------------------------------------------------------------------


async def get_snapshot_service(
    db: DbSessionDep,
    price_cache: PriceCacheDep,
    settings: SettingsDep,
) -> SnapshotServiceDep:
    """Return a ``SnapshotService`` wired to the current session.

    Example::

        @router.post("/account/snapshot")
        async def snapshot(
            account_id: UUID,
            svc: Annotated[SnapshotService, Depends(get_snapshot_service)],
        ):
            await svc.capture_minute_snapshot(account_id)
    """
    from src.portfolio.snapshots import SnapshotService  # noqa: PLC0415

    return SnapshotService(db, price_cache, settings)


try:
    from src.portfolio.snapshots import SnapshotService as _SnapshotService

    SnapshotServiceDep: TypeAlias = Annotated[_SnapshotService, Depends(get_snapshot_service)]
except ImportError:
    SnapshotServiceDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

# The BacktestEngine is a singleton — it holds active sessions in memory.
_backtest_engine_instance: Any | None = None


def get_backtest_engine() -> BacktestEngineDep:
    """Return the singleton ``BacktestEngine`` instance.

    The engine is created lazily on the first call.  It holds active
    backtest sessions in memory across requests.
    """
    global _backtest_engine_instance  # noqa: PLW0603
    if _backtest_engine_instance is None:
        from src.backtesting.engine import BacktestEngine  # noqa: PLC0415
        from src.database.session import get_session_factory  # noqa: PLC0415

        _backtest_engine_instance = BacktestEngine(get_session_factory())
    return _backtest_engine_instance


try:
    from src.backtesting.engine import BacktestEngine as _BacktestEngine

    BacktestEngineDep: TypeAlias = Annotated[_BacktestEngine, Depends(get_backtest_engine)]
except ImportError:
    BacktestEngineDep: TypeAlias = Any  # type: ignore[misc,no-redef]


# ---------------------------------------------------------------------------
# Backtest repository
# ---------------------------------------------------------------------------


async def get_backtest_repo(
    db: DbSessionDep,
) -> BacktestRepoDep:
    """Return a ``BacktestRepository`` wired to the current session."""
    from src.database.repositories.backtest_repo import BacktestRepository  # noqa: PLC0415

    return BacktestRepository(db)


try:
    from src.database.repositories.backtest_repo import BacktestRepository as _BacktestRepo

    BacktestRepoDep: TypeAlias = Annotated[_BacktestRepo, Depends(get_backtest_repo)]
except ImportError:
    BacktestRepoDep: TypeAlias = Any  # type: ignore[misc,no-redef]
