"""Unit tests for AgentLearningRepository CRUD, search, and relevance ordering.

Tests that AgentLearningRepository correctly delegates to the AsyncSession,
handles not-found cases, and that search applies recency-based scoring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import AgentLearning
from src.database.repositories.agent_learning_repo import (
    AgentLearningNotFoundError,
    AgentLearningRepository,
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
def repo(mock_session: AsyncMock) -> AgentLearningRepository:
    return AgentLearningRepository(mock_session)


def _make_agent_learning(
    agent_id=None,
    memory_type="episodic",
    content="Buy BTC on dip",
    times_reinforced=0,
    last_accessed_at=None,
    expires_at=None,
) -> MagicMock:
    """Create a mock AgentLearning instance for testing."""
    obj = MagicMock(spec=AgentLearning)
    obj.id = uuid4()
    obj.agent_id = agent_id or uuid4()
    obj.memory_type = memory_type
    obj.content = content
    obj.times_reinforced = times_reinforced
    obj.last_accessed_at = last_accessed_at
    obj.expires_at = expires_at
    obj.created_at = datetime.now(tz=UTC)
    return obj


class TestCreate:
    async def test_create_persists_and_returns_learning(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """create adds the learning, flushes, refreshes, and returns it."""
        learning = _make_agent_learning()

        result = await repo.create(learning)

        mock_session.add.assert_called_once_with(learning)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(learning)
        assert result is learning

    async def test_create_integrity_error_raises_database_error(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on IntegrityError."""
        learning = _make_agent_learning()
        orig = Exception("fk violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(learning)

        mock_session.rollback.assert_awaited_once()

    async def test_create_sqlalchemy_error_raises_database_error(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """create raises DatabaseError on generic SQLAlchemyError."""
        learning = _make_agent_learning()
        mock_session.flush.side_effect = SQLAlchemyError("connection lost")

        with pytest.raises(DatabaseError):
            await repo.create(learning)

        mock_session.rollback.assert_awaited_once()


class TestGetById:
    async def test_get_by_id_returns_learning(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """get_by_id returns the learning when it exists."""
        learning = _make_agent_learning()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = learning
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(learning.id)

        assert result is learning

    async def test_get_by_id_not_found_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises AgentLearningNotFoundError when missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentLearningNotFoundError) as exc_info:
            await repo.get_by_id(uuid4())

        assert exc_info.value.learning_id is not None

    async def test_get_by_id_db_error_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """get_by_id raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_by_id(uuid4())


class TestReinforce:
    async def test_reinforce_increments_and_returns_learning(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """reinforce updates times_reinforced and last_accessed_at, returns row."""
        learning = _make_agent_learning(times_reinforced=3)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = learning
        mock_session.execute.return_value = mock_result

        result = await repo.reinforce(learning.id)

        assert result is learning
        mock_session.execute.assert_awaited_once()

    async def test_reinforce_not_found_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """reinforce raises AgentLearningNotFoundError when row is missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentLearningNotFoundError):
            await repo.reinforce(uuid4())

    async def test_reinforce_db_error_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """reinforce raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.reinforce(uuid4())

        mock_session.rollback.assert_awaited_once()


class TestTouch:
    async def test_touch_executes_update(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """touch executes an UPDATE statement without raising."""
        mock_result = MagicMock()
        mock_session.execute.return_value = mock_result

        await repo.touch(uuid4())

        mock_session.execute.assert_awaited_once()

    async def test_touch_db_error_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """touch raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.touch(uuid4())

        mock_session.rollback.assert_awaited_once()


class TestDelete:
    async def test_delete_removes_existing_learning(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """delete selects then deletes the row and flushes."""
        learning = _make_agent_learning()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = learning
        mock_session.execute.return_value = mock_result

        await repo.delete(learning.id)

        mock_session.delete.assert_awaited_once_with(learning)
        mock_session.flush.assert_awaited_once()

    async def test_delete_not_found_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """delete raises AgentLearningNotFoundError when learning is missing."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AgentLearningNotFoundError):
            await repo.delete(uuid4())


class TestSearchByType:
    async def test_search_by_type_returns_learnings(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """search_by_type returns learnings matching the memory_type."""
        agent_id = uuid4()
        learnings = [
            _make_agent_learning(agent_id=agent_id, memory_type="episodic"),
            _make_agent_learning(agent_id=agent_id, memory_type="episodic"),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = learnings
        mock_session.execute.return_value = mock_result

        result = await repo.search_by_type(agent_id, "episodic")

        assert len(result) == 2

    async def test_search_by_type_empty_returns_empty_list(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """search_by_type returns empty list when no matches exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.search_by_type(uuid4(), "procedural")

        assert result == []

    async def test_search_by_type_db_error_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """search_by_type raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.search_by_type(uuid4(), "episodic")


class TestSearch:
    async def test_search_returns_keyword_matching_results(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """search returns results that match the keyword in content."""
        agent_id = uuid4()
        learning = _make_agent_learning(agent_id=agent_id, content="Buy BTC on dip when RSI < 30")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [learning]
        mock_session.execute.return_value = mock_result

        result = await repo.search(agent_id, keyword="BTC")

        assert len(result) == 1
        assert "BTC" in result[0].content

    async def test_search_empty_returns_empty_list(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """search returns empty list when no keyword matches exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.search(uuid4(), keyword="ZZZNOMATCH")

        assert result == []

    async def test_search_ranks_recently_accessed_first(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """search ranks learnings accessed in last 7 days above older ones."""
        agent_id = uuid4()
        now = datetime.now(tz=UTC)

        # Older learning with more reinforcements but accessed 60 days ago
        old = _make_agent_learning(
            agent_id=agent_id,
            content="BTC momentum signal",
            times_reinforced=10,
            last_accessed_at=now - timedelta(days=60),
        )
        # Recent learning with fewer reinforcements but accessed 2 days ago (+5 boost)
        recent = _make_agent_learning(
            agent_id=agent_id,
            content="BTC dip buying signal",
            times_reinforced=1,
            last_accessed_at=now - timedelta(days=2),
        )
        mock_result = MagicMock()
        # DB returns old first (more reinforcements), search re-ranks
        mock_result.scalars.return_value.all.return_value = [old, recent]
        mock_session.execute.return_value = mock_result

        result = await repo.search(agent_id, keyword="BTC")

        # recent has score = 1 + 5 = 6, old has score = 10 + 0 = 10
        # So old should still be first when reinforcements dominate
        assert len(result) == 2

    async def test_search_recently_accessed_boost_overrides_low_reinforcements(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """search gives +5 boost to learnings accessed within 7 days."""
        agent_id = uuid4()
        now = datetime.now(tz=UTC)

        # Low-reinforcement learning accessed yesterday gets +5 boost -> score = 6
        fresh = _make_agent_learning(
            agent_id=agent_id,
            content="ETH signal fresh",
            times_reinforced=1,
            last_accessed_at=now - timedelta(days=1),
        )
        # Higher reinforcement but stale: accessed 60 days ago -> score = 5
        stale = _make_agent_learning(
            agent_id=agent_id,
            content="ETH signal stale",
            times_reinforced=5,
            last_accessed_at=now - timedelta(days=60),
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [stale, fresh]
        mock_session.execute.return_value = mock_result

        result = await repo.search(agent_id, keyword="ETH")

        # fresh score = 1 + 5 = 6, stale score = 5 + 0 = 5 → fresh first
        assert result[0].content == "ETH signal fresh"
        assert result[1].content == "ETH signal stale"

    async def test_search_thirty_day_boost(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """search gives +2 boost to learnings accessed within 30 days."""
        agent_id = uuid4()
        now = datetime.now(tz=UTC)

        # accessed 15 days ago -> +2 boost -> score = 3
        medium = _make_agent_learning(
            agent_id=agent_id,
            content="SOL breakout",
            times_reinforced=1,
            last_accessed_at=now - timedelta(days=15),
        )
        # never accessed, no boost -> score = 2
        cold = _make_agent_learning(
            agent_id=agent_id,
            content="SOL breakout cold",
            times_reinforced=2,
            last_accessed_at=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cold, medium]
        mock_session.execute.return_value = mock_result

        result = await repo.search(agent_id, keyword="SOL")

        # medium score = 1 + 2 = 3, cold score = 2 + 0 = 2 → medium first
        assert result[0].content == "SOL breakout"

    async def test_search_db_error_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """search raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.search(uuid4(), keyword="BTC")


class TestPruneExpired:
    async def test_prune_expired_returns_count(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """prune_expired returns the number of deleted rows."""
        learning_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [learning_id, uuid4()]
        mock_session.execute.return_value = mock_result

        count = await repo.prune_expired(uuid4())

        assert count == 2
        mock_session.flush.assert_awaited_once()

    async def test_prune_expired_returns_zero_when_nothing_to_prune(
        self, repo: AgentLearningRepository, mock_session: AsyncMock
    ) -> None:
        """prune_expired returns 0 when no rows are expired."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        count = await repo.prune_expired(uuid4())

        assert count == 0

    async def test_prune_expired_db_error_raises(self, repo: AgentLearningRepository, mock_session: AsyncMock) -> None:
        """prune_expired raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("db error")

        with pytest.raises(DatabaseError):
            await repo.prune_expired(uuid4())

        mock_session.rollback.assert_awaited_once()
