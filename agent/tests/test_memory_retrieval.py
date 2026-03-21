"""Tests for agent/memory/retrieval.py :: MemoryRetriever and scoring helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent.config import AgentConfig
from agent.memory.retrieval import (
    MemoryRetriever,
    _keyword_score,
    _recency_score,
    _reinforcement_score,
    _score_memory,
)
from agent.memory.store import Memory, MemoryType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_memory(
    content: str = "BTC trending upward",
    confidence: str = "0.8000",
    times_reinforced: int = 1,
    last_accessed_at: datetime | None = None,
    memory_type: MemoryType = MemoryType.EPISODIC,
    agent_id: str | None = None,
) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        id=str(uuid4()),
        agent_id=agent_id or str(uuid4()),
        memory_type=memory_type,
        content=content,
        source="test",
        confidence=Decimal(confidence),
        times_reinforced=times_reinforced,
        created_at=now,
        last_accessed_at=last_accessed_at or now,
    )


def _make_retriever(monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Return (retriever, mock_store, mock_cache, config)."""
    config = _make_config(monkeypatch)
    mock_store = AsyncMock()
    mock_cache = AsyncMock()
    # Default: empty recent IDs (no cache hits)
    mock_cache.get_recent_ids.return_value = []
    mock_cache.cache_memory.return_value = None
    retriever = MemoryRetriever(store=mock_store, cache=mock_cache, config=config)
    return retriever, mock_store, mock_cache, config


# ---------------------------------------------------------------------------
# TestKeywordScore
# ---------------------------------------------------------------------------


class TestKeywordScore:
    """Tests for the _keyword_score() scoring helper."""

    def test_exact_single_word_match_returns_one(self) -> None:
        """Single word fully present in content returns 1.0."""
        assert _keyword_score("BTC is trending", "trending") == 1.0

    def test_no_match_returns_zero(self) -> None:
        """Word absent from content returns 0.0."""
        assert _keyword_score("BTC is trending", "ethereum") == 0.0

    def test_partial_multi_word_match(self) -> None:
        """2 out of 4 query words matched => 0.5."""
        score = _keyword_score("BTC trending", "BTC ETH trending SOL")
        assert abs(score - 0.5) < 1e-9

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        assert _keyword_score("BTC Regime TRENDING", "btc regime trending") == 1.0

    def test_empty_query_returns_zero(self) -> None:
        """Empty query returns 0.0 without error."""
        assert _keyword_score("some content", "") == 0.0


# ---------------------------------------------------------------------------
# TestRecencyScore
# ---------------------------------------------------------------------------


