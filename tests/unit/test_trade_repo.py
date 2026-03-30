"""Unit tests for TradeRepository CRUD and query operations.

Tests that TradeRepository correctly delegates to the AsyncSession
and handles filtering, pagination, and error scenarios.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import Trade
from src.database.repositories.trade_repo import TradeRepository
from src.utils.exceptions import DatabaseError, TradeNotFoundError


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
def repo(mock_session: AsyncMock) -> TradeRepository:
    return TradeRepository(mock_session)


def _make_trade(
    account_id=None,
    agent_id=None,
    order_id=None,
    symbol="BTCUSDT",
    side="buy",
    quantity="0.01000000",
    price="50000.00000000",
    quote_amount="500.00000000",
    fee="0.50000000",
    realized_pnl=None,
) -> Trade:
    """Create a Trade instance for testing."""
    return Trade(
        account_id=account_id or uuid4(),
        agent_id=agent_id,
        order_id=order_id or uuid4(),
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        quote_amount=Decimal(quote_amount),
        fee=Decimal(fee),
        realized_pnl=Decimal(realized_pnl) if realized_pnl else None,
    )


class TestCreate:
    async def test_create_trade_inserts_and_flushes(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """create inserts trade, flushes, and refreshes."""
        trade = _make_trade()

        result = await repo.create(trade)

        mock_session.add.assert_called_once_with(trade)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(trade)
        assert result is trade

    async def test_create_integrity_error_raises(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on FK violation."""
        trade = _make_trade()
        orig = Exception("FK violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(trade)

        mock_session.rollback.assert_awaited_once()

    async def test_create_db_error_raises(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on generic SQLAlchemy error."""
        trade = _make_trade()
        mock_session.flush.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.create(trade)


class TestGetById:
    async def test_get_by_id_returns_trade(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """get_by_id returns trade when found."""
        trade = _make_trade()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = trade
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(uuid4())

        assert result is trade

    async def test_get_by_id_not_found_raises(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises TradeNotFoundError when no row."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(TradeNotFoundError):
            await repo.get_by_id(uuid4())

    async def test_get_by_id_with_account_scope(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """get_by_id with account_id adds ownership filter."""
        trade = _make_trade()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = trade
        mock_session.execute.return_value = mock_result

        await repo.get_by_id(uuid4(), account_id=uuid4())

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "account_id" in compiled


class TestListByAccount:
    async def test_list_by_account_returns_trades(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_account returns trades for account."""
        trades = [_make_trade(), _make_trade(side="sell")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = trades
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_account(uuid4())

        assert len(result) == 2

    async def test_list_by_account_with_symbol_filter(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_account with symbol filters by symbol."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), symbol="ETHUSDT")

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "symbol" in compiled

    async def test_list_by_account_with_side_filter(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_account with side filters by buy/sell."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), side="buy")

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "side" in compiled

    async def test_list_by_account_with_agent_filter(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_account with agent_id scopes to agent."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), agent_id=uuid4())

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled

    async def test_list_by_account_with_pagination(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_account with limit + offset works correctly."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_account(uuid4(), limit=50, offset=10)

        mock_session.execute.assert_awaited_once()

    async def test_list_by_account_db_error_raises(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_account raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.list_by_account(uuid4())


class TestListByAgent:
    async def test_list_by_agent_returns_trades(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_agent returns trades scoped to agent."""
        trades = [_make_trade()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = trades
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(uuid4())

        assert len(result) == 1
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled


class TestListBySymbol:
    async def test_list_by_symbol_returns_trades(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_symbol returns trades filtered by symbol."""
        trades = [_make_trade(symbol="ETHUSDT")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = trades
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_symbol("ETHUSDT")

        assert len(result) == 1

    async def test_list_by_symbol_empty(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """list_by_symbol returns empty list for unknown symbol."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_symbol("FOOBARUSDT")

        assert result == []


class TestCountByAccount:
    async def test_get_trade_count(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """count_by_account returns total count for account."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_session.execute.return_value = mock_result

        result = await repo.count_by_account(uuid4())

        assert result == 42

    async def test_get_trade_count_with_agent(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """count_by_account with agent_id scopes to agent."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 10
        mock_session.execute.return_value = mock_result

        result = await repo.count_by_account(uuid4(), agent_id=uuid4())

        assert result == 10
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled

    async def test_get_trade_count_db_error_raises(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """count_by_account raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.count_by_account(uuid4())


class TestSumDailyPnl:
    async def test_sum_daily_realized_pnl_returns_decimal(self, repo: TradeRepository, mock_session: AsyncMock) -> None:
        """sum_daily_realized_pnl returns Decimal sum."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = Decimal("150.50")
        mock_session.execute.return_value = mock_result

        result = await repo.sum_daily_realized_pnl(uuid4())

        assert result == Decimal("150.50")

    async def test_sum_daily_realized_pnl_zero_when_no_trades(
        self, repo: TradeRepository, mock_session: AsyncMock
    ) -> None:
        """sum_daily_realized_pnl returns 0 when no trades."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_session.execute.return_value = mock_result

        result = await repo.sum_daily_realized_pnl(uuid4())

        assert result == Decimal("0")

    async def test_sum_daily_realized_pnl_with_specific_day(
        self, repo: TradeRepository, mock_session: AsyncMock
    ) -> None:
        """sum_daily_realized_pnl accepts specific day parameter."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = Decimal("-200")
        mock_session.execute.return_value = mock_result

        result = await repo.sum_daily_realized_pnl(uuid4(), day=date(2026, 3, 15))

        assert result == Decimal("-200")
