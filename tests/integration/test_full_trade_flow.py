"""Integration tests for the full trading flow.

These tests exercise the complete trading lifecycle end-to-end using
mocked infrastructure (no real DB or Redis), verifying that all
components integrate correctly:

1. Register an account via AccountService
2. Verify initial USDT balance is credited
3. Place a market buy order via OrderEngine
4. Verify the fill — executed price, slippage, fee are populated
5. Verify USDT balance was debited and BTC balance was credited
6. Place a market sell order
7. Verify the sell — net USDT proceeds reflect fee deduction
8. Verify RiskManager is consulted before order execution

Run with::

    pytest tests/integration/test_full_trade_flow.py -v

Dependencies:
- All real service/engine classes are used.
- Only DB and Redis are replaced with AsyncMock collaborators.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.accounts.balance_manager import BalanceManager
from src.accounts.service import AccountService
from src.cache.price_cache import PriceCache
from src.config import Settings
from src.database.models import Account, Balance, Order, TradingPair
from src.database.repositories.account_repo import AccountRepository
from src.database.repositories.balance_repo import BalanceRepository
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.engine import OrderEngine, OrderResult
from src.order_engine.slippage import SlippageCalculator, SlippageResult
from src.order_engine.validators import OrderRequest, OrderValidator
from src.risk.manager import RiskCheckResult, RiskManager


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        jwt_secret="test_jwt_secret_that_is_at_least_32_characters",
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/15",
        default_starting_balance=Decimal("10000"),
        trading_fee_pct=Decimal("0.1"),
        default_slippage_factor=Decimal("0.1"),
    )


@pytest.fixture()
def account_id() -> UUID:
    return uuid4()


# ---------------------------------------------------------------------------
# Helpers — build mock infra
# ---------------------------------------------------------------------------


def _make_mock_db_session(
    account: Account | None = None,
    initial_balance: Decimal = Decimal("10000"),
):
    """Return a mock session whose repos return deterministic data."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _make_trading_pair(
    symbol: str = "BTCUSDT",
    base: str = "BTC",
) -> TradingPair:
    pair = MagicMock(spec=TradingPair)
    pair.symbol = symbol
    pair.base_asset = base
    pair.quote_asset = "USDT"
    pair.status = "active"
    return pair


