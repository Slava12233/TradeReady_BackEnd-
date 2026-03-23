"""Tests for the memory-driven learning loop.

Covers:
- TradingJournal.save_episodic_memory() — creates EPISODIC memory from trade data
- TradingJournal.save_episodic_memory() — no-op when memory_store is None
- TradingJournal.save_episodic_memory() — uses market_snapshot as entry fallback
- TradingJournal.save_episodic_memory() — derives regime from risk_assessment
- TradingJournal.save_procedural_memory() — creates new PROCEDURAL memory
- TradingJournal.save_procedural_memory() — reinforces existing matching memory
- TradingJournal.save_procedural_memory() — no-op when memory_store is None
- TradingJournal.save_procedural_memory() — search failure falls through to save
- TradingJournal._save_learnings_to_memory() — procedural keywords route to save_procedural_memory
- TradingJournal._save_learnings_to_memory() — non-procedural strings saved as EPISODIC
- TradingJournal._save_learnings_to_memory() — procedural without regime saved as PROCEDURAL Memory directly
- TradingJournal.generate_reflection() — calls save_episodic_memory in addition to _save_learnings_to_memory
- ContextBuilder._fetch_learnings_section() — past-experience block included when symbol + regime provided
- ContextBuilder._fetch_learnings_section() — past-experience block skipped when symbol/regime not set
- ContextBuilder._fetch_learnings_section() — deduplication: past-experience IDs excluded from general list
- ContextBuilder._fetch_learnings_section() — returns empty when no memories exist
- ContextBuilder._fetch_learnings_section() — search failure is non-fatal (degraded to general only)
- ContextBuilder.build() — passes symbol + regime to _fetch_learnings_section
- ContextBuilder.build_trade_context() — convenience wrapper delegates to build()
- times_reinforced incremented on reinforcement path in save_procedural_memory()
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent.config import AgentConfig
from agent.memory.store import Memory, MemoryType
from agent.models.ecosystem import TradeReflection
from agent.trading.journal import TradingJournal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-loop")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_memory(
    memory_type: MemoryType = MemoryType.EPISODIC,
    content: str = "test memory",
    memory_id: str | None = None,
    times_reinforced: int = 1,
) -> Memory:
    now = datetime.now(UTC)
    return Memory(
        id=memory_id or str(uuid4()),
        agent_id=str(uuid4()),
        memory_type=memory_type,
        content=content,
        source="test",
        confidence=Decimal("0.8000"),
        times_reinforced=times_reinforced,
        created_at=now,
        last_accessed_at=now,
    )


def _make_decision_dict(
    symbol: str = "BTCUSDT",
    direction: str = "buy",
    confidence: float = 0.75,
    outcome_pnl: float | None = 42.50,
    regime: str | None = "trending_up",
) -> dict[str, Any]:
    risk: dict[str, Any] = {"approved": True}
    if regime:
        risk["detected_regime"] = regime
    return {
        "id": str(uuid4()),
        "agent_id": str(uuid4()),
        "decision_type": "trade",
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "reasoning": "Ensemble buy signal at 75% confidence.",
        "market_snapshot": {symbol: "67500.00"},
        "signals": [],
        "risk_assessment": risk,
        "outcome_pnl": outcome_pnl,
        "created_at": datetime.now(UTC),
    }


def _make_journal(config: AgentConfig, memory_store: MagicMock | None = None) -> TradingJournal:
    return TradingJournal(config=config, memory_store=memory_store)


def _make_mock_store(search_results: list[Memory] | None = None) -> MagicMock:
    """Return an AsyncMock MemoryStore (typed as MagicMock for convenience)."""
    store = MagicMock()
    store.save = AsyncMock(return_value=str(uuid4()))
    store.search = AsyncMock(return_value=search_results or [])
    store.reinforce = AsyncMock(return_value=None)
    store.get_recent = AsyncMock(return_value=[])
    return store


# ---------------------------------------------------------------------------
# TestSaveEpisodicMemory
# ---------------------------------------------------------------------------


class TestSaveEpisodicMemory:
    """Tests for TradingJournal.save_episodic_memory()."""

    async def test_no_op_when_no_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns empty string and saves nothing when memory_store is None."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config, memory_store=None)
        decision = _make_decision_dict()

        result = await journal.save_episodic_memory(
            agent_id=str(uuid4()),
            decision_row=decision,
        )

        assert result == ""

    async def test_saves_episodic_memory_with_explicit_prices(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save_episodic_memory creates a Memory record using provided prices."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)
        decision = _make_decision_dict(symbol="BTCUSDT", direction="buy", outcome_pnl=42.50)
        memory_id = str(uuid4())
        store.save.return_value = memory_id

        result = await journal.save_episodic_memory(
            agent_id=str(uuid4()),
            decision_row=decision,
            entry_price=Decimal("67500.00"),
            exit_price=Decimal("68000.00"),
        )

        assert result == memory_id
        store.save.assert_awaited_once()
        saved_mem: Memory = store.save.call_args[0][0]
        assert saved_mem.memory_type == MemoryType.EPISODIC
        assert "BTCUSDT" in saved_mem.content
        assert "67500.00" in saved_mem.content
        assert "68000.00" in saved_mem.content

    async def test_falls_back_to_snapshot_for_entry_price(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to market_snapshot for entry price when entry_price not provided."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)
        decision = _make_decision_dict(symbol="ETHUSDT", outcome_pnl=5.0)
        decision["market_snapshot"] = {"ETHUSDT": "3200.00"}

        await journal.save_episodic_memory(
            agent_id=str(uuid4()),
            decision_row=decision,
        )

        saved_mem: Memory = store.save.call_args[0][0]
        assert "3200.00" in saved_mem.content

    async def test_derives_regime_from_risk_assessment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regime from risk_assessment.detected_regime is embedded in the memory content."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)
        decision = _make_decision_dict(regime="ranging")

        await journal.save_episodic_memory(
            agent_id=str(uuid4()),
            decision_row=decision,
        )

        saved_mem: Memory = store.save.call_args[0][0]
        assert "ranging" in saved_mem.content

    async def test_explicit_regime_overrides_risk_assessment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicitly provided regime takes precedence over risk_assessment."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)
        decision = _make_decision_dict(regime="ranging")

        await journal.save_episodic_memory(
            agent_id=str(uuid4()),
            decision_row=decision,
            regime="volatile",
        )

        saved_mem: Memory = store.save.call_args[0][0]
        assert "volatile" in saved_mem.content
        assert "ranging" not in saved_mem.content

    async def test_returns_empty_string_on_save_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty string when store.save() raises an exception."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        store.save.side_effect = Exception("DB error")
        journal = _make_journal(config, memory_store=store)
        decision = _make_decision_dict()

        result = await journal.save_episodic_memory(
            agent_id=str(uuid4()),
            decision_row=decision,
        )

        assert result == ""


# ---------------------------------------------------------------------------
# TestSaveProceduralMemory
# ---------------------------------------------------------------------------


class TestSaveProceduralMemory:
    """Tests for TradingJournal.save_procedural_memory()."""

    async def test_no_op_when_no_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns empty string and saves nothing when memory_store is None."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config, memory_store=None)

        result = await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="RSI divergence works in trending regime",
            regime="trending_up",
        )

        assert result == ""

    async def test_creates_new_procedural_memory_when_no_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Creates a new PROCEDURAL memory when no matching memory is found."""
        config = _make_config(monkeypatch)
        store = _make_mock_store(search_results=[])
        memory_id = str(uuid4())
        store.save.return_value = memory_id
        journal = _make_journal(config, memory_store=store)

        result = await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="Volume breakout works in trending regime",
            regime="trending_up",
            symbol="BTCUSDT",
        )

        assert result == memory_id
        store.save.assert_awaited_once()
        saved_mem: Memory = store.save.call_args[0][0]
        assert saved_mem.memory_type == MemoryType.PROCEDURAL
        assert "trending_up" in saved_mem.content
        assert "BTCUSDT" in saved_mem.content

    async def test_reinforces_existing_matching_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reinforces a matching existing memory instead of creating a duplicate."""
        config = _make_config(monkeypatch)
        existing_id = str(uuid4())
        existing = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="Volume breakout works for BTCUSDT in trending_up regime",
            memory_id=existing_id,
            times_reinforced=2,
        )
        store = _make_mock_store(search_results=[existing])
        journal = _make_journal(config, memory_store=store)

        result = await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="Volume breakout works in trending",
            regime="trending_up",
            symbol="BTCUSDT",
        )

        # Should reinforce, not save a new one.
        assert result == existing_id
        store.reinforce.assert_awaited_once_with(existing_id)
        store.save.assert_not_awaited()

    async def test_times_reinforced_not_duplicated_across_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each reinforcement call increments times_reinforced by exactly one."""
        config = _make_config(monkeypatch)
        existing_id = str(uuid4())
        existing = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="RSI divergence works for ETHUSDT in ranging regime",
            memory_id=existing_id,
            times_reinforced=5,
        )
        store = _make_mock_store(search_results=[existing])
        journal = _make_journal(config, memory_store=store)

        await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="RSI divergence works in ranging",
            regime="ranging",
            symbol="ETHUSDT",
        )

        # Reinforce should be called exactly once per invocation.
        assert store.reinforce.await_count == 1

    async def test_search_failure_falls_through_to_save(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When search raises, a new memory is saved (graceful degradation)."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        store.search.side_effect = Exception("Redis unavailable")
        memory_id = str(uuid4())
        store.save.return_value = memory_id
        journal = _make_journal(config, memory_store=store)

        result = await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="avoid low-volume entries",
            regime="ranging",
        )

        assert result == memory_id
        store.save.assert_awaited_once()

    async def test_symbol_scoping_in_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Symbol is included in the saved content string."""
        config = _make_config(monkeypatch)
        store = _make_mock_store(search_results=[])
        journal = _make_journal(config, memory_store=store)

        await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="momentum works",
            regime="trending_up",
            symbol="SOLUSDT",
        )

        saved_mem: Memory = store.save.call_args[0][0]
        assert "SOLUSDT" in saved_mem.content

    async def test_no_symbol_scoping_without_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Content does not include 'for None' when symbol is not provided."""
        config = _make_config(monkeypatch)
        store = _make_mock_store(search_results=[])
        journal = _make_journal(config, memory_store=store)

        await journal.save_procedural_memory(
            agent_id=str(uuid4()),
            pattern="avoid trading at low volume",
            regime="volatile",
        )

        saved_mem: Memory = store.save.call_args[0][0]
        assert "None" not in saved_mem.content


