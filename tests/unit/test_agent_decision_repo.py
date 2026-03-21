"""Unit tests for AgentDecisionRepository CRUD, outcome updates, and filtering.

Tests that AgentDecisionRepository correctly delegates to the AsyncSession,
handles not-found cases, updates outcomes, and filters by type/symbol.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import AgentDecision
from src.database.repositories.agent_decision_repo import (
    AgentDecisionNotFoundError,
    AgentDecisionRepository,
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
def repo(mock_session: AsyncMock) -> AgentDecisionRepository:
    return AgentDecisionRepository(mock_session)


def _make_agent_decision(
    agent_id=None,
    decision_type="trade",
    symbol="BTCUSDT",
    direction="buy",
    order_id=None,
) -> MagicMock:
    """Create a mock AgentDecision instance for testing."""
    obj = MagicMock(spec=AgentDecision)
    obj.id = uuid4()
    obj.agent_id = agent_id or uuid4()
    obj.decision_type = decision_type
    obj.symbol = symbol
    obj.direction = direction
    obj.order_id = order_id
    obj.outcome_pnl = None
    obj.outcome_recorded_at = None
    obj.created_at = datetime.now(tz=UTC)
    return obj


class TestCreate:
    async def test_create_persists_and_returns_decision(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """create adds the decision, flushes, refreshes, and returns it."""
        decision = _make_agent_decision()

        result = await repo.create(decision)

        mock_session.add.assert_called_once_with(decision)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(decision)
        assert result is decision

    async def test_create_integrity_error_raises_database_error(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on IntegrityError."""
        decision = _make_agent_decision()
        orig = Exception("fk violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(decision)

        mock_session.rollback.assert_awaited_once()

    async def test_create_sqlalchemy_error_raises_database_error(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on generic SQLAlchemyError."""
        decision = _make_agent_decision()
        mock_session.flush.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.create(decision)

        mock_session.rollback.assert_awaited_once()


class TestGetById:
    async def test_get_by_id_returns_decision(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """get_by_id returns the decision when it exists."""
        decision = _make_agent_decision()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = decision
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(decision.id)

        assert result is decision

    async def test_get_by_id_not_found_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """get_by_id raises AgentDecisionNotFoundError when missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentDecisionNotFoundError) as exc_info:
            await repo.get_by_id(uuid4())

        assert exc_info.value.decision_id is not None

    async def test_get_by_id_db_error_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """get_by_id raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_by_id(uuid4())


class TestUpdateOutcome:
    async def test_update_outcome_returns_updated_decision(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """update_outcome writes PnL and recorded_at, returns the row."""
        decision = _make_agent_decision()
        decision.outcome_pnl = Decimal("150.50")
        decision.outcome_recorded_at = datetime.now(tz=UTC)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = decision
        mock_session.execute.return_value = mock_result

        result = await repo.update_outcome(
            decision.id,
            outcome_pnl=Decimal("150.50"),
            outcome_recorded_at=datetime.now(tz=UTC),
        )

        assert result is decision
        assert result.outcome_pnl == Decimal("150.50")
        mock_session.execute.assert_awaited_once()

    async def test_update_outcome_not_found_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """update_outcome raises AgentDecisionNotFoundError when row is missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentDecisionNotFoundError):
            await repo.update_outcome(
                uuid4(),
                outcome_pnl=Decimal("0"),
                outcome_recorded_at=datetime.now(tz=UTC),
            )

    async def test_update_outcome_negative_pnl(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """update_outcome accepts negative PnL (losing trade)."""
        decision = _make_agent_decision()
        decision.outcome_pnl = Decimal("-250.00")
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = decision
        mock_session.execute.return_value = mock_result

        result = await repo.update_outcome(
            decision.id,
            outcome_pnl=Decimal("-250.00"),
            outcome_recorded_at=datetime.now(tz=UTC),
        )

        assert result.outcome_pnl == Decimal("-250.00")

    async def test_update_outcome_db_error_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """update_outcome raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.update_outcome(
                uuid4(),
                outcome_pnl=Decimal("100"),
                outcome_recorded_at=datetime.now(tz=UTC),
            )

        mock_session.rollback.assert_awaited_once()


class TestDelete:
    async def test_delete_removes_existing_decision(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """delete selects then deletes the row and flushes."""
        decision = _make_agent_decision()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = decision
        mock_session.execute.return_value = mock_result

        await repo.delete(decision.id)

        mock_session.delete.assert_awaited_once_with(decision)
        mock_session.flush.assert_awaited_once()

    async def test_delete_not_found_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """delete raises AgentDecisionNotFoundError when decision is missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentDecisionNotFoundError):
            await repo.delete(uuid4())


class TestListByAgent:
    async def test_list_by_agent_returns_decisions(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent returns decisions for the agent."""
        agent_id = uuid4()
        decisions = [
            _make_agent_decision(agent_id=agent_id, decision_type="trade"),
            _make_agent_decision(agent_id=agent_id, decision_type="hold"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = decisions
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(agent_id)

        assert len(result) == 2

    async def test_list_by_agent_empty_returns_empty_list(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent returns empty list when no decisions exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(uuid4())

        assert result == []

    async def test_list_by_agent_filters_by_decision_type(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent with decision_type filter executes the query."""
        agent_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_agent(agent_id, decision_type="trade")

        mock_session.execute.assert_awaited_once()

    async def test_list_by_agent_filters_by_symbol(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent with symbol filter executes the query."""
        agent_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_agent(agent_id, symbol="ETHUSDT")

        mock_session.execute.assert_awaited_once()

    async def test_list_by_agent_db_error_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.list_by_agent(uuid4())


class TestFindUnresolved:
    async def test_find_unresolved_returns_decisions_without_outcome(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """find_unresolved returns decisions where outcome_recorded_at is NULL."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_agent_decision(agent_id=agent_id, order_id=order_id)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [decision]
        mock_session.execute.return_value = mock_result

        result = await repo.find_unresolved(agent_id)

        assert len(result) == 1
        assert result[0].outcome_recorded_at is None

    async def test_find_unresolved_empty_when_all_resolved(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """find_unresolved returns empty list when all decisions have outcomes."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.find_unresolved(uuid4())

        assert result == []

    async def test_find_unresolved_db_error_raises(
        self, repo: AgentDecisionRepository, mock_session: AsyncMock
    ) -> None:
        """find_unresolved raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.find_unresolved(uuid4())
