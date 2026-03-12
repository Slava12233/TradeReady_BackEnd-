"""Unit tests for src.order_engine.engine.OrderEngine.

Tests cover:
- Market buy order — filled immediately, correct fee and slippage
- Market sell order — filled immediately with sell direction
- Insufficient balance rejects market order
- Limit order — queued as pending, funds locked
- Stop-loss order — queued as pending
- Take-profit order — queued as pending
- cancel_order — unlocks funds, transitions to cancelled
- cancel_all_orders — cancels every open order
- execute_pending_order — fills a pending order at trigger price
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.accounts.balance_manager import BalanceManager, TradeSettlement
from src.database.models import Balance, Order, TradingPair
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.engine import OrderEngine, OrderResult
from src.order_engine.slippage import SlippageCalculator, SlippageResult
from src.order_engine.validators import OrderRequest, OrderValidator
from src.utils.exceptions import InsufficientBalanceError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order_request(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    type_: str = "market",
    quantity: str = "1",
    price: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        type=type_,
        quantity=Decimal(quantity),
        price=Decimal(price) if price else None,
    )


def _make_trading_pair(
    symbol: str = "BTCUSDT",
    base: str = "BTC",
    quote: str = "USDT",
) -> TradingPair:
    pair = MagicMock(spec=TradingPair)
    pair.symbol = symbol
    pair.base_asset = base
    pair.quote_asset = quote
    pair.status = "active"
    return pair


def _make_db_order(
    account_id=None,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    type_: str = "market",
    quantity: str = "1",
    price: str | None = None,
    status: str = "pending",
    session_id=None,
) -> Order:
    order = MagicMock(spec=Order)
    order.id = uuid4()
    order.account_id = account_id or uuid4()
    order.symbol = symbol
    order.side = side
    order.type = type_
    order.quantity = float(quantity)
    order.price = float(price) if price else None
    order.status = status
    order.session_id = session_id
    return order


def _make_slippage(
    exec_price: str = "60010",
    slippage_pct: str = "0.0001",
    fee: str = "60",
) -> SlippageResult:
    return SlippageResult(
        execution_price=Decimal(exec_price),
        slippage_amount=Decimal("10"),
        slippage_pct=Decimal(slippage_pct),
        fee=Decimal(fee),
    )


def _make_settlement(
    fee: str = "60",
    quote_amount: str = "60000",
    exec_price: str = "60010",
) -> TradeSettlement:
    settlement = MagicMock(spec=TradeSettlement)
    settlement.fee_charged = Decimal(fee)
    settlement.quote_amount = Decimal(quote_amount)
    settlement.execution_price = Decimal(exec_price)
    return settlement


def _make_balance(available: str = "100000") -> Balance:
    bal = MagicMock(spec=Balance)
    bal.available = Decimal(available)
    return bal


def _build_engine(
    account_id=None,
    pair=None,
    price: str = "60000",
    slippage: SlippageResult | None = None,
    settlement: TradeSettlement | None = None,
    db_order: Order | None = None,
    balance_available: str = "100000",
    is_limit_order: bool = False,
) -> tuple[OrderEngine, dict]:
    """Build an OrderEngine with all collaborators mocked."""
    if account_id is None:
        account_id = uuid4()
    if pair is None:
        pair = _make_trading_pair()

    # Session mock — _upsert_position calls self._session.execute(stmt) then
    # result.scalar_one_or_none().  We need execute() to return an object whose
    # scalar_one_or_none() returns None (no existing position).
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=_exec_result)
    session.add = MagicMock()

    price_cache = AsyncMock()
    price_cache.get_price = AsyncMock(return_value=Decimal(price))

    # Slippage calculator
    slippage_calc = AsyncMock(spec=SlippageCalculator)
    slippage_calc.calculate = AsyncMock(return_value=slippage or _make_slippage())

    # Balance manager
    balance_mgr = AsyncMock(spec=BalanceManager)
    balance_mgr.has_sufficient_balance = AsyncMock(return_value=True)
    balance_mgr.execute_trade = AsyncMock(return_value=settlement or _make_settlement())
    balance_mgr.get_balance = AsyncMock(return_value=_make_balance(balance_available))
    balance_mgr.lock = AsyncMock()
    balance_mgr.unlock = AsyncMock()

    # Order repo
    created_order = db_order or _make_db_order(account_id=account_id)
    order_repo = AsyncMock(spec=OrderRepository)
    order_repo.create = AsyncMock(return_value=created_order)
    order_repo.get_by_id = AsyncMock(return_value=created_order)
    order_repo.list_open_by_account = AsyncMock(return_value=[])
    order_repo.update_status = AsyncMock()
    # cancel() must return the order object (not a bare AsyncMock) so that
    # _release_locked_funds can access .price, .quantity, .side as real values.
    order_repo.cancel = AsyncMock(return_value=created_order)
    order_repo.count_open_by_account = AsyncMock(return_value=0)

    # Trade repo
    trade_repo = AsyncMock(spec=TradeRepository)
    trade_repo.create = AsyncMock(return_value=None)

    engine = OrderEngine(
        session=session,
        price_cache=price_cache,
        balance_manager=balance_mgr,
        slippage_calculator=slippage_calc,
        order_repo=order_repo,
        trade_repo=trade_repo,
    )

    # Patch validator to return pair without hitting DB
    engine._validator = AsyncMock(spec=OrderValidator)
    engine._validator.validate = AsyncMock(return_value=pair)

    mocks = {
        "account_id": account_id,
        "session": session,
        "price_cache": price_cache,
        "slippage_calc": slippage_calc,
        "balance_mgr": balance_mgr,
        "order_repo": order_repo,
        "trade_repo": trade_repo,
        "created_order": created_order,
    }
    return engine, mocks


# ---------------------------------------------------------------------------
# Market buy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_buy_returns_filled_result():
    """place_order(market buy) returns OrderResult with status='filled'."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="buy", type_="market")

    result = await engine.place_order(mocks["account_id"], order_req)

    assert isinstance(result, OrderResult)
    assert result.status == "filled"
    assert result.executed_price is not None
    assert result.executed_quantity == Decimal("1")
    assert result.fee is not None