# ---------------------------------------------------------------------------
# TestSaveLearningsToMemory (updated behaviour)
# ---------------------------------------------------------------------------


class TestSaveLearningsToMemory:
    """Tests for TradingJournal._save_learnings_to_memory (updated routing)."""

    async def test_no_op_when_store_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_save_learnings_to_memory is a no-op when memory_store is None."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config, memory_store=None)

        # Should not raise.
        await journal._save_learnings_to_memory(
            agent_id=str(uuid4()),
            learnings=["Good entry at RSI divergence."],
            source="test",
        )

    async def test_no_op_when_learnings_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_save_learnings_to_memory is a no-op when the learnings list is empty."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)

        await journal._save_learnings_to_memory(
            agent_id=str(uuid4()),
            learnings=[],
            source="test",
        )

        store.save.assert_not_awaited()

    async def test_procedural_keyword_routes_to_save_procedural_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Learnings with procedural keywords and a known regime call save_procedural_memory."""
        config = _make_config(monkeypatch)
        store = _make_mock_store(search_results=[])
        journal = _make_journal(config, memory_store=store)
        agent_id = str(uuid4())
        decision = _make_decision_dict(regime="trending_up", symbol="BTCUSDT")

        # Spy on save_procedural_memory.
        journal.save_procedural_memory = AsyncMock(return_value=str(uuid4()))

        await journal._save_learnings_to_memory(
            agent_id=agent_id,
            learnings=["always check regime before entering position"],
            source="test",
            decision_row=decision,
        )

        journal.save_procedural_memory.assert_awaited_once()
        call_kwargs = journal.save_procedural_memory.call_args
        assert call_kwargs.kwargs.get("regime") == "trending_up" or (
            len(call_kwargs.args) > 2 and call_kwargs.args[2] == "trending_up"
        )

    async def test_non_procedural_learning_saved_as_episodic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Learnings without procedural keywords and without a regime are saved as EPISODIC."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)

        await journal._save_learnings_to_memory(
            agent_id=str(uuid4()),
            learnings=["Profitable trade on BTCUSDT at 75% confidence."],
            source="test",
            # No decision_row => no regime => no procedural routing
        )

        store.save.assert_awaited_once()
        saved_mem: Memory = store.save.call_args[0][0]
        assert saved_mem.memory_type == MemoryType.EPISODIC

    async def test_procedural_without_regime_saved_as_procedural_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Procedural-keyword learnings without regime bypass save_procedural_memory and go direct."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)

        await journal._save_learnings_to_memory(
            agent_id=str(uuid4()),
            learnings=["always verify volume before entry"],
            source="test",
            # No decision_row => regime is None
        )

        store.save.assert_awaited_once()
        saved_mem: Memory = store.save.call_args[0][0]
        assert saved_mem.memory_type == MemoryType.PROCEDURAL


# ---------------------------------------------------------------------------
# TestGenerateReflectionMemoryIntegration
# ---------------------------------------------------------------------------


class TestGenerateReflectionMemoryIntegration:
    """Tests that generate_reflection() calls save_episodic_memory before _save_learnings."""

    async def test_generate_reflection_calls_save_episodic_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """generate_reflection() invokes save_episodic_memory on the decision row."""
        config = _make_config(monkeypatch)
        store = _make_mock_store()
        journal = _make_journal(config, memory_store=store)

        decision_row = _make_decision_dict()

        # Stub internal helpers.
        journal._fetch_decision = AsyncMock(return_value=decision_row)
        journal._llm_reflection = AsyncMock(return_value=None)
        reflection = TradeReflection(
            trade_id=str(uuid4()),
            symbol="BTCUSDT",
            entry_quality="good",
            exit_quality="good",
            pnl=Decimal("42.50"),
            max_adverse_excursion=Decimal("5.00"),
            learnings=["Strong momentum."],
            would_take_again=True,
            improvement_notes="",
        )
        journal._template_reflection = MagicMock(return_value=reflection)
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))

        # Spy on save_episodic_memory.
        journal.save_episodic_memory = AsyncMock(return_value=str(uuid4()))

        await journal.generate_reflection(decision_id=str(uuid4()))

        journal.save_episodic_memory.assert_awaited_once()
        call_kwargs = journal.save_episodic_memory.call_args
        # First positional arg after self is agent_id, second is decision_row.
        assert call_kwargs.kwargs.get("decision_row") == decision_row or (
            len(call_kwargs.args) >= 2 and call_kwargs.args[1] == decision_row
        )


# ---------------------------------------------------------------------------
# TestContextBuilderLearningsSection
# ---------------------------------------------------------------------------


class TestContextBuilderLearningsSection:
    """Tests for ContextBuilder._fetch_learnings_section() with symbol + regime."""

    def _make_builder(self, monkeypatch: pytest.MonkeyPatch, store: MagicMock) -> object:
        """Build a ContextBuilder with the given memory store."""
        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-ctx")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        return ContextBuilder(config=config, memory_store=store)

    async def test_past_experience_block_included_when_symbol_and_regime_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past Experience section appears when symbol + regime are specified."""
        procedural_mem = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="Volume breakout works for BTCUSDT in trending_up regime",
        )
        store = _make_mock_store(search_results=[procedural_mem])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(
            agent_id=str(uuid4()),
            symbol="BTCUSDT",
            regime="trending_up",
        )

        assert "Past Experience" in result
        assert "BTCUSDT" in result or "trending_up" in result

    async def test_past_experience_block_skipped_without_symbol_or_regime(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past Experience section is absent when neither symbol nor regime is given."""
        mem = _make_memory(memory_type=MemoryType.PROCEDURAL, content="Some rule.")
        store = _make_mock_store()
        store.get_recent = AsyncMock(return_value=[mem])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(agent_id=str(uuid4()))

        assert "Past Experience" not in result
        store.search.assert_not_awaited()

    async def test_deduplication_past_experience_ids_excluded_from_general(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Memory shown in past-experience block does not repeat in general section."""
        shared_id = str(uuid4())
        procedural_mem = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="RSI divergence works for BTCUSDT in trending_up regime",
            memory_id=shared_id,
        )
        store = _make_mock_store(search_results=[procedural_mem])
        # The same memory is also returned by get_recent.
        store.get_recent = AsyncMock(return_value=[procedural_mem])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(
            agent_id=str(uuid4()),
            symbol="BTCUSDT",
            regime="trending_up",
        )

        # The content should appear exactly once.
        assert result.count("RSI divergence works for BTCUSDT") == 1

    async def test_returns_empty_when_no_memories(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty string when memory store has no entries."""
        store = _make_mock_store(search_results=[])
        store.get_recent = AsyncMock(return_value=[])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(
            agent_id=str(uuid4()),
            symbol="BTCUSDT",
            regime="ranging",
        )

        assert result == ""

    async def test_search_failure_degrades_to_general_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Search failure is non-fatal; general memories are still included."""
        store = _make_mock_store()
        store.search.side_effect = Exception("Redis unavailable")
        general_mem = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="General rule from recent memory.",
        )
        store.get_recent = AsyncMock(return_value=[general_mem])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(
            agent_id=str(uuid4()),
            symbol="BTCUSDT",
            regime="ranging",
        )

        assert "General rule from recent memory" in result

    async def test_times_reinforced_shown_for_multi_reinforced_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reinforcement count is shown in the past-experience block for reinforced memories."""
        multi_reinforced = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="Volume works for BTCUSDT in trending_up regime",
            times_reinforced=7,
        )
        store = _make_mock_store(search_results=[multi_reinforced])
        store.get_recent = AsyncMock(return_value=[])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(
            agent_id=str(uuid4()),
            symbol="BTCUSDT",
            regime="trending_up",
        )

        assert "reinforced 7x" in result

    async def test_no_reinforcement_note_for_new_memories(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reinforcement note is absent for memories with times_reinforced == 1."""
        single = _make_memory(
            memory_type=MemoryType.PROCEDURAL,
            content="Some rule for BTCUSDT in ranging regime",
            times_reinforced=1,
        )
        store = _make_mock_store(search_results=[single])
        store.get_recent = AsyncMock(return_value=[])
        builder = self._make_builder(monkeypatch, store)

        result = await builder._fetch_learnings_section(
            agent_id=str(uuid4()),
            symbol="BTCUSDT",
            regime="ranging",
        )

        assert "reinforced" not in result


