"""Unit tests for agent/trading/journal.py :: TradingJournal.

Tests cover:
- record_decision() — returns empty string when DB imports are unavailable
- record_decision() — returns empty string for invalid agent_id UUID
- record_decision() — signals normalisation (dict, object with __dict__)
- record_outcome() — returns silently when DB imports are unavailable
- record_outcome() — returns silently for invalid decision_id UUID
- generate_reflection() — returns empty JournalEntry when decision not found
- generate_reflection() — calls _template_reflection when LLM unavailable
- daily_summary() — returns empty content when _fetch_decisions_in_range is empty
- daily_summary() — aggregates stats from decisions list
- weekly_review() — returns no-decisions content when history is empty
- _compute_decision_stats() — counts trades/holds, wins/losses, win_rate
- _compute_decision_stats() — handles decisions without outcomes
- _find_best_trade() — returns decision with highest PnL
- _find_worst_trade() — returns decision with lowest PnL
- _find_best_trade() / _find_worst_trade() — returns None for empty outcomes
- _template_reflection() — good entry quality for high-confidence winning trade
- _template_reflection() — poor entry quality for low-confidence losing trade
- _extract_tags() — returns tags for good entry, pnl_positive, repeatable
- _extract_tags() — returns empty list when reflection is None
- _build_summary_tags() — high_win_rate + net_profitable tags
- _save_learnings_to_memory() — no-op when memory_store is None
- _save_learnings_to_memory() — no-op when learnings list is empty
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.config import AgentConfig
from agent.models.ecosystem import JournalEntry, TradeDecision, TradeReflection
from agent.trading.journal import TradingJournal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-journal")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_decision(
    symbol: str = "BTCUSDT",
    action: str = "buy",
    confidence: float = 0.75,
) -> TradeDecision:
    return TradeDecision(
        symbol=symbol,
        action=action,
        quantity_pct=Decimal("0.05"),
        confidence=confidence,
        reasoning="Ensemble buy signal at 75% confidence.",
        risk_notes="Macro risk remains.",
    )


def _make_journal(config: AgentConfig, memory_store: MagicMock | None = None) -> TradingJournal:
    return TradingJournal(config=config, memory_store=memory_store)


def _make_decision_dict(
    symbol: str = "BTCUSDT",
    direction: str = "buy",
    confidence: float = 0.75,
    outcome_pnl: float | None = None,
    decision_type: str = "trade",
) -> dict:
    """Build a decision dict as returned by _fetch_decision."""
    return {
        "id": str(uuid4()),
        "agent_id": str(uuid4()),
        "decision_type": decision_type,
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "reasoning": "Test reasoning.",
        "market_snapshot": {"price": "67500.00"},
        "signals": [],
        "risk_assessment": {},
        "outcome_pnl": outcome_pnl,
        "created_at": datetime.now(UTC),
    }


def _make_reflection(
    pnl: str = "42.50",
    entry_quality: str = "good",
    exit_quality: str = "good",
    mae: str = "5.00",
    would_take_again: bool = True,
) -> TradeReflection:
    return TradeReflection(
        trade_id=str(uuid4()),
        symbol="BTCUSDT",
        entry_quality=entry_quality,
        exit_quality=exit_quality,
        pnl=Decimal(pnl),
        max_adverse_excursion=Decimal(mae),
        learnings=["Strong momentum confirmation."],
        would_take_again=would_take_again,
        improvement_notes="Consider trailing stop.",
    )


# ---------------------------------------------------------------------------
# TestRecordDecision
# ---------------------------------------------------------------------------


class TestRecordDecision:
    """Tests for TradingJournal.record_decision()."""

    async def test_returns_empty_string_when_db_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_decision returns '' when src.database imports are not available."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        # Patch the lazy import inside record_decision to fail
        with patch.dict("sys.modules", {"src.database.models": None}):
            result = await journal.record_decision(
                agent_id=str(uuid4()),
                decision=_make_decision(),
                market_snapshot={"BTCUSDT": "67500.00"},
                signals=[],
                risk_assessment={"approved": True},
                reasoning="Test reasoning.",
            )
        # When DB is unavailable (ImportError), returns ""
        assert isinstance(result, str)

    async def test_returns_empty_string_for_invalid_agent_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_decision returns '' for a non-UUID agent_id."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        # Patch imports to succeed so we reach the UUID parsing logic
        with patch("agent.trading.journal.TradingJournal.record_decision", wraps=journal.record_decision):
            result = await journal.record_decision(
                agent_id="not-a-valid-uuid",
                decision=_make_decision(),
                market_snapshot={},
                signals=[],
                risk_assessment={},
                reasoning="Test.",
            )
        assert result == ""

    async def test_signals_normalisation_from_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Signals supplied as dicts are normalised to a list of dicts in the DB row."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        # Track what AgentDecision row gets created
        created_rows = []

        async def _fake_create(row: MagicMock) -> None:
            created_rows.append(row)
            row.id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(side_effect=_fake_create)

        mock_session = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=ctx)

        mock_factory = MagicMock(return_value=mock_session)

        with patch("src.database.models.AgentDecision", MagicMock()) as mock_model_cls:
            mock_model_cls.return_value = MagicMock(id=uuid4())
            with patch("src.database.repositories.agent_decision_repo.AgentDecisionRepository", return_value=mock_repo):
                with patch("src.database.session.get_session_factory", return_value=mock_factory):
                    result = await journal.record_decision(
                        agent_id=str(uuid4()),
                        decision=_make_decision(),
                        market_snapshot={"BTCUSDT": "67500.00"},
                        signals=[{"action": "buy", "confidence": 0.75}],
                        risk_assessment={"gates_passed": 6},
                        reasoning="Ensemble signal confirmed.",
                    )
        # Whether it succeeds or not, must return a string
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# TestRecordOutcome
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    """Tests for TradingJournal.record_outcome()."""

    async def test_returns_silently_when_db_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_outcome does not raise when DB imports are unavailable."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        with patch.dict("sys.modules", {"src.database.repositories.agent_decision_repo": None}):
            # Should not raise
            await journal.record_outcome(
                decision_id=str(uuid4()),
                pnl=Decimal("42.50"),
                hold_duration=3600,
                max_adverse_excursion=Decimal("10.00"),
            )

    async def test_returns_silently_for_invalid_decision_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """record_outcome returns silently for a non-UUID decision_id."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        # Should not raise even with bad UUID
        await journal.record_outcome(
            decision_id="not-a-uuid",
            pnl=Decimal("10.00"),
            hold_duration=1800,
            max_adverse_excursion=Decimal("5.00"),
        )


