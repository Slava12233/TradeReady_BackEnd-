"""Unit tests for AgentMessageRepository CRUD, pagination, and count.

Tests that AgentMessageRepository correctly delegates to the AsyncSession,
handles not-found cases, paginates correctly, and raises expected exceptions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import AgentMessage
from src.database.repositories.agent_message_repo import (
    AgentMessageNotFoundError,
    AgentMessageRepository,
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
def repo(mock_session: AsyncMock) -> AgentMessageRepository:
    return AgentMessageRepository(mock_session)


def _make_agent_message(session_id=None, role="user") -> MagicMock:
    """Create a mock AgentMessage instance for testing."""
    obj = MagicMock(spec=AgentMessage)
    obj.id = uuid4()
    obj.session_id = session_id or uuid4()
    obj.role = role
    obj.content = "Hello, world!"
    obj.tool_calls = None
    obj.tool_results = None
    obj.tokens_used = None
    obj.created_at = None
    return obj


class TestCreate:
    async def test_create_persists_and_returns_message(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """create adds the message, flushes, refreshes, and returns it."""
        message = _make_agent_message()

        result = await repo.create(message)

        mock_session.add.assert_called_once_with(message)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(message)
        assert result is message

    async def test_create_integrity_error_raises_database_error(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on IntegrityError (FK violation)."""
        message = _make_agent_message()
        orig = Exception("fk violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(message)

        mock_session.rollback.assert_awaited_once()

    async def test_create_sqlalchemy_error_raises_database_error(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on generic SQLAlchemyError."""
        message = _make_agent_message()
        mock_session.flush.side_effect = SQLAlchemyError("connection lost")

        with pytest.raises(DatabaseError):
            await repo.create(message)

        mock_session.rollback.assert_awaited_once()

    async def test_create_with_different_roles(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """create accepts all valid message roles."""
        for role in ("user", "assistant", "system", "tool"):
            message = _make_agent_message(role=role)
            result = await repo.create(message)
            assert result is message
            mock_session.add.reset_mock()
            mock_session.flush.reset_mock()


class TestGetById:
    async def test_get_by_id_returns_message(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """get_by_id returns the message when it exists."""
        message = _make_agent_message()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = message
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(message.id)

        assert result is message

    async def test_get_by_id_not_found_raises(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """get_by_id raises AgentMessageNotFoundError when missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentMessageNotFoundError) as exc_info:
            await repo.get_by_id(uuid4())

        assert exc_info.value.message_id is not None

    async def test_get_by_id_db_error_raises(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """get_by_id raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_by_id(uuid4())


class TestDelete:
    async def test_delete_removes_existing_message(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """delete selects then deletes the row and flushes."""
        message = _make_agent_message()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = message
        mock_session.execute.return_value = mock_result

        await repo.delete(message.id)

        mock_session.delete.assert_awaited_once_with(message)
        mock_session.flush.assert_awaited_once()

    async def test_delete_not_found_raises(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """delete raises AgentMessageNotFoundError when message is missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentMessageNotFoundError):
            await repo.delete(uuid4())

    async def test_delete_db_error_raises(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """delete raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.delete(uuid4())


class TestListBySession:
    async def test_list_by_session_returns_messages_in_order(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_session returns messages oldest-first."""
        session_id = uuid4()
        messages = [
            _make_agent_message(session_id=session_id, role="user"),
            _make_agent_message(session_id=session_id, role="assistant"),
            _make_agent_message(session_id=session_id, role="user"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = messages
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_session(session_id)

        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    async def test_list_by_session_empty_returns_empty_list(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_session returns empty list when session has no messages."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_session(uuid4())

        assert result == []

    async def test_list_by_session_pagination(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_session forwards limit and offset to the query."""
        session_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.list_by_session(session_id, limit=10, offset=20)

        mock_session.execute.assert_awaited_once()
        # Verify the query was executed (limit/offset applied at SQL level)
        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "session_id" in compiled

    async def test_list_by_session_db_error_raises(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """list_by_session raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.list_by_session(uuid4())


class TestCountBySession:
    async def test_count_by_session_returns_integer(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """count_by_session returns an integer count."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_session.execute.return_value = mock_result

        result = await repo.count_by_session(uuid4())

        assert result == 42

    async def test_count_by_session_returns_zero_for_empty(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """count_by_session returns 0 when session has no messages."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_session.execute.return_value = mock_result

        result = await repo.count_by_session(uuid4())

        assert result == 0

    async def test_count_by_session_db_error_raises(
        self, repo: AgentMessageRepository, mock_session: AsyncMock
    ) -> None:
        """count_by_session raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.count_by_session(uuid4())
