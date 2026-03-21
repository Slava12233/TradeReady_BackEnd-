"""Role definitions and hierarchy for the agent permission system.

Roles are ordered from least to most privileged.  Each role inherits a fixed
set of capabilities defined in :data:`ROLE_CAPABILITIES`.  The ``ADMIN`` role
uses the wildcard sentinel ``"*"`` so :func:`has_role_capability` always
returns ``True`` for it regardless of the capability requested.

:data:`ROLE_CAPABILITIES` uses raw capability string values (matching the
:class:`~agent.permissions.capabilities.Capability` enum members) to avoid a
circular import — ``roles.py`` must not import from ``capabilities.py`` at
module level since ``capabilities.py`` imports :class:`AgentRole` from here.

Typical usage::

    from agent.permissions.roles import AgentRole, ROLE_HIERARCHY, get_role_capabilities

    role = AgentRole.PAPER_TRADER
    caps = get_role_capabilities(role)
    print(caps)  # frozenset({"can_trade", "can_read_portfolio", ...})

    # Check whether one role outranks another
    if ROLE_HIERARCHY[AgentRole.LIVE_TRADER] > ROLE_HIERARCHY[AgentRole.VIEWER]:
        print("live_trader outranks viewer")
"""

from __future__ import annotations

from enum import unique

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11 shim
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


@unique
class AgentRole(StrEnum):
    """Broad role assigned to a trading agent.

    Roles form a strict linear hierarchy (see :data:`ROLE_HIERARCHY`).  Higher
    roles grant a superset of the capabilities granted by lower roles — with
    the exception of ``ADMIN``, which uses a wildcard.

    Attributes:
        VIEWER:       Read-only access.  Can observe portfolio and market data.
        PAPER_TRADER: Can place orders in the sandbox environment only.
        LIVE_TRADER:  Full trading access including strategy and risk
                      modification.
        ADMIN:        Unrestricted access to all capabilities (wildcard).
    """

    VIEWER = "viewer"
    PAPER_TRADER = "paper_trader"
    LIVE_TRADER = "live_trader"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Hierarchy table — higher integer == more privileged
# ---------------------------------------------------------------------------

ROLE_HIERARCHY: dict[AgentRole, int] = {
    AgentRole.VIEWER: 0,
    AgentRole.PAPER_TRADER: 1,
    AgentRole.LIVE_TRADER: 2,
    AgentRole.ADMIN: 3,
}

# ---------------------------------------------------------------------------
# Capability grants per role
#
# Uses raw string values (matching Capability enum members) to avoid a
# circular import between roles.py and capabilities.py.
#
# The ADMIN role uses the sentinel frozenset {"*"} — callers that need to
# check whether a specific capability is covered by the role should use
# :func:`has_role_capability` rather than inspecting the set directly.
# ---------------------------------------------------------------------------

ROLE_CAPABILITIES: dict[AgentRole, frozenset[str]] = {
    AgentRole.VIEWER: frozenset(
        {
            "can_read_portfolio",
            "can_read_market",
            "can_journal",
        }
    ),
    AgentRole.PAPER_TRADER: frozenset(
        {
            "can_trade",
            "can_read_portfolio",
            "can_read_market",
            "can_journal",
            "can_backtest",
            "can_report",
        }
    ),
    AgentRole.LIVE_TRADER: frozenset(
        {
            "can_trade",
            "can_read_portfolio",
            "can_read_market",
            "can_journal",
            "can_backtest",
            "can_report",
            "can_modify_strategy",
            "can_adjust_risk",
        }
    ),
    # Wildcard sentinel — has_role_capability() interprets this as "all"
    AgentRole.ADMIN: frozenset({"*"}),
}

# ---------------------------------------------------------------------------
# Internal sentinel
# ---------------------------------------------------------------------------

_WILDCARD: frozenset[str] = frozenset({"*"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def has_role_capability(role: AgentRole, capability: str) -> bool:
    """Return True if *role* grants *capability*.

    ``ADMIN`` always returns ``True`` (wildcard).  For all other roles the
    exact capability string must appear in :data:`ROLE_CAPABILITIES`.

    Because :class:`~agent.permissions.capabilities.Capability` is a
    :class:`~enum.StrEnum`, passing a ``Capability`` member is equivalent to
    passing its string value.

    Args:
        role: The :class:`AgentRole` to check.
        capability: The capability string (or
            :class:`~agent.permissions.capabilities.Capability` enum member)
            being tested.

    Returns:
        ``True`` if the role grants the capability, ``False`` otherwise.
    """
    grants = ROLE_CAPABILITIES.get(role, frozenset())
    if grants == _WILDCARD:
        return True
    return capability in grants


def get_role_capabilities(role: AgentRole) -> frozenset[str]:
    """Return the set of capability strings granted by *role*.

    For ``ADMIN`` the returned set contains only the sentinel ``"*"``.
    Callers that need a concrete capability check should use
    :func:`has_role_capability` instead.

    Args:
        role: The :class:`AgentRole` to look up.

    Returns:
        Immutable :class:`frozenset` of capability string values.
    """
    return ROLE_CAPABILITIES.get(role, frozenset())


def role_from_string(value: str) -> AgentRole:
    """Convert a string role value to :class:`AgentRole`.

    Args:
        value: Raw role string (e.g. ``"paper_trader"``).

    Returns:
        The matching :class:`AgentRole` member.

    Raises:
        ValueError: If *value* does not match any known role.
    """
    try:
        return AgentRole(value)
    except ValueError:
        valid = ", ".join(r.value for r in AgentRole)
        raise ValueError(
            f"Unknown agent role {value!r}. Valid roles: {valid}"
        ) from None