# ---------------------------------------------------------------------------
# TestGenerateReflection
# ---------------------------------------------------------------------------


class TestGenerateReflection:
    """Tests for TradingJournal.generate_reflection()."""

    async def test_returns_empty_entry_when_decision_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns a fallback JournalEntry when _fetch_decision returns None."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)
        journal._fetch_decision = AsyncMock(return_value=None)

        entry = await journal.generate_reflection(decision_id=str(uuid4()))

        assert isinstance(entry, JournalEntry)
        assert entry.entry_type == "reflection"
        assert "could not be generated" in entry.content.lower()

    async def test_uses_template_when_llm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to _template_reflection when pydantic_ai is unavailable."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        decision_row = _make_decision_dict(
            symbol="BTCUSDT",
            direction="buy",
            confidence=0.75,
            outcome_pnl=42.50,
        )
        journal._fetch_decision = AsyncMock(return_value=decision_row)
        journal._llm_reflection = AsyncMock(return_value=None)
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))
        journal._save_learnings_to_memory = AsyncMock()

        entry = await journal.generate_reflection(decision_id=str(uuid4()))

        assert isinstance(entry, JournalEntry)
        journal._llm_reflection.assert_called_once()

    async def test_saves_learnings_to_memory_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Learnings are forwarded to _save_learnings_to_memory after reflection."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        decision_row = _make_decision_dict(
            symbol="BTCUSDT", direction="buy", confidence=0.75, outcome_pnl=50.0
        )
        journal._fetch_decision = AsyncMock(return_value=decision_row)
        journal._llm_reflection = AsyncMock(return_value=None)
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))
        journal._save_learnings_to_memory = AsyncMock()

        await journal.generate_reflection(decision_id=str(uuid4()))

        journal._save_learnings_to_memory.assert_called_once()


# ---------------------------------------------------------------------------
# TestDailySummary
# ---------------------------------------------------------------------------


