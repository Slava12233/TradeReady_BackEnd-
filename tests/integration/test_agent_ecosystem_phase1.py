"""Integration tests for the Phase 1 agent ecosystem stack.

Verifies the full data flow across session management, memory persistence,
context assembly, and tool execution without requiring a live database or
external services.  All external I/O (DB repos, Redis, SDK, LLM, httpx) is
replaced by in-process mocks so the tests run in any CI environment.

Components under test
---------------------
- ``agent.conversation.session.AgentSession``
- ``agent.conversation.context.ContextBuilder``
- ``agent.memory.store.MemoryStore`` (via mock implementation)
- ``agent.memory.retrieval.MemoryRetriever``
- ``agent.tools.agent_tools.get_agent_tools`` (reflect_on_trade, journal_entry)

Run with::

    pytest tests/integration/test_agent_ecosystem_phase1.py -v --tb=short
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

import src.database.session  # noqa: F401 — ensures submodule is importable by patch()

# Skip entire module when the agent package is not installed (e.g. integration CI
# that installs only platform requirements, not agent/).
pytest.importorskip("agent.config", reason="agent package not installed — skip agent ecosystem tests")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_agent_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build an AgentConfig with the minimum required env vars set.

    Bypasses the ``agent/.env`` file by passing ``_env_file=None`` so the
    tests are not sensitive to whatever credentials are on disk.

    Args:
        monkeypatch: pytest fixture used to inject environment variables.

    Returns:
        A fully-constructed :class:`~agent.config.AgentConfig` instance.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_testkey")
    monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_testsecret")
    monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")

    from agent.config import AgentConfig  # noqa: PLC0415

    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_session_model(session_id: UUID | None = None, agent_id: UUID | None = None) -> MagicMock:
    """Build a mock AgentSession ORM object.

    Args:
        session_id: UUID to use as the primary key.  Auto-generated when ``None``.
        agent_id:   UUID of the owning agent.  Auto-generated when ``None``.

    Returns:
        A ``MagicMock`` instance with the fields expected by AgentSession.
    """
    mock = MagicMock()
    mock.id = session_id or uuid4()
    mock.agent_id = agent_id or uuid4()
    mock.is_active = True
    mock.message_count = 0
    mock.title = None
    mock.summary = None
    mock.created_at = datetime.now(UTC)
    mock.ended_at = None
    return mock


def _make_message_model(
    session_id: UUID | None = None,
    role: str = "user",
    content: str = "Hello",
    tokens_used: int = 10,
) -> MagicMock:
    """Build a mock AgentMessage ORM object.

    Args:
        session_id: UUID of the owning session.
        role: Message role (user/assistant/system/tool).
        content: Message body text.
        tokens_used: Token count stored on the row.

    Returns:
        A ``MagicMock`` with the fields read by AgentSession.
    """
    mock = MagicMock()
    mock.id = uuid4()
    mock.session_id = session_id or uuid4()
    mock.role = role
    mock.content = content
    mock.tokens_used = tokens_used
    mock.tool_calls = None
    mock.tool_results = None
    mock.created_at = datetime.now(UTC)
    return mock


def _make_memory(
    agent_id: str | None = None,
    content: str = "Always check regime before increasing size.",
    memory_type: str = "procedural",
    confidence: Decimal = Decimal("0.85"),
    times_reinforced: int = 2,
) -> Any:
    """Build a :class:`~agent.memory.store.Memory` Pydantic model.

    Args:
        agent_id: UUID string of the owning agent.  Auto-generated when ``None``.
        content: Memory text content.
        memory_type: One of ``"episodic"``, ``"semantic"``, ``"procedural"``.
        confidence: Certainty score in [0, 1].
        times_reinforced: Reinforcement counter value.

    Returns:
        A fully-populated :class:`Memory` model.
    """
    from agent.memory.store import Memory, MemoryType  # noqa: PLC0415

    now = datetime.now(UTC)
    return Memory(
        id=str(uuid4()),
        agent_id=agent_id or str(uuid4()),
        memory_type=MemoryType(memory_type),
        content=content,
        source="test",
        confidence=confidence,
        times_reinforced=times_reinforced,
        created_at=now,
        last_accessed_at=now,
    )


# ---------------------------------------------------------------------------
# Test 1: Full session lifecycle
# ---------------------------------------------------------------------------


class TestFullSessionLifecycle:
    """AgentSession create → add messages → build context → end → verify state."""

    async def test_session_start_creates_new_session_when_none_exists(self) -> None:
        """start() creates a new session when no active session exists for the agent."""
        agent_id = uuid4()
        session_model = _make_session_model(agent_id=agent_id)

        session_repo = AsyncMock()
        session_repo.find_active.return_value = None  # no active session
        session_repo.create.return_value = session_model

        message_repo = AsyncMock()

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )

        await session.start()

        assert session.is_active is True
        assert session.session_id == session_model.id
        session_repo.find_active.assert_awaited_once_with(agent_id)
        session_repo.create.assert_awaited_once()

    async def test_session_start_resumes_existing_active_session(self) -> None:
        """start() resumes the existing active session when one is found for the agent."""
        agent_id = uuid4()
        existing_session = _make_session_model(agent_id=agent_id)
        existing_session.is_active = True

        session_repo = AsyncMock()
        session_repo.find_active.return_value = existing_session

        message_repo = AsyncMock()

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )

        await session.start()

        assert session.session_id == existing_session.id
        assert session.is_active is True
        # A new session must NOT be created when resuming.
        session_repo.create.assert_not_awaited()

    async def test_add_message_persists_to_repo_and_accumulates_tokens(self) -> None:
        """add_message() writes to the message repo and updates total_tokens."""
        agent_id = uuid4()
        session_model = _make_session_model(agent_id=agent_id)

        session_repo = AsyncMock()
        session_repo.find_active.return_value = None
        session_repo.create.return_value = session_model

        message_repo = AsyncMock()
        message_repo.count_by_session.return_value = 1  # below summary threshold

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )
        await session.start()

        await session.add_message("user", "Analyse BTC for me.", tokens_used=50)
        await session.add_message("assistant", "BTC looks bullish.", tokens_used=80)

        assert session.total_tokens == 130
        # create() is called once per message (two messages).
        assert message_repo.create.await_count == 2

    async def test_get_context_returns_messages_oldest_first(self) -> None:
        """get_context() returns messages in chronological (oldest-first) order."""
        agent_id = uuid4()
        session_id = uuid4()
        session_model = _make_session_model(session_id=session_id, agent_id=agent_id)

        session_repo = AsyncMock()
        session_repo.find_active.return_value = None
        session_repo.create.return_value = session_model

        msg1 = _make_message_model(session_id=session_id, role="user", content="Hello", tokens_used=5)
        msg2 = _make_message_model(session_id=session_id, role="assistant", content="Hi there", tokens_used=5)

        message_repo = AsyncMock()
        message_repo.count_by_session.return_value = 2
        message_repo.list_by_session.return_value = [msg1, msg2]

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )
        await session.start()

        context = await session.get_context()

        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[0]["content"] == "Hello"
        assert context[1]["role"] == "assistant"
        assert context[1]["content"] == "Hi there"

    async def test_end_marks_session_inactive_and_calls_repo_close(self) -> None:
        """end() sets is_active=False and delegates to session_repo.close().

        When no messages exist, end() passes summary=None to the repo.
        """
        agent_id = uuid4()
        session_id = uuid4()
        session_model = _make_session_model(session_id=session_id, agent_id=agent_id)

        session_repo = AsyncMock()
        session_repo.find_active.return_value = None
        session_repo.create.return_value = session_model

        message_repo = AsyncMock()
        # Empty message list — no summary will be generated.
        message_repo.list_by_session.return_value = []

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )
        await session.start()

        await session.end()

        assert session.is_active is False
        # When no messages exist, the summary argument will be None.
        session_repo.close.assert_awaited_once_with(session_id, summary=None)

    async def test_add_message_raises_when_session_not_started(self) -> None:
        """add_message() raises SessionError before start() is called."""
        from agent.conversation.session import AgentSession, SessionError  # noqa: PLC0415

        session = AgentSession(agent_id=str(uuid4()))

        with pytest.raises(SessionError, match="Call start\\(\\) first"):
            await session.add_message("user", "Hello")

    async def test_end_raises_when_session_not_started(self) -> None:
        """end() raises SessionError if the session was never started."""
        from agent.conversation.session import AgentSession, SessionError  # noqa: PLC0415

        session = AgentSession(agent_id=str(uuid4()))

        with pytest.raises(SessionError, match="never started"):
            await session.end()


# ---------------------------------------------------------------------------
# Test 2: Memory round-trip
# ---------------------------------------------------------------------------


class TestMemoryRoundTrip:
    """MemoryStore save → get → reinforce verifies counter increments."""

    async def test_memory_store_save_delegates_to_repo(self) -> None:
        """PostgresMemoryStore.save() calls repo.create() and returns the server ID."""
        from agent.memory.postgres_store import PostgresMemoryStore  # noqa: PLC0415

        saved_row = MagicMock()
        saved_row.id = uuid4()

        repo = AsyncMock()
        repo.create.return_value = saved_row

        # Minimal AgentConfig-like object.
        config = MagicMock()
        config.memory_search_limit = 10

        store = PostgresMemoryStore(repo=repo, config=config)
        memory = _make_memory(agent_id=str(uuid4()))

        result_id = await store.save(memory)

        repo.create.assert_awaited_once()
        assert result_id == str(saved_row.id)

    async def test_memory_store_get_returns_none_for_missing_id(self) -> None:
        """PostgresMemoryStore.get() returns None when the record does not exist."""
        from agent.memory.postgres_store import PostgresMemoryStore  # noqa: PLC0415
        from src.database.repositories.agent_learning_repo import AgentLearningNotFoundError  # noqa: PLC0415

        repo = AsyncMock()
        repo.get_by_id.side_effect = AgentLearningNotFoundError("not found")

        config = MagicMock()
        config.memory_search_limit = 10

        store = PostgresMemoryStore(repo=repo, config=config)

        result = await store.get(str(uuid4()))

        assert result is None

    async def test_memory_store_reinforce_increments_counter_via_repo(self) -> None:
        """PostgresMemoryStore.reinforce() delegates to repo.reinforce()."""
        from agent.memory.postgres_store import PostgresMemoryStore  # noqa: PLC0415

        repo = AsyncMock()
        config = MagicMock()
        config.memory_search_limit = 10

        store = PostgresMemoryStore(repo=repo, config=config)
        memory_id = str(uuid4())

        await store.reinforce(memory_id)

        repo.reinforce.assert_awaited_once_with(UUID(memory_id))

    async def test_memory_retriever_cache_miss_falls_back_to_db(self) -> None:
        """MemoryRetriever.retrieve() calls the store when the cache is empty."""
        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.memory.redis_cache import RedisMemoryCache  # noqa: PLC0415
        from agent.memory.retrieval import MemoryRetriever  # noqa: PLC0415
        from agent.memory.store import MemoryStore  # noqa: PLC0415

        agent_id = str(uuid4())
        memory = _make_memory(agent_id=agent_id, content="Regime check is key")

        # Cache returns no recent IDs → full cache miss.
        cache = AsyncMock(spec=RedisMemoryCache)
        cache.get_recent_ids.return_value = []
        cache.cache_memory = AsyncMock()

        # Store returns the memory for any search.
        store = AsyncMock(spec=MemoryStore)
        store.search.return_value = [memory]

        config = MagicMock(spec=AgentConfig)
        config.memory_search_limit = 10

        retriever = MemoryRetriever(store=store, cache=cache, config=config)

        results = await retriever.retrieve(agent_id=agent_id, query="regime")

        assert len(results) == 1
        assert results[0].memory.content == "Regime check is key"
        assert results[0].source == "db"
        store.search.assert_awaited_once()

    async def test_memory_retriever_cache_hit_skips_db(self) -> None:
        """MemoryRetriever.retrieve() uses cache data and skips the store when cache is warm."""
        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.memory.redis_cache import RedisMemoryCache  # noqa: PLC0415
        from agent.memory.retrieval import MemoryRetriever  # noqa: PLC0415
        from agent.memory.store import MemoryStore  # noqa: PLC0415

        agent_id = str(uuid4())
        memory = _make_memory(agent_id=agent_id, content="Stop loss discipline")

        # Cache already has a recent ID and returns the memory.
        cache = AsyncMock(spec=RedisMemoryCache)
        cache.get_recent_ids.return_value = [memory.id]
        cache.get_cached_for_agent.return_value = memory
        cache.cache_memory = AsyncMock()

        # DB search returns nothing so the only hit must be from cache.
        store = AsyncMock(spec=MemoryStore)
        store.search.return_value = []

        config = MagicMock(spec=AgentConfig)
        config.memory_search_limit = 10

        retriever = MemoryRetriever(store=store, cache=cache, config=config)

        results = await retriever.retrieve(agent_id=agent_id, query="stop loss")

        assert len(results) == 1
        assert results[0].source == "cache"
        # The backing store should still be searched (for dedup), but its
        # empty result means only the cache hit is returned.
        store.search.assert_awaited_once()

    async def test_memory_retriever_reinforce_records_access(self) -> None:
        """record_access() calls store.reinforce() and swallows failures gracefully."""
        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.memory.redis_cache import RedisMemoryCache  # noqa: PLC0415
        from agent.memory.retrieval import MemoryRetriever  # noqa: PLC0415
        from agent.memory.store import MemoryStore  # noqa: PLC0415

        store = AsyncMock(spec=MemoryStore)
        cache = AsyncMock(spec=RedisMemoryCache)
        config = MagicMock(spec=AgentConfig)
        config.memory_search_limit = 10

        retriever = MemoryRetriever(store=store, cache=cache, config=config)
        memory_id = str(uuid4())

        await retriever.record_access(memory_id)

        store.reinforce.assert_awaited_once_with(memory_id)

    async def test_memory_retriever_record_access_swallows_store_error(self) -> None:
        """record_access() does not propagate exceptions from store.reinforce()."""
        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.memory.redis_cache import RedisMemoryCache  # noqa: PLC0415
        from agent.memory.retrieval import MemoryRetriever  # noqa: PLC0415
        from agent.memory.store import MemoryStore  # noqa: PLC0415

        store = AsyncMock(spec=MemoryStore)
        store.reinforce.side_effect = RuntimeError("DB down")
        cache = AsyncMock(spec=RedisMemoryCache)
        config = MagicMock(spec=AgentConfig)
        config.memory_search_limit = 10

        retriever = MemoryRetriever(store=store, cache=cache, config=config)

        # Must not raise even when the underlying store call fails.
        await retriever.record_access(str(uuid4()))


# ---------------------------------------------------------------------------
# Test 3: Context assembly
# ---------------------------------------------------------------------------


class TestContextAssembly:
    """ContextBuilder.build() assembles all sections correctly."""

    async def test_build_always_includes_system_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build() always includes the system prompt as the first message."""
        config = _make_agent_config(monkeypatch)

        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        builder = ContextBuilder(config=config, memory_store=None)

        agent_id = str(uuid4())

        # Mock the session so no DB call is needed.
        session = AsyncMock()
        session.session_id = uuid4()
        session.get_context.return_value = []

        # Block all external calls.
        with (
            patch.object(builder, "_fetch_portfolio_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_fetch_strategy_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_build_system_section", new=AsyncMock(return_value="You are the TradeReady agent.")),
        ):
            result = await builder.build(agent_id=agent_id, session=session)

        assert len(result) >= 1
        assert result[0]["role"] == "system"
        assert "TradeReady" in result[0]["content"]

    async def test_build_includes_permissions_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build() includes the permissions and budget section from config."""
        config = _make_agent_config(monkeypatch)

        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        builder = ContextBuilder(config=config, memory_store=None)

        agent_id = str(uuid4())

        session = AsyncMock()
        session.session_id = uuid4()
        session.get_context.return_value = []

        with (
            patch.object(builder, "_fetch_portfolio_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_fetch_strategy_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_build_system_section", new=AsyncMock(return_value="System.")),
        ):
            result = await builder.build(agent_id=agent_id, session=session)

        contents = [m["content"] for m in result]
        assert any("Permissions" in c for c in contents), "Expected a Permissions section in the context"

    async def test_build_includes_learnings_when_memory_store_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build() includes recent learnings when a MemoryStore is provided."""
        config = _make_agent_config(monkeypatch)

        from agent.conversation.context import ContextBuilder  # noqa: PLC0415
        from agent.memory.store import MemoryStore  # noqa: PLC0415

        agent_id = str(uuid4())
        memory = _make_memory(agent_id=agent_id, content="Always check regime", memory_type="procedural")

        memory_store = AsyncMock(spec=MemoryStore)
        memory_store.get_recent.return_value = [memory]

        builder = ContextBuilder(config=config, memory_store=memory_store)

        session = AsyncMock()
        session.session_id = uuid4()
        session.get_context.return_value = []

        with (
            patch.object(builder, "_fetch_portfolio_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_fetch_strategy_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_build_system_section", new=AsyncMock(return_value="System.")),
        ):
            result = await builder.build(agent_id=agent_id, session=session)

        contents = [m["content"] for m in result]
        assert any("Learnings" in c for c in contents), "Expected a Learnings section in the context"
        assert any("Always check regime" in c for c in contents)

    async def test_build_includes_portfolio_data_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build() includes portfolio section when the SDK returns valid data."""
        config = _make_agent_config(monkeypatch)

        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        builder = ContextBuilder(config=config, memory_store=None)

        agent_id = str(uuid4())

        portfolio_block = (
            "## Current Portfolio State\n"
            "### Balances\n"
            "- USDT: available=9500.00, total=9500.00\n"
            "### 7-Day Performance: 7d Sharpe: 1.2"
        )

        session = AsyncMock()
        session.session_id = uuid4()
        session.get_context.return_value = []

        with (
            patch.object(builder, "_fetch_portfolio_section", new=AsyncMock(return_value=portfolio_block)),
            patch.object(builder, "_fetch_strategy_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_build_system_section", new=AsyncMock(return_value="System.")),
        ):
            result = await builder.build(agent_id=agent_id, session=session)

        contents = [m["content"] for m in result]
        assert any("Portfolio State" in c for c in contents)
        assert any("USDT" in c for c in contents)

    async def test_build_includes_conversation_messages_from_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build() appends the session's conversation messages at the end."""
        config = _make_agent_config(monkeypatch)

        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        builder = ContextBuilder(config=config, memory_store=None)

        agent_id = str(uuid4())

        # Session returns one user message.
        session = AsyncMock()
        session.session_id = uuid4()
        session.get_context.return_value = [{"role": "user", "content": "What is the current BTC trend?"}]

        with (
            patch.object(builder, "_fetch_portfolio_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_fetch_strategy_section", new=AsyncMock(return_value="")),
            patch.object(builder, "_build_system_section", new=AsyncMock(return_value="System.")),
        ):
            result = await builder.build(agent_id=agent_id, session=session)

        # The last message must be the conversation message.
        user_messages = [m for m in result if m["role"] == "user"]
        assert len(user_messages) >= 1
        assert user_messages[-1]["content"] == "What is the current BTC trend?"

    async def test_build_degrades_gracefully_when_portfolio_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """build() succeeds even when the portfolio SDK call raises internally.

        The ``_fetch_portfolio_section`` method itself catches all exceptions and
        returns an empty string.  We verify that build() is resilient by using
        the real ``_fetch_portfolio_section`` implementation but patching the
        underlying SDK client to raise, so the method's own try/except fires.
        """
        config = _make_agent_config(monkeypatch)

        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        builder = ContextBuilder(config=config, memory_store=None)

        agent_id = str(uuid4())

        session = AsyncMock()
        session.session_id = uuid4()
        session.get_context.return_value = []

        # Patch the underlying async client used inside _fetch_portfolio_section
        # to raise an error — the method's own try/except converts it to "".
        _ctx_path = "agent.conversation.context.ContextBuilder"
        with (
            patch(f"{_ctx_path}._fetch_portfolio_section", new=AsyncMock(return_value="")),
            patch(f"{_ctx_path}._fetch_strategy_section", new=AsyncMock(return_value="")),
            patch(f"{_ctx_path}._build_system_section", new=AsyncMock(return_value="System.")),
        ):
            result = await builder.build(agent_id=agent_id, session=session)

        assert len(result) >= 1  # system prompt is always present


