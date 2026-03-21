# agent/permissions/ — Roles, Capabilities, Budget Limits, and Enforcement

<!-- last-updated: 2026-03-21 -->

> Four-layer permission system for trading agents: role definitions, capability management, per-agent budget tracking, and enforcement with audit logging.

## What This Module Does

The `agent/permissions/` package controls what actions an agent is allowed to perform and how many resources it may consume. It provides:

- **Role definitions** (`AgentRole`, `ROLE_HIERARCHY`, `ROLE_CAPABILITIES`) — four tiered roles from view-only to admin, each with a fixed capability set.
- **Capability management** (`Capability`, `CapabilityManager`) — resolves an agent's actual capabilities at runtime from role grants plus per-agent JSONB overrides stored in Postgres, with a Redis cache.
- **Budget tracking** (`BudgetManager`) — enforces four financial limits (daily trade count, exposure cap, daily loss limit, position size) using Redis counters that auto-reset at midnight UTC.
- **Enforcement** (`PermissionEnforcer`, `PermissionDenied`) — the single entry point for all checks; combines capability validation, budget checks, and async audit log persistence in one call.

## Key Files

| File | Purpose |
|------|---------|
| `roles.py` | `AgentRole` StrEnum, `ROLE_HIERARCHY`, `ROLE_CAPABILITIES`, helper functions |
| `capabilities.py` | `Capability` StrEnum, `ALL_CAPABILITIES`, `CapabilityManager` |
| `budget.py` | `BudgetManager`, `_BudgetLimits`, budget counter Redis keys |
| `enforcement.py` | `PermissionEnforcer`, `PermissionDenied`, `ACTION_CAPABILITY_MAP`, `require()` decorator |
| `__init__.py` | Re-exports all public symbols from all four submodules |

## Public API

### `AgentRole`, `ROLE_HIERARCHY`, `ROLE_CAPABILITIES` — `roles.py`

```python
from agent.permissions import AgentRole, ROLE_HIERARCHY, ROLE_CAPABILITIES
from agent.permissions import has_role_capability, get_role_capabilities, role_from_string
```

**`AgentRole` (StrEnum):**

| Value | Hierarchy Level | Description |
|-------|----------------|-------------|
| `VIEWER` | 0 | Read-only access — market data and portfolio observation |
| `PAPER_TRADER` | 1 | Simulated trading only; no live orders |
| `LIVE_TRADER` | 2 | Full live trading including order placement |
| `ADMIN` | 3 | All capabilities including strategy and risk modification |

**`ROLE_HIERARCHY: dict[AgentRole, int]`** — maps each role to its numeric level. Used for `>=` comparisons (e.g. `ROLE_HIERARCHY[role] >= ROLE_HIERARCHY[AgentRole.LIVE_TRADER]`).

**`ROLE_CAPABILITIES: dict[AgentRole, frozenset[str]]`** — maps each role to its default capability set. `ADMIN` uses the sentinel `frozenset({"*"})` (wildcard — grants all capabilities). All other roles use explicit `Capability` string values.

**Helper functions:**

| Function | Returns | Description |
|----------|---------|-------------|
| `has_role_capability(role, capability)` | `bool` | Returns `True` if the role grants the capability, including wildcard `"*"` check |
| `get_role_capabilities(role)` | `frozenset[str]` | Returns the capability frozenset for a role |
| `role_from_string(value)` | `AgentRole` | Case-insensitive string → `AgentRole`; raises `ValueError` on unknown values |

---

### `Capability`, `CapabilityManager` — `capabilities.py`

```python
from agent.permissions import Capability, ALL_CAPABILITIES, CapabilityManager

manager = CapabilityManager(
    session_factory=my_async_sessionmaker,
    redis_client=my_redis,
)
caps = await manager.get_capabilities(agent_id="550e8400-...")
can_trade = await manager.has_capability(agent_id, Capability.CAN_TRADE)
```

**`Capability` (StrEnum):**