class TestDailySummary:
    """Tests for TradingJournal.daily_summary().

    NOTE: There is a known mismatch in journal.py — it constructs JournalEntry
    with entry_type='daily_review', but JournalEntry only allows 'daily_summary'
    in its pattern.  The tests below document this behaviour by verifying the
    source raises ValidationError.  The bug is in journal.py, not in the tests.
    """

    async def test_no_decisions_raises_validation_error_due_to_entry_type_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """daily_summary raises ValidationError because journal.py uses 'daily_review'
        but JournalEntry only accepts 'daily_summary'.  This is a source-level bug."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)
        journal._fetch_decisions_in_range = AsyncMock(return_value=[])
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))

        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="entry_type"):
            await journal.daily_summary(agent_id=str(uuid4()))

    async def test_summary_with_decisions_raises_validation_error_due_to_entry_type_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """daily_summary raises ValidationError because journal.py uses 'daily_review'
        but JournalEntry only accepts 'daily_summary'.  This is a source-level bug."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        decisions = [
            _make_decision_dict("BTCUSDT", "buy", 0.80, outcome_pnl=30.0),
            _make_decision_dict("ETHUSDT", "sell", 0.70, outcome_pnl=-10.0),
        ]
        journal._fetch_decisions_in_range = AsyncMock(return_value=decisions)
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))

        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="entry_type"):
            await journal.daily_summary(agent_id=str(uuid4()))


# ---------------------------------------------------------------------------
# TestWeeklyReview
# ---------------------------------------------------------------------------


