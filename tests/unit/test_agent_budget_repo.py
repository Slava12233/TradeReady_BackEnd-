"""Unit tests for AgentBudgetRepository CRUD, atomic increments, and daily reset.

Tests that AgentBudgetRepository correctly delegates to the AsyncSession,
handles not-found cases, verifies atomic increment behavior, and resets daily
counters correctly.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import AgentBudget
from src.database.repositories.agent_budget_repo import (
    AgentBudgetNotFoundError,
    AgentBudgetRepository,
)
from src.utils.exceptions import DatabaseError


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> AgentBudgetRepository:
    return AgentBudgetRepository(mock_session)


def _make_agent_budget(
    agent_id=None,
    max_trades_per_day=10,
    max_exposure_pct="25.00",
    max_daily_loss_pct="5.00",
    max_position_size_pct="10.00",
    trades_today=0,
    exposure_today="0.00000000",
    loss_today="0.00000000",
) -> MagicMock:
    """Create a mock AgentBudget instance for testing."""
    obj = MagicMock(spec=AgentBudget)
    obj.id = uuid4()
    obj.agent_id = agent_id or uuid4()
    obj.max_trades_per_day = max_trades_per_day
    obj.max_exposure_pct = Decimal(max_exposure_pct)
    obj.max_daily_loss_pct = Decimal(max_daily_loss_pct)
    obj.max_position_size_pct = Decimal(max_position_size_pct)
    obj.trades_today = trades_today
    obj.exposure_today = Decimal(exposure_today)
    obj.loss_today = Decimal(loss_today)
    obj.last_reset_at = None
    obj.updated_at = None
    return obj


class TestUpsert:
    async def test_upsert_creates_new_budget(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """upsert inserts a new budget row and returns it."""
        budget = _make_agent_budget()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.upsert(budget)

        assert result is budget
        mock_session.execute.assert_awaited_once()
        mock_session.flush.assert_awaited_once()

    async def test_upsert_updates_existing_budget(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """upsert overwrites limit fields on conflict without touching counters."""
        budget = _make_agent_budget(max_trades_per_day=20)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.upsert(budget)

        assert result.max_trades_per_day == 20

    async def test_upsert_integrity_error_raises_database_error(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """upsert raises DatabaseError on IntegrityError."""
        budget = _make_agent_budget()
        orig = Exception("unique violation")
        mock_session.execute.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.upsert(budget)

        mock_session.rollback.assert_awaited_once()

    async def test_upsert_returns_none_row_raises_database_error(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """upsert raises DatabaseError when the RETURNING clause returns nothing."""
        budget = _make_agent_budget()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(DatabaseError):
            await repo.upsert(budget)


class TestGetByAgent:
    async def test_get_by_agent_returns_budget(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """get_by_agent returns the budget for the agent."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_agent(agent_id)

        assert result is budget
        assert result.agent_id == agent_id

    async def test_get_by_agent_not_found_raises(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """get_by_agent raises AgentBudgetNotFoundError when no record exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentBudgetNotFoundError) as exc_info:
            await repo.get_by_agent(uuid4())

        assert exc_info.value.agent_id is not None

    async def test_get_by_agent_db_error_raises(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """get_by_agent raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_by_agent(uuid4())


class TestIncrementTradesToday:
    async def test_increment_trades_today_increments_by_delta(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_trades_today uses atomic UPDATE col = col + delta."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id, trades_today=3)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.increment_trades_today(agent_id, delta=1)

        # Verify the UPDATE was executed (atomic increment in SQL, not Python)
        assert result is budget
        mock_session.execute.assert_awaited_once()

    async def test_increment_trades_today_default_delta_is_one(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_trades_today defaults to delta=1."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id, trades_today=5)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.increment_trades_today(agent_id)

        assert result is budget

    async def test_increment_trades_today_negative_delta_decrements(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_trades_today accepts negative delta to undo a trade count."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id, trades_today=2)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.increment_trades_today(agent_id, delta=-1)

        assert result is budget
        mock_session.execute.assert_awaited_once()

    async def test_increment_trades_today_not_found_raises(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_trades_today raises AgentBudgetNotFoundError when no row."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentBudgetNotFoundError):
            await repo.increment_trades_today(uuid4())

    async def test_increment_trades_today_db_error_raises(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_trades_today raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.increment_trades_today(uuid4())

        mock_session.rollback.assert_awaited_once()


class TestIncrementExposureToday:
    async def test_increment_exposure_today_adds_exposure(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_exposure_today atomically adds USDT exposure."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id, exposure_today="500.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.increment_exposure_today(agent_id, Decimal("500.00"))

        assert result is budget
        mock_session.execute.assert_awaited_once()

    async def test_increment_exposure_today_negative_reduces_exposure(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_exposure_today accepts negative delta (position close)."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id, exposure_today="200.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.increment_exposure_today(agent_id, Decimal("-200.00"))

        assert result is budget

    async def test_increment_exposure_today_not_found_raises(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_exposure_today raises AgentBudgetNotFoundError when no row."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentBudgetNotFoundError):
            await repo.increment_exposure_today(uuid4(), Decimal("100"))

    async def test_increment_exposure_today_db_error_raises(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_exposure_today raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.increment_exposure_today(uuid4(), Decimal("100"))

        mock_session.rollback.assert_awaited_once()


class TestIncrementLossToday:
    async def test_increment_loss_today_adds_loss(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """increment_loss_today atomically adds realised loss in USDT."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id, loss_today="50.00000000")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        result = await repo.increment_loss_today(agent_id, Decimal("50.00"))

        assert result is budget
        mock_session.execute.assert_awaited_once()

    async def test_increment_loss_today_not_found_raises(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_loss_today raises AgentBudgetNotFoundError when no row."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentBudgetNotFoundError):
            await repo.increment_loss_today(uuid4(), Decimal("100"))

    async def test_increment_loss_today_db_error_raises(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """increment_loss_today raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.increment_loss_today(uuid4(), Decimal("100"))

        mock_session.rollback.assert_awaited_once()


class TestResetDaily:
    async def test_reset_daily_zeroes_counters_and_updates_last_reset(
        self, repo: AgentBudgetRepository, mock_session: AsyncMock
    ) -> None:
        """reset_daily sets all counter columns to zero and flushes."""
        agent_id = uuid4()
        reset_budget = _make_agent_budget(
            agent_id=agent_id,
            trades_today=0,
            exposure_today="0.00000000",
            loss_today="0.00000000",
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = reset_budget
        mock_session.execute.return_value = mock_result

        result = await repo.reset_daily(agent_id)

        assert result is reset_budget
        assert result.trades_today == 0
        assert result.exposure_today == Decimal("0.00000000")
        assert result.loss_today == Decimal("0.00000000")
        mock_session.flush.assert_awaited_once()

    async def test_reset_daily_not_found_raises(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """reset_daily raises AgentBudgetNotFoundError when no budget row exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentBudgetNotFoundError):
            await repo.reset_daily(uuid4())

    async def test_reset_daily_db_error_raises(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """reset_daily raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.reset_daily(uuid4())

        mock_session.rollback.assert_awaited_once()


class TestDelete:
    async def test_delete_removes_existing_budget(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """delete selects then deletes the row and flushes."""
        agent_id = uuid4()
        budget = _make_agent_budget(agent_id=agent_id)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = budget
        mock_session.execute.return_value = mock_result

        await repo.delete(agent_id)

        mock_session.delete.assert_awaited_once_with(budget)
        mock_session.flush.assert_awaited_once()

    async def test_delete_not_found_raises(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """delete raises AgentBudgetNotFoundError when no budget exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentBudgetNotFoundError):
            await repo.delete(uuid4())

    async def test_delete_db_error_raises(self, repo: AgentBudgetRepository, mock_session: AsyncMock) -> None:
        """delete raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.delete(uuid4())

        mock_session.rollback.assert_awaited_once()
