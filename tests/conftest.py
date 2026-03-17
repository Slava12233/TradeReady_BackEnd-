"""Shared pytest fixtures for unit and integration tests.

Provides:
- ``mock_asyncpg_pool`` — mock asyncpg connection pool for TickBuffer tests.
- ``mock_redis`` — mock redis.asyncio.Redis instance for PriceCache tests.
- ``sample_tick`` / ``sample_ticks`` — pre-built Tick namedtuples.
- ``test_settings`` — Settings with safe defaults for tests (no real services).
- ``make_account`` / ``make_agent`` / ``make_order`` / ``make_trade`` /
  ``make_battle`` / ``make_balance`` — ORM model factory functions.
- ``mock_db_session`` — shared ``AsyncSession`` mock.
- ``mock_price_cache`` — shared ``PriceCache`` mock.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.cache.price_cache import Tick
from src.database.models import Account, Agent, Balance, Battle, Order, Trade

# ---------------------------------------------------------------------------
# pytest-asyncio configuration
# ---------------------------------------------------------------------------

pytest_plugins = ("pytest_asyncio",)


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_settings():
    """Return a Settings instance with test-safe values (no real infra needed).

    Uses ``patch`` so the lru_cache on ``get_settings`` is bypassed.

    Example::

        def test_something(test_settings):
            assert test_settings.tick_buffer_max_size == 100
    """
    with patch("src.config.get_settings") as mock_get_settings:
        from src.config import Settings

        settings = Settings(
            jwt_secret="test_secret_that_is_at_least_32_characters_long",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/15",
            tick_flush_interval=1.0,
            tick_buffer_max_size=100,
        )
        mock_get_settings.return_value = settings
        yield settings


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def make_tick(
    symbol: str = "BTCUSDT",
    price: str = "64521.30",
    quantity: str = "0.01200000",
    timestamp: datetime | None = None,
    is_buyer_maker: bool = False,
    trade_id: int = 123456789,
) -> Tick:
    """Factory function that returns a :class:`~src.cache.price_cache.Tick`.

    Args:
        symbol: Trading pair symbol.
        price: Price as a decimal string.
        quantity: Quantity as a decimal string.
        timestamp: UTC datetime; defaults to current UTC time.
        is_buyer_maker: Whether the buyer is the maker.
        trade_id: Binance trade ID integer.

    Returns:
        A fully populated :class:`Tick` namedtuple.
    """
    return Tick(
        symbol=symbol,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=timestamp or datetime.now(UTC),
        is_buyer_maker=is_buyer_maker,
        trade_id=trade_id,
    )


@pytest.fixture()
def sample_tick() -> Tick:
    """Single BTCUSDT tick for use in tests."""
    return make_tick()


@pytest.fixture()
def sample_ticks() -> list[Tick]:
    """List of three ticks across two symbols."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    return [
        make_tick("BTCUSDT", "64000.00", "0.01", ts, False, 1),
        make_tick("ETHUSDT", "3400.00", "0.50", ts, True, 2),
        make_tick("BTCUSDT", "64100.00", "0.02", ts, False, 3),
    ]


# ---------------------------------------------------------------------------
# Mock asyncpg pool
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_asyncpg_pool() -> MagicMock:
    """Return a mock asyncpg Pool whose ``acquire()`` context manager succeeds.

    The inner connection exposes a ``copy_records_to_table`` coroutine mock so
    that :class:`~src.price_ingestion.tick_buffer.TickBuffer` can call it
    without a real database.

    Example::

        async def test_flush(mock_asyncpg_pool):
            buffer = TickBuffer(db_pool=mock_asyncpg_pool)
            ...
    """
    mock_conn = AsyncMock()
    mock_conn.copy_records_to_table = AsyncMock(return_value=None)

    # asyncpg pool.acquire() is used as an async context manager
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=mock_acquire)

    return pool