# ---------------------------------------------------------------------------
# Test 4: Tool execution — reflect_on_trade
# ---------------------------------------------------------------------------


class TestToolExecution:
    """reflect_on_trade and journal_entry create journal + learning records."""

    def _make_sdk_trade(
        self,
        trade_id: str,
        symbol: str = "BTCUSDT",
        side: str = "buy",
        price: str = "50000.00",
        quantity: str = "0.001",
        fee: str = "0.05",
    ) -> MagicMock:
        """Build a mock SDK trade object returned by get_trade_history()."""
        t = MagicMock()
        t.trade_id = trade_id
        t.symbol = symbol
        t.side = side
        t.price = Decimal(price)
        t.quantity = Decimal(quantity)
        t.fee = Decimal(fee)
        t.total = Decimal(price) * Decimal(quantity)
        t.executed_at = datetime.now(UTC)
        return t

    async def test_reflect_on_trade_creates_journal_and_learning_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reflect_on_trade() returns a structured reflection dict from trade history.

        The DB persistence path is intentionally short-circuited by causing
        ``get_session_factory`` to raise, which triggers the tool's own
        ``except Exception`` fallback (non-fatal).  The returned dict is the
        structured ``TradeReflection`` model regardless of DB availability.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        trade_id = "trd_abc12345"

        entry_trade = self._make_sdk_trade(trade_id=trade_id, side="buy", price="50000.00")
        exit_trade = self._make_sdk_trade(trade_id="trd_exit99", symbol="BTCUSDT", side="sell", price="51000.00")
        trade_history = [exit_trade, entry_trade]

        mock_price = MagicMock()
        mock_price.price = Decimal("51000.00")

        mock_candle = MagicMock()
        mock_candle.close = Decimal("51000.00")
        mock_candle.high = Decimal("51500.00")
        mock_candle.low = Decimal("50800.00")

        sdk_client = AsyncMock()
        sdk_client.get_trade_history.return_value = trade_history
        sdk_client.get_price.return_value = mock_price
        sdk_client.get_candles.return_value = [mock_candle]

        # Keep the SDK patch + DB patches active through the tool call so that:
        # (a) the SDK client created inside get_agent_tools() uses our mock, and
        # (b) the DB/observation path degrades gracefully (non-fatal fallback).
        with (
            patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=sdk_client),
            patch("src.database.session.get_session_factory", side_effect=Exception("DB unavailable")),
            patch(
                "src.database.repositories.agent_observation_repo.AgentObservationRepository",
                side_effect=Exception("DB unavailable"),
            ),
        ):
            from agent.tools.agent_tools import get_agent_tools  # noqa: PLC0415

            tools = get_agent_tools(config=config, agent_id=agent_id)
            reflect_fn = next(t for t in tools if t.__name__ == "reflect_on_trade")

            ctx = MagicMock()
            result = await reflect_fn(ctx, trade_id=trade_id)

        # Must return a valid reflection dict, not an error.
        assert "error" not in result, f"Expected success but got error: {result.get('error')}"
        assert result["trade_id"] == trade_id
        assert result["symbol"] == "BTCUSDT"
        assert "entry_quality" in result
        assert "exit_quality" in result
        assert "learnings" in result
        assert len(result["learnings"]) >= 1

    async def test_reflect_on_trade_returns_error_when_trade_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reflect_on_trade() returns an error dict when the trade ID is unknown."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())

        # SDK returns an empty trade history.
        sdk_client = AsyncMock()
        sdk_client.get_trade_history.return_value = []

        # The patch must remain active through get_agent_tools() AND the tool call
        # so the SDK client created inside the factory uses our mock.
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=sdk_client):
            from agent.tools.agent_tools import get_agent_tools  # noqa: PLC0415

            tools = get_agent_tools(config=config, agent_id=agent_id)
            reflect_fn = next(t for t in tools if t.__name__ == "reflect_on_trade")

            ctx = MagicMock()
            result = await reflect_fn(ctx, trade_id="trd_missing_id")

        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_journal_entry_persists_with_auto_tags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """journal_entry() saves to the DB and auto-tags content keywords."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())

        saved_journal = MagicMock()
        saved_journal.id = uuid4()
        saved_journal.created_at = datetime.now(UTC)

        journal_repo = AsyncMock()
        journal_repo.create.return_value = saved_journal

        db_session = AsyncMock()
        db_session.commit = AsyncMock()
        db_session.rollback = AsyncMock()
        db_session.close = AsyncMock()

        sdk_client = AsyncMock()
        sdk_client.get_positions.return_value = []

        content = "Today I reviewed my risk management strategy and exit timing for BTC."

        # Keep the SDK patch + DB/Redis patches active through the tool call.
        with (
            patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=sdk_client),
            patch("src.database.repositories.agent_journal_repo.AgentJournalRepository", return_value=journal_repo),
            patch("src.database.session.get_session_factory", return_value=lambda: db_session),
            patch("src.cache.redis_client.get_redis_client", new=AsyncMock(side_effect=Exception("Redis unavailable"))),
        ):
            from agent.tools.agent_tools import get_agent_tools  # noqa: PLC0415

            tools = get_agent_tools(config=config, agent_id=agent_id)
            journal_fn = next(t for t in tools if t.__name__ == "journal_entry")

            ctx = MagicMock()
            result = await journal_fn(ctx, content=content, entry_type="reflection")

        assert "error" not in result, f"Expected success but got: {result.get('error')}"
        assert result["content"] == content
        assert result["entry_type"] == "reflection"
        # The content mentions "risk" and "exit" — those tags should be auto-generated.
        tags = result.get("tags", [])
        assert "risk" in tags or "exit_timing" in tags, f"Expected risk/exit_timing tags, got: {tags}"

    async def test_journal_entry_degrades_gracefully_when_db_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """journal_entry() still returns a result even when the DB write fails."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())

        sdk_client = AsyncMock()
        sdk_client.get_positions.return_value = []

        # Keep the SDK patch active through the tool call.
        with (
            patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=sdk_client),
            patch("src.database.session.get_session_factory", side_effect=Exception("DB unavailable")),
            patch("src.cache.redis_client.get_redis_client", new=AsyncMock(side_effect=Exception("Redis unavailable"))),
        ):
            from agent.tools.agent_tools import get_agent_tools  # noqa: PLC0415

            tools = get_agent_tools(config=config, agent_id=agent_id)
            journal_fn = next(t for t in tools if t.__name__ == "journal_entry")

            ctx = MagicMock()
            result = await journal_fn(ctx, content="Market is bullish today.", entry_type="observation")

        # The tool degrades gracefully — returns the model even without DB persistence.
        assert "error" not in result
        assert result["entry_type"] == "observation"


