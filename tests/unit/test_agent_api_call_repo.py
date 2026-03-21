"""Unit tests for src/database/repositories/agent_api_call_repo.py."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.repositories.agent_api_call_repo import AgentApiCallRepository
from src.utils.exceptions import DatabaseError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session() -> AsyncMock:
    """Return a mock AsyncSession with standard methods wired."""
    session = AsyncMock()
    session.add = MagicMock()  # synchronous in SQLAlchemy
    session.add_all = MagicMock()  # synchronous in SQLAlchemy
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_api_call(agent_id=None):
    """Return a mock AgentApiCall ORM instance."""
    call = MagicMock()
    call.id = uuid4()
    call.agent_id = agent_id or uuid4()
    call.trace_id = "abc123"
    call.channel = "rest"
    call.endpoint = "/api/v1/market/prices"
    call.method = "GET"
    call.status_code = 200
    call.latency_ms = Decimal("42.50")
    call.error = None
    return call


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for AgentApiCallRepository.create()."""

    async def test_create_adds_and_flushes(self) -> None:
        """create() calls session.add() and session.flush() then returns the record."""
        session = _make_mock_session()
        repo = AgentApiCallRepository(session)
        api_call = _make_api_call()

        result = await repo.create(api_call)

        session.add.assert_called_once_with(api_call)
        session.flush.assert_called_once()
        session.refresh.assert_called_once_with(api_call)
        assert result is api_call

    async def test_create_refreshes_to_get_server_defaults(self) -> None:
        """create() calls session.refresh() so server-generated id/created_at are populated."""
        session = _make_mock_session()
        repo = AgentApiCallRepository(session)
        api_call = _make_api_call()

        await repo.create(api_call)

        session.refresh.assert_called_once_with(api_call)

    async def test_create_integrity_error_raises_database_error(self) -> None:
        """create() raises DatabaseError when an IntegrityError is caught."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception()))
        repo = AgentApiCallRepository(session)

        with pytest.raises(DatabaseError):
            await repo.create(_make_api_call())

        session.rollback.assert_called_once()

    async def test_create_sqlalchemy_error_raises_database_error(self) -> None:
        """create() raises DatabaseError when a generic SQLAlchemyError is caught."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=SQLAlchemyError("connection lost"))
        repo = AgentApiCallRepository(session)

        with pytest.raises(DatabaseError):
            await repo.create(_make_api_call())

        session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# bulk_create()
# ---------------------------------------------------------------------------


class TestBulkCreate:
    """Tests for AgentApiCallRepository.bulk_create()."""

    async def test_bulk_create_calls_add_all_with_all_records(self) -> None:
        """bulk_create() calls session.add_all() with the full list."""
        session = _make_mock_session()
        repo = AgentApiCallRepository(session)
        agent_id = uuid4()
        calls = [_make_api_call(agent_id=agent_id) for _ in range(5)]

        count = await repo.bulk_create(calls)

        session.add_all.assert_called_once_with(calls)
        session.flush.assert_called_once()
        assert count == 5

    async def test_bulk_create_returns_correct_count(self) -> None:
        """bulk_create() returns the number of rows inserted."""
        session = _make_mock_session()
        repo = AgentApiCallRepository(session)
        agent_id = uuid4()
        calls = [_make_api_call(agent_id=agent_id) for _ in range(3)]

        count = await repo.bulk_create(calls)

        assert count == 3

    async def test_bulk_create_empty_list_returns_zero_without_db_call(self) -> None:
        """bulk_create([]) short-circuits and returns 0 without touching the DB."""
        session = _make_mock_session()
        repo = AgentApiCallRepository(session)

        count = await repo.bulk_create([])

        assert count == 0
        session.add_all.assert_not_called()
        session.flush.assert_not_called()

    async def test_bulk_create_integrity_error_raises_database_error(self) -> None:
        """bulk_create() raises DatabaseError on IntegrityError."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception()))
        repo = AgentApiCallRepository(session)
        agent_id = uuid4()
        calls = [_make_api_call(agent_id=agent_id)]

        with pytest.raises(DatabaseError):
            await repo.bulk_create(calls)

        session.rollback.assert_called_once()

    async def test_bulk_create_sqlalchemy_error_raises_database_error(self) -> None:
        """bulk_create() raises DatabaseError on generic SQLAlchemyError."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=SQLAlchemyError("timeout"))
        repo = AgentApiCallRepository(session)
        agent_id = uuid4()
        calls = [_make_api_call(agent_id=agent_id)]

        with pytest.raises(DatabaseError):
            await repo.bulk_create(calls)

        session.rollback.assert_called_once()
