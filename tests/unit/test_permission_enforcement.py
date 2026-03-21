"""Tests for agent/permissions/enforcement.py.

Covers: PermissionEnforcer.check_action (capability pass/fail, budget pass/fail,
unknown action), require_action raises PermissionDenied on failure, @require
decorator on async functions, audit log buffering, escalation request,
privilege escalation is prevented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.models.ecosystem import BudgetCheckResult, EnforcementResult
from agent.permissions.capabilities import Capability
from agent.permissions.enforcement import (
    ACTION_CAPABILITY_MAP,
    BUDGET_CHECKED_ACTIONS,
    PermissionDenied,
    PermissionEnforcer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cap_mgr(has_capability: bool = True) -> AsyncMock:
    mgr = AsyncMock()
    mgr.has_capability = AsyncMock(return_value=has_capability)
    return mgr


def _make_budget_mgr(allowed: bool = True, reason: str = "") -> AsyncMock:
    mgr = AsyncMock()
    result = BudgetCheckResult(
        allowed=allowed,
        reason=reason or ("" if allowed else "Budget denied"),
        remaining_trades=5 if allowed else 0,
        remaining_exposure=Decimal("1000.00"),
        remaining_loss_budget=Decimal("200.00"),
    )
    # The enforcer calls check_and_record (not check_budget directly)
    mgr.check_and_record = AsyncMock(return_value=result)
    mgr.check_budget = AsyncMock(return_value=result)
    return mgr


def _make_enforcer(
    has_cap: bool = True,
    budget_allowed: bool = True,
    budget_reason: str = "",
) -> PermissionEnforcer:
    cap_mgr = _make_cap_mgr(has_capability=has_cap)
    budget_mgr = _make_budget_mgr(allowed=budget_allowed, reason=budget_reason)
    return PermissionEnforcer(capability_mgr=cap_mgr, budget_mgr=budget_mgr)


# ---------------------------------------------------------------------------
# ACTION_CAPABILITY_MAP and BUDGET_CHECKED_ACTIONS sanity checks
# ---------------------------------------------------------------------------


class TestActionMaps:
    """Tests for the global action-to-capability mapping constants."""

    def test_trade_action_requires_can_trade(self) -> None:
        """'trade' action maps to CAN_TRADE capability."""
        assert ACTION_CAPABILITY_MAP["trade"] == Capability.CAN_TRADE

    def test_read_portfolio_requires_can_read_portfolio(self) -> None:
        """'read_portfolio' maps to CAN_READ_PORTFOLIO."""
        assert ACTION_CAPABILITY_MAP["read_portfolio"] == Capability.CAN_READ_PORTFOLIO

    def test_modify_strategy_requires_can_modify_strategy(self) -> None:
        """'create_strategy' maps to CAN_MODIFY_STRATEGY."""
        assert ACTION_CAPABILITY_MAP["create_strategy"] == Capability.CAN_MODIFY_STRATEGY

    def test_adjust_risk_requires_can_adjust_risk(self) -> None:
        """'set_stop_loss' maps to CAN_ADJUST_RISK."""
        assert ACTION_CAPABILITY_MAP["set_stop_loss"] == Capability.CAN_ADJUST_RISK

    def test_budget_checked_actions_include_trade(self) -> None:
        """'trade' and 'place_order' are in the budget-checked set."""
        assert "trade" in BUDGET_CHECKED_ACTIONS
        assert "place_order" in BUDGET_CHECKED_ACTIONS

    def test_read_market_is_not_budget_checked(self) -> None:
        """'get_price' is NOT in BUDGET_CHECKED_ACTIONS (not a financial action)."""
        assert "get_price" not in BUDGET_CHECKED_ACTIONS


# ---------------------------------------------------------------------------
# PermissionEnforcer.check_action — happy path
# ---------------------------------------------------------------------------


class TestCheckActionAllowed:
    """Tests for check_action when the action is permitted."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_capability_pass_budget_pass_returns_allowed(self) -> None:
        """Both checks passing returns allowed=True in EnforcementResult."""
        enforcer = _make_enforcer(has_cap=True, budget_allowed=True)
        result = await enforcer.check_action(self.agent_id, "trade", {"value": "100.00"})

        assert isinstance(result, EnforcementResult)
        assert result.allowed is True
        assert result.capability_check_passed is True
        assert result.budget_check_passed is True
        assert result.reason == ""

    async def test_unknown_action_skips_capability_check(self) -> None:
        """An action not in ACTION_CAPABILITY_MAP is automatically capability-passed."""
        enforcer = _make_enforcer(has_cap=True, budget_allowed=True)
        result = await enforcer.check_action(self.agent_id, "some_unknown_action")

        assert result.allowed is True
        assert result.capability_check_passed is True
        enforcer._capability_mgr.has_capability.assert_not_called()

    async def test_non_budget_action_skips_budget_check(self) -> None:
        """Non-financial actions skip the budget check entirely."""
        enforcer = _make_enforcer(has_cap=True, budget_allowed=True)
        result = await enforcer.check_action(self.agent_id, "get_price")

        assert result.allowed is True
        assert result.budget_check_passed is True
        enforcer._budget_mgr.check_and_record.assert_not_called()

    async def test_check_action_records_audit_entry(self) -> None:
        """check_action appends exactly one audit entry to the buffer."""
        enforcer = _make_enforcer()
        await enforcer.check_action(self.agent_id, "trade")

        async with enforcer._audit_lock:
            buffer = list(enforcer._audit_buffer)

        assert len(buffer) == 1
        assert buffer[0].agent_id == self.agent_id
        assert buffer[0].action == "trade"
        assert buffer[0].result == "allow"

    async def test_check_action_records_context_in_audit_entry(self) -> None:
        """Context dict is stored verbatim in the audit entry."""
        enforcer = _make_enforcer()
        ctx = {"symbol": "BTCUSDT", "value": "250.00"}
        await enforcer.check_action(self.agent_id, "trade", ctx)

        async with enforcer._audit_lock:
            entry = enforcer._audit_buffer[-1]

        assert entry.context == ctx


