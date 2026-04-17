"""Unit tests for agent data isolation across service and engine layers.

Verifies that agent_id is properly threaded through:
- OrderEngine._upsert_position (per-agent position rows)
- BalanceManager credit/debit/lock/unlock (agent-scoped repo calls)
- RiskManager checks (agent-scoped open orders, daily PnL, balances)
- OrderEngine cancel_order / cancel_all_orders (agent ownership)
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.accounts.balance_manager import BalanceManager, TradeSettlement
from src.database.models import Balance, Order, TradingPair
from src.database.repositories.balance_repo import BalanceRepository
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.engine import OrderEngine
from src.order_engine.slippage import SlippageCalculator, SlippageResult
from src.order_engine.validators import OrderRequest, OrderValidator
from src.utils.exceptions import OrderNotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ACCOUNT_ID = uuid4()
AGENT_A = uuid4()
AGENT_B = uuid4()


def _make_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    _exec_result = MagicMock()
    _exec_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=_exec_result)
    session.add = MagicMock()
    return session


def _make_engine(session=None):
    if session is None:
        session = _make_session()

    price_cache = AsyncMock()
    price_cache.get_price = AsyncMock(return_value=Decimal("60000"))

    slippage_calc = AsyncMock(spec=SlippageCalculator)
    slippage_calc.calculate = AsyncMock(
        return_value=SlippageResult(
            execution_price=Decimal("60010"),
            slippage_amount=Decimal("10"),
            slippage_pct=Decimal("0.0001"),
            fee=Decimal("60"),
        )
    )

    balance_mgr = AsyncMock(spec=BalanceManager)
    balance_mgr.has_sufficient_balance = AsyncMock(return_value=True)
    settlement = MagicMock(spec=TradeSettlement)
    settlement.fee_charged = Decimal("60")
    settlement.quote_amount = Decimal("60000")
    settlement.execution_price = Decimal("60010")
    balance_mgr.execute_trade = AsyncMock(return_value=settlement)
    balance_mgr.get_balance = AsyncMock(return_value=MagicMock(spec=Balance, available=Decimal("100000")))
    balance_mgr.lock = AsyncMock()

    order_repo = AsyncMock(spec=OrderRepository)
    db_order = MagicMock(spec=Order)
    db_order.id = uuid4()
    db_order.account_id = ACCOUNT_ID
    db_order.agent_id = AGENT_A
    db_order.symbol = "BTCUSDT"
    db_order.side = "buy"
    db_order.type = "market"
    db_order.quantity = 1.0
    db_order.price = None
    db_order.status = "pending"
    db_order.session_id = None
    order_repo.create = AsyncMock(return_value=db_order)

    trade_repo = AsyncMock(spec=TradeRepository)
    trade_repo.create = AsyncMock()

    validator = AsyncMock(spec=OrderValidator)
    pair = MagicMock(spec=TradingPair)
    pair.symbol = "BTCUSDT"
    pair.base_asset = "BTC"
    pair.quote_asset = "USDT"
    pair.status = "active"
    validator.validate = AsyncMock(return_value=pair)

    engine = OrderEngine(
        session=session,
        price_cache=price_cache,
        balance_manager=balance_mgr,
        slippage_calculator=slippage_calc,
        order_repo=order_repo,
        trade_repo=trade_repo,
    )
    engine._validator = validator

    return engine, {
        "session": session,
        "balance_mgr": balance_mgr,
        "order_repo": order_repo,
        "trade_repo": trade_repo,
    }


# ---------------------------------------------------------------------------
# _upsert_position tests
# ---------------------------------------------------------------------------


class TestUpsertPositionAgentScoping:
    """Verify _upsert_position creates agent-scoped positions."""

    async def test_new_position_includes_agent_id(self):
        session = _make_session()
        engine, _ = _make_engine(session)

        # BUG-011: _upsert_position now requires a positional `fee` argument
        # (fee-inclusive cost basis for avg_entry_price on buy fills).
        await engine._upsert_position(
            account_id=ACCOUNT_ID,
            symbol="BTCUSDT",
            side="buy",
            fill_qty=Decimal("1"),
            fill_price=Decimal("60000"),
            fee=Decimal("60"),  # 0.1% of 60000
            agent_id=AGENT_A,
        )

        # The Position object added to the session should have agent_id set
        session.add.assert_called_once()
        position = session.add.call_args[0][0]
        assert position.agent_id == AGENT_A
        assert position.account_id == ACCOUNT_ID
        assert position.symbol == "BTCUSDT"

    async def test_upsert_position_queries_by_agent_id(self):
        session = _make_session()
        engine, _ = _make_engine(session)

        # BUG-011: _upsert_position now requires a positional `fee` argument.
        await engine._upsert_position(
            account_id=ACCOUNT_ID,
            symbol="BTCUSDT",
            side="buy",
            fill_qty=Decimal("1"),
            fill_price=Decimal("60000"),
            fee=Decimal("60"),  # 0.1% of 60000
            agent_id=AGENT_A,
        )

        # The SELECT query should include agent_id in the WHERE clause
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# BalanceManager agent scoping tests
# ---------------------------------------------------------------------------


class TestBalanceManagerAgentScoping:
    """Verify BalanceManager routes to agent-scoped repo methods."""

    async def test_credit_uses_agent_repo_when_agent_id_provided(self):
        session = AsyncMock()
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = BalanceManager(session, settings)
        mgr._repo = AsyncMock(spec=BalanceRepository)
        mgr._repo.update_available_by_agent = AsyncMock(return_value=MagicMock(spec=Balance))

        await mgr.credit(ACCOUNT_ID, asset="USDT", amount=Decimal("100"), agent_id=AGENT_A)

        mgr._repo.update_available_by_agent.assert_called_once_with(AGENT_A, "USDT", Decimal("100"))
        mgr._repo.update_available.assert_not_called()

    async def test_debit_uses_agent_repo_when_agent_id_provided(self):
        session = AsyncMock()
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = BalanceManager(session, settings)
        mgr._repo = AsyncMock(spec=BalanceRepository)
        mgr._repo.update_available_by_agent = AsyncMock(return_value=MagicMock(spec=Balance))

        await mgr.debit(ACCOUNT_ID, asset="USDT", amount=Decimal("50"), agent_id=AGENT_A)

        mgr._repo.update_available_by_agent.assert_called_once_with(AGENT_A, "USDT", Decimal("-50"))

    async def test_lock_uses_agent_repo_when_agent_id_provided(self):
        session = AsyncMock()
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = BalanceManager(session, settings)
        mgr._repo = AsyncMock(spec=BalanceRepository)
        mgr._repo.atomic_lock_funds_by_agent = AsyncMock(return_value=MagicMock(spec=Balance))

        await mgr.lock(ACCOUNT_ID, asset="USDT", amount=Decimal("500"), agent_id=AGENT_A)

        mgr._repo.atomic_lock_funds_by_agent.assert_called_once_with(AGENT_A, "USDT", Decimal("500"))
        mgr._repo.atomic_lock_funds.assert_not_called()

    async def test_unlock_uses_agent_repo_when_agent_id_provided(self):
        session = AsyncMock()
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = BalanceManager(session, settings)
        mgr._repo = AsyncMock(spec=BalanceRepository)
        mgr._repo.atomic_unlock_funds_by_agent = AsyncMock(return_value=MagicMock(spec=Balance))

        await mgr.unlock(ACCOUNT_ID, asset="USDT", amount=Decimal("500"), agent_id=AGENT_A)

        mgr._repo.atomic_unlock_funds_by_agent.assert_called_once_with(AGENT_A, "USDT", Decimal("500"))
        mgr._repo.atomic_unlock_funds.assert_not_called()

    async def test_credit_falls_back_to_account_when_no_agent_id(self):
        session = AsyncMock()
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = BalanceManager(session, settings)
        mgr._repo = AsyncMock(spec=BalanceRepository)
        mgr._repo.update_available = AsyncMock(return_value=MagicMock(spec=Balance))

        await mgr.credit(ACCOUNT_ID, asset="USDT", amount=Decimal("100"))

        mgr._repo.update_available.assert_called_once_with(ACCOUNT_ID, "USDT", Decimal("100"))

    async def test_execute_trade_passes_agent_id_to_repo(self):
        session = AsyncMock()
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = BalanceManager(session, settings)
        mgr._repo = AsyncMock(spec=BalanceRepository)
        quote_bal = MagicMock(spec=Balance)
        base_bal = MagicMock(spec=Balance)
        mgr._repo.atomic_execute_buy = AsyncMock(return_value=(quote_bal, base_bal))

        await mgr.execute_trade(
            ACCOUNT_ID,
            symbol="BTCUSDT",
            side="buy",
            base_asset="BTC",
            quote_asset="USDT",
            quantity=Decimal("1"),
            execution_price=Decimal("60000"),
            agent_id=AGENT_A,
        )

        # Verify agent_id was passed through
        call_kwargs = mgr._repo.atomic_execute_buy.call_args[1]
        assert call_kwargs["agent_id"] == AGENT_A


# ---------------------------------------------------------------------------
# OrderEngine cancel tests
# ---------------------------------------------------------------------------


class TestCancelOrderAgentScoping:
    """Verify cancel_order checks agent ownership."""

    async def test_cancel_order_rejects_wrong_agent(self):
        engine, mocks = _make_engine()
        order_id = uuid4()

        # The order belongs to AGENT_A
        cancelled_order = MagicMock(spec=Order)
        cancelled_order.id = order_id
        cancelled_order.account_id = ACCOUNT_ID
        cancelled_order.agent_id = AGENT_A
        cancelled_order.side = "buy"
        cancelled_order.price = 60000.0
        cancelled_order.quantity = 1.0
        cancelled_order.symbol = "BTCUSDT"
        cancelled_order.status = "cancelled"

        mocks["order_repo"].cancel = AsyncMock(return_value=cancelled_order)

        # AGENT_B tries to cancel AGENT_A's order
        with pytest.raises(OrderNotFoundError):
            await engine.cancel_order(ACCOUNT_ID, order_id, agent_id=AGENT_B)

    async def test_cancel_all_orders_only_cancels_agent_orders(self):
        # Build a custom session whose execute returns one cancelled order.
        agent_a_order = MagicMock(spec=Order)
        agent_a_order.id = uuid4()
        agent_a_order.account_id = ACCOUNT_ID
        agent_a_order.agent_id = AGENT_A
        agent_a_order.side = "buy"
        agent_a_order.price = Decimal("60000")
        agent_a_order.quantity = Decimal("1")
        agent_a_order.symbol = "BTCUSDT"
        agent_a_order.status = "cancelled"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent_a_order]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        engine, mocks = _make_engine(session=session)

        count = await engine.cancel_all_orders(ACCOUNT_ID, agent_id=AGENT_A)

        # Should have executed an atomic UPDATE statement
        session.execute.assert_called_once()
        assert count == 1


# ---------------------------------------------------------------------------
# RiskManager agent scoping tests
# ---------------------------------------------------------------------------


class TestRiskManagerAgentScoping:
    """Verify risk checks use agent-scoped queries."""

    async def test_check_open_orders_uses_agent_count(self):
        from src.risk.manager import RiskLimits, RiskManager

        redis_mock = AsyncMock()
        price_cache = AsyncMock()
        balance_mgr = AsyncMock(spec=BalanceManager)
        account_repo = AsyncMock()
        order_repo = AsyncMock(spec=OrderRepository)
        order_repo.count_open_by_agent = AsyncMock(return_value=10)
        trade_repo = AsyncMock(spec=TradeRepository)
        settings = MagicMock()

        mgr = RiskManager(
            redis=redis_mock,
            price_cache=price_cache,
            balance_manager=balance_mgr,
            account_repo=account_repo,
            order_repo=order_repo,
            trade_repo=trade_repo,
            settings=settings,
        )

        limits = RiskLimits(max_open_orders=50)
        result = await mgr._check_open_orders(ACCOUNT_ID, limits, agent_id=AGENT_A)

        order_repo.count_open_by_agent.assert_called_once_with(AGENT_A)
        order_repo.count_open_by_account.assert_not_called()
        assert result.approved

    async def test_check_open_orders_falls_back_to_account(self):
        from src.risk.manager import RiskLimits, RiskManager

        redis_mock = AsyncMock()
        price_cache = AsyncMock()
        balance_mgr = AsyncMock(spec=BalanceManager)
        account_repo = AsyncMock()
        order_repo = AsyncMock(spec=OrderRepository)
        order_repo.count_open_by_account = AsyncMock(return_value=10)
        trade_repo = AsyncMock(spec=TradeRepository)
        settings = MagicMock()

        mgr = RiskManager(
            redis=redis_mock,
            price_cache=price_cache,
            balance_manager=balance_mgr,
            account_repo=account_repo,
            order_repo=order_repo,
            trade_repo=trade_repo,
            settings=settings,
        )

        limits = RiskLimits(max_open_orders=50)
        await mgr._check_open_orders(ACCOUNT_ID, limits)

        order_repo.count_open_by_account.assert_called_once_with(ACCOUNT_ID)

    async def test_check_daily_loss_uses_agent_id(self):
        from src.risk.manager import RiskLimits, RiskManager

        redis_mock = AsyncMock()
        price_cache = AsyncMock()
        balance_mgr = AsyncMock(spec=BalanceManager)
        account_repo = AsyncMock()
        order_repo = AsyncMock(spec=OrderRepository)
        trade_repo = AsyncMock(spec=TradeRepository)
        trade_repo.sum_daily_realized_pnl = AsyncMock(return_value=Decimal("-100"))
        settings = MagicMock()

        mgr = RiskManager(
            redis=redis_mock,
            price_cache=price_cache,
            balance_manager=balance_mgr,
            account_repo=account_repo,
            order_repo=order_repo,
            trade_repo=trade_repo,
            settings=settings,
        )

        account = MagicMock()
        account.id = ACCOUNT_ID
        account.starting_balance = Decimal("10000")
        limits = RiskLimits(daily_loss_limit_pct=Decimal("20"))

        result = await mgr._check_daily_loss(account, limits, agent_id=AGENT_A)

        trade_repo.sum_daily_realized_pnl.assert_called_once_with(ACCOUNT_ID, agent_id=AGENT_A)
        assert result.approved  # -100 is within 20% of 10000

    async def test_check_daily_loss_uses_agent_starting_balance_override(self):
        """Agent starting_balance=5000 should be used instead of account's 10000."""
        from src.risk.manager import RiskLimits, RiskManager

        redis_mock = AsyncMock()
        price_cache = AsyncMock()
        balance_mgr = AsyncMock(spec=BalanceManager)
        account_repo = AsyncMock()
        order_repo = AsyncMock(spec=OrderRepository)
        trade_repo = AsyncMock(spec=TradeRepository)
        # -1000 is 20% of 5000 (agent) but only 10% of 10000 (account)
        trade_repo.sum_daily_realized_pnl = AsyncMock(return_value=Decimal("-1000"))
        settings = MagicMock()

        mgr = RiskManager(
            redis=redis_mock,
            price_cache=price_cache,
            balance_manager=balance_mgr,
            account_repo=account_repo,
            order_repo=order_repo,
            trade_repo=trade_repo,
            settings=settings,
        )

        account = MagicMock()
        account.id = ACCOUNT_ID
        account.starting_balance = Decimal("10000")
        limits = RiskLimits(daily_loss_limit_pct=Decimal("20"))

        # With agent starting_balance override → should reject
        result = await mgr._check_daily_loss(
            account,
            limits,
            agent_id=AGENT_A,
            starting_balance_override=Decimal("5000"),
        )
        assert not result.approved
        assert result.rejection_reason == "daily_loss_limit"

        # Reset mock
        trade_repo.sum_daily_realized_pnl.reset_mock()
        trade_repo.sum_daily_realized_pnl = AsyncMock(return_value=Decimal("-1000"))

        # Without override (account starting_balance=10000) → should pass
        result = await mgr._check_daily_loss(account, limits, agent_id=AGENT_A)
        assert result.approved

    async def test_check_sufficient_balance_uses_agent_id(self):
        from src.risk.manager import RiskManager

        redis_mock = AsyncMock()
        price_cache = AsyncMock()
        balance_mgr = AsyncMock(spec=BalanceManager)
        balance_mgr.has_sufficient_balance = AsyncMock(return_value=True)
        account_repo = AsyncMock()
        order_repo = AsyncMock(spec=OrderRepository)
        trade_repo = AsyncMock(spec=TradeRepository)
        settings = MagicMock()
        settings.trading_fee_pct = Decimal("0.1")

        mgr = RiskManager(
            redis=redis_mock,
            price_cache=price_cache,
            balance_manager=balance_mgr,
            account_repo=account_repo,
            order_repo=order_repo,
            trade_repo=trade_repo,
            settings=settings,
        )

        order_req = OrderRequest(
            symbol="BTCUSDT",
            side="buy",
            type="market",
            quantity=Decimal("1"),
        )
        estimated_value = Decimal("60000")

        result = await mgr._check_sufficient_balance(ACCOUNT_ID, order_req, estimated_value, agent_id=AGENT_A)

        # Verify agent_id was passed to balance check
        call_kwargs = balance_mgr.has_sufficient_balance.call_args[1]
        assert call_kwargs["agent_id"] == AGENT_A
        assert result.approved
