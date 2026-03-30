"""Unit tests for AgentSessionRepository CRUD operations.

Tests that AgentSessionRepository correctly delegates to the AsyncSession,
handles not-found cases, and raises expected exceptions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import AgentSession
from src.database.repositories.agent_session_repo import (
    AgentSessionNotFoundError,
    AgentSessionRepository,
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
def repo(mock_session: AsyncMock) -> AgentSessionRepository:
    return AgentSessionRepository(mock_session)


def _make_agent_session(agent_id=None, is_active=True) -> MagicMock:
    """Create a mock AgentSession instance for testing."""
    obj = MagicMock(spec=AgentSession)
    obj.id = uuid4()
    obj.agent_id = agent_id or uuid4()
    obj.title = "Test Session"
    obj.is_active = is_active
    obj.summary = None
    obj.started_at = None
    obj.ended_at = None
    return obj


class TestCreate:
    async def test_create_persists_and_returns_session(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """create adds the session, flushes, refreshes, and returns it."""
        agent_session = _make_agent_session()

        result = await repo.create(agent_session)

        mock_session.add.assert_called_once_with(agent_session)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(agent_session)
        assert result is agent_session

    async def test_create_integrity_error_raises_database_error(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on IntegrityError (e.g. duplicate FK)."""
        agent_session = _make_agent_session()
        orig = Exception("fk violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(agent_session)

        mock_session.rollback.assert_awaited_once()

    async def test_create_sqlalchemy_error_raises_database_error(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on generic SQLAlchemyError."""
        agent_session = _make_agent_session()
        mock_session.flush.side_effect = SQLAlchemyError("connection lost")

        with pytest.raises(DatabaseError):
            await repo.create(agent_session)

        mock_session.rollback.assert_awaited_once()


class TestGetById:
    async def test_get_by_id_returns_session(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """get_by_id returns the session when it exists."""
        agent_session = _make_agent_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = agent_session
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(agent_session.id)

        assert result is agent_session

    async def test_get_by_id_not_found_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises AgentSessionNotFoundError when missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentSessionNotFoundError):
            await repo.get_by_id(uuid4())

    async def test_get_by_id_db_error_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_by_id(uuid4())


class TestUpdate:
    async def test_update_returns_updated_session(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """update executes an UPDATE statement and returns the row."""
        agent_session = _make_agent_session()
        agent_session.title = "Updated Title"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = agent_session
        mock_session.execute.return_value = mock_result

        result = await repo.update(agent_session.id, title="Updated Title")

        assert result is agent_session
        mock_session.execute.assert_awaited_once()

    async def test_update_not_found_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """update raises AgentSessionNotFoundError when no row is updated."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentSessionNotFoundError):
            await repo.update(uuid4(), title="Ghost")

    async def test_update_db_error_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """update raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.update(uuid4(), title="X")

        mock_session.rollback.assert_awaited_once()


class TestClose:
    async def test_close_sets_is_active_false(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """close delegates to update with is_active=False and ended_at."""
        closed_session = _make_agent_session(is_active=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = closed_session
        mock_session.execute.return_value = mock_result

        result = await repo.close(closed_session.id)

        assert result is closed_session
        mock_session.execute.assert_awaited_once()

    async def test_close_with_summary(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """close passes summary text through to the update call."""
        closed_session = _make_agent_session(is_active=False)
        closed_session.summary = "Session ended cleanly"
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = closed_session
        mock_session.execute.return_value = mock_result

        result = await repo.close(closed_session.id, summary="Session ended cleanly")

        assert result.summary == "Session ended cleanly"


class TestDelete:
    async def test_delete_removes_existing_session(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """delete selects then deletes the row and flushes."""
        agent_session = _make_agent_session()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = agent_session
        mock_session.execute.return_value = mock_result

        await repo.delete(agent_session.id)

        mock_session.delete.assert_awaited_once_with(agent_session)
        mock_session.flush.assert_awaited_once()

    async def test_delete_not_found_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """delete raises AgentSessionNotFoundError when session is missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentSessionNotFoundError):
            await repo.delete(uuid4())


class TestFindActive:
    async def test_find_active_returns_session_when_present(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """find_active returns the active session for an agent."""
        agent_id = uuid4()
        agent_session = _make_agent_session(agent_id=agent_id, is_active=True)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = agent_session
        mock_session.execute.return_value = mock_result

        result = await repo.find_active(agent_id)

        assert result is agent_session
        assert result.is_active is True

    async def test_find_active_returns_none_when_no_active_session(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """find_active returns None when no active session exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.find_active(uuid4())

        assert result is None

    async def test_find_active_db_error_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """find_active raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.find_active(uuid4())


class TestListByAgent:
    async def test_list_by_agent_returns_all_sessions(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent returns all sessions for an agent by default."""
        agent_id = uuid4()
        sessions = [
            _make_agent_session(agent_id=agent_id, is_active=False),
            _make_agent_session(agent_id=agent_id, is_active=True),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sessions
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(agent_id)

        assert len(result) == 2

    async def test_list_by_agent_include_closed_false_filters_inactive(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent with include_closed=False returns only active sessions."""
        agent_id = uuid4()
        active_session = _make_agent_session(agent_id=agent_id, is_active=True)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active_session]
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(agent_id, include_closed=False)

        assert len(result) == 1
        assert result[0].is_active is True

    async def test_list_by_agent_empty_returns_empty_list(
        self, repo: AgentSessionRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_agent returns an empty list when no sessions exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_agent(uuid4())

        assert result == []

    async def test_list_by_agent_db_error_raises(self, repo: AgentSessionRepository, mock_session: AsyncMock) -> None:
        """list_by_agent raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.list_by_agent(uuid4())
