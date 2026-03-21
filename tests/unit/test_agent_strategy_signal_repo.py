"""Unit tests for src/database/repositories/agent_strategy_signal_repo.py."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.repositories.agent_strategy_signal_repo import AgentStrategySignalRepository
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


def _make_signal(agent_id=None):
    """Return a mock AgentStrategySignal ORM instance."""
    signal = MagicMock()
    signal.id = uuid4()
    signal.agent_id = agent_id or uuid4()
    signal.trace_id = "abc123"
    signal.strategy_name = "ppo_rl"
    signal.symbol = "BTCUSDT"
    signal.action = "buy"
    signal.confidence = Decimal("0.85")
    signal.weight = Decimal("0.40")
    signal.signal_data = {}
    return signal


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


class TestCreate:
    """Tests for AgentStrategySignalRepository.create()."""

    async def test_create_adds_and_flushes(self) -> None:
        """create() calls session.add() and session.flush() then returns the signal."""
        session = _make_mock_session()
        repo = AgentStrategySignalRepository(session)
        signal = _make_signal()

        result = await repo.create(signal)

        session.add.assert_called_once_with(signal)
        session.flush.assert_called_once()
        session.refresh.assert_called_once_with(signal)
        assert result is signal

    async def test_create_refreshes_to_get_server_defaults(self) -> None:
        """create() calls session.refresh() so server-generated id/created_at are populated."""
        session = _make_mock_session()
        repo = AgentStrategySignalRepository(session)
        signal = _make_signal()

        await repo.create(signal)

        session.refresh.assert_called_once_with(signal)

    async def test_create_integrity_error_raises_database_error(self) -> None:
        """create() raises DatabaseError when an IntegrityError is caught."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception()))
        repo = AgentStrategySignalRepository(session)

        with pytest.raises(DatabaseError):
            await repo.create(_make_signal())

        session.rollback.assert_called_once()

    async def test_create_sqlalchemy_error_raises_database_error(self) -> None:
        """create() raises DatabaseError when a generic SQLAlchemyError is caught."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=SQLAlchemyError("connection lost"))
        repo = AgentStrategySignalRepository(session)

        with pytest.raises(DatabaseError):
            await repo.create(_make_signal())

        session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# bulk_create()
# ---------------------------------------------------------------------------


class TestBulkCreate:
    """Tests for AgentStrategySignalRepository.bulk_create()."""

    async def test_bulk_create_calls_add_all_with_all_signals(self) -> None:
        """bulk_create() calls session.add_all() with the full list."""
        session = _make_mock_session()
        repo = AgentStrategySignalRepository(session)
        agent_id = uuid4()
        signals = [_make_signal(agent_id=agent_id) for _ in range(4)]

        count = await repo.bulk_create(signals)

        session.add_all.assert_called_once_with(signals)
        session.flush.assert_called_once()
        assert count == 4

    async def test_bulk_create_returns_correct_count(self) -> None:
        """bulk_create() returns the number of rows inserted."""
        session = _make_mock_session()
        repo = AgentStrategySignalRepository(session)
        agent_id = uuid4()
        signals = [_make_signal(agent_id=agent_id) for _ in range(7)]

        count = await repo.bulk_create(signals)

        assert count == 7

    async def test_bulk_create_empty_list_returns_zero_without_db_call(self) -> None:
        """bulk_create([]) short-circuits and returns 0 without touching the DB."""
        session = _make_mock_session()
        repo = AgentStrategySignalRepository(session)

        count = await repo.bulk_create([])

        assert count == 0
        session.add_all.assert_not_called()
        session.flush.assert_not_called()

    async def test_bulk_create_integrity_error_raises_database_error(self) -> None:
        """bulk_create() raises DatabaseError on IntegrityError."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=IntegrityError("stmt", {}, Exception()))
        repo = AgentStrategySignalRepository(session)
        signals = [_make_signal()]

        with pytest.raises(DatabaseError):
            await repo.bulk_create(signals)

        session.rollback.assert_called_once()

    async def test_bulk_create_sqlalchemy_error_raises_database_error(self) -> None:
        """bulk_create() raises DatabaseError on generic SQLAlchemyError."""
        session = _make_mock_session()
        session.flush = AsyncMock(side_effect=SQLAlchemyError("timeout"))
        repo = AgentStrategySignalRepository(session)
        signals = [_make_signal()]

        with pytest.raises(DatabaseError):
            await repo.bulk_create(signals)

        session.rollback.assert_called_once()

    async def test_bulk_create_single_signal(self) -> None:
        """bulk_create() works correctly for a list with exactly one signal."""
        session = _make_mock_session()
        repo = AgentStrategySignalRepository(session)
        signals = [_make_signal()]

        count = await repo.bulk_create(signals)

        assert count == 1
        session.add_all.assert_called_once_with(signals)