# ---------------------------------------------------------------------------
# Mock Redis client
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis() -> AsyncMock:
    """Return a mock ``redis.asyncio.Redis`` instance.

    All Redis commands (hset, hget, hgetall, publish, pipeline) are
    pre-wired as AsyncMock objects so tests can inspect call arguments
    or inject return values.

    Example::

        async def test_get_price(mock_redis):
            mock_redis.hget.return_value = "64521.30"
            cache = PriceCache(mock_redis)
            price = await cache.get_price("BTCUSDT")
            assert price == Decimal("64521.30")
    """
    redis = AsyncMock()
    redis.hset = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    redis.hgetall = AsyncMock(return_value={})
    redis.publish = AsyncMock(return_value=1)

    # register_script is synchronous in real redis-py and returns a Script
    # object whose __call__ is async.  Wire up a MagicMock (sync) that returns
    # an AsyncMock (the callable script).
    mock_script = AsyncMock(return_value=1)
    redis.register_script = MagicMock(return_value=mock_script)

    # Pipeline mock — supports async context manager usage.
    # hset/publish are synchronous inside a pipeline (only execute() is awaited).
    mock_pipe = MagicMock()
    mock_pipe.hset = MagicMock()
    mock_pipe.publish = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 1])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)

    redis.pipeline = MagicMock(return_value=mock_pipe)

    return redis


# ---------------------------------------------------------------------------
# Async event loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default asyncio event loop policy for the test session."""
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# ORM model factory functions
# ---------------------------------------------------------------------------


def make_account(
    display_name: str = "TestBot",
    balance: str = "10000.00000000",
    *,
    account_id: UUID | None = None,
    email: str | None = None,
    status: str = "active",
) -> Account:
    """Factory for :class:`Account` instances.

    Args:
        display_name: Account display name.
        balance: Starting balance string (stored as risk_profile metadata).
        account_id: Override the auto-generated UUID.
        email: Override the auto-generated email.
        status: Account status (active, suspended, archived).

    Returns:
        A populated :class:`Account` instance (not persisted).
    """
    _id = account_id or uuid4()
    return Account(
        id=_id,
        api_key=f"ak_live_test_{_id.hex[:16]}",
        api_key_hash=f"hash_{_id.hex[:16]}",
        api_secret_hash=f"secret_{_id.hex[:16]}",
        display_name=display_name,
        email=email or f"test_{_id.hex[:8]}@example.com",
        status=status,
        risk_profile={"starting_balance": balance},
    )


def make_agent(
    account_id: UUID | None = None,
    name: str = "TestAgent",
    risk_profile: dict | None = None,
    *,
    agent_id: UUID | None = None,
) -> Agent:
    """Factory for :class:`Agent` instances.

    Args:
        account_id: Owning account UUID.
        name: Agent display name.
        risk_profile: Risk configuration dict.
        agent_id: Override the auto-generated UUID.

    Returns:
        A populated :class:`Agent` instance (not persisted).
    """
    _id = agent_id or uuid4()
    return Agent(
        id=_id,
        account_id=account_id or uuid4(),
        display_name=name,
        api_key=f"ak_agent_test_{_id.hex[:16]}",
        api_key_hash=f"hash_{_id.hex[:16]}",
        risk_profile=risk_profile or {},
        starting_balance=Decimal("10000"),
        status="active",
    )


