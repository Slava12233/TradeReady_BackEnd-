"""Agent permission system — roles, granular capability management, budget enforcement,
and central permission enforcement with audit logging.

This package provides four complementary layers for controlling agent autonomy:

1. **Roles** (:mod:`agent.permissions.roles`) — coarse-grained access levels
   (``viewer`` → ``paper_trader`` → ``live_trader`` → ``admin``) with
   pre-defined capability sets per role.

2. **Capabilities** (:mod:`agent.permissions.capabilities`) — fine-grained
   feature flags that can be granted or revoked independently of the agent's
   role.  Managed at runtime by :class:`~agent.permissions.capabilities.CapabilityManager`.

3. **Budget enforcement** (:mod:`agent.permissions.budget`) — financial limits
   on daily trade count, total exposure, daily loss, and position size.
   Counters are stored in Redis (fast path, <5 ms) and persisted to Postgres
   every 5 minutes.  Managed by :class:`~agent.permissions.budget.BudgetManager`.

4. **Permission enforcement** (:mod:`agent.permissions.enforcement`) — central
   enforcement point that combines capability + budget checks, writes an audit
   log, and provides the :class:`~agent.permissions.enforcement.PermissionDenied`
   exception and the :meth:`~agent.permissions.enforcement.PermissionEnforcer.require`
   decorator.

Public API::

    from agent.permissions import (
        # Enums
        AgentRole,
        Capability,
        # Constants
        ROLE_HIERARCHY,
        ROLE_CAPABILITIES,
        ALL_CAPABILITIES,
        ACTION_CAPABILITY_MAP,
        BUDGET_CHECKED_ACTIONS,
        # Managers
        CapabilityManager,
        BudgetManager,
        PermissionEnforcer,
        # Exception
        PermissionDenied,
        # Helpers
        has_role_capability,
        get_role_capabilities,
        role_from_string,
    )

Quick usage::

    from agent.permissions import (
        AgentRole, Capability, CapabilityManager, BudgetManager,
        PermissionEnforcer, PermissionDenied,
    )
    from agent.config import AgentConfig
    from decimal import Decimal

    config = AgentConfig()

    # --- Capability checks ---
    cap_manager = CapabilityManager(config=config)
    allowed = await cap_manager.has_capability("agent-uuid", Capability.CAN_TRADE)
    caps = await cap_manager.get_capabilities("agent-uuid")
    await cap_manager.set_role("agent-uuid", AgentRole.LIVE_TRADER, granted_by="admin-uuid")
    await cap_manager.grant_capability("agent-uuid", Capability.CAN_ADJUST_RISK, granted_by="admin-uuid")
    await cap_manager.revoke_capability("agent-uuid", Capability.CAN_TRADE, granted_by="admin-uuid")

    # --- Budget checks ---
    budget_manager = BudgetManager(config=config)
    result = await budget_manager.check_budget("agent-uuid", Decimal("500.00"))
    if result.allowed:
        await budget_manager.record_trade("agent-uuid", Decimal("500.00"))
    status = await budget_manager.get_budget_status("agent-uuid")

    # --- Central enforcement ---
    enforcer = PermissionEnforcer(capability_mgr=cap_manager, budget_mgr=budget_manager)

    # Inline check — never raises
    result = await enforcer.check_action("agent-uuid", "trade", {"value": "500.00"})
    if result.allowed:
        ...  # proceed

    # Raising variant
    try:
        await enforcer.require_action("agent-uuid", "trade")
    except PermissionDenied as exc:
        print(exc.reason)

    # Decorator
    @enforcer.require(Capability.CAN_TRADE)
    async def execute_order(agent_id: str, symbol: str) -> dict:
        ...

    # Permission escalation request
    feedback_id = await enforcer.request_escalation(
        "agent-uuid", Capability.CAN_TRADE, "Need trading access for live signals."
    )
"""

from agent.permissions.budget import BudgetManager
from agent.permissions.capabilities import (
    ALL_CAPABILITIES,
    Capability,
    CapabilityManager,
)
from agent.permissions.enforcement import (
    ACTION_CAPABILITY_MAP,
    BUDGET_CHECKED_ACTIONS,
    PermissionDenied,
    PermissionEnforcer,
)
from agent.permissions.roles import (
    ROLE_CAPABILITIES,
    ROLE_HIERARCHY,
    AgentRole,
    get_role_capabilities,
    has_role_capability,
    role_from_string,
)

__all__ = [
    # Enums
    "AgentRole",
    "Capability",
    # Constants
    "ALL_CAPABILITIES",
    "ROLE_CAPABILITIES",
    "ROLE_HIERARCHY",
    "ACTION_CAPABILITY_MAP",
    "BUDGET_CHECKED_ACTIONS",
    # Managers
    "BudgetManager",
    "CapabilityManager",
    "PermissionEnforcer",
    # Exception
    "PermissionDenied",
    # Helpers
    "get_role_capabilities",
    "has_role_capability",
    "role_from_string",
]
