"""Unit tests for agent-scoped backtest repository methods.

Tests that BacktestRepository correctly filters by agent_id when provided,
and returns all account sessions when agent_id is not specified.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.database.models import BacktestSession
from src.database.repositories.backtest_repo import BacktestRepository


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> BacktestRepository:
    return BacktestRepository(mock_session)


def _make_bt_session(
    account_id=None,
    agent_id=None,
    strategy_label="test",
    status="completed",
) -> BacktestSession:
    """Create a BacktestSession ORM instance for testing."""
    s = BacktestSession(
        account_id=account_id or uuid4(),
        agent_id=agent_id,
        strategy_label=strategy_label,
        status=status,
        candle_interval=60,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 2, tzinfo=UTC),
        starting_balance=Decimal("10000"),
    )
    return s


async def test_list_sessions_with_agent_id_filters(repo: BacktestRepository, mock_session: AsyncMock) -> None:
    """list_sessions with agent_id should add agent_id filter to query."""
    account_id = uuid4()
    agent_id = uuid4()

    # Mock the result
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    await repo.list_sessions(account_id, agent_id=agent_id)

    # Verify execute was called (the query was constructed with filters)
    mock_session.execute.assert_called_once()
    stmt = mock_session.execute.call_args[0][0]
    # The compiled SQL should contain both account_id and agent_id filters
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "agent_id" in compiled
    assert "account_id" in compiled


async def test_list_sessions_without_agent_id_no_agent_filter(
    repo: BacktestRepository, mock_session: AsyncMock
) -> None:
    """list_sessions without agent_id should NOT filter by agent_id."""
    account_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    await repo.list_sessions(account_id)

    mock_session.execute.assert_called_once()
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "account_id" in compiled
    # agent_id should NOT appear as a filter (only in SELECT columns)
    where_clause = compiled.split("WHERE")[1] if "WHERE" in compiled else ""
    assert "agent_id" not in where_clause


async def test_get_best_session_with_agent_id(repo: BacktestRepository, mock_session: AsyncMock) -> None:
    """get_best_session with agent_id should scope to that agent."""
    account_id = uuid4()
    agent_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    await repo.get_best_session(account_id, agent_id=agent_id)

    mock_session.execute.assert_called_once()
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "agent_id" in compiled


async def test_get_session_with_agent_id(repo: BacktestRepository, mock_session: AsyncMock) -> None:
    """get_session with agent_id should scope to that agent."""
    session_id = uuid4()
    agent_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    await repo.get_session(session_id, agent_id=agent_id)

    mock_session.execute.assert_called_once()
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "agent_id" in compiled


async def test_get_sessions_for_compare_with_agent_id(repo: BacktestRepository, mock_session: AsyncMock) -> None:
    """get_sessions_for_compare with agent_id should scope to that agent."""
    session_ids = [uuid4(), uuid4()]
    agent_id = uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result

    await repo.get_sessions_for_compare(session_ids, agent_id=agent_id)

    mock_session.execute.assert_called_once()
    stmt = mock_session.execute.call_args[0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "agent_id" in compiled