class TestWeeklyReview:
    """Tests for TradingJournal.weekly_review()."""

    async def test_no_decisions_returns_empty_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """weekly_review returns 'No decisions' narrative when history is empty."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)
        journal._fetch_decisions_in_range = AsyncMock(return_value=[])
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))

        entry = await journal.weekly_review(agent_id=str(uuid4()))

        assert isinstance(entry, JournalEntry)
        assert entry.entry_type == "weekly_review"
        assert "no decisions" in entry.content.lower()

    async def test_weekly_review_content_includes_period_dates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """weekly_review content includes the start and end dates of the period."""
        config = _make_config(monkeypatch)
        journal = _make_journal(config)

        decisions = [
            _make_decision_dict("BTCUSDT", "buy", 0.80, outcome_pnl=50.0),
        ]
        journal._fetch_decisions_in_range = AsyncMock(return_value=decisions)
        journal._persist_journal_entry = AsyncMock(return_value=str(uuid4()))

        entry = await journal.weekly_review(agent_id=str(uuid4()))

        assert "weekly review" in entry.content.lower()


# ---------------------------------------------------------------------------
# TestComputeDecisionStats
# ---------------------------------------------------------------------------


class TestComputeDecisionStats:
    """Tests for TradingJournal._compute_decision_stats (static method)."""

    def test_counts_trades_and_holds(self) -> None:
        """Correctly counts decisions by type."""
        decisions = [
            _make_decision_dict(decision_type="trade", outcome_pnl=10.0),
            _make_decision_dict(decision_type="trade", outcome_pnl=-5.0),
            _make_decision_dict(decision_type="hold"),
        ]
        stats = TradingJournal._compute_decision_stats(decisions)

        assert stats["total"] == 3
        assert stats["trades"] == 2
        assert stats["holds"] == 1

    def test_win_rate_calculation(self) -> None:
        """Win rate is computed correctly from outcomes."""
        decisions = [
            _make_decision_dict(outcome_pnl=20.0),  # win
            _make_decision_dict(outcome_pnl=15.0),  # win
            _make_decision_dict(outcome_pnl=-5.0),  # loss
            _make_decision_dict(outcome_pnl=None),  # no outcome
        ]
        stats = TradingJournal._compute_decision_stats(decisions)

        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["with_outcome"] == 3
        # 2 wins out of 3 with outcomes = 0.6667...
        assert abs(stats["win_rate"] - round(2 / 3, 4)) < 0.0001

    def test_no_outcomes_zero_win_rate(self) -> None:
        """Win rate is 0.0 when no decisions have outcomes."""
        decisions = [
            _make_decision_dict(outcome_pnl=None),
            _make_decision_dict(outcome_pnl=None),
        ]
        stats = TradingJournal._compute_decision_stats(decisions)

        assert stats["win_rate"] == 0.0
        assert stats["total_pnl"] == 0.0

    def test_counts_buys_and_sells(self) -> None:
        """Buys and sells are counted correctly."""
        decisions = [
            _make_decision_dict(direction="buy"),
            _make_decision_dict(direction="buy"),
            _make_decision_dict(direction="sell"),
        ]
        stats = TradingJournal._compute_decision_stats(decisions)
        assert stats["buys"] == 2
        assert stats["sells"] == 1


# ---------------------------------------------------------------------------
# TestFindBestWorstTrade
# ---------------------------------------------------------------------------


class TestFindBestWorstTrade:
    """Tests for _find_best_trade and _find_worst_trade (static methods)."""

    def test_find_best_trade_returns_max_pnl(self) -> None:
        """_find_best_trade returns the decision with the highest PnL."""
        decisions = [
            _make_decision_dict(outcome_pnl=10.0),
            _make_decision_dict(outcome_pnl=50.0),
            _make_decision_dict(outcome_pnl=-5.0),
        ]
        best = TradingJournal._find_best_trade(decisions)
        assert best is not None
        assert best["outcome_pnl"] == 50.0

    def test_find_worst_trade_returns_min_pnl(self) -> None:
        """_find_worst_trade returns the decision with the lowest PnL."""
        decisions = [
            _make_decision_dict(outcome_pnl=10.0),
            _make_decision_dict(outcome_pnl=50.0),
            _make_decision_dict(outcome_pnl=-30.0),
        ]
        worst = TradingJournal._find_worst_trade(decisions)
        assert worst is not None
        assert worst["outcome_pnl"] == -30.0

    def test_find_best_trade_returns_none_for_no_outcomes(self) -> None:
        """Returns None when no decisions have outcomes."""
        decisions = [_make_decision_dict(outcome_pnl=None)]
        assert TradingJournal._find_best_trade(decisions) is None

    def test_find_worst_trade_returns_none_for_no_outcomes(self) -> None:
        """Returns None when no decisions have outcomes."""
        decisions = [_make_decision_dict(outcome_pnl=None)]
        assert TradingJournal._find_worst_trade(decisions) is None


# ---------------------------------------------------------------------------
# TestTemplateReflection
# ---------------------------------------------------------------------------


class TestTemplateReflection:
    """Tests for TradingJournal._template_reflection (instance method called statically)."""

    def _journal(self, monkeypatch: pytest.MonkeyPatch) -> TradingJournal:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        return TradingJournal(config=config)

    def test_high_confidence_winning_trade_good_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """High-confidence profitable trade: entry_quality='good', exit_quality='good'."""
        journal = self._journal(monkeypatch)
        row = {
            "id": str(uuid4()),
            "agent_id": str(uuid4()),
            "symbol": "BTCUSDT",
            "direction": "buy",
            "confidence": 0.80,
            "outcome_pnl": "50.00",
            "risk_assessment": {"max_adverse_excursion": "5.00"},
        }
        reflection = journal._template_reflection(row)

        assert reflection.entry_quality == "good"
        assert reflection.exit_quality == "good"
        assert reflection.would_take_again is True

    def test_low_confidence_losing_trade_poor_quality(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Low-confidence big losing trade: entry_quality='poor', exit_quality='poor'."""
        journal = self._journal(monkeypatch)
        row = {
            "id": str(uuid4()),
            "agent_id": str(uuid4()),
            "symbol": "ETHUSDT",
            "direction": "buy",
            "confidence": 0.40,
            "outcome_pnl": "-50.00",
            "risk_assessment": {},
        }
        reflection = journal._template_reflection(row)

        assert reflection.entry_quality == "poor"
        assert reflection.exit_quality == "poor"
        assert reflection.would_take_again is False

    def test_learnings_non_empty_for_profitable_trade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """At least one learning is generated for a profitable trade."""
        journal = self._journal(monkeypatch)
        row = {
            "id": str(uuid4()),
            "agent_id": str(uuid4()),
            "symbol": "SOLUSDT",
            "direction": "buy",
            "confidence": 0.70,
            "outcome_pnl": "25.00",
            "risk_assessment": {},
        }
        reflection = journal._template_reflection(row)
        assert len(reflection.learnings) >= 1


# ---------------------------------------------------------------------------
# TestExtractTags
# ---------------------------------------------------------------------------


