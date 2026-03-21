"""Tests for agent/memory/postgres_store.py :: PostgresMemoryStore."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from src.database.repositories.agent_learning_repo import AgentLearningNotFoundError
from src.utils.exceptions import DatabaseError

from agent.config import AgentConfig
from agent.memory.store import Memory, MemoryNotFoundError, MemoryType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    """Build a minimal AgentConfig without reading any .env file."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_memory(
    agent_id: str | None = None,
    memory_type: MemoryType = MemoryType.EPISODIC,
    content: str = "BTC crashed 10% after FOMC.",
    confidence: str = "0.8500",
    times_reinforced: int = 1,
) -> Memory:
    """Build a fully-populated Memory fixture."""
    now = datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC)
    return Memory(
        id=str(uuid4()),
        agent_id=agent_id or str(uuid4()),
        memory_type=memory_type,
        content=content,
        source="test_session",
        confidence=Decimal(confidence),
        times_reinforced=times_reinforced,
        created_at=now,
        last_accessed_at=now,
    )


def _make_orm_row(memory: Memory) -> MagicMock:
    """Build a mock AgentLearning ORM row that mirrors the given Memory."""
    row = MagicMock()
    row.id = UUID(memory.id)
    row.agent_id = UUID(memory.agent_id)
    row.memory_type = memory.memory_type.value
    row.content = memory.content
    row.source = memory.source
    row.confidence = memory.confidence
    row.times_reinforced = memory.times_reinforced
    row.created_at = memory.created_at
    row.last_accessed_at = memory.last_accessed_at
    row.expires_at = None
    return row