# ---------------------------------------------------------------------------
# PermissionEnforcer.check_action — denial paths
# ---------------------------------------------------------------------------


class TestCheckActionDenied:
    """Tests for check_action when the action is denied."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_capability_fail_returns_denied(self) -> None:
        """Missing capability returns allowed=False with a non-empty reason."""
        enforcer = _make_enforcer(has_cap=False)
        result = await enforcer.check_action(self.agent_id, "trade")

        assert result.allowed is False
        assert result.capability_check_passed is False
        assert len(result.reason) > 0

    async def test_budget_fail_returns_denied(self) -> None:
        """Budget denial returns allowed=False with the budget reason."""
        enforcer = _make_enforcer(has_cap=True, budget_allowed=False, budget_reason="Daily limit reached")
        result = await enforcer.check_action(self.agent_id, "trade")

        assert result.allowed is False
        assert result.budget_check_passed is False
        assert "Daily limit reached" in result.reason

    async def test_capability_fail_skips_budget_check(self) -> None:
        """When capability check fails the budget check is not even invoked."""
        enforcer = _make_enforcer(has_cap=False)
        await enforcer.check_action(self.agent_id, "trade")

        enforcer._budget_mgr.check_and_record.assert_not_called()

    async def test_denied_audit_entry_has_deny_result(self) -> None:
        """Denied checks produce an audit entry with result='deny'."""
        enforcer = _make_enforcer(has_cap=False)
        await enforcer.check_action(self.agent_id, "trade")

        async with enforcer._audit_lock:
            entry = enforcer._audit_buffer[-1]

        assert entry.result == "deny"
        assert len(entry.reason) > 0


# ---------------------------------------------------------------------------
# PermissionEnforcer.require_action — raises PermissionDenied
# ---------------------------------------------------------------------------


class TestRequireAction:
    """Tests for require_action which raises PermissionDenied on failure."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_require_action_passes_silently_when_allowed(self) -> None:
        """require_action returns None (no exception) when the action is allowed."""
        enforcer = _make_enforcer(has_cap=True, budget_allowed=True)
        # Should not raise
        result = await enforcer.require_action(self.agent_id, "trade")
        assert result is None

    async def test_require_action_raises_permission_denied_on_capability_fail(self) -> None:
        """require_action raises PermissionDenied when capability check fails."""
        enforcer = _make_enforcer(has_cap=False)

        with pytest.raises(PermissionDenied) as exc_info:
            await enforcer.require_action(self.agent_id, "trade")

        exc = exc_info.value
        assert exc.agent_id == self.agent_id
        assert exc.action == "trade"
        assert len(exc.reason) > 0
        assert exc.enforcement_result is not None
        assert exc.enforcement_result.allowed is False

    async def test_require_action_raises_permission_denied_on_budget_fail(self) -> None:
        """require_action raises PermissionDenied when budget check fails."""
        enforcer = _make_enforcer(has_cap=True, budget_allowed=False, budget_reason="Trade count exceeded")

        with pytest.raises(PermissionDenied) as exc_info:
            await enforcer.require_action(self.agent_id, "place_order", {"value": "100.00"})

        exc = exc_info.value
        assert "Trade count exceeded" in exc.reason

    async def test_privilege_escalation_blocked(self) -> None:
        """A VIEWER agent cannot escalate to LIVE_TRADER by calling adjust_risk."""
        # Agent does NOT have can_adjust_risk
        enforcer = _make_enforcer(has_cap=False)

        with pytest.raises(PermissionDenied) as exc_info:
            await enforcer.require_action(self.agent_id, "adjust_risk")

        exc = exc_info.value
        assert exc.action == "adjust_risk"
        assert exc.enforcement_result is not None
        assert exc.enforcement_result.allowed is False
        assert exc.enforcement_result.capability_check_passed is False

    async def test_permission_denied_has_correct_attributes(self) -> None:
        """PermissionDenied exception carries agent_id, action, reason, and result."""
        enforcer = _make_enforcer(has_cap=False)

        with pytest.raises(PermissionDenied) as exc_info:
            await enforcer.require_action(self.agent_id, "modify_strategy")

        exc = exc_info.value
        assert exc.agent_id == self.agent_id
        assert exc.action == "modify_strategy"
        assert isinstance(exc.enforcement_result, EnforcementResult)