def make_order(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    type: str = "market",
    quantity: str = "0.01000000",
    price: str | None = None,
    status: str = "pending",
    *,
    account_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> Order:
    """Factory for :class:`Order` instances.

    Args:
        symbol: Trading pair symbol.
        side: Order side (buy/sell).
        type: Order type (market/limit/stop_loss/take_profit).
        quantity: Order quantity as Decimal string.
        price: Limit price as Decimal string (None for market orders).
        status: Order status.
        account_id: Override the auto-generated account UUID.
        agent_id: Override the auto-generated agent UUID.

    Returns:
        A populated :class:`Order` instance (not persisted).
    """
    return Order(
        account_id=account_id or uuid4(),
        agent_id=agent_id or uuid4(),
        symbol=symbol,
        side=side,
        type=type,
        quantity=Decimal(quantity),
        price=Decimal(price) if price else None,
        status=status,
    )


def make_trade(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    quantity: str = "0.01000000",
    price: str = "50000.00000000",
    fee: str = "0.50000000",
    pnl: str | None = None,
    *,
    account_id: UUID | None = None,
    agent_id: UUID | None = None,
    order_id: UUID | None = None,
) -> Trade:
    """Factory for :class:`Trade` instances.

    Args:
        symbol: Trading pair symbol.
        side: Trade side (buy/sell).
        quantity: Trade quantity as Decimal string.
        price: Execution price as Decimal string.
        fee: Fee as Decimal string.
        pnl: Realized PnL as Decimal string (None for opening trades).
        account_id: Override the auto-generated account UUID.
        agent_id: Override the auto-generated agent UUID.
        order_id: Override the auto-generated order UUID.

    Returns:
        A populated :class:`Trade` instance (not persisted).
    """
    qty = Decimal(quantity)
    px = Decimal(price)
    return Trade(
        account_id=account_id or uuid4(),
        agent_id=agent_id or uuid4(),
        order_id=order_id or uuid4(),
        symbol=symbol,
        side=side,
        quantity=qty,
        price=px,
        quote_amount=qty * px,
        fee=Decimal(fee),
        realized_pnl=Decimal(pnl) if pnl else None,
    )


def make_battle(
    name: str = "Test Battle",
    status: str = "draft",
    mode: str = "live",
    config: dict | None = None,
    *,
    account_id: UUID | None = None,
) -> Battle:
    """Factory for :class:`Battle` instances.

    Args:
        name: Battle display name.
        status: Battle status (draft/pending/active/completed/cancelled).
        mode: Battle mode (live/historical).
        config: Battle configuration dict.
        account_id: Override the auto-generated account UUID.

    Returns:
        A populated :class:`Battle` instance (not persisted).
    """
    return Battle(
        account_id=account_id or uuid4(),
        name=name,
        status=status,
        battle_mode=mode,
        config=config or {"duration_minutes": 60, "starting_balance": "10000"},
    )


def make_balance(
    asset: str = "USDT",
    available: str = "10000.00000000",
    locked: str = "0.00000000",
    *,
    account_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> Balance:
    """Factory for :class:`Balance` instances.

    Args:
        asset: Asset ticker (e.g. USDT, BTC).
        available: Available amount as Decimal string.
        locked: Locked amount as Decimal string.
        account_id: Override the auto-generated account UUID.
        agent_id: Override the auto-generated agent UUID.

    Returns:
        A populated :class:`Balance` instance (not persisted).
    """
    return Balance(
        account_id=account_id or uuid4(),
        agent_id=agent_id,
        asset=asset,
        available=Decimal(available),
        locked=Decimal(locked),
    )


# ---------------------------------------------------------------------------
# Shared mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db_session() -> AsyncMock:
    """Return a mock ``AsyncSession`` with execute/flush/commit/rollback.

    Pre-wired as AsyncMock objects so tests can set return values and
    inspect call arguments.

    Example::

        async def test_repo(mock_db_session):
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = some_obj
            mock_db_session.execute.return_value = mock_result
    """
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.close = AsyncMock()
    # begin_nested returns an async context manager
    nested = AsyncMock()
    nested.__aenter__ = AsyncMock()
    nested.__aexit__ = AsyncMock(return_value=False)
    session.begin_nested = MagicMock(return_value=nested)
    return session


@pytest.fixture()
def mock_price_cache() -> AsyncMock:
    """Return a mock ``PriceCache`` with get_price/set_price pre-wired.

    Example::

        async def test_something(mock_price_cache):
            mock_price_cache.get_price.return_value = Decimal("50000")
    """
    cache = AsyncMock()
    cache.get_price = AsyncMock(return_value=None)
    cache.set_price = AsyncMock(return_value=None)
    cache.get_all_prices = AsyncMock(return_value={})
    cache.update_ticker = AsyncMock(return_value=None)
    return cache