def _make_store(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Return (store, mock_repo, config) ready for testing."""
    from agent.memory.postgres_store import PostgresMemoryStore

    config = _make_config(monkeypatch)
    mock_repo = AsyncMock()
    # session attribute needed for forget()
    mock_repo._session = AsyncMock()
    mock_repo._session.add = MagicMock()
    mock_repo._session.flush = AsyncMock()
    mock_repo._session.rollback = AsyncMock()

    store = PostgresMemoryStore(repo=mock_repo, config=config)
    return store, mock_repo, config


# ---------------------------------------------------------------------------
# TestPostgresMemoryStoreSave
# ---------------------------------------------------------------------------


class TestPostgresMemoryStoreSave:
    """Tests for PostgresMemoryStore.save()."""

    async def test_save_returns_server_assigned_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """save() returns the UUID string from the ORM row assigned by the DB."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory()
        saved_row = _make_orm_row(mem)
        server_id = uuid4()
        saved_row.id = server_id
        mock_repo.create.return_value = saved_row

        result = await store.save(mem)

        assert result == str(server_id)
        mock_repo.create.assert_called_once()

    async def test_save_constructs_orm_row_from_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """save() passes an AgentLearning ORM object to repo.create()."""
        from src.database.models import AgentLearning

        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory(memory_type=MemoryType.PROCEDURAL)
        saved_row = _make_orm_row(mem)
        mock_repo.create.return_value = saved_row

        await store.save(mem)

        call_args = mock_repo.create.call_args[0]
        orm_row = call_args[0]
        assert isinstance(orm_row, AgentLearning)
        assert orm_row.memory_type == MemoryType.PROCEDURAL.value
        assert orm_row.content == mem.content

    async def test_save_propagates_database_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """save() re-raises DatabaseError from the repository unchanged."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.create.side_effect = DatabaseError("DB write failed.")

        with pytest.raises(DatabaseError, match="DB write failed"):
            await store.save(_make_memory())

    async def test_save_wraps_unexpected_exception_as_database_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save() wraps non-DatabaseError exceptions in DatabaseError."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.create.side_effect = RuntimeError("unexpected")

        with pytest.raises(DatabaseError, match="Failed to save memory"):
            await store.save(_make_memory())


# ---------------------------------------------------------------------------
# TestPostgresMemoryStoreGet
# ---------------------------------------------------------------------------


class TestPostgresMemoryStoreGet:
    """Tests for PostgresMemoryStore.get()."""

    async def test_get_returns_memory_on_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() returns a Memory when the row exists."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory()
        row = _make_orm_row(mem)
        mock_repo.get_by_id.return_value = row
        mock_repo.touch.return_value = None

        result = await store.get(mem.id)

        assert result is not None
        assert result.id == str(row.id)
        assert result.content == mem.content
        assert result.memory_type == mem.memory_type

    async def test_get_returns_none_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() returns None instead of raising when the record is missing."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.get_by_id.side_effect = AgentLearningNotFoundError()

        result = await store.get(str(uuid4()))

        assert result is None

    async def test_get_touches_last_accessed_at(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() calls repo.touch() as a side-effect after a successful fetch."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory()
        row = _make_orm_row(mem)
        mock_repo.get_by_id.return_value = row
        mock_repo.touch.return_value = None

        await store.get(mem.id)

        mock_repo.touch.assert_called_once_with(UUID(mem.id))

    async def test_get_survives_touch_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() still returns the memory when touch() raises DatabaseError."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory()
        row = _make_orm_row(mem)
        mock_repo.get_by_id.return_value = row
        mock_repo.touch.side_effect = DatabaseError("touch failed")

        # Should not raise; touch failure is swallowed.
        result = await store.get(mem.id)
        assert result is not None

    async def test_get_propagates_database_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() re-raises DatabaseError from get_by_id."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.get_by_id.side_effect = DatabaseError("conn lost")

        with pytest.raises(DatabaseError, match="conn lost"):
            await store.get(str(uuid4()))


# ---------------------------------------------------------------------------
# TestPostgresMemoryStoreSearch
# ---------------------------------------------------------------------------


class TestPostgresMemoryStoreSearch:
    """Tests for PostgresMemoryStore.search()."""

    async def test_search_returns_list_of_memories(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """search() converts ORM rows to Memory models."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem1 = _make_memory(content="BTC regime trending")
        mem2 = _make_memory(content="BTC volume spike")
        mock_repo.search.return_value = [_make_orm_row(mem1), _make_orm_row(mem2)]

        results = await store.search(agent_id=mem1.agent_id, query="BTC")

        assert len(results) == 2
        assert all(isinstance(r, Memory) for r in results)

    async def test_search_respects_config_memory_search_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """search() caps the effective limit at config.memory_search_limit."""
        store, mock_repo, config = _make_store(monkeypatch)
        # config.memory_search_limit defaults to 10; pass 9999 as limit
        mock_repo.search.return_value = []

        await store.search(agent_id=str(uuid4()), query="test", limit=9999)

        call_kwargs = mock_repo.search.call_args[1]
        assert call_kwargs["limit"] == config.memory_search_limit

    async def test_search_with_memory_type_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """search() forwards the memory_type string to the repository."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.search.return_value = []

        await store.search(
            agent_id=str(uuid4()),
            query="regime",
            memory_type=MemoryType.PROCEDURAL,
        )

        call_kwargs = mock_repo.search.call_args[1]
        assert call_kwargs["memory_type"] == MemoryType.PROCEDURAL.value

    async def test_search_empty_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """search() returns an empty list when no rows match."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.search.return_value = []

        results = await store.search(agent_id=str(uuid4()), query="no match")

        assert results == []


# ---------------------------------------------------------------------------
# TestPostgresMemoryStoreReinforce
# ---------------------------------------------------------------------------


class TestPostgresMemoryStoreReinforce:
    """Tests for PostgresMemoryStore.reinforce()."""

    async def test_reinforce_calls_repo_reinforce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reinforce() delegates to repo.reinforce() with the correct UUID."""
        store, mock_repo, _ = _make_store(monkeypatch)
        memory_id = str(uuid4())
        mock_repo.reinforce.return_value = MagicMock()

        await store.reinforce(memory_id)

        mock_repo.reinforce.assert_called_once_with(UUID(memory_id))

    async def test_reinforce_raises_memory_not_found_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reinforce() converts AgentLearningNotFoundError to MemoryNotFoundError."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.reinforce.side_effect = AgentLearningNotFoundError()

        with pytest.raises(MemoryNotFoundError):
            await store.reinforce(str(uuid4()))

    async def test_reinforce_propagates_database_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reinforce() re-raises DatabaseError from the repo."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.reinforce.side_effect = DatabaseError("write failed")

        with pytest.raises(DatabaseError, match="write failed"):
            await store.reinforce(str(uuid4()))


# ---------------------------------------------------------------------------
# TestPostgresMemoryStoreForget
# ---------------------------------------------------------------------------


class TestPostgresMemoryStoreForget:
    """Tests for PostgresMemoryStore.forget()."""

    async def test_forget_sets_expires_at_on_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """forget() sets expires_at on the ORM row and flushes the session."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory()
        row = _make_orm_row(mem)
        mock_repo.get_by_id.return_value = row

        await store.forget(mem.id)

        assert row.expires_at is not None
        mock_repo._session.add.assert_called_once_with(row)
        mock_repo._session.flush.assert_called_once()

    async def test_forget_raises_memory_not_found_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """forget() converts AgentLearningNotFoundError to MemoryNotFoundError."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.get_by_id.side_effect = AgentLearningNotFoundError()

        with pytest.raises(MemoryNotFoundError):
            await store.forget(str(uuid4()))

    async def test_forget_propagates_database_error_on_get(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """forget() re-raises DatabaseError from get_by_id."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.get_by_id.side_effect = DatabaseError("read failed")

        with pytest.raises(DatabaseError, match="read failed"):
            await store.forget(str(uuid4()))


# ---------------------------------------------------------------------------
# TestPostgresMemoryStoreGetRecent
# ---------------------------------------------------------------------------


class TestPostgresMemoryStoreGetRecent:
    """Tests for PostgresMemoryStore.get_recent()."""

    async def test_get_recent_with_type_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_recent() calls search_by_type once when memory_type is provided."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mem = _make_memory(memory_type=MemoryType.SEMANTIC)
        mock_repo.search_by_type.return_value = [_make_orm_row(mem)]

        results = await store.get_recent(
            agent_id=mem.agent_id, memory_type=MemoryType.SEMANTIC
        )

        assert len(results) == 1
        assert results[0].memory_type == MemoryType.SEMANTIC
        mock_repo.search_by_type.assert_called_once()

    async def test_get_recent_without_type_fetches_all_three_types(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_recent(memory_type=None) queries all 3 MemoryType values."""
        store, mock_repo, _ = _make_store(monkeypatch)
        mock_repo.search_by_type.return_value = []

        await store.get_recent(agent_id=str(uuid4()), memory_type=None)

        # One call per MemoryType (episodic, semantic, procedural)
        assert mock_repo.search_by_type.call_count == 3

    async def test_get_recent_sorts_merged_result_by_last_accessed_at(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_recent() returns memories ordered newest-first."""
        store, mock_repo, _ = _make_store(monkeypatch)

        early = _make_memory(content="old memory")
        recent = _make_memory(content="new memory")
        early_row = _make_orm_row(early)
        recent_row = _make_orm_row(recent)
        # Make recent_row newer by tweaking last_accessed_at
        early_row.last_accessed_at = datetime(2026, 1, 1, tzinfo=UTC)
        recent_row.last_accessed_at = datetime(2026, 3, 20, tzinfo=UTC)

        # Return them in un-sorted order from two separate search_by_type calls
        mock_repo.search_by_type.side_effect = [[early_row], [recent_row], []]

        results = await store.get_recent(agent_id=str(uuid4()), memory_type=None)

        assert results[0].content == "new memory"
        assert results[1].content == "old memory"
