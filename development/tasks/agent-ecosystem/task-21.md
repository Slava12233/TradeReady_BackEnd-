---
task_id: 21
title: "Permission system — roles and capabilities"
type: task
agent: "backend-developer"
phase: 2
depends_on: [3]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "high"
files: ["agent/permissions/__init__.py", "agent/permissions/roles.py", "agent/permissions/capabilities.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 21: Permission system — roles and capabilities

## Assigned Agent: `backend-developer`

## Objective
Create the RBAC role system and granular capability toggles for controlling agent autonomy. This is safety-critical — agents must not be able to trade beyond their permissions.

## Files to Create
- `agent/permissions/__init__.py` — export public classes
- `agent/permissions/roles.py` — role definitions and hierarchy
- `agent/permissions/capabilities.py` — granular capability management

## Key Design

### roles.py
```python
class AgentRole(str, Enum):
    VIEWER = "viewer"             # Read-only access
    PAPER_TRADER = "paper_trader" # Can trade with virtual money
    LIVE_TRADER = "live_trader"   # Can trade with real money (future)
    ADMIN = "admin"               # Full access

# Role hierarchy: admin > live_trader > paper_trader > viewer
ROLE_HIERARCHY = {
    AgentRole.VIEWER: 0,
    AgentRole.PAPER_TRADER: 1,
    AgentRole.LIVE_TRADER: 2,
    AgentRole.ADMIN: 3,
}

# Default capabilities per role
ROLE_CAPABILITIES = {
    AgentRole.VIEWER: {"can_read_portfolio", "can_read_market", "can_journal"},
    AgentRole.PAPER_TRADER: {"can_trade", "can_read_portfolio", "can_read_market", "can_journal", "can_backtest", "can_report"},
    AgentRole.LIVE_TRADER: {"can_trade", "can_read_portfolio", "can_read_market", "can_journal", "can_backtest", "can_report", "can_modify_strategy", "can_adjust_risk"},
    AgentRole.ADMIN: {"*"},  # all capabilities
}
```

### capabilities.py
```python
class Capability(str, Enum):
    CAN_TRADE = "can_trade"
    CAN_READ_PORTFOLIO = "can_read_portfolio"
    CAN_READ_MARKET = "can_read_market"
    CAN_JOURNAL = "can_journal"
    CAN_BACKTEST = "can_backtest"
    CAN_REPORT = "can_report"
    CAN_MODIFY_STRATEGY = "can_modify_strategy"
    CAN_ADJUST_RISK = "can_adjust_risk"

class CapabilityManager:
    async def get_capabilities(self, agent_id: str) -> set[Capability]: ...
    async def has_capability(self, agent_id: str, capability: Capability) -> bool: ...
    async def grant_capability(self, agent_id: str, capability: Capability, granted_by: str) -> None: ...
    async def revoke_capability(self, agent_id: str, capability: Capability) -> None: ...
```

## Acceptance Criteria
- [ ] Role hierarchy correctly determines permission inheritance
- [ ] Capabilities can be granted/revoked independently of role
- [ ] Role change updates capabilities automatically
- [ ] `has_capability()` checks both role-based and explicitly granted capabilities
- [ ] Permissions cached in Redis for fast lookups (via `agent:permissions:{agent_id}`)
- [ ] Cache invalidated on permission change

## Dependencies
- Task 03 (agent_permission_repo)

## Agent Instructions
1. Read the plan section 2.4 carefully
2. Use `agent_permission_repo` for persistence
3. Cache permissions in Redis with 5-minute TTL
4. Role hierarchy: admin inherits all lower role capabilities
5. Explicit capability grants can add to (but not subtract from) role capabilities

## Estimated Complexity
Medium — RBAC with caching, role hierarchy, and explicit overrides.