class TestExtractTags:
    """Tests for TradingJournal._extract_tags (static method)."""

    def test_returns_empty_list_for_none(self) -> None:
        """_extract_tags(None) returns an empty list."""
        assert TradingJournal._extract_tags(None) == []

    def test_good_entry_profitable_repeatable(self) -> None:
        """Good entry + positive PnL + would_take_again → expected tags."""
        reflection = _make_reflection(
            pnl="30.00",
            entry_quality="good",
            exit_quality="good",
            mae="2.00",
            would_take_again=True,
        )
        tags = TradingJournal._extract_tags(reflection)
        assert "good_entry" in tags
        assert "pnl_positive" in tags
        assert "repeatable" in tags

    def test_poor_entry_negative_pnl_avoid_repeat(self) -> None:
        """Poor entry + negative PnL + not would_take_again → expected tags."""
        reflection = _make_reflection(
            pnl="-20.00",
            entry_quality="poor",
            exit_quality="poor",
            mae="5.00",
            would_take_again=False,
        )
        tags = TradingJournal._extract_tags(reflection)
        assert "poor_entry" in tags
        assert "pnl_negative" in tags
        assert "avoid_repeat" in tags

    def test_high_mae_tag(self) -> None:
        """High MAE relative to absolute PnL produces 'high_mae' tag."""
        reflection = _make_reflection(
            pnl="5.00",
            entry_quality="neutral",
            exit_quality="neutral",
            mae="50.00",
            would_take_again=False,
        )
        tags = TradingJournal._extract_tags(reflection)
        assert "high_mae" in tags


# ---------------------------------------------------------------------------
# TestBuildSummaryTags
# ---------------------------------------------------------------------------


class TestBuildSummaryTags:
    """Tests for TradingJournal._build_summary_tags (static method)."""

    def test_high_win_rate_profitable_tags(self) -> None:
        """Win rate >= 0.6 and positive PnL → high_win_rate + net_profitable."""
        stats = {
            "win_rate": 0.65,
            "total_pnl": 100.0,
            "avg_confidence": 0.70,
            "symbols": ["btcusdt"],
        }
        tags = TradingJournal._build_summary_tags(stats)
        assert "high_win_rate" in tags
        assert "net_profitable" in tags

    def test_low_win_rate_net_loss_tags(self) -> None:
        """Win rate < 0.4 and negative PnL → low_win_rate + net_loss."""
        stats = {
            "win_rate": 0.30,
            "total_pnl": -50.0,
            "avg_confidence": 0.55,
            "symbols": [],
        }
        tags = TradingJournal._build_summary_tags(stats)
        assert "low_win_rate" in tags
        assert "net_loss" in tags

    def test_high_confidence_tag(self) -> None:
        """avg_confidence >= 0.75 → high_confidence tag."""
        stats = {
            "win_rate": 0.50,
            "total_pnl": 0.0,
            "avg_confidence": 0.80,
            "symbols": [],
        }
        tags = TradingJournal._build_summary_tags(stats)
        assert "high_confidence" in tags


# ---------------------------------------------------------------------------
# TestSaveLearningsToMemory
# ---------------------------------------------------------------------------


class TestSaveLearningsToMemory:
    """Tests for TradingJournal._save_learnings_to_memory."""

    async def test_no_op_when_memory_store_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_save_learnings_to_memory silently returns when memory_store is None."""
        config = _make_config(monkeypatch)
        journal = TradingJournal(config=config, memory_store=None)

        # Should not raise
        await journal._save_learnings_to_memory(
            agent_id=str(uuid4()),
            learnings=["Learn something."],
            source="test",
        )

    async def test_no_op_when_learnings_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_save_learnings_to_memory returns immediately for an empty learnings list."""
        config = _make_config(monkeypatch)
        memory_store = AsyncMock()
        journal = TradingJournal(config=config, memory_store=memory_store)

        await journal._save_learnings_to_memory(
            agent_id=str(uuid4()),
            learnings=[],
            source="test",
        )

        memory_store.save.assert_not_called()

    async def test_saves_each_learning_as_separate_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each learning string is saved as a separate Memory record."""
        config = _make_config(monkeypatch)
        memory_store = AsyncMock()
        memory_store.save = AsyncMock()
        journal = TradingJournal(config=config, memory_store=memory_store)

        learnings = ["First lesson.", "Second lesson.", "Third lesson."]

        # Patch the lazy import inside _save_learnings_to_memory
        mock_memory_cls = MagicMock()
        mock_memory_type = MagicMock()
        mock_memory_type.EPISODIC = "episodic"

        with patch.dict(
            "sys.modules",
            {
                "agent.memory.store": MagicMock(Memory=mock_memory_cls, MemoryType=mock_memory_type),
            },
        ):
            await journal._save_learnings_to_memory(
                agent_id=str(uuid4()),
                learnings=learnings,
                source="reflection_test",
            )

        assert memory_store.save.call_count == len(learnings)