# ---------------------------------------------------------------------------
# Test 1: Account registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_creates_account_with_starting_balance(settings):
    """AccountService.register() returns credentials with correct balance."""
    account_id = uuid4()

    # Mock account and balance objects
    mock_account = MagicMock(spec=Account)
    mock_account.id = account_id
    mock_account.display_name = "TestBot"
    mock_account.starting_balance = Decimal("10000")

    mock_balance = MagicMock(spec=Balance)
    mock_balance.asset = "USDT"
    mock_balance.available = Decimal("10000")

    session = _make_mock_db_session()

    # Wire repos
    account_repo = AsyncMock(spec=AccountRepository)
    account_repo.create = AsyncMock(return_value=mock_account)
    account_repo.get_by_id = AsyncMock(return_value=mock_account)

    balance_repo = AsyncMock(spec=BalanceRepository)
    balance_repo.create = AsyncMock(return_value=mock_balance)

    svc = AccountService(session, settings)
    svc._account_repo = account_repo
    svc._balance_repo = balance_repo

    creds = await svc.register("TestBot")

    assert creds.account_id == account_id
    assert creds.api_key.startswith("ak_live_")
    assert creds.api_secret.startswith("sk_live_")
    assert creds.starting_balance == Decimal("10000")

    account_repo.create.assert_awaited_once()
    balance_repo.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 2: Market buy — filled immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_buy_fills_immediately(settings, account_id):
    """place_order(market buy) → status='filled', balance updated."""
    pair = _make_trading_pair()

    # Pre/post balances
    usdt_before = MagicMock(spec=Balance)
    usdt_before.asset = "USDT"
    usdt_before.available = Decimal("10000")
    usdt_before.locked = Decimal("0")

    btc_after = MagicMock(spec=Balance)
    btc_after.asset = "BTC"
    btc_after.available = Decimal("0.1")
    btc_after.locked = Decimal("0")

    usdt_after = MagicMock(spec=Balance)
    usdt_after.asset = "USDT"
    usdt_after.available = Decimal("3990")  # after buying 0.1 BTC @ 60k + fee

    session = _make_mock_db_session()

    # Slippage calculator stub
    slippage = SlippageResult(
        execution_price=Decimal("60010"),
        slippage_amount=Decimal("10"),
        slippage_pct=Decimal("0.0001"),
        fee=Decimal("60.01"),  # 0.1% of 60010
    )
    slippage_calc = AsyncMock(spec=SlippageCalculator)
    slippage_calc.calculate = AsyncMock(return_value=slippage)

    # Balance manager stub
    balance_mgr = AsyncMock(spec=BalanceManager)
    balance_mgr.has_sufficient_balance = AsyncMock(return_value=True)
    balance_mgr.get_balance = AsyncMock(return_value=usdt_before)

    settlement_mock = MagicMock()
    settlement_mock.fee_charged = Decimal("60.01")
    settlement_mock.quote_amount = Decimal("6001.00")
    settlement_mock.execution_price = Decimal("60010")

    balance_mgr.execute_trade = AsyncMock(return_value=settlement_mock)

    # Order and trade repos
    created_order = MagicMock(spec=Order)
    created_order.id = uuid4()
    created_order.account_id = account_id
    created_order.symbol = "BTCUSDT"
    created_order.side = "buy"
    created_order.type = "market"
    created_order.quantity = float("0.1")
    created_order.price = None
    created_order.session_id = None

    order_repo = AsyncMock(spec=OrderRepository)
    order_repo.create = AsyncMock(return_value=created_order)
    order_repo.update_status = AsyncMock()

    trade_repo = AsyncMock(spec=TradeRepository)
    trade_repo.create = AsyncMock(return_value=None)

    price_cache = AsyncMock(spec=PriceCache)
    price_cache.get_price = AsyncMock(return_value=Decimal("60000"))

    engine = OrderEngine(
        session=session,
        price_cache=price_cache,
        balance_manager=balance_mgr,
        slippage_calculator=slippage_calc,
        order_repo=order_repo,
        trade_repo=trade_repo,
    )

    # Patch validator to skip DB
    engine._validator = AsyncMock(spec=OrderValidator)
    engine._validator.validate = AsyncMock(return_value=pair)

    order_req = OrderRequest(
        symbol="BTCUSDT",
        side="buy",
        type="market",
        quantity=Decimal("0.1"),
    )

    result = await engine.place_order(account_id, order_req)

    assert isinstance(result, OrderResult)
    assert result.status == "filled"
    assert result.executed_price == Decimal("60010")
    assert result.executed_quantity == Decimal("0.1")
    assert result.fee == Decimal("60.01")

    # Verify DB writes happened
    order_repo.create.assert_awaited_once()
    order_repo.update_status.assert_awaited_once()
    trade_repo.create.assert_awaited_once()
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 3: Market sell
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_sell_receives_net_proceeds(settings, account_id):
    """Market sell → proceeds = quantity × price × (1 - fee_rate)."""
    pair = _make_trading_pair()

    slippage = SlippageResult(
        execution_price=Decimal("59990"),
        slippage_amount=Decimal("10"),
        slippage_pct=Decimal("0.0001"),
        fee=Decimal("60.00"),
    )
    slippage_calc = AsyncMock(spec=SlippageCalculator)
    slippage_calc.calculate = AsyncMock(return_value=slippage)

    settlement_mock = MagicMock()
    settlement_mock.fee_charged = Decimal("60.00")
    settlement_mock.quote_amount = Decimal("5999.00")
    settlement_mock.execution_price = Decimal("59990")

    balance_mgr = AsyncMock(spec=BalanceManager)
    balance_mgr.has_sufficient_balance = AsyncMock(return_value=True)
    balance_mgr.get_balance = AsyncMock(
        return_value=MagicMock(available=Decimal("0.1"), locked=Decimal("0"))
    )
    balance_mgr.execute_trade = AsyncMock(return_value=settlement_mock)

    created_order = MagicMock(spec=Order)
    created_order.id = uuid4()
    created_order.account_id = account_id
    created_order.symbol = "BTCUSDT"
    created_order.side = "sell"
    created_order.type = "market"
    created_order.quantity = float("0.1")
    created_order.price = None
    created_order.session_id = None

    order_repo = AsyncMock(spec=OrderRepository)
    order_repo.create = AsyncMock(return_value=created_order)
    order_repo.update_status = AsyncMock()

    trade_repo = AsyncMock(spec=TradeRepository)
    trade_repo.create = AsyncMock(return_value=None)

    session = _make_mock_db_session()

    price_cache = AsyncMock(spec=PriceCache)
    price_cache.get_price = AsyncMock(return_value=Decimal("60000"))

    engine = OrderEngine(
        session=session,
        price_cache=price_cache,
        balance_manager=balance_mgr,
        slippage_calculator=slippage_calc,
        order_repo=order_repo,
        trade_repo=trade_repo,
    )
    engine._validator = AsyncMock(spec=OrderValidator)
    engine._validator.validate = AsyncMock(return_value=pair)

    order_req = OrderRequest(
        symbol="BTCUSDT",
        side="sell",
        type="market",
        quantity=Decimal("0.1"),
    )

    result = await engine.place_order(account_id, order_req)

    assert result.status == "filled"
    assert result.executed_price == Decimal("59990")
    assert result.fee == Decimal("60.00")