@pytest.mark.asyncio
async def test_market_buy_creates_order_and_trade():
    """Market buy creates one Order row and one Trade row."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="buy", type_="market")

    await engine.place_order(mocks["account_id"], order_req)

    mocks["order_repo"].create.assert_awaited_once()
    mocks["trade_repo"].create.assert_awaited_once()


@pytest.mark.asyncio
async def test_market_buy_commits_session():
    """Market buy commits the session exactly once."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="buy", type_="market")

    await engine.place_order(mocks["account_id"], order_req)

    mocks["session"].commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_market_buy_insufficient_balance_raises():
    """Insufficient balance causes InsufficientBalanceError before any writes."""
    engine, mocks = _build_engine()
    mocks["balance_mgr"].has_sufficient_balance = AsyncMock(return_value=False)
    order_req = _make_order_request(side="buy", type_="market")

    with pytest.raises(InsufficientBalanceError):
        await engine.place_order(mocks["account_id"], order_req)

    # No order should have been created
    mocks["order_repo"].create.assert_not_awaited()


# ---------------------------------------------------------------------------
# Market sell
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_sell_returns_filled_result():
    """place_order(market sell) returns OrderResult with status='filled'."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="sell", type_="market")

    result = await engine.place_order(mocks["account_id"], order_req)

    assert result.status == "filled"


# ---------------------------------------------------------------------------
# Limit order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_buy_returns_pending():
    """Limit buy order is queued — result status == 'pending'."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="buy", type_="limit", price="59000")

    result = await engine.place_order(mocks["account_id"], order_req)

    assert result.status == "pending"
    assert result.executed_price is None