| Value | Description |
|-------|-------------|
| `CAN_TRADE` | Place live orders |
| `CAN_READ_PORTFOLIO` | View balances, positions, and PnL |
| `CAN_READ_MARKET` | Fetch prices and candles |
| `CAN_JOURNAL` | Write journal entries and reflections |
| `CAN_BACKTEST` | Create and run backtest sessions |
| `CAN_REPORT` | Generate performance reports |
| `CAN_MODIFY_STRATEGY` | Create or update strategy definitions |
| `CAN_ADJUST_RISK` | Change risk parameters and stop-loss levels |

**`ALL_CAPABILITIES: frozenset[Capability]`** — the complete set of all 8 capabilities.

**Constructor:** `CapabilityManager(session_factory, redis_client=None)`

Resolves effective capabilities by combining role-level grants with per-agent JSONB overrides from `AgentPermissionRepository`. Results are cached in Redis for 5 minutes (key pattern: `agent:permissions:{agent_id}`). If `redis_client` is `None`, the cache is skipped and Postgres is queried on every call.

**Resolution logic:**
1. Check Redis cache — return immediately on hit.
2. Query Postgres for the agent's role and any explicit overrides (`agent_permissions` table).
3. Start with the role's default capabilities.
4. Apply overrides: explicit `true` grants additional capabilities; explicit `false` revokes them (overrides take precedence over role grants).
5. Cache the resolved set in Redis for 5 minutes.

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `get_capabilities(agent_id)` | `frozenset[Capability]` | Resolve full effective capability set; returns empty set on any error (fail-closed) |
| `has_capability(agent_id, capability)` | `bool` | True if `capability` is in the resolved set |
| `grant_capability(agent_id, capability)` | `None` | Upsert an explicit `true` override; invalidates Redis cache |
| `revoke_capability(agent_id, capability)` | `None` | Upsert an explicit `false` override; invalidates Redis cache |
| `set_role(agent_id, role)` | `None` | Update the agent's role in Postgres; invalidates Redis cache |
| `get_role(agent_id)` | `AgentRole` | Fetch the agent's current role from Postgres |

---

### `BudgetManager` — `budget.py`

```python
from agent.permissions import BudgetManager
from agent.models.ecosystem import BudgetCheckResult, BudgetStatus

manager = BudgetManager(
    session_factory=my_async_sessionmaker,
    redis_client=my_redis,
)
result: BudgetCheckResult = await manager.check_and_record(
    agent_id="550e8400-...",
    action="trade",
    trade_value=Decimal("500.00"),
    portfolio_value=Decimal("10000.00"),
)
if not result.allowed:
    print(result.reason)  # e.g. "Daily trade limit reached (50/50)"
```

**Constructor:** `BudgetManager(session_factory, redis_client)`

Tracks four per-agent financial limits using Redis counters. Counters use TTL equal to seconds-until-midnight-UTC, so they auto-reset every day without a scheduled job.

**Four enforced limits (from `_BudgetLimits`):**

| Limit | Description | Default |
|-------|-------------|---------|
| `max_daily_trades` | Maximum number of trades per day | 50 |
| `max_exposure_pct` | Maximum portfolio fraction in open positions | 0.80 (80%) |
| `max_daily_loss_pct` | Maximum daily PnL loss before further trades are blocked | 0.10 (10%) |
| `max_position_size` | Maximum USDT value in a single position | 1000.0 |

Limits are loaded from the `agent_budget_limits` table in Postgres on first use per agent. Postgres is flushed every `_PERSIST_INTERVAL_SECONDS = 300` (5 minutes) to reduce write pressure.

**Redis key patterns:**

| Key | Contents |
|-----|----------|
| `budget:{agent_id}:daily_trades` | Integer counter, TTL = seconds until midnight UTC |
| `budget:{agent_id}:daily_pnl` | Float string, TTL = seconds until midnight UTC |
| `budget:{agent_id}:exposure` | Float string (current exposure fraction), no TTL |
| `budget:{agent_id}:limits` | JSON-serialised `_BudgetLimits`, TTL = 1 hour |

**Key method:**

**`check_and_record(agent_id, action, trade_value=None, portfolio_value=None) -> BudgetCheckResult`**