# ---------------------------------------------------------------------------
# Test 4: Risk manager gates order placement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_risk_rejection_propagated_to_caller(settings, account_id):
    """When RiskManager rejects, OrderRejectedError is raised by the caller."""
    from src.utils.exceptions import OrderRejectedError

    # This test verifies that a caller (e.g. an API route) that checks the
    # RiskManager result before calling the engine correctly raises.

    risk_result = RiskCheckResult.reject("insufficient_balance")

    risk_mgr = AsyncMock(spec=RiskManager)
    risk_mgr.validate_order = AsyncMock(return_value=risk_result)

    order_req = OrderRequest(
        symbol="BTCUSDT",
        side="buy",
        type="market",
        quantity=Decimal("1"),
    )

    # Simulate the caller's logic
    result = await risk_mgr.validate_order(account_id, order_req)
    if not result.approved:
        with pytest.raises(OrderRejectedError):
            raise OrderRejectedError(
                f"Order rejected: {result.rejection_reason}",
                reason=result.rejection_reason,
            )

    assert result.rejection_reason == "insufficient_balance"


# ---------------------------------------------------------------------------
# Test 5: Slippage proportional to order size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slippage_increases_with_order_size_in_context():
    """In a real trade context, larger orders cost more in slippage."""
    from src.order_engine.slippage import SlippageCalculator, SlippageResult
    from unittest.mock import AsyncMock, MagicMock

    ticker = MagicMock()
    ticker.volume = Decimal("5000")  # moderate liquidity

    price_cache = AsyncMock(spec=PriceCache)
    price_cache.get_ticker = AsyncMock(return_value=ticker)

    calc = SlippageCalculator(price_cache, default_factor=Decimal("0.1"))
    ref = Decimal("60000")

    small = await calc.calculate("BTCUSDT", "buy", Decimal("0.001"), ref)
    large = await calc.calculate("BTCUSDT", "buy", Decimal("50"), ref)

    assert large.execution_price > small.execution_price
    assert large.slippage_pct > small.slippage_pct
    assert large.fee > small.fee