# ---------------------------------------------------------------------------
# @require decorator
# ---------------------------------------------------------------------------


class TestRequireDecorator:
    """Tests for the @enforcer.require(capability) decorator."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_decorator_allows_when_capability_held(self) -> None:
        """Decorated async function executes normally when capability passes."""
        enforcer = _make_enforcer(has_cap=True)

        @enforcer.require(Capability.CAN_TRADE)
        async def place_order(agent_id: str, symbol: str) -> dict:
            return {"status": "ok", "symbol": symbol}

        result = await place_order(self.agent_id, "BTCUSDT")
        assert result == {"status": "ok", "symbol": "BTCUSDT"}

    async def test_decorator_raises_permission_denied_when_capability_missing(self) -> None:
        """Decorated function raises PermissionDenied before executing when cap missing."""
        enforcer = _make_enforcer(has_cap=False)
        executed = []

        @enforcer.require(Capability.CAN_TRADE)
        async def place_order(agent_id: str) -> dict:
            executed.append(True)
            return {}

        with pytest.raises(PermissionDenied):
            await place_order(self.agent_id)

        # The function body must NOT have been reached
        assert executed == []

    async def test_decorator_resolves_agent_id_from_kwarg(self) -> None:
        """@require resolves agent_id from keyword argument."""
        enforcer = _make_enforcer(has_cap=True)

        @enforcer.require(Capability.CAN_READ_MARKET)
        async def get_price(agent_id: str, symbol: str) -> float:
            return 50000.0

        result = await get_price(agent_id=self.agent_id, symbol="BTCUSDT")
        assert result == 50000.0

    async def test_decorator_raises_type_error_on_sync_function(self) -> None:
        """@require raises TypeError when applied to a non-async function."""
        enforcer = _make_enforcer()

        with pytest.raises(TypeError, match="async"):

            @enforcer.require(Capability.CAN_TRADE)
            def sync_function(agent_id: str) -> None:  # type: ignore[return]
                pass

    async def test_decorator_raises_permission_denied_when_no_agent_id(self) -> None:
        """@require raises PermissionDenied when agent_id cannot be resolved."""
        enforcer = _make_enforcer(has_cap=True)

        @enforcer.require(Capability.CAN_TRADE)
        async def place_order(symbol: str) -> dict:
            return {}

        with pytest.raises(PermissionDenied, match="no 'agent_id'"):
            await place_order("BTCUSDT")

    async def test_decorator_preserves_function_name_and_docstring(self) -> None:
        """@require preserves __name__ and __doc__ via functools.wraps."""
        enforcer = _make_enforcer()

        @enforcer.require(Capability.CAN_TRADE)
        async def place_order(agent_id: str) -> dict:
            """Place an order."""
            return {}

        assert place_order.__name__ == "place_order"
        assert place_order.__doc__ == "Place an order."


# ---------------------------------------------------------------------------
# Audit log retrieval
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Tests for get_audit_log."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_get_audit_log_returns_entries_for_agent(self) -> None:
        """get_audit_log returns only entries for the requested agent_id."""
        enforcer = _make_enforcer()
        other_agent = str(uuid4())

        await enforcer.check_action(self.agent_id, "trade")
        await enforcer.check_action(other_agent, "get_price")

        log = await enforcer.get_audit_log(self.agent_id)

        assert len(log) == 1
        assert log[0].agent_id == self.agent_id

    async def test_get_audit_log_newest_first(self) -> None:
        """get_audit_log returns entries in newest-first order by checked_at timestamp."""
        from datetime import timedelta  # noqa: PLC0415

        from agent.models.ecosystem import AuditEntry  # noqa: PLC0415

        enforcer = _make_enforcer()

        now = datetime.now(UTC)
        older_entry = AuditEntry(
            agent_id=self.agent_id,
            action="get_price",
            result="allow",
            reason="",
            checked_at=now - timedelta(seconds=5),
        )
        newer_entry = AuditEntry(
            agent_id=self.agent_id,
            action="trade",
            result="allow",
            reason="",
            checked_at=now,
        )

        # Add entries directly to the buffer (oldest first)
        async with enforcer._audit_lock:
            enforcer._audit_buffer.append(older_entry)
            enforcer._audit_buffer.append(newer_entry)

        log = await enforcer.get_audit_log(self.agent_id)

        # Newest entry should be "trade"
        assert log[0].action == "trade"
        assert log[1].action == "get_price"

    async def test_get_audit_log_respects_limit(self) -> None:
        """get_audit_log returns at most `limit` entries."""
        enforcer = _make_enforcer()

        for _ in range(5):
            await enforcer.check_action(self.agent_id, "get_price")

        log = await enforcer.get_audit_log(self.agent_id, limit=3)
        assert len(log) <= 3

    async def test_audit_buffer_flushes_at_threshold(self) -> None:
        """Audit buffer triggers flush when it reaches _AUDIT_FLUSH_SIZE entries."""
        from agent.permissions.enforcement import _AUDIT_FLUSH_SIZE  # noqa: PLC0415

        enforcer = _make_enforcer()
        # Mock the flush to avoid DB calls
        enforcer._flush_audit_buffer = AsyncMock()

        for _i in range(_AUDIT_FLUSH_SIZE):
            await enforcer.check_action(self.agent_id, "get_price")

        # Flush should have been called at least once
        enforcer._flush_audit_buffer.assert_called()


# ---------------------------------------------------------------------------
# PermissionEnforcer.request_escalation
# ---------------------------------------------------------------------------


class TestRequestEscalation:
    """Tests for request_escalation — stores an escalation request."""

    def setup_method(self) -> None:
        self.agent_id = str(uuid4())

    async def test_escalation_request_stores_feedback_and_returns_id(self) -> None:
        """A valid escalation request returns a non-empty feedback_id string."""
        enforcer = _make_enforcer()

        mock_feedback = MagicMock()
        mock_feedback.id = uuid4()

        mock_session = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_session_cm

        mock_repo = AsyncMock()
        mock_repo.create.return_value = mock_feedback

        with (
            patch(
                "src.database.repositories.agent_feedback_repo.AgentFeedbackRepository",
                return_value=mock_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=lambda: mock_session,
            ),
        ):
            feedback_id = await enforcer.request_escalation(
                self.agent_id,
                Capability.CAN_TRADE,
                reason="Need trade access for live signals.",
                priority="high",
            )

        assert feedback_id == str(mock_feedback.id)
        mock_repo.create.assert_called_once()

    async def test_escalation_invalid_agent_id_returns_empty_string(self) -> None:
        """Invalid agent_id returns empty string without raising."""
        enforcer = _make_enforcer()
        result = await enforcer.request_escalation(
            "not-a-uuid",
            Capability.CAN_TRADE,
            "Some reason",
        )
        assert result == ""

    async def test_escalation_invalid_priority_coerced_to_medium(self) -> None:
        """An unknown priority value is silently coerced to 'medium'."""
        enforcer = _make_enforcer()

        mock_feedback = MagicMock()
        mock_feedback.id = uuid4()

        mock_session = MagicMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin.return_value = mock_session_cm

        mock_repo = AsyncMock()
        mock_repo.create.return_value = mock_feedback

        with (
            patch(
                "src.database.repositories.agent_feedback_repo.AgentFeedbackRepository",
                return_value=mock_repo,
            ),
            patch(
                "src.database.session.get_session_factory",
                return_value=lambda: mock_session,
            ),
        ):
            await enforcer.request_escalation(
                self.agent_id,
                Capability.CAN_MODIFY_STRATEGY,
                "Requesting strategy access.",
                priority="superurgent",  # invalid priority
            )

        # Should succeed and the invalid priority was coerced
        created_call_args = mock_repo.create.call_args[0][0]
        assert created_call_args.priority == "medium"


# ---------------------------------------------------------------------------
# PermissionEnforcer context manager
# ---------------------------------------------------------------------------


class TestEnforcerContextManager:
    """Tests for async context manager (__aenter__/__aexit__)."""

    async def test_context_manager_flushes_on_exit(self) -> None:
        """Exiting the context manager flushes remaining audit entries."""
        enforcer = _make_enforcer()
        enforcer._flush_audit_buffer = AsyncMock()

        agent_id = str(uuid4())
        async with enforcer:
            await enforcer.check_action(agent_id, "get_price")

        enforcer._flush_audit_buffer.assert_called()

    async def test_close_is_idempotent(self) -> None:
        """close() can be called multiple times without raising."""
        enforcer = _make_enforcer()
        enforcer._flush_audit_buffer = AsyncMock()

        await enforcer.close()
        await enforcer.close()  # second call should be a no-op
        assert enforcer._closed is True