Atomic check-then-record. Preferred entry point for all budget validation.
- Loads current counters and limits.
- Checks all applicable limits for the action.
- If allowed, increments the relevant counter.
- Returns `BudgetCheckResult(allowed=True/False, reason=str, remaining=dict)`.

A per-agent `asyncio.Lock` prevents TOCTOU races in single-process deployments.

**Other methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `get_status(agent_id)` | `BudgetStatus` | Full snapshot of current counters and limits |
| `record_trade(agent_id, trade_value, pnl=None)` | `None` | Increment trade counter; optionally update daily PnL |
| `update_exposure(agent_id, exposure_value, portfolio_value)` | `None` | Recalculate and store current exposure fraction |
| `reset_daily(agent_id)` | `None` | Force-reset daily counters (admin use; normally handled by TTL) |
| `set_limits(agent_id, limits)` | `None` | Update `_BudgetLimits` for an agent; invalidates Redis cache |

---

### `PermissionEnforcer`, `PermissionDenied` — `enforcement.py`

```python
from agent.permissions import PermissionEnforcer, PermissionDenied

enforcer = PermissionEnforcer(
    capability_manager=capability_manager,
    budget_manager=budget_manager,
    session_factory=my_async_sessionmaker,
)

# Inline check
try:
    await enforcer.check(agent_id, "place_order", trade_value=Decimal("500"))
except PermissionDenied as e:
    print(e.reason)   # "Agent lacks capability: CAN_TRADE"

# Decorator
@enforcer.require(Capability.CAN_TRADE)
async def execute_trade(agent_id: str, symbol: str, quantity: Decimal) -> dict:
    ...
```

**`PermissionDenied`:**

Not a subclass of `TradingPlatformError`. Has attributes:
- `agent_id: str`
- `action: str`
- `reason: str`

**`ACTION_CAPABILITY_MAP: dict[str, Capability]`**

Maps 29 action strings to the `Capability` they require:

| Action | Required Capability |
|--------|---------------------|
| `"place_order"`, `"cancel_order"`, `"modify_order"` | `CAN_TRADE` |
| `"view_balance"`, `"view_positions"`, `"view_pnl"` | `CAN_READ_PORTFOLIO` |
| `"get_price"`, `"get_candles"`, `"get_orderbook"`, `"get_ticker"` | `CAN_READ_MARKET` |
| `"write_journal"`, `"log_reflection"`, `"save_observation"` | `CAN_JOURNAL` |
| `"create_backtest"`, `"run_backtest"`, `"get_backtest_results"` | `CAN_BACKTEST` |
| `"generate_report"`, `"view_performance"` | `CAN_REPORT` |
| `"create_strategy"`, `"update_strategy"`, `"deploy_strategy"` | `CAN_MODIFY_STRATEGY` |
| `"adjust_stop_loss"`, `"adjust_take_profit"`, `"adjust_position_size"`, `"update_risk_params"` | `CAN_ADJUST_RISK` |
| (additional mappings) | (varies) |

**`BUDGET_CHECKED_ACTIONS: frozenset[str]`**

Six financial actions that trigger a `BudgetManager.check_and_record()` call in addition to the capability check: `"place_order"`, `"modify_order"`, `"create_backtest"`, `"run_backtest"`, `"adjust_position_size"`, `"update_risk_params"`.

**`PermissionEnforcer` constructor:**

`PermissionEnforcer(capability_manager, budget_manager, session_factory=None)`

The `session_factory` is optional and only required for audit log persistence. Without it, audit logging is disabled but all checks still function.

**Methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `check(agent_id, action, **kwargs)` | `None` | Check capability + budget; raises `PermissionDenied` on failure; always returns `None` on success |
| `require(capability)` | decorator | Factory that returns an `async def` decorator; wraps functions with an `agent_id` positional or keyword argument |
| `request_escalation(agent_id, description)` | `None` | Create an `AgentFeedback` row with `category="feature_request"`; used when an agent encounters a `PermissionDenied` and needs to surface it to a human |

**Audit logging:**

Denied permission events are buffered in memory and flushed to the `agent_feedback` table either when the buffer reaches 100 entries or every 30 seconds. Allowed events are not persisted (performance). The `session_factory` is required for flushing; if absent, the buffer accumulates silently.