# ---------------------------------------------------------------------------
# TestContextBuilderBuildIntegration
# ---------------------------------------------------------------------------


class TestContextBuilderBuildIntegration:
    """Tests that ContextBuilder.build() and build_trade_context() pass symbol/regime through."""

    def _make_builder(self, monkeypatch: pytest.MonkeyPatch, store: MagicMock) -> object:
        from agent.conversation.context import ContextBuilder  # noqa: PLC0415

        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-build")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        return ContextBuilder(config=config, memory_store=store)

    def _make_mock_session(self) -> MagicMock:
        session = MagicMock()
        session.session_id = uuid4()
        session.get_context = AsyncMock(return_value=[])
        return session

    async def test_build_passes_symbol_and_regime_to_learnings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build() forwards symbol and regime to _fetch_learnings_section."""
        store = _make_mock_store(search_results=[])
        store.get_recent = AsyncMock(return_value=[])
        builder = self._make_builder(monkeypatch, store)

        # Patch expensive sections to avoid network calls.
        builder._build_system_section = AsyncMock(return_value="## System")
        builder._fetch_portfolio_section = AsyncMock(return_value="")
        builder._fetch_strategy_section = AsyncMock(return_value="")
        builder._build_permissions_section = MagicMock(return_value="")
        builder._fetch_learnings_section = AsyncMock(return_value="")

        session = self._make_mock_session()

        await builder.build(
            agent_id=str(uuid4()),
            session=session,
            symbol="ETHUSDT",
            regime="ranging",
        )

        builder._fetch_learnings_section.assert_awaited_once_with(
            str(builder._fetch_learnings_section.call_args[0][0]),
            symbol="ETHUSDT",
            regime="ranging",
        )

    async def test_build_trade_context_delegates_to_build(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build_trade_context() calls build() with symbol and regime set."""
        store = _make_mock_store(search_results=[])
        store.get_recent = AsyncMock(return_value=[])
        builder = self._make_builder(monkeypatch, store)

        builder.build = AsyncMock(return_value=[{"role": "system", "content": "ok"}])
        session = self._make_mock_session()
        agent_id = str(uuid4())

        result = await builder.build_trade_context(
            agent_id=agent_id,
            session=session,
            symbol="SOLUSDT",
            regime="volatile",
        )

        builder.build.assert_awaited_once_with(
            agent_id=agent_id,
            session=session,
            max_tokens=None,
            symbol="SOLUSDT",
            regime="volatile",
        )
        assert result == [{"role": "system", "content": "ok"}]

    async def test_build_without_symbol_regime_does_not_pass_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """build() with no symbol/regime calls _fetch_learnings_section without them."""
        store = _make_mock_store()
        store.get_recent = AsyncMock(return_value=[])
        builder = self._make_builder(monkeypatch, store)

        builder._build_system_section = AsyncMock(return_value="## System")
        builder._fetch_portfolio_section = AsyncMock(return_value="")
        builder._fetch_strategy_section = AsyncMock(return_value="")
        builder._build_permissions_section = MagicMock(return_value="")
        builder._fetch_learnings_section = AsyncMock(return_value="")

        session = self._make_mock_session()

        await builder.build(agent_id=str(uuid4()), session=session)

        builder._fetch_learnings_section.assert_awaited_once_with(
            str(builder._fetch_learnings_section.call_args[0][0]),
            symbol=None,
            regime=None,
        )
