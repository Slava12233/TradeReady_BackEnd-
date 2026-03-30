"""Central permission enforcement layer for all agent actions.

Every agent action flows through :class:`PermissionEnforcer` before execution.
The enforcer combines two independent checks:

1. **Capability check** — via :class:`~agent.permissions.capabilities.CapabilityManager`:
   does the agent hold the required :class:`~agent.permissions.capabilities.Capability`
   for this action?

2. **Budget check** — via :class:`~agent.permissions.budget.BudgetManager`: does the
   agent have remaining budget headroom for financial actions such as trading?  For
   non-financial actions the budget check is skipped and always considered passed.

After each check the result is appended to an in-memory audit buffer.  The buffer
flushes automatically when it reaches :data:`_AUDIT_FLUSH_SIZE` entries or when the
background flush timer fires (every :data:`_AUDIT_FLUSH_INTERVAL_SECONDS` seconds).

The decorator :meth:`PermissionEnforcer.require` wraps an async tool function and
gates it behind a capability check before the function body runs.

Action-to-capability mapping
-----------------------------
The default mapping from action name strings to :class:`~agent.permissions.capabilities.Capability`
values is defined in :data:`ACTION_CAPABILITY_MAP`.  Actions not present in the map
are treated as requiring *no* capability (always allowed from a capability standpoint).

Exception types
---------------
:class:`PermissionDenied` is raised by :meth:`PermissionEnforcer.require_action` and
the :meth:`~PermissionEnforcer.require` decorator when an action is not allowed.  It
is intentionally **not** a subclass of :class:`~src.utils.exceptions.TradingPlatformError`
so that the agent layer remains independent of the platform HTTP layer.  Callers in
API routes should translate it to :class:`~src.utils.exceptions.PermissionDeniedError`
if needed.

Example::

    from agent.permissions import CapabilityManager, BudgetManager, Capability
    from agent.permissions.enforcement import PermissionEnforcer, PermissionDenied
    from agent.config import AgentConfig

    config = AgentConfig()
    enforcer = PermissionEnforcer(
        capability_mgr=CapabilityManager(config=config),
        budget_mgr=BudgetManager(config=config),
    )

    # Inline check
    result = await enforcer.check_action("agent-uuid", "trade", {"value": "500.00"})
    if result.allowed:
        ...  # proceed

    # Raises PermissionDenied on failure
    await enforcer.require_action("agent-uuid", "read_portfolio")

    # Decorator usage
    @enforcer.require(Capability.CAN_TRADE)
    async def place_order(agent_id: str, ...) -> dict:
        ...
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from agent.models.ecosystem import AuditEntry, EnforcementResult
from agent.permissions.budget import BudgetManager
from agent.permissions.capabilities import Capability, CapabilityManager

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Flush the audit buffer to DB when it reaches this size.
_AUDIT_FLUSH_SIZE: int = 100

# Flush the audit buffer every this many seconds even if size threshold not met.
_AUDIT_FLUSH_INTERVAL_SECONDS: float = 30.0

# Default Decimal trade value used when the action context does not supply one.
_DEFAULT_TRADE_VALUE = Decimal("0")

# ---------------------------------------------------------------------------
# Action → Capability mapping
# ---------------------------------------------------------------------------

#: Maps action name strings to the :class:`~agent.permissions.capabilities.Capability`
#: required to perform that action.  Actions not present in this map require no
#: specific capability (always allowed from a capability standpoint).
ACTION_CAPABILITY_MAP: dict[str, Capability] = {
    # Trading actions
    "trade": Capability.CAN_TRADE,
    "place_order": Capability.CAN_TRADE,
    "cancel_order": Capability.CAN_TRADE,
    "close_position": Capability.CAN_TRADE,
    # Portfolio read actions
    "read_portfolio": Capability.CAN_READ_PORTFOLIO,
    "get_portfolio": Capability.CAN_READ_PORTFOLIO,
    "get_positions": Capability.CAN_READ_PORTFOLIO,
    "get_balance": Capability.CAN_READ_PORTFOLIO,
    "get_trade_history": Capability.CAN_READ_PORTFOLIO,
    "get_performance": Capability.CAN_READ_PORTFOLIO,
    # Market data read actions
    "read_market": Capability.CAN_READ_MARKET,
    "get_price": Capability.CAN_READ_MARKET,
    "get_candles": Capability.CAN_READ_MARKET,
    "get_order_book": Capability.CAN_READ_MARKET,
    "scan_opportunities": Capability.CAN_READ_MARKET,
    # Journal actions
    "journal": Capability.CAN_JOURNAL,
    "journal_entry": Capability.CAN_JOURNAL,
    "write_journal": Capability.CAN_JOURNAL,
    # Backtesting actions
    "backtest": Capability.CAN_BACKTEST,
    "create_backtest": Capability.CAN_BACKTEST,
    "run_backtest": Capability.CAN_BACKTEST,
    "step_backtest": Capability.CAN_BACKTEST,
    # Reporting actions
    "report": Capability.CAN_REPORT,
    "generate_report": Capability.CAN_REPORT,
    "export_report": Capability.CAN_REPORT,
    # Strategy modification actions
    "modify_strategy": Capability.CAN_MODIFY_STRATEGY,
    "create_strategy": Capability.CAN_MODIFY_STRATEGY,
    "update_strategy": Capability.CAN_MODIFY_STRATEGY,
    "deploy_strategy": Capability.CAN_MODIFY_STRATEGY,
    "test_strategy": Capability.CAN_MODIFY_STRATEGY,
    # Risk adjustment actions
    "adjust_risk": Capability.CAN_ADJUST_RISK,
    "update_risk_profile": Capability.CAN_ADJUST_RISK,
    "set_stop_loss": Capability.CAN_ADJUST_RISK,
    "set_position_limit": Capability.CAN_ADJUST_RISK,
}

#: Actions that require a budget check in addition to the capability check.
#: These are financial actions that consume trade budget headroom.
BUDGET_CHECKED_ACTIONS: frozenset[str] = frozenset(
    {
        "trade",
        "place_order",
        "close_position",
        "backtest",
        "create_backtest",
        "run_backtest",
    }
)


# ---------------------------------------------------------------------------
# PermissionDenied exception
# ---------------------------------------------------------------------------


class PermissionDenied(Exception):
    """Raised when an agent action is not permitted by the enforcement layer.

    Intentionally **not** a subclass of
    :class:`~src.utils.exceptions.TradingPlatformError` so that the agent
    package stays decoupled from the platform HTTP layer.  API route handlers
    that call enforcer methods should translate this to
    :class:`~src.utils.exceptions.PermissionDeniedError` where needed.

    Attributes:
        agent_id: The agent whose action was denied.
        action: The action that was blocked.
        reason: Human-readable explanation of the denial.
        enforcement_result: The full :class:`~agent.models.ecosystem.EnforcementResult`
            that produced the denial, for introspection.

    Example::

        try:
            await enforcer.require_action("agent-uuid", "trade")
        except PermissionDenied as exc:
            logger.warning("agent.permission.action.blocked", reason=exc.reason)
    """

    def __init__(
        self,
        message: str,
        *,
        agent_id: str = "",
        action: str = "",
        reason: str = "",
        enforcement_result: EnforcementResult | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_id = agent_id
        self.action = action
        self.reason = reason or message
        self.enforcement_result = enforcement_result


# ---------------------------------------------------------------------------
# PermissionEnforcer
# ---------------------------------------------------------------------------


class PermissionEnforcer:
    """Central enforcement point for all agent permissions.

    Combines :class:`~agent.permissions.capabilities.CapabilityManager` and
    :class:`~agent.permissions.budget.BudgetManager` into a single call per
    agent action.  Every call writes an :class:`~agent.models.ecosystem.AuditEntry`
    to an in-memory buffer that is flushed to the ``agent_feedback`` table in
    batches.

    Audit buffer flush policy:
        - Flush immediately when :attr:`_audit_buffer` reaches
          :data:`_AUDIT_FLUSH_SIZE` entries (100).
        - Flush on a background timer every :data:`_AUDIT_FLUSH_INTERVAL_SECONDS`
          seconds (30 s).
        - Flush on :meth:`close` / ``async with`` exit.

    Args:
        capability_mgr: A configured :class:`~agent.permissions.capabilities.CapabilityManager`.
        budget_mgr: A configured :class:`~agent.permissions.budget.BudgetManager`.
        action_map: Optional override for :data:`ACTION_CAPABILITY_MAP`.
        budget_actions: Optional override for :data:`BUDGET_CHECKED_ACTIONS`.

    Example::

        config = AgentConfig()
        enforcer = PermissionEnforcer(
            capability_mgr=CapabilityManager(config=config),
            budget_mgr=BudgetManager(config=config),
        )

        result = await enforcer.check_action("agent-uuid", "trade")
        await enforcer.require_action("agent-uuid", "read_portfolio")

        @enforcer.require(Capability.CAN_TRADE)
        async def execute_trade(agent_id: str, ...) -> dict:
            ...
    """

    def __init__(
        self,
        capability_mgr: CapabilityManager,
        budget_mgr: BudgetManager,
        action_map: dict[str, Capability] | None = None,
        budget_actions: frozenset[str] | None = None,
        audit_allow_events: bool = True,
    ) -> None:
        self._capability_mgr = capability_mgr
        self._budget_mgr = budget_mgr
        self._action_map: dict[str, Capability] = action_map if action_map is not None else ACTION_CAPABILITY_MAP
        self._budget_actions: frozenset[str] = budget_actions if budget_actions is not None else BUDGET_CHECKED_ACTIONS
        # When True, "allow" events are persisted to the agent_audit_log table
        # in addition to "deny" events.  Disable in high-throughput deployments
        # where allow-event volume is prohibitive.  Deny events are always
        # persisted regardless of this flag.
        self._audit_allow_events: bool = audit_allow_events

        # Audit buffer — filled by _record_audit, flushed in batch.
        self._audit_buffer: list[AuditEntry] = []
        self._audit_lock = asyncio.Lock()

        # Background flush timer task (started lazily on first check).
        self._flush_task: asyncio.Task[None] | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> PermissionEnforcer:
        """Start the background flush timer and return self."""
        self._ensure_flush_task()
        return self

    async def __aexit__(self, *_: object) -> None:
        """Flush remaining audit entries and stop the background timer."""
        await self.close()

    async def close(self) -> None:
        """Flush remaining audit entries and stop the background flush timer.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        if self._closed:
            return
        self._closed = True

        # Cancel the background timer.
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush whatever remains in the buffer.
        await self._flush_audit_buffer()

    # ------------------------------------------------------------------
    # Lazy background flush timer
    # ------------------------------------------------------------------

    def _ensure_flush_task(self) -> None:
        """Start the background flush task if not already running."""
        if self._flush_task is None or self._flush_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._flush_task = loop.create_task(self._periodic_flush())
            except RuntimeError:
                # No running event loop — will be started lazily on next check_action.
                pass

    async def _periodic_flush(self) -> None:
        """Background coroutine that flushes the audit buffer every interval.

        Runs until cancelled (on :meth:`close`).
        """
        while True:
            try:
                await asyncio.sleep(_AUDIT_FLUSH_INTERVAL_SECONDS)
                await self._flush_audit_buffer()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "agent.permission.enforcer.periodic_flush_error",
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def _record_audit(self, entry: AuditEntry) -> None:
        """Append *entry* to the in-memory buffer and flush if threshold reached.

        Args:
            entry: The :class:`~agent.models.ecosystem.AuditEntry` to record.
        """
        async with self._audit_lock:
            self._audit_buffer.append(entry)
            should_flush = len(self._audit_buffer) >= _AUDIT_FLUSH_SIZE

        if should_flush:
            await self._flush_audit_buffer()

        # Start the periodic flush task lazily after the first audit entry.
        self._ensure_flush_task()

    async def _flush_audit_buffer(self) -> None:
        """Write all buffered audit entries to Postgres and clear the buffer.

        Uses :class:`~src.database.repositories.agent_feedback_repo.AgentFeedbackRepository`
        as the escalation storage target since there is no dedicated ``agent_audit_log``
        table yet.  Each :class:`~agent.models.ecosystem.AuditEntry` is mapped to an
        :class:`~src.database.models.AgentFeedback` row with
        ``category="bug"`` and ``priority="low"`` so denied checks are visible to
        human operators without polluting the bug queue.

        Silently swallows all errors so a flush failure never blocks action checks.
        """
        async with self._audit_lock:
            if not self._audit_buffer:
                return
            entries_to_flush = list(self._audit_buffer)
            self._audit_buffer.clear()

        if not entries_to_flush:
            return

        try:
            await self._persist_audit_entries(entries_to_flush)
            logger.debug(
                "agent.permission.enforcer.audit_flushed",
                count=len(entries_to_flush),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.permission.enforcer.audit_flush_error",
                count=len(entries_to_flush),
                error=str(exc),
            )

    async def _persist_audit_entries(self, entries: list[AuditEntry]) -> None:
        """Persist audit entries to the ``agent_audit_log`` table.

        Both "allow" and "deny" outcomes are persisted for a complete audit
        trail.  Allow-event persistence is gated by ``self._audit_allow_events``
        (default ``True``).

        Args:
            entries: List of :class:`~agent.models.ecosystem.AuditEntry` objects to persist.
        """
        from decimal import Decimal as _Decimal  # noqa: PLC0415
        from uuid import UUID  # noqa: PLC0415

        from src.database.models import AgentAuditLog  # noqa: PLC0415
        from src.database.repositories.agent_audit_log_repo import (  # noqa: PLC0415
            AgentAuditLogRepository,
        )
        from src.database.session import get_session_factory  # noqa: PLC0415

        factory = get_session_factory()

        try:
            session = factory()
            async with session.begin():
                repo = AgentAuditLogRepository(session)
                rows: list[AgentAuditLog] = []
                for entry in entries:
                    try:
                        agent_uuid = UUID(entry.agent_id)
                    except (ValueError, AttributeError):
                        logger.warning(
                            "agent.permission.enforcer.audit_invalid_agent_id",
                            agent_id=entry.agent_id,
                        )
                        continue

                    # Skip allow events if persistence is disabled.
                    if entry.result != "deny" and not self._audit_allow_events:
                        continue

                    # Extract trade_value from context if present.
                    trade_value = None
                    if entry.context and "trade_value" in entry.context:
                        try:
                            trade_value = _Decimal(str(entry.context["trade_value"]))
                        except Exception:  # noqa: BLE001
                            pass

                    rows.append(AgentAuditLog(
                        agent_id=agent_uuid,
                        action=entry.action,
                        outcome=entry.result,
                        reason=entry.reason,
                        trade_value=trade_value,
                        metadata=entry.context,
                    ))

                if rows:
                    await repo.bulk_create(rows)

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.permission.enforcer.persist_error",
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # Core permission check
    # ------------------------------------------------------------------

    async def check_action(
        self,
        agent_id: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> EnforcementResult:
        """Perform a full permission check for *action* by *agent_id*.

        Checks, in order:

        1. **Capability check** — does the agent hold the capability mapped to
           *action* by :data:`ACTION_CAPABILITY_MAP`?  Actions not in the map
           skip this check and are considered capability-passed.

        2. **Budget check** — for actions in :data:`BUDGET_CHECKED_ACTIONS`,
           calls :meth:`~agent.permissions.budget.BudgetManager.check_budget`
           with the trade value from ``context["value"]`` (or ``0`` if absent).
           Non-budget actions always pass this check.

        Every call produces an :class:`~agent.models.ecosystem.AuditEntry` that
        is appended to the buffer and eventually persisted to the DB.

        Args:
            agent_id: UUID string of the agent requesting the action.
            action: Action name string (e.g. ``"trade"``, ``"read_portfolio"``).
            context: Optional caller-supplied context dict.  Recognised keys:
                - ``"value"`` (`str` or `Decimal`) — USDT trade value for budget checks.
                - Any other key-value pairs are stored verbatim in the audit entry.

        Returns:
            An :class:`~agent.models.ecosystem.EnforcementResult` with ``allowed``
            set to ``True`` or ``False``.

        Example::

            result = await enforcer.check_action(
                "agent-uuid",
                "trade",
                {"symbol": "BTCUSDT", "value": "500.00"},
            )
            if result.allowed:
                ...
        """
        ctx: dict[str, Any] = context or {}
        now = datetime.now(UTC)

        # ----------------------------------------------------------------
        # 1. Capability check
        # ----------------------------------------------------------------
        required_capability = self._action_map.get(action)
        capability_passed = True
        cap_reason = ""

        if required_capability is not None:
            try:
                has_cap = await self._capability_mgr.has_capability(agent_id, required_capability)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "agent.permission.enforcer.capability_check_error",
                    agent_id=agent_id,
                    action=action,
                    error=str(exc),
                )
                # Fail closed on unexpected errors.
                has_cap = False

            if not has_cap:
                capability_passed = False
                cap_reason = (
                    f"Agent '{agent_id}' does not hold capability "
                    f"'{required_capability.value}' required for action '{action}'."
                )
                logger.info(
                    "agent.permission.enforcer.capability_denied",
                    agent_id=agent_id,
                    action=action,
                    required_capability=required_capability.value,
                )
                try:
                    from agent.metrics import agent_permission_denials  # noqa: PLC0415

                    agent_permission_denials.labels(
                        agent_id=agent_id,
                        capability=required_capability.value,
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass

        # ----------------------------------------------------------------
        # 2. Budget check (only for financial actions, only if cap passed)
        # ----------------------------------------------------------------
        budget_passed = True
        budget_reason = ""

        if capability_passed and action in self._budget_actions:
            trade_value = _DEFAULT_TRADE_VALUE
            raw_value = ctx.get("value")
            if raw_value is not None:
                try:
                    trade_value = Decimal(str(raw_value))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "agent.permission.enforcer.trade_value_parse_error",
                        agent_id=agent_id,
                        action=action,
                        raw_value=str(raw_value),
                        error=str(exc),
                    )

            try:
                # Use check_and_record to atomically gate and record the trade
                # within the per-agent lock, eliminating the TOCTOU race that
                # exists when check_budget and record_trade are called separately.
                budget_result = await self._budget_mgr.check_and_record(agent_id, trade_value)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "agent.permission.enforcer.budget_check_error",
                    agent_id=agent_id,
                    action=action,
                    error=str(exc),
                )
                # Fail closed on unexpected errors.
                budget_result = None  # type: ignore[assignment]

            if budget_result is None or not budget_result.allowed:
                budget_passed = False
                budget_reason = (
                    budget_result.reason
                    if budget_result is not None
                    else f"Budget check failed for action '{action}' (internal error)."
                )
                logger.info(
                    "agent.permission.enforcer.budget_denied",
                    agent_id=agent_id,
                    action=action,
                    reason=budget_reason,
                )
                try:
                    from agent.metrics import agent_permission_denials  # noqa: PLC0415

                    agent_permission_denials.labels(
                        agent_id=agent_id,
                        capability=f"budget:{action}",
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass

        # ----------------------------------------------------------------
        # 3. Assemble result
        # ----------------------------------------------------------------
        allowed = capability_passed and budget_passed
        if not allowed:
            reason = cap_reason or budget_reason
        else:
            reason = ""

        result = EnforcementResult(
            allowed=allowed,
            action=action,
            agent_id=agent_id,
            reason=reason,
            capability_check_passed=capability_passed,
            budget_check_passed=budget_passed,
            checked_at=now,
        )

        # ----------------------------------------------------------------
        # 4. Audit log
        # ----------------------------------------------------------------
        audit_entry = AuditEntry(
            audit_id="",
            agent_id=agent_id,
            action=action,
            result="allow" if allowed else "deny",
            reason=reason,
            context=ctx,
            checked_at=now,
        )
        await self._record_audit(audit_entry)

        return result

    async def require_action(
        self,
        agent_id: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Like :meth:`check_action` but raises :class:`PermissionDenied` on failure.

        Convenience wrapper that eliminates the need for callers to inspect the
        returned :class:`~agent.models.ecosystem.EnforcementResult` themselves.

        Args:
            agent_id: UUID string of the agent requesting the action.
            action: Action name string (e.g. ``"trade"``, ``"read_portfolio"``).
            context: Optional caller-supplied context dict (same as :meth:`check_action`).

        Raises:
            PermissionDenied: If the action is not permitted.

        Example::

            await enforcer.require_action("agent-uuid", "trade", {"value": "250.00"})
            # Raises PermissionDenied if not allowed; otherwise returns None.
        """
        result = await self.check_action(agent_id, action, context)
        if not result.allowed:
            raise PermissionDenied(
                result.reason,
                agent_id=agent_id,
                action=action,
                reason=result.reason,
                enforcement_result=result,
            )

    # ------------------------------------------------------------------
    # Audit log retrieval
    # ------------------------------------------------------------------

    async def get_audit_log(
        self,
        agent_id: str,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Return the most recent audit entries for *agent_id*.

        Returns entries from the in-memory buffer only (i.e. entries that have
        not yet been flushed to the DB are included, entries that were flushed
        are not returned here).  For a complete history, query the
        ``agent_feedback`` table directly.

        Args:
            agent_id: UUID string of the agent to retrieve entries for.
            limit: Maximum number of entries to return (newest first).

        Returns:
            A list of :class:`~agent.models.ecosystem.AuditEntry` objects,
            newest-first, limited to *limit* entries.
        """
        async with self._audit_lock:
            # Filter to this agent_id and return newest-first.
            agent_entries = [e for e in self._audit_buffer if e.agent_id == agent_id]

        agent_entries.sort(key=lambda e: e.checked_at, reverse=True)
        return agent_entries[:limit]

    # ------------------------------------------------------------------
    # Decorator
    # ------------------------------------------------------------------

    def require(self, capability: Capability) -> Callable:  # type: ignore[type-arg]
        """Decorator factory that enforces a :class:`~agent.permissions.capabilities.Capability`
        before an async tool function runs.

        The decorated function must have ``agent_id`` as its first positional
        argument or as a keyword argument.  The decorator resolves the action
        name from the capability value (prefixed with ``"cap:"`` to distinguish
        decorator-gated actions from string-name actions).

        Args:
            capability: The :class:`~agent.permissions.capabilities.Capability` that
                the calling agent must hold.

        Returns:
            A decorator function.

        Raises:
            :class:`PermissionDenied`: Before the wrapped function is called, if the
                agent does not hold *capability*.
            :class:`TypeError`: At decoration time if the decorated function is not
                an async callable.

        Example::

            @enforcer.require(Capability.CAN_TRADE)
            async def place_order(agent_id: str, symbol: str, side: str) -> dict:
                ...

            # agent_id is resolved from the first positional arg or 'agent_id' kwarg.
            await place_order("agent-uuid", "BTCUSDT", "buy")
        """

        def decorator(func: Callable) -> Callable:  # type: ignore[type-arg]
            if not inspect.iscoroutinefunction(func):
                raise TypeError(
                    f"@enforcer.require can only decorate async functions; "
                    f"'{func.__name__}' is not a coroutine function."
                )

            # Derive a synthetic action name from the capability value.
            action_name = f"cap:{capability.value}"

            # Inspect the function signature to locate 'agent_id' parameter.
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())
            agent_id_idx: int | None = None
            if "agent_id" in param_names:
                agent_id_idx = param_names.index("agent_id")

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                # Resolve agent_id from positional or keyword args.
                agent_id: str = ""
                if "agent_id" in kwargs:
                    agent_id = str(kwargs["agent_id"])
                elif agent_id_idx is not None and agent_id_idx < len(args):
                    agent_id = str(args[agent_id_idx])

                if not agent_id:
                    logger.warning(
                        "agent.permission.enforcer.require_no_agent_id",
                        func=func.__name__,
                        capability=capability.value,
                    )
                    # Fail closed — cannot enforce without knowing the agent.
                    raise PermissionDenied(
                        f"Cannot enforce capability '{capability.value}': "
                        "no 'agent_id' resolved from function arguments.",
                        action=action_name,
                        reason=(
                            f"Cannot enforce capability '{capability.value}': "
                            "no 'agent_id' resolved from function arguments."
                        ),
                    )

                # Override capability map for this synthetic action.
                original_map = self._action_map
                merged_map = {**original_map, action_name: capability}
                self._action_map = merged_map
                try:
                    await self.require_action(agent_id, action_name)
                finally:
                    # Restore the original map to avoid permanent mutation.
                    self._action_map = original_map

                return await func(*args, **kwargs)

            return wrapper

        return decorator

    # ------------------------------------------------------------------
    # Permission escalation
    # ------------------------------------------------------------------

    async def request_escalation(
        self,
        agent_id: str,
        capability: Capability,
        reason: str,
        *,
        priority: str = "medium",
    ) -> str:
        """Log a permission escalation request to the ``agent_feedback`` table.

        Agents can REQUEST higher permissions by calling this method.  The
        request is stored as an ``AgentFeedback`` row with
        ``category="feature_request"`` and the provided *priority*.  Human
        operators review the queue and may then call
        :meth:`~agent.permissions.capabilities.CapabilityManager.grant_capability`
        to fulfil the request.

        Args:
            agent_id: UUID string of the agent requesting escalation.
            capability: The :class:`~agent.permissions.capabilities.Capability`
                the agent is requesting.
            reason: Human-readable justification for the request.
            priority: Urgency level: ``"low"``, ``"medium"``, ``"high"``, or
                ``"critical"``.  Defaults to ``"medium"``.

        Returns:
            The ``str`` UUID of the newly created ``AgentFeedback`` row, or
            ``""`` if persistence failed.

        Example::

            feedback_id = await enforcer.request_escalation(
                "agent-uuid",
                Capability.CAN_TRADE,
                "Need trade access to execute live signals.",
                priority="high",
            )
        """
        from uuid import UUID  # noqa: PLC0415

        from src.database.models import AgentFeedback  # noqa: PLC0415
        from src.database.repositories.agent_feedback_repo import (  # noqa: PLC0415
            AgentFeedbackRepository,
        )
        from src.database.session import get_session_factory  # noqa: PLC0415

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            logger.warning(
                "agent.permission.enforcer.escalation_invalid_agent_id",
                agent_id=agent_id,
                error=str(exc),
            )
            return ""

        valid_priorities = {"low", "medium", "high", "critical"}
        if priority not in valid_priorities:
            logger.warning(
                "agent.permission.enforcer.escalation_invalid_priority",
                agent_id=agent_id,
                priority=priority,
            )
            priority = "medium"

        description = (
            f"[PERMISSION ESCALATION REQUEST] capability={capability.value!r} "
            f"agent_id={agent_id!r} reason={reason!r}"
        )

        factory = get_session_factory()
        try:
            session = factory()
            async with session.begin():
                repo = AgentFeedbackRepository(session)
                feedback_row = AgentFeedback(
                    agent_id=agent_uuid,
                    description=description,
                    category="feature_request",
                    priority=priority,
                    status="new",
                )
                created = await repo.create(feedback_row)
                feedback_id = str(created.id)

            logger.info(
                "agent.permission.enforcer.escalation_logged",
                agent_id=agent_id,
                capability=capability.value,
                feedback_id=feedback_id,
                priority=priority,
            )
            return feedback_id

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "agent.permission.enforcer.escalation_persist_error",
                agent_id=agent_id,
                capability=capability.value,
                error=str(exc),
            )
            return ""