**`require(capability)` decorator:**

```python
@enforcer.require(Capability.CAN_BACKTEST)
async def create_backtest_session(agent_id: str, config: dict) -> dict:
    # Only called if agent has CAN_BACKTEST
    ...
```

The decorated function must have `agent_id` as its first positional argument or as a keyword argument. The decorator extracts it automatically. Raises `PermissionDenied` before calling the wrapped function if the check fails.

---

## Dependency Direction

```
agent.permissions
    │
    ├── src.database.repositories.agent_permission_repo (CapabilityManager)
    ├── src.database.repositories.agent_budget_repo (BudgetManager)
    ├── src.database.repositories.agent_feedback_repo (PermissionEnforcer audit log)
    ├── src.database.models (AgentPermission, AgentBudget, AgentFeedback — lazy imports)
    ├── agent.models.ecosystem (BudgetCheckResult, BudgetStatus)
    └── redis.asyncio (CapabilityManager cache, BudgetManager counters)
```

All `src.database` imports are lazy (inside methods) to keep the module importable without a running database.

## Patterns

- **Fail-closed**: `CapabilityManager.get_capabilities()` returns an empty `frozenset` on any error (Postgres failure, Redis failure, unknown agent). An empty capability set denies all actions. This is intentional — unexpected failures should block trading, not allow it.
- **Override beats role**: In `CapabilityManager`, an explicit `false` override always beats a role grant. This allows revoking a single capability from an admin without changing the role.
- **TTL-based daily reset**: `BudgetManager` uses Redis key TTL (seconds-until-midnight) rather than a scheduled cleanup job. This means budget counters reset automatically at midnight UTC without any Celery task or cron job.
- **Per-agent lock**: `BudgetManager` maintains a per-agent `asyncio.Lock` to prevent TOCTOU races in the check-then-increment flow. This works correctly in a single-process deployment. For multi-process deployments, a Redis-based distributed lock would be needed.
- **Audit buffer batching**: `PermissionEnforcer` batches denied-permission events and flushes them in bulk, rather than writing one DB row per denial. This prevents a misbehaving agent from generating excessive write load.
- **`require()` for route-level protection**: The `@enforcer.require(Capability.X)` decorator pattern is analogous to FastAPI's `Depends()` — declare the required capability at the function definition, not in the body.

## Gotchas

- **`PermissionDenied` is not a `TradingPlatformError`**: It will not be auto-serialized by the global exception handler in `src/main.py`. Catch it explicitly in route handlers or workflow code.
- **Admin wildcard is `{"*"}`, not the full set**: `ROLE_CAPABILITIES[AgentRole.ADMIN]` returns `frozenset({"*"})`. Do not iterate it expecting 8 `Capability` values. Use `has_role_capability(role, cap)` which handles the wildcard check.
- **`check()` kwargs are forwarded to `BudgetManager`**: When calling `enforcer.check(agent_id, "place_order", trade_value=Decimal("500"), portfolio_value=Decimal("10000"))`, the keyword arguments are passed through to `budget_manager.check_and_record()`. Only pass them for budget-checked actions.
- **`set_limits()` affects future sessions only**: Changing limits via `BudgetManager.set_limits()` invalidates the Redis cache and updates Postgres, but does not retroactively change counters already incremented in the current day.
- **Audit flush is not guaranteed on process exit**: The in-memory audit buffer may have unsent entries when the process terminates. Add an explicit `await enforcer.flush_audit_log()` in shutdown hooks for production deployments where audit completeness is required.
- **Redis outage degrades to Postgres-only**: Both `CapabilityManager` and `BudgetManager` fall back to Postgres when Redis is unavailable. This is slower but functionally correct. The 5-minute flush interval means budget counters may be slightly stale after a Redis restart.
- **`role_from_string()` is case-insensitive**: `role_from_string("live_trader")`, `"LIVE_TRADER"`, and `"Live_Trader"` all return `AgentRole.LIVE_TRADER`. Use it when parsing role strings from user input or config files.