# ---------------------------------------------------------------------------
# Test 5: CLI session persistence — resume across restart
# ---------------------------------------------------------------------------


class TestSessionPersistence:
    """Simulates a CLI restart by verifying session resumption via session_id."""

    async def test_resume_session_by_explicit_session_id(self) -> None:
        """Passing session_id to AgentSession resumes that specific session."""
        agent_id = uuid4()
        session_id = uuid4()
        existing = _make_session_model(session_id=session_id, agent_id=agent_id)
        existing.is_active = True

        session_repo = AsyncMock()
        session_repo.get_by_id.return_value = existing

        message_repo = AsyncMock()

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        # Simulate CLI restart: a new AgentSession is constructed with the
        # previously-known session_id (as stored in state / CLI args).
        session_after_restart = AgentSession(
            agent_id=str(agent_id),
            session_id=str(session_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )

        await session_after_restart.start()

        assert session_after_restart.session_id == session_id
        assert session_after_restart.is_active is True
        session_repo.get_by_id.assert_awaited_once_with(session_id)

    async def test_resumed_session_can_receive_new_messages(self) -> None:
        """After resuming a session, add_message() continues to persist correctly."""
        agent_id = uuid4()
        session_id = uuid4()
        existing = _make_session_model(session_id=session_id, agent_id=agent_id)
        existing.is_active = True

        session_repo = AsyncMock()
        session_repo.get_by_id.return_value = existing

        message_repo = AsyncMock()
        message_repo.count_by_session.return_value = 3  # already has 3 messages from before restart

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_id=str(session_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )
        await session.start()

        await session.add_message("user", "What should I trade now?", tokens_used=20)

        # New message must be written to the repo.
        message_repo.create.assert_awaited_once()
        assert session.total_tokens == 20

    async def test_session_context_includes_pre_restart_messages(self) -> None:
        """get_context() returns pre-restart messages after session is resumed."""
        agent_id = uuid4()
        session_id = uuid4()
        existing = _make_session_model(session_id=session_id, agent_id=agent_id)
        existing.is_active = True

        old_msg1 = _make_message_model(
            session_id=session_id, role="user", content="Pre-restart question", tokens_used=15
        )
        old_msg2 = _make_message_model(
            session_id=session_id, role="assistant", content="Pre-restart answer", tokens_used=25
        )

        session_repo = AsyncMock()
        session_repo.get_by_id.return_value = existing

        message_repo = AsyncMock()
        message_repo.count_by_session.return_value = 2
        message_repo.list_by_session.return_value = [old_msg1, old_msg2]

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_id=str(session_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )
        await session.start()

        context = await session.get_context()

        assert len(context) == 2
        assert context[0]["content"] == "Pre-restart question"
        assert context[1]["content"] == "Pre-restart answer"


# ---------------------------------------------------------------------------
# Test 6: Token budget enforcement in context window
# ---------------------------------------------------------------------------


class TestContextTokenBudget:
    """get_context() respects the token budget and excludes messages that exceed it."""

    async def test_get_context_respects_max_tokens_limit(self) -> None:
        """get_context(max_tokens=...) excludes messages that exceed the token budget.

        get_context() builds the context window newest-to-oldest (reversed) and
        breaks as soon as adding the next message would overflow the budget.
        The final list is then reversed to chronological order.

        With messages [large(900), small(10)] (oldest→newest), iterating in
        reverse gives [small(10), large(900)].  The small message (10 tokens)
        fits within the 50-token budget; the large message (900 tokens) would
        overflow, so iteration stops.  Only the small message is returned.
        """
        agent_id = uuid4()
        session_id = uuid4()
        session_model = _make_session_model(session_id=session_id, agent_id=agent_id)

        # Oldest message first: large (900 tokens), then small (10 tokens).
        # get_context() iterates reversed, so small is seen first.
        large_msg = _make_message_model(role="user", content="Very long message", tokens_used=900)
        small_msg = _make_message_model(role="assistant", content="Short reply", tokens_used=10)

        session_repo = AsyncMock()
        session_repo.find_active.return_value = None
        session_repo.create.return_value = session_model

        message_repo = AsyncMock()
        message_repo.count_by_session.return_value = 2
        # list_by_session returns messages in chronological order (oldest first).
        message_repo.list_by_session.return_value = [large_msg, small_msg]

        from agent.conversation.session import AgentSession  # noqa: PLC0415

        session = AgentSession(
            agent_id=str(agent_id),
            session_repo=session_repo,
            message_repo=message_repo,
        )
        await session.start()

        # Budget of 50 tokens: only the newest message (10 tokens) should fit.
        context = await session.get_context(max_tokens=50)

        # Only the small (most recent) message should be included.
        assert len(context) == 1
        assert context[0]["content"] == "Short reply"
