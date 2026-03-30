"""Unit tests for src/tasks/agent_analytics.py — settle_agent_decisions task.

Tests the 5-minute Celery beat task that closes the feedback loop from trade
outcome to agent learning by settling unresolved AgentDecision rows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory():
    """Build a mock async session factory supporting async context-manager use."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_ctx)
    return mock_factory, mock_session


def _make_agent(agent_id=None, status="active"):
    """Create a lightweight agent mock."""
    obj = MagicMock()
    obj.id = agent_id or uuid4()
    obj.status = status
    obj.created_at = datetime.now(tz=UTC)
    return obj


def _make_decision(agent_id=None, order_id=None):
    """Create a lightweight AgentDecision mock (unresolved)."""
    obj = MagicMock()
    obj.id = uuid4()
    obj.agent_id = agent_id or uuid4()
    obj.order_id = order_id or uuid4()
    obj.outcome_pnl = None
    obj.outcome_recorded_at = None
    return obj


def _make_order(order_id=None, status="filled"):
    """Create a lightweight Order mock."""
    obj = MagicMock()
    obj.id = order_id or uuid4()
    obj.status = status
    return obj


def _make_trade(order_id=None, realized_pnl=None):
    """Create a lightweight Trade mock."""
    obj = MagicMock()
    obj.id = uuid4()
    obj.order_id = order_id or uuid4()
    obj.realized_pnl = realized_pnl
    return obj


def _mock_execute_chain(*scalars_sequence):
    """Return a chain of execute results yielding successive scalars sequences.

    Each positional arg becomes the ``scalars().all()`` or ``scalars().first()``
    return value for successive ``session.execute()`` calls.
    """
    results = []
    for item in scalars_sequence:
        result = MagicMock()
        if isinstance(item, list):
            result.scalars.return_value.all.return_value = item
            result.scalars.return_value.first.return_value = item[0] if item else None
        else:
            result.scalars.return_value.first.return_value = item
            result.scalars.return_value.all.return_value = [item] if item is not None else []
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Tests: settle_agent_decisions — happy-path flows
# ---------------------------------------------------------------------------


class TestSettleAgentDecisionsHappyPath:
    """Covers normal settlement flows where orders are filled and PnL exists."""

    async def test_no_active_agents_returns_zero_counts(self) -> None:
        """Task returns all-zero counts when no active agents exist."""
        mock_factory, mock_session = _make_session_factory()

        # Agent query returns empty list.
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = agent_result

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.agent_analytics import _run_settle_agent_decisions

            result = await _run_settle_agent_decisions()

        assert result["agents_processed"] == 0
        assert result["agents_failed"] == 0
        assert result["decisions_settled"] == 0
        assert result["decisions_skipped"] == 0
        assert result["duration_ms"] >= 0

    async def test_agent_with_no_unresolved_decisions_is_processed(self) -> None:
        """Agents that have no unresolved decisions are still counted as processed."""
        agent_id = uuid4()
        mock_factory, mock_session = _make_session_factory()

        # First execute: agent query returns one agent.
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        mock_session.execute.side_effect = [agent_result]

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[])

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            from importlib import import_module  # noqa: PLC0415

            mod = import_module("src.tasks.agent_analytics")
            result = await mod._run_settle_agent_decisions()

        assert result["agents_processed"] == 1
        assert result["decisions_settled"] == 0

    async def test_settled_decisions_with_realized_pnl(self) -> None:
        """Decisions linked to filled orders with realized_pnl are settled correctly."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_decision(agent_id=agent_id, order_id=order_id)
        order = _make_order(order_id=order_id, status="filled")
        trade1 = _make_trade(order_id=order_id, realized_pnl=Decimal("100.50"))
        trade2 = _make_trade(order_id=order_id, realized_pnl=Decimal("50.25"))

        mock_factory, mock_session = _make_session_factory()

        # Track calls to update_outcome so we can assert the computed PnL.
        settled_pnl: list[Decimal] = []

        async def mock_update_outcome(decision_id, *, outcome_pnl, outcome_recorded_at):
            settled_pnl.append(outcome_pnl)

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[decision])
        mock_decision_repo.update_outcome = mock_update_outcome

        # execute() calls: (1) order query, (2) trades query.
        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        trades_result = MagicMock()
        trades_result.scalars.return_value.all.return_value = [trade1, trade2]

        # Agent query is the first execute on the *outer* session.
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        # Outer session gets agent query; inner session gets order + trades queries.
        outer_mock_factory, outer_session = _make_session_factory()
        inner_mock_factory, inner_session = _make_session_factory()

        outer_session.execute.return_value = agent_result
        inner_session.execute.side_effect = [order_result, trades_result]

        call_count = 0

        def _factory_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return outer_mock_factory()
            return inner_mock_factory()

        combined_factory = MagicMock(side_effect=_factory_side_effect)
        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        inner_ctx = MagicMock()
        inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        inner_ctx.__aexit__ = AsyncMock(return_value=False)
        combined_factory.side_effect = [outer_ctx, inner_ctx]

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["decisions_settled"] == 1
        assert result["decisions_skipped"] == 0
        assert len(settled_pnl) == 1
        assert settled_pnl[0] == Decimal("150.75")

    async def test_pending_order_is_skipped(self) -> None:
        """Decisions linked to still-pending orders are skipped (not settled)."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_decision(agent_id=agent_id, order_id=order_id)
        order = _make_order(order_id=order_id, status="pending")

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[decision])
        mock_decision_repo.update_outcome = AsyncMock()

        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        outer_ctx = MagicMock()
        inner_ctx = MagicMock()
        outer_session = AsyncMock()
        inner_session = AsyncMock()
        outer_session.execute.return_value = agent_result
        inner_session.execute.return_value = order_result
        inner_session.commit = AsyncMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        inner_ctx.__aexit__ = AsyncMock(return_value=False)

        combined_factory = MagicMock(side_effect=[outer_ctx, inner_ctx])

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["decisions_skipped"] == 1
        assert result["decisions_settled"] == 0
        mock_decision_repo.update_outcome.assert_not_awaited()

    async def test_no_realized_pnl_records_zero_outcome(self) -> None:
        """Opening buy trades (realized_pnl=None) produce outcome_pnl=Decimal('0')."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_decision(agent_id=agent_id, order_id=order_id)
        order = _make_order(order_id=order_id, status="filled")
        # Buy that opens position — no realized PnL yet.
        trade = _make_trade(order_id=order_id, realized_pnl=None)

        settled_pnl: list[Decimal] = []

        async def mock_update_outcome(decision_id, *, outcome_pnl, outcome_recorded_at):
            settled_pnl.append(outcome_pnl)

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[decision])
        mock_decision_repo.update_outcome = mock_update_outcome

        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        trades_result = MagicMock()
        trades_result.scalars.return_value.all.return_value = [trade]

        outer_session = AsyncMock()
        inner_session = AsyncMock()
        outer_session.execute.return_value = agent_result
        inner_session.execute.side_effect = [order_result, trades_result]
        inner_session.commit = AsyncMock()

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        inner_ctx = MagicMock()
        inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        inner_ctx.__aexit__ = AsyncMock(return_value=False)

        combined_factory = MagicMock(side_effect=[outer_ctx, inner_ctx])

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["decisions_settled"] == 1
        assert len(settled_pnl) == 1
        assert settled_pnl[0] == Decimal("0")

    async def test_missing_order_records_zero_outcome(self) -> None:
        """If the linked order row was deleted, outcome_pnl=0 is recorded to unblock."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_decision(agent_id=agent_id, order_id=order_id)

        settled_pnl: list[Decimal] = []

        async def mock_update_outcome(decision_id, *, outcome_pnl, outcome_recorded_at):
            settled_pnl.append(outcome_pnl)

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[decision])
        mock_decision_repo.update_outcome = mock_update_outcome

        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        # Order query returns None (order was deleted).
        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = None

        outer_session = AsyncMock()
        inner_session = AsyncMock()
        outer_session.execute.return_value = agent_result
        inner_session.execute.return_value = order_result
        inner_session.commit = AsyncMock()

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        inner_ctx = MagicMock()
        inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        inner_ctx.__aexit__ = AsyncMock(return_value=False)

        combined_factory = MagicMock(side_effect=[outer_ctx, inner_ctx])

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["decisions_settled"] == 1
        assert settled_pnl[0] == Decimal("0")

    async def test_negative_pnl_recorded_for_losing_trade(self) -> None:
        """Negative realized PnL (losing sell) is passed through correctly."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_decision(agent_id=agent_id, order_id=order_id)
        order = _make_order(order_id=order_id, status="filled")
        trade = _make_trade(order_id=order_id, realized_pnl=Decimal("-200.00"))

        settled_pnl: list[Decimal] = []

        async def mock_update_outcome(decision_id, *, outcome_pnl, outcome_recorded_at):
            settled_pnl.append(outcome_pnl)

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[decision])
        mock_decision_repo.update_outcome = mock_update_outcome

        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        trades_result = MagicMock()
        trades_result.scalars.return_value.all.return_value = [trade]

        outer_session = AsyncMock()
        inner_session = AsyncMock()
        outer_session.execute.return_value = agent_result
        inner_session.execute.side_effect = [order_result, trades_result]
        inner_session.commit = AsyncMock()

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        inner_ctx = MagicMock()
        inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        inner_ctx.__aexit__ = AsyncMock(return_value=False)

        combined_factory = MagicMock(side_effect=[outer_ctx, inner_ctx])

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["decisions_settled"] == 1
        assert settled_pnl[0] == Decimal("-200.00")

    async def test_cancelled_order_recorded_with_zero_pnl(self) -> None:
        """Cancelled orders (no trades) produce outcome_pnl=0."""
        agent_id = uuid4()
        order_id = uuid4()
        decision = _make_decision(agent_id=agent_id, order_id=order_id)
        order = _make_order(order_id=order_id, status="cancelled")

        settled_pnl: list[Decimal] = []

        async def mock_update_outcome(decision_id, *, outcome_pnl, outcome_recorded_at):
            settled_pnl.append(outcome_pnl)

        mock_decision_repo = AsyncMock()
        mock_decision_repo.find_unresolved = AsyncMock(return_value=[decision])
        mock_decision_repo.update_outcome = mock_update_outcome

        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id]

        order_result = MagicMock()
        order_result.scalars.return_value.first.return_value = order

        trades_result = MagicMock()
        trades_result.scalars.return_value.all.return_value = []  # no fills for cancelled order

        outer_session = AsyncMock()
        inner_session = AsyncMock()
        outer_session.execute.return_value = agent_result
        inner_session.execute.side_effect = [order_result, trades_result]
        inner_session.commit = AsyncMock()

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        inner_ctx = MagicMock()
        inner_ctx.__aenter__ = AsyncMock(return_value=inner_session)
        inner_ctx.__aexit__ = AsyncMock(return_value=False)

        combined_factory = MagicMock(side_effect=[outer_ctx, inner_ctx])

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_decision_repo,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["decisions_settled"] == 1
        assert settled_pnl[0] == Decimal("0")


# ---------------------------------------------------------------------------
# Tests: settle_agent_decisions — error paths
# ---------------------------------------------------------------------------


class TestSettleAgentDecisionsErrorPaths:
    """Covers failure modes: DB errors, per-agent isolation, load-agents failure."""

    async def test_load_agents_failure_returns_zeros(self) -> None:
        """If the initial agent query fails, returns all-zero counts without raising."""
        outer_session = AsyncMock()
        outer_session.execute.side_effect = Exception("DB unreachable")

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)

        combined_factory = MagicMock(return_value=outer_ctx)

        with patch("src.database.session.get_session_factory", return_value=combined_factory):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["agents_processed"] == 0
        assert result["agents_failed"] == 0
        assert result["decisions_settled"] == 0

    async def test_per_agent_error_isolated_does_not_abort_other_agents(self) -> None:
        """An error on one agent is counted as failed; other agents are processed."""
        agent_id_good = uuid4()
        agent_id_bad = uuid4()

        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = [agent_id_bad, agent_id_good]

        outer_session = AsyncMock()
        outer_session.execute.return_value = agent_result

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)

        # First inner session (bad agent): raises on find_unresolved.
        bad_inner_session = AsyncMock()
        bad_inner_session.commit = AsyncMock()
        bad_inner_ctx = MagicMock()
        bad_inner_ctx.__aenter__ = AsyncMock(return_value=bad_inner_session)
        bad_inner_ctx.__aexit__ = AsyncMock(return_value=False)

        bad_decision_repo = AsyncMock()
        bad_decision_repo.find_unresolved = AsyncMock(side_effect=RuntimeError("oops"))

        # Second inner session (good agent): find_unresolved returns empty.
        good_inner_session = AsyncMock()
        good_inner_session.commit = AsyncMock()
        good_inner_ctx = MagicMock()
        good_inner_ctx.__aenter__ = AsyncMock(return_value=good_inner_session)
        good_inner_ctx.__aexit__ = AsyncMock(return_value=False)

        good_decision_repo = AsyncMock()
        good_decision_repo.find_unresolved = AsyncMock(return_value=[])

        call_count = 0

        def _repo_factory(session):
            nonlocal call_count
            call_count += 1
            return bad_decision_repo if call_count == 1 else good_decision_repo

        combined_factory = MagicMock(side_effect=[outer_ctx, bad_inner_ctx, good_inner_ctx])

        with (
            patch("src.database.session.get_session_factory", return_value=combined_factory),
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                side_effect=_repo_factory,
            ),
        ):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert result["agents_failed"] == 1
        assert result["agents_processed"] == 1  # the good agent

    async def test_return_dict_has_all_required_keys(self) -> None:
        """Return dict always contains all documented keys regardless of outcome."""
        outer_session = AsyncMock()
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = []
        outer_session.execute.return_value = agent_result

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=outer_ctx)

        with patch("src.database.session.get_session_factory", return_value=factory):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        required_keys = {
            "agents_processed",
            "agents_failed",
            "decisions_settled",
            "decisions_skipped",
            "duration_ms",
        }
        assert required_keys.issubset(result.keys())

    async def test_duration_ms_is_non_negative_number(self) -> None:
        """duration_ms is always a non-negative float."""
        outer_session = AsyncMock()
        agent_result = MagicMock()
        agent_result.scalars.return_value.all.return_value = []
        outer_session.execute.return_value = agent_result

        outer_ctx = MagicMock()
        outer_ctx.__aenter__ = AsyncMock(return_value=outer_session)
        outer_ctx.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=outer_ctx)

        with patch("src.database.session.get_session_factory", return_value=factory):
            import src.tasks.agent_analytics as mod  # noqa: PLC0415

            result = await mod._run_settle_agent_decisions()

        assert isinstance(result["duration_ms"], int | float)
        assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Tests: beat schedule registration
# ---------------------------------------------------------------------------


class TestBeatScheduleRegistration:
    """Verifies the task is registered in the beat schedule."""

    def test_settle_agent_decisions_in_beat_schedule(self) -> None:
        """settle_agent_decisions is present in the Celery beat schedule."""
        from src.tasks.celery_app import app  # noqa: PLC0415

        assert "settle-agent-decisions" in app.conf.beat_schedule

    def test_settle_agent_decisions_schedule_is_300_seconds(self) -> None:
        """settle_agent_decisions fires every 300 seconds (5 minutes)."""
        from src.tasks.celery_app import app  # noqa: PLC0415

        entry = app.conf.beat_schedule["settle-agent-decisions"]
        assert entry["schedule"] == 300.0

    def test_settle_agent_decisions_task_name_matches(self) -> None:
        """The beat schedule entry points to the correct fully-qualified task name."""
        from src.tasks.celery_app import app  # noqa: PLC0415

        entry = app.conf.beat_schedule["settle-agent-decisions"]
        assert entry["task"] == "src.tasks.agent_analytics.settle_agent_decisions"

    def test_settle_agent_decisions_task_is_registered(self) -> None:
        """The task is discoverable via the Celery app task registry."""
        from src.tasks.celery_app import app  # noqa: PLC0415

        assert "src.tasks.agent_analytics.settle_agent_decisions" in app.tasks