@pytest.mark.asyncio
async def test_limit_buy_locks_funds():
    """Limit buy locks USDT (quote asset) at placement time."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="buy", type_="limit", quantity="1", price="59000")

    await engine.place_order(mocks["account_id"], order_req)

    mocks["balance_mgr"].lock.assert_awaited_once()


@pytest.mark.asyncio
async def test_limit_sell_locks_base_asset():
    """Limit sell locks the base asset (BTC) at placement time."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="sell", type_="limit", quantity="0.5", price="65000")

    await engine.place_order(mocks["account_id"], order_req)

    lock_call = mocks["balance_mgr"].lock.call_args
    assert lock_call.kwargs.get("asset") == "BTC"


@pytest.mark.asyncio
async def test_stop_loss_queued_as_pending():
    """stop_loss order is queued — status == 'pending'."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="sell", type_="stop_loss", price="55000")

    result = await engine.place_order(mocks["account_id"], order_req)

    assert result.status == "pending"


@pytest.mark.asyncio
async def test_take_profit_queued_as_pending():
    """take_profit order is queued — status == 'pending'."""
    engine, mocks = _build_engine()
    order_req = _make_order_request(side="sell", type_="take_profit", price="70000")

    result = await engine.place_order(mocks["account_id"], order_req)

    assert result.status == "pending"


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_order_returns_true():
    """cancel_order() returns True on success."""
    pending_order = _make_db_order(side="buy", type_="limit", status="pending", price="59000")
    engine, mocks = _build_engine(db_order=pending_order)

    result = await engine.cancel_order(mocks["account_id"], pending_order.id)

    assert result is True


@pytest.mark.asyncio
async def test_cancel_order_unlocks_funds():
    """cancel_order() calls balance_mgr.unlock for buy limit orders."""
    pending_order = _make_db_order(side="buy", type_="limit", status="pending", price="59000")
    engine, mocks = _build_engine(db_order=pending_order)

    await engine.cancel_order(mocks["account_id"], pending_order.id)

    mocks["balance_mgr"].unlock.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_all_orders_returns_count():
    """cancel_all_orders() returns number of cancelled orders."""
    orders = [
        _make_db_order(side="buy", type_="limit", status="pending", price="59000"),
        _make_db_order(side="sell", type_="limit", status="pending", price="65000"),
    ]
    engine, mocks = _build_engine()
    mocks["order_repo"].list_open_by_account = AsyncMock(return_value=orders)
    # cancel() must return the order being cancelled so _release_locked_funds
    # can access .price/.quantity/.side as real values (not bare AsyncMock).
    mocks["order_repo"].cancel = AsyncMock(side_effect=orders)

    count = await engine.cancel_all_orders(mocks["account_id"])

    assert count == 2
    assert mocks["order_repo"].cancel.await_count == 2


# ---------------------------------------------------------------------------
# execute_pending_order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_pending_order_returns_filled():
    """execute_pending_order() transitions status to filled."""
    pending_order = _make_db_order(side="buy", type_="limit", status="pending", price="59000")
    engine, mocks = _build_engine(db_order=pending_order)

    result = await engine.execute_pending_order(pending_order.id, Decimal("59000"))

    assert result.status == "filled"
    assert result.executed_price is not None


@pytest.mark.asyncio
async def test_execute_pending_order_creates_trade_record():
    """execute_pending_order() always creates a Trade row."""
    pending_order = _make_db_order(side="buy", type_="limit", status="pending", price="59000")
    engine, mocks = _build_engine(db_order=pending_order)

    await engine.execute_pending_order(pending_order.id, Decimal("59000"))

    mocks["trade_repo"].create.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_pending_order_zero_price_raises():
    """execute_pending_order() with price=0 raises PriceNotAvailableError."""
    from src.utils.exceptions import PriceNotAvailableError

    engine, mocks = _build_engine()

    with pytest.raises(PriceNotAvailableError):
        await engine.execute_pending_order(uuid4(), Decimal("0"))
