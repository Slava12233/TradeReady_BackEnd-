"""Unit tests for OrderRepository CRUD and lifecycle operations.

Tests that OrderRepository correctly delegates to the AsyncSession
and raises the expected exceptions on errors.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import Order
from src.database.repositories.order_repo import OrderRepository
from src.utils.exceptions import (
    DatabaseError,
    OrderNotCancellableError,
    OrderNotFoundError,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> OrderRepository:
    return OrderRepository(mock_session)


def _make_order(
    account_id=None,
    agent_id=None,
    symbol="BTCUSDT",
    side="buy",
    type="market",
    quantity="0.01000000",
    status="pending",
    **kwargs,
) -> Order:
    """Create an Order instance for testing."""
    return Order(
        account_id=account_id or uuid4(),
        agent_id=agent_id,
        symbol=symbol,
        side=side,
        type=type,
        quantity=Decimal(quantity),
        status=status,
        **kwargs,
    )


class TestCreate:
    async def test_create_order_inserts_and_flushes(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """create inserts order, flushes, and refreshes."""
        order = _make_order()

        result = await repo.create(order)

        mock_session.add.assert_called_once_with(order)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(order)
        assert result is order

    async def test_create_integrity_error_raises(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on constraint violation."""
        order = _make_order()
        orig = Exception("FK violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(order)

        mock_session.rollback.assert_awaited_once()

    async def test_create_db_error_raises(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on generic SQLAlchemy error."""
        order = _make_order()
        mock_session.flush.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.create(order)


class TestGetById:
    async def test_get_by_id_returns_order(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """get_by_id returns order when found."""
        order = _make_order()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid4())

        assert result is order

    async def test_get_by_id_not_found_raises(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises OrderNotFoundError when no row."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(OrderNotFoundError):
            await repo.get_by_id(uuid4())

    async def test_get_by_id_with_account_scope(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """get_by_id with account_id adds ownership filter."""
        order = _make_order()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid4(), account_id=uuid4())

        assert result is order
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "account_id" in compiled


class TestListByAccount:
    async def test_list_by_account_returns_orders(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_by_account returns orders for account."""
        orders = [_make_order(), _make_order(side="sell")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = orders
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_account(uuid4())

        assert len(result) == 2

    async def test_list_by_account_with_status_filter(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_by_account with status parameter filters correctly."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), status="pending")

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "status" in compiled

    async def test_list_by_account_with_symbol_filter(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_by_account with symbol parameter filters correctly."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), symbol="BTCUSDT")

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "symbol" in compiled

    async def test_list_by_account_with_agent_filter(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_by_account with agent_id filters by agent."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), agent_id=uuid4())

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled


class TestListByAgent:
    async def test_list_by_agent_returns_orders(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_by_agent returns orders scoped to agent."""
        orders = [_make_order()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = orders
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(uuid4())

        assert len(result) == 1
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled

    async def test_list_by_agent_db_error_raises(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_by_agent raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.list_by_agent(uuid4())


class TestListPending:
    async def test_list_pending_returns_pending_orders(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_pending filters by status=pending."""
        orders = [_make_order(status="pending")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = orders
        mock_session.execute.return_value = mock_result

        result = await repo.list_pending()

        assert len(result) == 1

    async def test_list_pending_with_symbol_filter(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """list_pending with symbol filters by symbol+status."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_pending(symbol="ETHUSDT")

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "symbol" in compiled


class TestCancel:
    async def test_cancel_pending_order_succeeds(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """cancel transitions a pending order to cancelled."""
        order_id = uuid4()
        account_id = uuid4()
        order = _make_order(account_id=account_id, status="pending")

        # First call: get_by_id returns the pending order
        # Second call: the UPDATE returning
        cancelled_order = _make_order(account_id=account_id, status="cancelled")
        mock_result_get = MagicMock()
        mock_result_get.scalars.return_value.first.return_value = order
        mock_result_update = MagicMock()
        mock_result_update.scalars.return_value.first.return_value = cancelled_order
        mock_session.execute.side_effect = [mock_result_get, mock_result_update]

        result = await repo.cancel(order_id, account_id)

        assert result.status == "cancelled"

    async def test_cancel_filled_order_raises(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """cancel raises OrderNotCancellableError for filled order."""
        order_id = uuid4()
        account_id = uuid4()
        order = _make_order(account_id=account_id, status="filled")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = mock_result

        with pytest.raises(OrderNotCancellableError):
            await repo.cancel(order_id, account_id)


class TestUpdateStatus:
    async def test_update_status_returns_updated(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """update_status returns order with new status."""
        order = _make_order(status="filled")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = mock_result

        result = await repo.update_status(uuid4(), "filled")

        assert result is order

    async def test_update_status_with_extra_fields(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """update_status passes extra_fields to UPDATE."""
        order = _make_order(status="filled")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = order
        mock_session.execute.return_value = mock_result

        extra = {"executed_price": Decimal("50000"), "executed_qty": Decimal("0.01")}
        result = await repo.update_status(uuid4(), "filled", extra_fields=extra)

        assert result is order

    async def test_update_status_not_found_raises(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """update_status raises OrderNotFoundError when row missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(OrderNotFoundError):
            await repo.update_status(uuid4(), "filled")


class TestCountOpen:
    async def test_count_open_by_account(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """count_open_by_account returns count of pending orders."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 5
        mock_session.execute.return_value = mock_result

        result = await repo.count_open_by_account(uuid4())

        assert result == 5

    async def test_count_open_by_agent(self, repo: OrderRepository, mock_session: AsyncMock) -> None:
        """count_open_by_agent returns count for specific agent."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 3
        mock_session.execute.return_value = mock_result

        result = await repo.count_open_by_agent(uuid4())

        assert result == 3
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled
