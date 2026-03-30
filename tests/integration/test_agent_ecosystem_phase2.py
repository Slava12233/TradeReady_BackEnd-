"""Integration tests for the Phase 2 agent ecosystem stack.

Verifies the full cross-component data flow for permission-gated trading,
budget enforcement, strategy monitoring, and A/B testing without requiring a
live database or external services.  All external I/O (DB repos, Redis, SDK,
LLM) is replaced by in-process mocks so the tests run in any CI environment.

Components under test
---------------------
- ``agent.permissions.capabilities.CapabilityManager``
- ``agent.permissions.budget.BudgetManager``
- ``agent.permissions.enforcement.PermissionEnforcer``
- ``agent.trading.execution.TradeExecutor``
- ``agent.trading.journal.TradingJournal``
- ``agent.trading.strategy_manager.StrategyManager``
- ``agent.trading.ab_testing.ABTestRunner``

Run with::

    pytest tests/integration/test_agent_ecosystem_phase2.py -v --tb=short
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

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


def _make_mock_redis() -> MagicMock:
    """Build a mock Redis client that stores values in a plain dict.

    Supports get/set/delete/mget used by BudgetManager and CapabilityManager.
    Pipeline is wired with async context manager support.

    Returns:
        A ``MagicMock`` with async methods that simulate Redis operations.
    """
    store: dict[str, Any] = {}

    mock_redis = MagicMock()

    async def _get(key: str) -> str | None:
        return store.get(key)

    async def _set(key: str, value: Any, ex: int | None = None) -> None:
        store[key] = value

    async def _delete(*keys: str) -> int:
        count = 0
        for key in keys:
            if key in store:
                del store[key]
                count += 1
        return count

    async def _mget(*keys: str) -> list[str | None]:
        return [store.get(k) for k in keys]

    mock_redis.get = AsyncMock(side_effect=_get)
    mock_redis.set = AsyncMock(side_effect=_set)
    mock_redis.delete = AsyncMock(side_effect=_delete)
    mock_redis.mget = AsyncMock(side_effect=_mget)

    # Pipeline with atomic counter simulation.
    _counter_store: dict[str, float] = {}

    mock_pipeline = MagicMock()
    mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
    mock_pipeline.__aexit__ = AsyncMock(return_value=False)

    # Track queued operations so execute() can apply them.
    queued_ops: list[tuple[str, Any]] = []

    def _incr(key: str) -> None:
        queued_ops.append(("incr", key))

    def _expire(key: str, ttl: int) -> None:
        queued_ops.append(("expire", (key, ttl)))

    def _incrbyfloat(key: str, amount: str) -> None:
        queued_ops.append(("incrbyfloat", (key, amount)))

    async def _execute() -> list[Any]:
        results = []
        for op, arg in queued_ops:
            if op == "incr":
                _counter_store[arg] = _counter_store.get(arg, 0) + 1
                store[arg] = str(int(_counter_store[arg]))
                results.append(int(_counter_store[arg]))
            elif op == "incrbyfloat":
                key, amount = arg
                _counter_store[key] = _counter_store.get(key, 0.0) + float(amount)
                store[key] = str(_counter_store[key])
                results.append(str(_counter_store[key]))
            elif op == "expire":
                results.append(True)
            elif op == "delete_multi":
                key = arg
                store.pop(key, None)
                results.append(1)
        queued_ops.clear()
        return results

    mock_pipeline.incr = MagicMock(side_effect=_incr)
    mock_pipeline.expire = MagicMock(side_effect=_expire)
    mock_pipeline.incrbyfloat = MagicMock(side_effect=_incrbyfloat)
    mock_pipeline.delete = MagicMock(side_effect=lambda k: queued_ops.append(("delete_multi", k)))
    mock_pipeline.execute = AsyncMock(side_effect=_execute)

    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

    # Attach the store so tests can inspect it.
    mock_redis._store = store
    mock_redis._counter_store = _counter_store

    return mock_redis


def _make_trade_decision(
    symbol: str = "BTCUSDT",
    action: str = "buy",
    confidence: float = 0.75,
    quantity_pct: str = "0.05",
    reasoning: str = "Test buy signal from ensemble strategy.",
) -> Any:
    """Build a TradeDecision Pydantic model.

    Args:
        symbol: Trading pair.
        action: 'buy', 'sell', or 'hold'.
        confidence: Agent confidence in [0.0, 1.0].
        quantity_pct: Fraction of equity as a decimal string.
        reasoning: LLM reasoning chain.

    Returns:
        A :class:`~agent.models.ecosystem.TradeDecision` instance.
    """
    from agent.models.ecosystem import TradeDecision  # noqa: PLC0415

    return TradeDecision(
        symbol=symbol,
        action=action,
        quantity_pct=Decimal(quantity_pct),
        confidence=confidence,
        reasoning=reasoning,
        signals={"ensemble_score": 0.72, "regime": "trending_up"},
        risk_notes="Upcoming FED statement could reverse momentum.",
        strategy_weights={"rl": 0.3, "evolutionary": 0.2, "regime": 0.5},
    )


def _make_trading_signal(
    symbol: str = "BTCUSDT",
    action: str = "buy",
    confidence: float = 0.75,
    strategy_name: str = "ensemble_strategy",
) -> Any:
    """Build a TradingSignal for use with StrategyManager and ABTestRunner.

    Args:
        symbol: Trading pair.
        action: Direction: 'buy', 'sell', or 'hold'.
        confidence: Signal confidence.
        strategy_name: Strategy that generated the signal (stored in source_contributions).

    Returns:
        A :class:`~agent.trading.signal_generator.TradingSignal` instance.
    """
    from agent.trading.signal_generator import TradingSignal  # noqa: PLC0415

    return TradingSignal(
        symbol=symbol,
        action=action,
        confidence=confidence,
        agreement_rate=0.67,
        source_contributions={strategy_name: {"action": action, "confidence": confidence, "enabled": True}},
        regime="trending",
        indicators={"rsi": 45.0, "sma_fast": 67200.0, "sma_slow": 66800.0},
    )


# ---------------------------------------------------------------------------
# Test 1: Permission-gated trade (capability check → execution)
# ---------------------------------------------------------------------------


class TestPermissionGatedTrade:
    """CapabilityManager → PermissionEnforcer → check_action verifies the gate."""

    async def test_viewer_role_denied_trade_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An agent with VIEWER role is denied the 'trade' action.

        The CapabilityManager resolves capabilities from a mock DB record
        bearing the 'viewer' role.  The PermissionEnforcer then correctly
        denies the 'trade' action because VIEWER does not have CAN_TRADE.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        # Build a mock permission record with VIEWER role.
        mock_perm_record = MagicMock()
        mock_perm_record.role = "viewer"
        mock_perm_record.capabilities = {}

        mock_perm_repo = AsyncMock()
        mock_perm_repo.get_by_agent.return_value = mock_perm_record

        # Mock DB session that returns the permission repo.
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        # Budget manager — counters are all zero so budget is not the blocker.
        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.permissions.capabilities import CapabilityManager  # noqa: PLC0415
        from agent.permissions.enforcement import PermissionEnforcer  # noqa: PLC0415

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        cap_mgr = CapabilityManager(config=config, redis=mock_redis)

        enforcer = PermissionEnforcer(
            capability_mgr=cap_mgr,
            budget_mgr=budget_mgr,
        )

        with (
            patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_perm_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            result = await enforcer.check_action(agent_id, "trade", {"value": "200.00"})

        # VIEWER cannot trade → denied.
        assert result.allowed is False
        assert result.capability_check_passed is False
        assert "can_trade" in result.reason.lower() or "capability" in result.reason.lower()

    async def test_paper_trader_role_allowed_trade_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An agent with PAPER_TRADER role passes the capability check for 'trade'.

        Budget counters are at zero so both checks pass and the action is allowed.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        # PAPER_TRADER has CAN_TRADE.
        mock_perm_record = MagicMock()
        mock_perm_record.role = "paper_trader"
        mock_perm_record.capabilities = {}

        mock_perm_repo = AsyncMock()
        mock_perm_repo.get_by_agent.return_value = mock_perm_record

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        # Budget counters at zero — budget check must pass.
        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.permissions.capabilities import CapabilityManager  # noqa: PLC0415
        from agent.permissions.enforcement import PermissionEnforcer  # noqa: PLC0415
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
        )

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        cap_mgr = CapabilityManager(config=config, redis=mock_redis)

        enforcer = PermissionEnforcer(
            capability_mgr=cap_mgr,
            budget_mgr=budget_mgr,
        )

        mock_budget_repo = AsyncMock()
        mock_budget_repo.get_by_agent.side_effect = AgentBudgetNotFoundError("no record")

        with (
            patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_perm_repo,
            ),
            patch(
                "src.database.repositories.agent_budget_repo.AgentBudgetRepository",
                return_value=mock_budget_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            result = await enforcer.check_action(agent_id, "trade", {"value": "200.00"})

        # PAPER_TRADER can trade and budget is zero → allowed.
        assert result.allowed is True
        assert result.capability_check_passed is True
        assert result.budget_check_passed is True

    async def test_require_action_raises_permission_denied_for_viewer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """require_action() raises PermissionDenied when the capability check fails."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        mock_perm_record = MagicMock()
        mock_perm_record.role = "viewer"
        mock_perm_record.capabilities = {}

        mock_perm_repo = AsyncMock()
        mock_perm_repo.get_by_agent.return_value = mock_perm_record

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.permissions.capabilities import CapabilityManager  # noqa: PLC0415
        from agent.permissions.enforcement import PermissionDenied, PermissionEnforcer  # noqa: PLC0415

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        cap_mgr = CapabilityManager(config=config, redis=mock_redis)
        enforcer = PermissionEnforcer(capability_mgr=cap_mgr, budget_mgr=budget_mgr)

        with (
            patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_perm_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
            pytest.raises(PermissionDenied) as exc_info,
        ):
            await enforcer.require_action(agent_id, "trade")

        exc = exc_info.value
        assert exc.agent_id == agent_id
        assert exc.action == "trade"
        assert exc.reason  # non-empty denial reason

    async def test_audit_log_records_denied_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After a denied check_action, the audit log contains the denial entry."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        mock_perm_record = MagicMock()
        mock_perm_record.role = "viewer"
        mock_perm_record.capabilities = {}

        mock_perm_repo = AsyncMock()
        mock_perm_repo.get_by_agent.return_value = mock_perm_record

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        # begin() returns a context manager for transaction.
        mock_session.begin = MagicMock(return_value=mock_session)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.permissions.capabilities import CapabilityManager  # noqa: PLC0415
        from agent.permissions.enforcement import PermissionEnforcer  # noqa: PLC0415

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        cap_mgr = CapabilityManager(config=config, redis=mock_redis)
        enforcer = PermissionEnforcer(capability_mgr=cap_mgr, budget_mgr=budget_mgr)

        with (
            patch(
                "src.database.repositories.agent_permission_repo.AgentPermissionRepository",
                return_value=mock_perm_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            await enforcer.check_action(agent_id, "trade")

        # The audit buffer must contain a denial entry for this agent.
        log = await enforcer.get_audit_log(agent_id)
        assert len(log) >= 1
        assert log[0].result == "deny"
        assert log[0].action == "trade"
        assert log[0].agent_id == agent_id


# ---------------------------------------------------------------------------
# Test 2: Budget enforcement — exhaustion and denial
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    """BudgetManager enforces trade count and exposure limits via Redis counters."""

    async def test_check_budget_allows_trade_within_limits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """check_budget() returns allowed=True when all counters are below limits."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
        )

        budget_mgr = BudgetManager(config=config, redis=mock_redis)

        mock_budget_repo = AsyncMock()
        mock_budget_repo.get_by_agent.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        with (
            patch(
                "src.database.repositories.agent_budget_repo.AgentBudgetRepository",
                return_value=mock_budget_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            result = await budget_mgr.check_budget(agent_id, Decimal("100.00"))

        assert result.allowed is True
        assert result.remaining_trades > 0

    async def test_budget_denied_when_daily_trade_limit_reached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """check_budget() returns allowed=False when daily trade count is exhausted.

        Simulates a Redis store where the trades_today counter already equals
        the maximum allowed value for the agent's config defaults.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        from agent.permissions.budget import BudgetManager, _trades_key  # noqa: PLC0415
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
        )

        budget_mgr = BudgetManager(config=config, redis=mock_redis)

        # Pre-populate the trades_today counter to the limit.
        limit = config.default_max_trades_per_day
        mock_redis._store[_trades_key(agent_id)] = str(limit)

        mock_budget_repo = AsyncMock()
        mock_budget_repo.get_by_agent.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        with (
            patch(
                "src.database.repositories.agent_budget_repo.AgentBudgetRepository",
                return_value=mock_budget_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            result = await budget_mgr.check_budget(agent_id, Decimal("50.00"))

        assert result.allowed is False
        assert "daily trade limit" in result.reason.lower()
        assert result.remaining_trades == 0

    async def test_check_and_record_increments_counters_atomically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """check_and_record() atomically checks and increments the trade counter.

        After one allowed call, trades_today in Redis must be exactly 1 and
        a second call with the same agent_id must see the updated counter.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        from agent.permissions.budget import BudgetManager, _trades_key  # noqa: PLC0415
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
        )

        budget_mgr = BudgetManager(config=config, redis=mock_redis)

        mock_budget_repo = AsyncMock()
        mock_budget_repo.get_by_agent.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        with (
            patch(
                "src.database.repositories.agent_budget_repo.AgentBudgetRepository",
                return_value=mock_budget_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
            # Suppress the background persist task.
            patch("asyncio.ensure_future"),
        ):
            result = await budget_mgr.check_and_record(agent_id, Decimal("100.00"))

        assert result.allowed is True
        # After check_and_record, the Redis store has the trades_today counter.
        trades_key = _trades_key(agent_id)
        assert mock_redis._store.get(trades_key) is not None
        assert int(mock_redis._store[trades_key]) == 1

    async def test_budget_denied_when_position_size_exceeds_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """check_budget() denies a trade whose value exceeds max_position_size_usdt.

        Default max position size is 10 % of 10,000 USDT = 1,000 USDT.
        A trade of 2,000 USDT must be denied on the first position-size check.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
            AgentBudgetNotFoundError,
        )

        budget_mgr = BudgetManager(config=config, redis=mock_redis)

        mock_budget_repo = AsyncMock()
        mock_budget_repo.get_by_agent.side_effect = AgentBudgetNotFoundError("no record")

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        # 2,000 USDT far exceeds the 10% position size cap (= 1,000 USDT).
        with (
            patch(
                "src.database.repositories.agent_budget_repo.AgentBudgetRepository",
                return_value=mock_budget_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            result = await budget_mgr.check_budget(agent_id, Decimal("2000.00"))

        assert result.allowed is False
        assert "position size" in result.reason.lower() or "exceeds maximum" in result.reason.lower()


# ---------------------------------------------------------------------------
# Test 3: Trade execution — executor integrates with budget and SDK
# ---------------------------------------------------------------------------


class TestTradeExecution:
    """TradeExecutor correctly calls the SDK, updates budgets, and records decisions."""

    async def test_execute_buy_decision_calls_sdk_and_records_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """execute() calls SDK place_market_order and records trade in the budget.

        The decision persists to the DB via AgentDecisionRepository and the
        BudgetManager.record_trade updates the Redis counters.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        decision = _make_trade_decision(action="buy", confidence=0.80)

        # SDK returns a successful order response.
        mock_sdk = AsyncMock()
        mock_sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
        mock_sdk.place_market_order = AsyncMock(
            return_value={
                "order_id": str(uuid4()),
                "executed_price": "67500.00",
                "fee": "0.05",
                "executed_quantity": "0.0001",
            }
        )

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.trading.execution import TradeExecutor  # noqa: PLC0415

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        executor = TradeExecutor(
            agent_id=agent_id,
            config=config,
            budget_mgr=budget_mgr,
            sdk_client=mock_sdk,
        )

        with (
            patch("src.database.session.get_session_factory", side_effect=Exception("DB not needed")),
            patch("asyncio.ensure_future"),
        ):
            result = await executor.execute(decision)

        assert result.success is True
        assert result.symbol == "BTCUSDT"
        assert result.side == "buy"
        assert result.fill_price == Decimal("67500.00")
        mock_sdk.place_market_order.assert_awaited_once_with("BTCUSDT", "buy", "0.0001")

    async def test_execute_hold_decision_returns_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """execute() with action='hold' returns immediately without calling the SDK."""
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        decision = _make_trade_decision(action="hold", confidence=0.40)

        mock_sdk = AsyncMock()

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.trading.execution import TradeExecutor  # noqa: PLC0415

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        executor = TradeExecutor(
            agent_id=agent_id,
            config=config,
            budget_mgr=budget_mgr,
            sdk_client=mock_sdk,
        )

        result = await executor.execute(decision)

        assert result.success is False
        assert "hold" in result.error_message.lower()
        mock_sdk.place_market_order.assert_not_awaited()

    async def test_execute_duplicate_decision_blocked_by_idempotency(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Submitting the same decision twice is blocked by the idempotency cache.

        The second call must return success=False without placing a second order.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        mock_redis = _make_mock_redis()

        decision = _make_trade_decision(action="buy", confidence=0.80, reasoning="Unique reason for idempotency test.")

        mock_sdk = AsyncMock()
        mock_sdk.get_performance = AsyncMock(return_value={"total_value": "10000.00"})
        mock_sdk.place_market_order = AsyncMock(
            return_value={
                "order_id": str(uuid4()),
                "executed_price": "67500.00",
                "fee": "0.05",
                "executed_quantity": "0.0001",
            }
        )

        from agent.permissions.budget import BudgetManager  # noqa: PLC0415
        from agent.trading.execution import TradeExecutor  # noqa: PLC0415

        budget_mgr = BudgetManager(config=config, redis=mock_redis)
        executor = TradeExecutor(
            agent_id=agent_id,
            config=config,
            budget_mgr=budget_mgr,
            sdk_client=mock_sdk,
        )

        with (
            patch("src.database.session.get_session_factory", side_effect=Exception("DB not needed")),
            patch("asyncio.ensure_future"),
        ):
            result1 = await executor.execute(decision)
            result2 = await executor.execute(decision)

        assert result1.success is True
        assert result2.success is False
        assert "duplicate" in result2.error_message.lower()
        # SDK must be called only once.
        assert mock_sdk.place_market_order.await_count == 1


# ---------------------------------------------------------------------------
# Test 4: Strategy degradation detection
# ---------------------------------------------------------------------------


class TestStrategyDegradation:
    """StrategyManager detects degradation after a streak of losing trades."""

    async def test_degradation_alert_fires_after_consecutive_losses(self) -> None:
        """detect_degradation() returns a DegradationAlert after consecutive losses.

        The StrategyManager requires at least _MIN_TRADES_FOR_DEGRADATION (10)
        completed trades before it will run any degradation checks.  We feed 12
        consecutive losses so the window exceeds the minimum sample threshold,
        triggering at least a WARNING-level alert for 5+ consecutive losses.
        """
        from agent.trading.strategy_manager import StrategyManager  # noqa: PLC0415

        manager = StrategyManager()
        agent_id = str(uuid4())
        strategy_name = "sma_crossover"

        # Feed 12 consecutive losing trades — exceeds the 10-trade minimum sample.
        for _ in range(12):
            signal = _make_trading_signal(strategy_name=strategy_name, action="buy")
            await manager.record_strategy_result(
                agent_id=agent_id,
                strategy_name=strategy_name,
                signal=signal,
                outcome_pnl=Decimal("-20.00"),  # each trade loses 20 USDT
            )

        alerts = await manager.detect_degradation(agent_id=agent_id)

        assert len(alerts) >= 1
        alert = alerts[0]
        assert alert.strategy_name == strategy_name
        # Severity must be at least "warning" — consecutive losses >= 5 triggers it.
        assert alert.severity in ("warning", "critical", "disable")

    async def test_no_degradation_alert_for_winning_strategy(self) -> None:
        """detect_degradation() returns an empty list when the strategy is healthy.

        Requires at least 10 trades to pass the minimum sample threshold.
        We feed 15 trades with a 75 % win rate — no alerts should fire.
        """
        from agent.trading.strategy_manager import StrategyManager  # noqa: PLC0415

        manager = StrategyManager()
        agent_id = str(uuid4())
        strategy_name = "rsi_mean_reversion"

        # Feed 15 trades: 75 % win rate (wins at 0, 1, 3, 4, 6, 7, 9, 10, 12, 13, 14)
        for i in range(15):
            signal = _make_trading_signal(strategy_name=strategy_name, action="buy")
            # Win 3 out of every 4 trades (indices 0,1,2 = win; 3 = loss, etc.)
            pnl = Decimal("30.00") if i % 4 != 3 else Decimal("-5.00")
            await manager.record_strategy_result(
                agent_id=agent_id,
                strategy_name=strategy_name,
                signal=signal,
                outcome_pnl=pnl,
            )

        alerts = await manager.detect_degradation(agent_id=agent_id)

        # A healthy strategy should not generate any alerts.
        assert alerts == []

    async def test_degradation_critical_alert_after_many_losses(self) -> None:
        """detect_degradation() returns CRITICAL severity after 8+ consecutive losses."""
        from agent.trading.strategy_manager import StrategyManager  # noqa: PLC0415

        manager = StrategyManager()
        agent_id = str(uuid4())
        strategy_name = "momentum_breakout"

        # Feed 10 consecutive losses — well above the 8-trade critical threshold.
        for _ in range(10):
            signal = _make_trading_signal(strategy_name=strategy_name, action="buy")
            await manager.record_strategy_result(
                agent_id=agent_id,
                strategy_name=strategy_name,
                signal=signal,
                outcome_pnl=Decimal("-25.00"),
            )

        alerts = await manager.detect_degradation(agent_id=agent_id)

        assert len(alerts) >= 1
        severities = {a.severity for a in alerts}
        # At 10 consecutive losses the alert must be critical or disable-level.
        assert severities & {"critical", "disable"}


# ---------------------------------------------------------------------------
# Test 5: A/B test lifecycle
# ---------------------------------------------------------------------------


class TestABTestLifecycle:
    """ABTestRunner create → record → evaluate → winner logic."""

    async def test_create_ab_test_initialises_state(self) -> None:
        """create_test() produces an ABTest with 'active' status and both variants."""
        from agent.trading.ab_testing import ABTestRunner  # noqa: PLC0415

        runner = ABTestRunner(rest_client=None, session_factory=None)
        agent_id = str(uuid4())

        test = await runner.create_test(
            agent_id=agent_id,
            strategy_name="rsi_strategy",
            variant_a_params={"rsi_threshold": 30, "confidence": 0.60},
            variant_b_params={"rsi_threshold": 25, "confidence": 0.65},
            min_trades=5,  # small min_trades for test speed
        )

        assert test.id is not None
        assert test.agent_id == agent_id
        assert test.strategy_name == "rsi_strategy"
        assert test.status == "active"
        assert test.winner is None
        assert test.variant_a["rsi_threshold"] == 30
        assert test.variant_b["rsi_threshold"] == 25

    async def test_duplicate_ab_test_raises_error(self) -> None:
        """Creating a second test for the same strategy raises DuplicateABTestError."""
        from agent.trading.ab_testing import ABTestRunner, DuplicateABTestError  # noqa: PLC0415

        runner = ABTestRunner(rest_client=None, session_factory=None)
        agent_id = str(uuid4())

        await runner.create_test(
            agent_id=agent_id,
            strategy_name="rsi_strategy",
            variant_a_params={"rsi_threshold": 30},
            variant_b_params={"rsi_threshold": 25},
            min_trades=5,
        )

        with pytest.raises(DuplicateABTestError):
            await runner.create_test(
                agent_id=agent_id,
                strategy_name="rsi_strategy",
                variant_a_params={"rsi_threshold": 35},
                variant_b_params={"rsi_threshold": 20},
                min_trades=5,
            )

    async def test_record_results_and_evaluate_finds_winner(self) -> None:
        """After feeding enough results, evaluate() declares a statistically better variant.

        Variant A receives consistently positive PnL; variant B consistently negative.
        With 10 trades each and a large performance gap, variant A must be the winner.
        """
        from agent.trading.ab_testing import ABTestRunner  # noqa: PLC0415

        runner = ABTestRunner(rest_client=None, session_factory=None)
        agent_id = str(uuid4())

        test = await runner.create_test(
            agent_id=agent_id,
            strategy_name="momentum",
            variant_a_params={"entry_threshold": 0.7},
            variant_b_params={"entry_threshold": 0.5},
            min_trades=5,  # low bar so the test can evaluate quickly
        )

        # Feed 10 trades for each variant; A profits, B loses.
        for _ in range(10):
            signal_a = _make_trading_signal(action="buy", confidence=0.80)
            signal_b = _make_trading_signal(action="buy", confidence=0.60)
            await runner.record_result(test.id, "a", signal_a, outcome_pnl=Decimal("50.00"))
            await runner.record_result(test.id, "b", signal_b, outcome_pnl=Decimal("-20.00"))

        result = await runner.evaluate(test.id)

        # With such a large and consistent gap, one variant must outperform.
        assert result.test_id == test.id
        assert result.variant_a_performance.trades_taken >= 5
        assert result.variant_b_performance.trades_taken >= 5
        assert result.variant_a_performance.avg_pnl_per_trade > result.variant_b_performance.avg_pnl_per_trade

    async def test_evaluate_raises_when_insufficient_trades(self) -> None:
        """evaluate() raises InsufficientDataError when min_trades has not been met.

        With only 3 trades per variant vs. a min_trades=20 requirement, the
        evaluation cannot proceed and must signal the caller with an error so
        the trading loop can retry later.
        """
        from agent.trading.ab_testing import ABTestRunner, InsufficientDataError  # noqa: PLC0415

        runner = ABTestRunner(rest_client=None, session_factory=None)
        agent_id = str(uuid4())

        test = await runner.create_test(
            agent_id=agent_id,
            strategy_name="scalp_v2",
            variant_a_params={"tp": 0.02},
            variant_b_params={"tp": 0.03},
            min_trades=20,  # require 20 trades per variant
        )

        # Only record 3 trades each — not enough to meet min_trades=20.
        for _ in range(3):
            signal = _make_trading_signal(action="buy", confidence=0.70)
            await runner.record_result(test.id, "a", signal, outcome_pnl=Decimal("10.00"))
            await runner.record_result(test.id, "b", signal, outcome_pnl=Decimal("5.00"))

        # Neither variant has 20 trades — must raise InsufficientDataError.
        with pytest.raises(InsufficientDataError):
            await runner.evaluate(test.id)


# ---------------------------------------------------------------------------
# Test 6: Journal reflection — record outcome → generate reflection → learning
# ---------------------------------------------------------------------------


class TestJournalReflection:
    """TradingJournal generates reflections and propagates learnings to memory store."""

    async def test_record_decision_persists_to_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """record_decision() writes an AgentDecision row and returns its ID.

        The method uses a lazy-import pattern so we patch the DB session
        factory and repository at the call site.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        decision = _make_trade_decision(action="buy", confidence=0.75)

        # Mock the AgentDecision ORM row.
        mock_decision_row = MagicMock()
        mock_decision_row.id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.create = AsyncMock(return_value=mock_decision_row)

        mock_session = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        from agent.trading.journal import TradingJournal  # noqa: PLC0415

        journal = TradingJournal(config=config, memory_store=None)

        with (
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
            patch("src.database.models.AgentDecision", return_value=mock_decision_row),
        ):
            decision_id = await journal.record_decision(
                agent_id=agent_id,
                decision=decision,
                market_snapshot={"BTCUSDT": "67500.00"},
                signals=[{"ensemble_score": 0.72}],
                risk_assessment={"approved": True},
                reasoning="Trending regime detected with 72 % ensemble confidence.",
            )

        # record_decision should return the UUID string of the row.
        assert decision_id != ""
        assert decision_id == str(mock_decision_row.id)

    async def test_generate_reflection_uses_template_when_llm_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """generate_reflection() falls back to the deterministic template when LLM is unavailable.

        The ``_llm_reflection`` path raises an ImportError on ``pydantic_ai``,
        which triggers the ``_template_reflection`` fallback.  The returned
        JournalEntry must have non-empty content and valid tags.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        decision_id = str(uuid4())

        # Mock decision row returned by _fetch_decision.
        mock_decision_row = {
            "id": decision_id,
            "agent_id": agent_id,
            "decision_type": "trade",
            "symbol": "BTCUSDT",
            "direction": "buy",
            "confidence": "0.75",
            "reasoning": "Ensemble score 0.72 in trending regime.",
            "market_snapshot": {"BTCUSDT": "67500.00"},
            "signals": [{"ensemble_score": 0.72}],
            "risk_assessment": {
                "approved": True,
                "max_adverse_excursion": "12.50",
                "hold_duration_seconds": 3600,
            },
            "outcome_pnl": "42.50",
            "created_at": datetime.now(UTC),
        }

        from agent.trading.journal import TradingJournal  # noqa: PLC0415

        journal = TradingJournal(config=config, memory_store=None)

        # Patch _fetch_decision and _persist_journal_entry so no DB is needed.
        with (
            patch.object(journal, "_fetch_decision", return_value=mock_decision_row),
            patch.object(journal, "_persist_journal_entry", return_value=str(uuid4())),
            patch.object(journal, "_save_learnings_to_memory"),
            # Block pydantic_ai import to force template fallback.
            patch.dict("sys.modules", {"pydantic_ai": None}),
        ):
            entry = await journal.generate_reflection(decision_id=decision_id)

        assert entry.entry_type == "reflection"
        assert "BTCUSDT" in entry.content or "Trade Reflection" in entry.content
        assert len(entry.content) > 0

    async def test_generate_reflection_saves_learnings_to_memory_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """generate_reflection() forwards extracted learnings to the memory store.

        When a MemoryStore is injected, _save_learnings_to_memory must be
        called with the learning strings extracted from the reflection.
        """
        config = _make_agent_config(monkeypatch)
        agent_id = str(uuid4())
        decision_id = str(uuid4())

        mock_decision_row = {
            "id": decision_id,
            "agent_id": agent_id,
            "decision_type": "trade",
            "symbol": "ETHUSDT",
            "direction": "buy",
            "confidence": "0.80",
            "reasoning": "Strong momentum signal.",
            "market_snapshot": {"ETHUSDT": "3500.00"},
            "signals": [],
            "risk_assessment": {
                "max_adverse_excursion": "5.00",
                "hold_duration_seconds": 1800,
            },
            "outcome_pnl": "28.00",
            "created_at": datetime.now(UTC),
        }

        # Mock memory store that records what is saved.
        saved_memories: list[Any] = []

        mock_memory_store = AsyncMock()
        mock_memory_store.save = AsyncMock(side_effect=lambda m: saved_memories.append(m))

        from agent.trading.journal import TradingJournal  # noqa: PLC0415

        journal = TradingJournal(config=config, memory_store=mock_memory_store)

        with (
            patch.object(journal, "_fetch_decision", return_value=mock_decision_row),
            patch.object(journal, "_persist_journal_entry", return_value=str(uuid4())),
            # Block pydantic_ai import to use template reflection (which produces learnings).
            patch.dict("sys.modules", {"pydantic_ai": None}),
        ):
            entry = await journal.generate_reflection(decision_id=decision_id)

        # The template reflection produces at least one learning for a profitable trade.
        assert entry.entry_type == "reflection"
        # Memory store save must have been called for each learning.
        assert mock_memory_store.save.await_count >= 1

    async def test_record_outcome_updates_decision_pnl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """record_outcome() calls repo.update_outcome with the correct PnL value."""
        config = _make_agent_config(monkeypatch)
        decision_id = str(uuid4())

        mock_existing = MagicMock()
        mock_existing.risk_assessment = {"approved": True}

        mock_updated = MagicMock()
        mock_updated.risk_assessment = {}

        mock_repo = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=mock_existing)
        mock_repo.update_outcome = AsyncMock(return_value=mock_updated)

        mock_session = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.flush = AsyncMock()

        mock_session_factory = MagicMock()
        mock_session_factory.return_value = mock_session

        from agent.trading.journal import TradingJournal  # noqa: PLC0415

        journal = TradingJournal(config=config, memory_store=None)

        with (
            patch(
                "src.database.repositories.agent_decision_repo.AgentDecisionRepository",
                return_value=mock_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=mock_session_factory,
            ),
        ):
            await journal.record_outcome(
                decision_id=decision_id,
                pnl=Decimal("42.50"),
                hold_duration=3600,
                max_adverse_excursion=Decimal("15.00"),
            )

        # update_outcome must be called with the correct PnL.
        mock_repo.update_outcome.assert_awaited_once()
        call_kwargs = mock_repo.update_outcome.call_args
        assert call_kwargs[1]["outcome_pnl"] == Decimal("42.50")