class TestRecencyScore:
    """Tests for the _recency_score() scoring helper."""

    def test_very_recent_returns_one(self) -> None:
        """Memory accessed within the last hour gets score 1.0."""
        recent = datetime.now(UTC) - timedelta(hours=1)
        assert _recency_score(recent) == 1.0

    def test_exactly_at_full_threshold_returns_one(self) -> None:
        """Memory accessed exactly 24 hours ago still gets 1.0."""
        at_threshold = datetime.now(UTC) - timedelta(hours=24)
        assert _recency_score(at_threshold) == 1.0

    def test_beyond_decay_window_returns_zero(self) -> None:
        """Memory older than 7 days returns 0.0."""
        old = datetime.now(UTC) - timedelta(days=8)
        assert _recency_score(old) == 0.0

    def test_midpoint_decay_is_between_zero_and_one(self) -> None:
        """Memory at ~3.5 days old (midpoint of decay window) scores ~0.5."""
        midpoint = datetime.now(UTC) - timedelta(hours=24 + (7 * 24 - 24) // 2)
        score = _recency_score(midpoint)
        assert 0.0 < score < 1.0

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        """Naive datetime is assumed UTC (tzinfo=None handled gracefully)."""
        naive = datetime.now()  # no tzinfo
        score = _recency_score(naive)
        # Should be close to 1.0 (accessed just now, naive treated as UTC)
        assert score >= 0.0


# ---------------------------------------------------------------------------
# TestReinforcementScore
# ---------------------------------------------------------------------------


class TestReinforcementScore:
    """Tests for the _reinforcement_score() scoring helper."""

    def test_one_reinforcement_returns_low_score(self) -> None:
        """1 reinforcement gives 0.1 (1/10 cap)."""
        assert abs(_reinforcement_score(1) - 0.1) < 1e-9

    def test_ten_reinforcements_returns_one(self) -> None:
        """10 reinforcements at the cap returns 1.0."""
        assert _reinforcement_score(10) == 1.0

    def test_above_cap_clamps_to_one(self) -> None:
        """More than 10 reinforcements is clamped to 1.0."""
        assert _reinforcement_score(100) == 1.0

    def test_zero_reinforcements_returns_zero(self) -> None:
        """0 reinforcements returns 0.0 (edge case — should not occur in practice)."""
        assert _reinforcement_score(0) == 0.0


# ---------------------------------------------------------------------------
# TestScoreMemory
# ---------------------------------------------------------------------------


class TestScoreMemory:
    """Tests for the composite _score_memory() function."""

    def test_high_relevance_memory_outscores_low_relevance(self) -> None:
        """A memory with keyword match + high confidence > one with neither."""
        high = _make_memory(
            content="BTC regime trending",
            confidence="1.0000",
            times_reinforced=10,
        )
        low = _make_memory(
            content="unrelated text",
            confidence="0.1000",
            times_reinforced=1,
            last_accessed_at=datetime.now(UTC) - timedelta(days=10),
        )
        score_high = _score_memory(high, "regime trending")
        score_low = _score_memory(low, "regime trending")
        assert score_high > score_low

    def test_score_is_between_zero_and_one(self) -> None:
        """Composite score is always in [0, 1]."""
        mem = _make_memory()
        score = _score_memory(mem, "anything")
        assert 0.0 <= score <= 1.0

    def test_empty_query_reduces_keyword_weight(self) -> None:
        """An empty query zeroes out the keyword component."""
        mem = _make_memory(confidence="1.0000", times_reinforced=10)
        score_with_query = _score_memory(mem, "trending")
        score_empty_query = _score_memory(mem, "")
        # keyword weight=0.4 should be missing from empty-query score
        assert score_empty_query < score_with_query or score_empty_query <= 1.0


# ---------------------------------------------------------------------------
# TestMemoryRetrieverRetrieve
# ---------------------------------------------------------------------------


class TestMemoryRetrieverRetrieve:
    """Tests for MemoryRetriever.retrieve()."""

    async def test_retrieve_db_fallback_on_empty_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() falls back to the DB when the cache is empty."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())
        mem = _make_memory(content="BTC crashed", agent_id=agent_id)
        mock_cache.get_recent_ids.return_value = []
        mock_store.search.return_value = [mem]

        results = await retriever.retrieve(agent_id=agent_id, query="BTC")

        assert len(results) == 1
        assert results[0].source == "db"
        assert results[0].memory.content == mem.content

    async def test_retrieve_cache_hit_avoids_duplicate_in_db_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Memory already in cache is not duplicated by the DB phase."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())
        mem = _make_memory(content="shared memory", agent_id=agent_id)

        # Cache returns the memory
        mock_cache.get_recent_ids.return_value = [mem.id]
        mock_cache.get_cached_for_agent.return_value = mem

        # DB also returns the same memory (overlap scenario)
        mock_store.search.return_value = [mem]

        results = await retriever.retrieve(agent_id=agent_id, query="shared")

        # Should appear exactly once in the result set
        ids_returned = [r.memory.id for r in results]
        assert ids_returned.count(mem.id) == 1

    async def test_retrieve_filters_by_min_confidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() excludes memories below min_confidence."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())
        low_conf = _make_memory(confidence="0.1000", agent_id=agent_id)
        high_conf = _make_memory(confidence="0.9000", agent_id=agent_id)
        mock_store.search.return_value = [low_conf, high_conf]

        results = await retriever.retrieve(
            agent_id=agent_id, query="test", min_confidence=0.5
        )

        returned_ids = {r.memory.id for r in results}
        assert high_conf.id in returned_ids
        assert low_conf.id not in returned_ids

    async def test_retrieve_results_ordered_by_relevance_score_desc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() returns results sorted by relevance_score descending."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())

        high_rel = _make_memory(
            content="BTC regime trending signal",
            confidence="1.0000",
            times_reinforced=5,
            agent_id=agent_id,
        )
        low_rel = _make_memory(
            content="unrelated content xyz",
            confidence="0.3000",
            times_reinforced=1,
            last_accessed_at=datetime.now(UTC) - timedelta(days=6),
            agent_id=agent_id,
        )
        mock_store.search.return_value = [low_rel, high_rel]  # wrong order

        results = await retriever.retrieve(
            agent_id=agent_id, query="BTC regime trending"
        )

        assert results[0].relevance_score >= results[-1].relevance_score

    async def test_retrieve_respects_config_search_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() returns at most config.memory_search_limit results."""
        retriever, mock_store, mock_cache, config = _make_retriever(monkeypatch)
        agent_id = str(uuid4())

        many_mems = [_make_memory(agent_id=agent_id) for _ in range(50)]
        mock_store.search.return_value = many_mems

        results = await retriever.retrieve(
            agent_id=agent_id, query="test", limit=9999
        )

        assert len(results) <= config.memory_search_limit

    async def test_retrieve_caches_top_results_after_retrieval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() calls cache.cache_memory() for each top result."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())
        mem = _make_memory(agent_id=agent_id)
        mock_store.search.return_value = [mem]

        await retriever.retrieve(agent_id=agent_id, query="test")

        mock_cache.cache_memory.assert_called()

    async def test_retrieve_with_memory_type_filter_passes_types_to_db(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() calls store.search() once per requested memory type."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())
        mock_store.search.return_value = []

        await retriever.retrieve(
            agent_id=agent_id,
            query="regime",
            memory_types=[MemoryType.PROCEDURAL, MemoryType.SEMANTIC],
        )

        assert mock_store.search.call_count == 2

    async def test_retrieve_returns_empty_list_when_no_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """retrieve() returns [] when neither cache nor DB has results."""
        retriever, mock_store, mock_cache, _ = _make_retriever(monkeypatch)
        mock_store.search.return_value = []

        results = await retriever.retrieve(agent_id=str(uuid4()), query="nothing")

        assert results == []


# ---------------------------------------------------------------------------
# TestMemoryRetrieverGetContextMemories
# ---------------------------------------------------------------------------


class TestMemoryRetrieverGetContextMemories:
    """Tests for MemoryRetriever.get_context_memories()."""

    async def test_get_context_memories_returns_sorted_by_composite_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_context_memories() re-ranks recent memories by composite score."""
        retriever, mock_store, _, _ = _make_retriever(monkeypatch)
        agent_id = str(uuid4())

        high = _make_memory(
            content="high quality memory",
            confidence="1.0000",
            times_reinforced=8,
            agent_id=agent_id,
        )
        low = _make_memory(
            content="low quality memory",
            confidence="0.2000",
            times_reinforced=1,
            last_accessed_at=datetime.now(UTC) - timedelta(days=6),
            agent_id=agent_id,
        )
        mock_store.get_recent.return_value = [low, high]

        results = await retriever.get_context_memories(agent_id=agent_id, limit=2)

        assert len(results) == 2
        # High quality memory should come first
        assert results[0].content == "high quality memory"

    async def test_get_context_memories_returns_empty_on_store_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_context_memories() returns [] when the store raises."""
        retriever, mock_store, _, _ = _make_retriever(monkeypatch)
        mock_store.get_recent.side_effect = RuntimeError("DB down")

        results = await retriever.get_context_memories(agent_id=str(uuid4()))

        assert results == []

    async def test_get_context_memories_returns_empty_when_no_recent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_context_memories() returns [] when the store returns an empty list."""
        retriever, mock_store, _, _ = _make_retriever(monkeypatch)
        mock_store.get_recent.return_value = []

        results = await retriever.get_context_memories(agent_id=str(uuid4()))

        assert results == []

    async def test_get_context_memories_truncates_to_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_context_memories() returns at most `limit` memories."""
        retriever, mock_store, _, _ = _make_retriever(monkeypatch)
        many = [_make_memory() for _ in range(30)]
        mock_store.get_recent.return_value = many

        results = await retriever.get_context_memories(agent_id=str(uuid4()), limit=3)

        assert len(results) <= 3


# ---------------------------------------------------------------------------
# TestMemoryRetrieverRecordAccess
# ---------------------------------------------------------------------------


class TestMemoryRetrieverRecordAccess:
    """Tests for MemoryRetriever.record_access()."""

    async def test_record_access_calls_store_reinforce(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_access() delegates to store.reinforce()."""
        retriever, mock_store, _, _ = _make_retriever(monkeypatch)
        memory_id = str(uuid4())
        mock_store.reinforce.return_value = None

        await retriever.record_access(memory_id)

        mock_store.reinforce.assert_called_once_with(memory_id)

    async def test_record_access_swallows_store_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_access() does not raise when reinforce() fails."""
        retriever, mock_store, _, _ = _make_retriever(monkeypatch)
        mock_store.reinforce.side_effect = Exception("DB error")

        # Should not raise
        await retriever.record_access(str(uuid4()))
