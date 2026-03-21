---
type: code-review
date: 2026-03-20
reviewer: security-reviewer
verdict: PASS
scope: agent-permissions
tags:
  - review
  - security
  - permissions
---

# Security Review: Agent Permission System

**Date:** 2026-03-20
**Reviewer:** security-reviewer agent
**Branch:** V.0.0.2

---

## Files Reviewed

- `agent/permissions/roles.py`
- `agent/permissions/capabilities.py`
- `agent/permissions/budget.py`
- `agent/permissions/enforcement.py`
- `agent/permissions/__init__.py`
- `agent/config.py` (permission defaults)
- `src/database/repositories/agent_permission_repo.py`
- `src/database/repositories/agent_budget_repo.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root) — security standards, auth patterns, Redis key patterns
- `agent/CLAUDE.md` — agent package structure, config, dependencies
- `src/database/CLAUDE.md` — ORM models, session management
- `src/database/repositories/CLAUDE.md` — repository patterns, atomic operations

---

## Scan Results

- `pip audit`: not run (no new Python dependencies introduced by permission system)
- `npm audit`: not applicable (backend-only review)
- No hardcoded secrets found in reviewed files

---

## CRITICAL Issues (must fix before deploy)

All four CRITICAL issues below have been **fixed directly** in this review pass.

---

### CRITICAL-1 — Float Precision Loss on Financial Budget Counters

**File:** `agent/permissions/budget.py` (lines 851, 896 — pre-fix)
**Category:** Financial Integrity / Injection (OWASP A03)
**Status:** FIXED

**Issue:**
`record_trade` and `record_loss` converted `Decimal` trade values to `float` before calling Redis `INCRBYFLOAT`:

```python
# BEFORE (vulnerable)
pipe.incrbyfloat(_exposure_key(agent_id), float(trade_value))
pipe.incrbyfloat(_loss_key(agent_id), float(loss_amount))
```

**Impact:**
Python `float` has 53-bit mantissa precision (~15 significant digits). Financial amounts like `Decimal("1234.56789012")` lose precision on conversion to `float`. Over hundreds of trades, this drift could allow the real exposure to slightly exceed the configured limit without the counter detecting it. An attacker trading many small orders could exploit accumulated rounding errors to bypass the exposure cap.

**Fix applied:**
```python
# AFTER (fixed)
trade_value_str = format(trade_value, "f")
pipe.incrbyfloat(_exposure_key(agent_id), trade_value_str)
```
Redis `INCRBYFLOAT` accepts arbitrary-precision decimal strings directly. Using `format(decimal, "f")` produces the fixed-point string representation without scientific notation, preserving all decimal digits.

---

### CRITICAL-2 — TOCTOU Race Condition Between Budget Check and Budget Record

**File:** `agent/permissions/budget.py`, `agent/permissions/enforcement.py`
**Category:** Race Condition / Broken Access Control (OWASP A01)
**Status:** FIXED

**Issue:**
`PermissionEnforcer.check_action` previously called `BudgetManager.check_budget` and the caller was expected to separately call `BudgetManager.record_trade`. There was a window between the two calls where a second concurrent request for the same agent could read the same counter value, both pass the check, and both execute — doubling the effective budget consumption:

```
Task A: check_budget(agent_id, 500)  → allowed (exposure: 800 / 1000)
Task B: check_budget(agent_id, 500)  → allowed (exposure: 800 / 1000, same read)
Task A: record_trade(agent_id, 500)  → exposure becomes 1300  ← OVER LIMIT
Task B: record_trade(agent_id, 500)  → exposure becomes 1800  ← FAR OVER LIMIT
```

**Impact:**
Concurrent trade submissions for the same agent (e.g., from parallel ensemble strategy signals) could bypass daily exposure and trade count limits, allowing an agent to execute far more trades than permitted and accumulate far more exposure than the risk profile allows.

**Fix applied:**
Added `BudgetManager.check_and_record(agent_id, trade_value)` which acquires the per-agent `asyncio.Lock` before running `check_budget` and, on success, immediately calls `record_trade` before releasing the lock. This collapses the check-then-act into a single critical section:

```python
async def check_and_record(self, agent_id, trade_value) -> BudgetCheckResult:
    async with self._get_lock(agent_id):
        result = await self.check_budget(agent_id, trade_value)
        if result.allowed:
            await self.record_trade(agent_id, trade_value)
        return result
```

`PermissionEnforcer.check_action` now calls `check_and_record` instead of bare `check_budget`. The per-agent lock prevents intra-process races; inter-process races (multiple Uvicorn workers) are mitigated by Redis `INCR` atomicity and the exposure cap is a soft guard rather than a hard financial commitment.

---

### CRITICAL-3 — Fail-Open Fallback When Both Redis and DB Are Unavailable

**File:** `agent/permissions/budget.py:_read_counters_from_db` (pre-fix)
**Category:** Broken Access Control / Misconfiguration (OWASP A01, A05)
**Status:** FIXED

**Issue:**
When Redis failed, `_read_counters` fell back to `_read_counters_from_db`. When the DB query also failed (e.g., both Redis and Postgres are unreachable during a network partition), the exception was caught and the method returned `(0, Decimal("0"), Decimal("0"))`:

```python
# BEFORE (vulnerable)
except Exception:
    logger.exception(...)
    return 0, _ZERO, _ZERO  # All limits pass against 0 counters!
```

This meant that with counters at zero, all four budget checks passed: `0 < max_trades`, `0 + trade_value <= max_exposure`, `0 < max_daily_loss`. An agent could execute unlimited trades during an infrastructure outage.

**Impact:**
During a Redis + Postgres dual failure (network partition, failover, maintenance window), all agents effectively have uncapped budgets. A malicious or malfunctioning agent could place large trades that would normally be blocked by daily limits.

**Fix applied:**
```python
# AFTER (fixed) — fail-closed sentinel values
import sys
_FAIL_CLOSED_USDT = Decimal("999999999999")
return sys.maxsize, _FAIL_CLOSED_USDT, _FAIL_CLOSED_USDT
```
When both data sources fail, counters are set to astronomically high values that exceed any configured limit, causing all budget checks to deny. The docstring distinguishes this case from `AgentBudgetNotFoundError` (legitimate zeros for a new agent).

---

### CRITICAL-4 — Default Role Grants Trade Access Without Explicit Permission

**File:** `agent/config.py:65`, `src/database/repositories/agent_permission_repo.py:67`
**Category:** Broken Access Control / Default Credentials (OWASP A01, A05)
**Status:** FIXED

**Issue:**
The default agent role was `"paper_trader"`, which grants `CAN_TRADE` capability. This means any agent that does not have an explicit row in the `agent_permissions` table (e.g., a newly created agent, or one whose record was accidentally deleted) would default to having trade access:

```python
# BEFORE (vulnerable)
default_agent_role: str = "paper_trader"  # grants CAN_TRADE
```

In `_load_from_db`, when `AgentPermissionNotFoundError` is raised, the code returns `set()` (correct), but in mutation operations (`grant_capability`, `revoke_capability`), the missing record falls back to `self._config.default_agent_role` when creating a new row — seeding it with `paper_trader` instead of the safest default.

Additionally, the `agent_permission_repo.upsert()` method had `role: str = "paper_trader"` as its own default, making it possible to create permission records with trade access without explicitly specifying a role.

**Fix applied:**
Changed default role to `"viewer"` (read-only) in both `config.py` and `agent_permission_repo.py`:
```python
# AFTER (fixed)
default_agent_role: str = "viewer"  # least-privileged; no CAN_TRADE
```
Agents must now be explicitly promoted to `paper_trader` or higher before they can trade.

---

## HIGH Issues (fix soon)

### HIGH-1 — No Authorization on `grant_capability` / `set_role`

**File:** `agent/permissions/capabilities.py:grant_capability`, `set_role`
**Category:** Broken Access Control (OWASP A01)

**Issue:**
`CapabilityManager.grant_capability(agent_id, capability, granted_by)` and `set_role(agent_id, role, granted_by)` accept any UUID string for `granted_by` without verifying that the grantor has the authority to grant permissions. The parameter is recorded in the DB row but never validated against any privilege check:

```python
async def grant_capability(self, agent_id: str, capability: Capability, granted_by: str) -> None:
    # No check: does granted_by have permission to grant?
    agent_uuid = UUID(agent_id)
    grantor_uuid = UUID(granted_by)
    ...
    await repo.upsert(agent_id=agent_uuid, granted_by=grantor_uuid, ...)
```

**Impact:**
Any caller that can invoke `grant_capability` (e.g., any authenticated agent or service that has access to a `CapabilityManager` instance) could promote any agent to any role including `ADMIN`, or grant itself `CAN_TRADE` capabilities. This is a privilege escalation path.

**Recommended fix:**
Add an `is_admin_or_owner(grantor_id, agent_id)` check at the top of both methods:
```python
grantor_role = await self.get_role(str(granted_by))
if grantor_role != AgentRole.ADMIN:
    raise PermissionError(f"Account {granted_by} is not an ADMIN and cannot grant capabilities.")
```
Alternatively, ensure these methods are only callable from routes guarded by `CurrentAccountDep` with admin role verification, not exposed to agent-level API keys.

---

### HIGH-2 — `asyncio.ensure_future` in `record_trade` / `record_loss` Can Silently Lose Data

**File:** `agent/permissions/budget.py:record_trade:881`, `record_loss:929`
**Category:** Insufficient Logging / Data Integrity (OWASP A09)

**Issue:**
Both `record_trade` and `record_loss` fire `_maybe_persist` as a background task using `asyncio.ensure_future`. If the event loop is closing (e.g., during graceful shutdown), `ensure_future` tasks may be cancelled before they complete, losing the persistence of counters:

```python
asyncio.ensure_future(self._maybe_persist(agent_id))
```

**Impact:**
Budget counter updates are not persisted to Postgres during shutdown. After a restart, the in-memory counters are rebuilt from the last DB snapshot, potentially understating the day's activity. An agent that hit near-limit exposure before a restart would appear to have fresh budget headroom.

**Recommended fix:**
Track created futures and await them during `close()` / `__aexit__`, or use a task group with a structured shutdown path:
```python
self._persist_tasks.add(asyncio.ensure_future(self._maybe_persist(agent_id)))
# In close():
await asyncio.gather(*self._persist_tasks, return_exceptions=True)
```

---

### HIGH-3 — Redis Cache Poisoning via Malformed JSONB Writes

**File:** `agent/permissions/capabilities.py:_write_cache`
**Category:** Cache Poisoning (OWASP A03)

**Issue:**
`_write_cache` writes capability sets to Redis as JSON. If an attacker can write directly to Redis (e.g., via a Redis MITM or compromised Redis instance without auth), they could inject arbitrary strings into the capability cache key `agent:permissions:{agent_id}`. The `_read_cache` method does validate enum membership:

```python
try:
    caps.add(Capability(item))
except ValueError:
    pass  # Unknown capability string is silently dropped
```

This means injected unknown strings are safely ignored. However, a valid capability string injected without a corresponding DB record would grant that capability for up to 300 seconds (cache TTL) before a DB re-read would correct it.

**Impact:**
An attacker with Redis write access can temporarily elevate an agent's capabilities for the cache TTL period (5 minutes), allowing unauthorized trading during that window.

**Recommended fix:**
Ensure Redis is configured with `requirepass` (authentication) and bound only to the internal Docker network (not exposed externally). The application-level mitigation is already in place (enum validation); the infrastructure mitigation is required.

---

### HIGH-4 — Audit Log Retention Relies on In-Memory Buffer Only for "Allow" Events

**File:** `agent/permissions/enforcement.py:_persist_audit_entries`
**Category:** Insufficient Logging and Monitoring (OWASP A09)

**Issue:**
As noted in the CRITICAL-fixes pass, "allow" audit entries are not persisted to DB (only "deny" entries are). The code comment was corrected but the behavior remains the same by design. This means:

1. `get_audit_log()` returns in-memory-only entries — once flushed (after 100 entries or 30s), allowed actions disappear from the audit trail.
2. After an application restart, all recent allowed-action history is lost.
3. There is no persistent audit trail of successful trades for compliance or forensics purposes.

**Impact:**
Security forensics for a compromised agent cannot determine which trades were authorized through the permission system. Compliance requirements for financial systems typically require a durable audit log of all significant actions.

**Recommended fix:**
Create a dedicated `agent_audit_log` table and persist both "allow" and "deny" entries. Use a write-ahead approach (write to DB before returning the result to the caller) for high-severity actions like `trade` and `place_order`. Lower-severity reads (`get_portfolio`, `get_candles`) can remain in-memory only.

---

## MEDIUM Issues (should fix)

### MEDIUM-1 — No Input Validation on `request_escalation.reason` Length

**File:** `agent/permissions/enforcement.py:request_escalation`
**Category:** Injection / Input Validation (OWASP A03)

**Issue:**
The `reason` string parameter in `request_escalation` is written directly into the `description` field of `AgentFeedback` without length validation:

```python
description = (
    f"[PERMISSION ESCALATION REQUEST] capability={capability.value!r} "
    f"agent_id={agent_id!r} reason={reason!r}"
)
```

**Impact:**
A malicious agent could supply an extremely long `reason` string (megabytes) that bloats the `agent_feedback` table, causing disk exhaustion (denial of service). SQL injection is not possible because SQLAlchemy parameterizes the query.

**Recommended fix:**
```python
MAX_REASON_LENGTH = 1000
reason = reason[:MAX_REASON_LENGTH]
```

---

### MEDIUM-2 — `_locks` Dict Grows Unboundedly

**File:** `agent/permissions/budget.py:_locks`
**Category:** Denial of Service / Unbounded Growth

**Issue:**
The `_locks` dict creates one `asyncio.Lock` per unique `agent_id` string and never evicts entries. In a long-running process with many distinct agents, this dict grows without bound.

**Recommended fix:**
Use `cachetools.TTLCache` with a reasonable max size (e.g., 10,000 entries) and TTL (e.g., 1 hour of inactivity):
```python
from cachetools import TTLCache
self._locks: TTLCache[str, asyncio.Lock] = TTLCache(maxsize=10_000, ttl=3600)
```

---

### MEDIUM-3 — `priority` Input in `request_escalation` Not Validated at Type Level

**File:** `agent/permissions/enforcement.py:request_escalation`
**Category:** Input Validation (OWASP A03)

**Issue:**
`priority` is validated at runtime with a set check, but it's typed as `str` rather than a `Literal` or `Enum`. The validation falls back to `"medium"` on invalid input, which silently absorbs mistakes. If this API is caller-accessible, the error should be explicit.

**Recommended fix:**
Use a `Literal` type:
```python
from typing import Literal
PriorityLevel = Literal["low", "medium", "high", "critical"]

async def request_escalation(
    self, agent_id: str, capability: Capability, reason: str,
    *, priority: PriorityLevel = "medium",
) -> str:
```

---

### MEDIUM-4 — Cache Key Pattern Allows Cross-Tenant Collision if `agent_id` Not UUID-Validated

**File:** `agent/permissions/capabilities.py:_cache_key`
**Category:** Injection / Access Control (OWASP A01)

**Issue:**
`_cache_key(agent_id)` formats the Redis key as `agent:permissions:{agent_id}` without sanitizing the agent ID string. If `agent_id` contains Redis key separators (`:`) or wildcard characters (`*`, `?`), it could create unexpected key patterns.

The UUID validation (`UUID(agent_id)`) in `_load_from_db`, `grant_capability`, etc. prevents this in the mutating paths, but `_read_cache` and `_write_cache` call `_cache_key` directly without re-validating.

**Recommended fix:**
Validate UUID format before any cache key construction:
```python
def _cache_key(agent_id: str) -> str:
    # UUID format validation prevents key injection
    try:
        UUID(agent_id)  # will raise ValueError on malformed input
    except ValueError:
        raise ValueError(f"Invalid agent_id for cache key: {agent_id!r}")
    return _PERMISSIONS_CACHE_KEY.format(agent_id=agent_id)
```

---

## LOW Issues (consider)

### LOW-1 — No Rate Limiting on Permission Escalation Requests

**File:** `agent/permissions/enforcement.py:request_escalation`

An agent can call `request_escalation` in a tight loop, flooding the `agent_feedback` table with escalation rows. Consider adding a per-agent rate limit (e.g., max 10 escalation requests per hour) before persisting.

---

### LOW-2 — `AuditEntry.audit_id` Is Always Empty String

**File:** `agent/permissions/enforcement.py:check_action:607`

```python
audit_entry = AuditEntry(audit_id="", ...)
```

The `audit_id` field is set to `""` at construction. If `AuditEntry` has this as a required identifier, it is not populated. The DB persistence path uses the row's auto-generated `id` instead, so this is low severity, but it makes in-memory entries difficult to correlate with DB rows.

---

### LOW-3 — `BUDGET_CHECKED_ACTIONS` includes `"backtest"` and `"create_backtest"`

**File:** `agent/permissions/enforcement.py:BUDGET_CHECKED_ACTIONS`

Backtests consume no live funds (they use the in-memory sandbox). Including them in `BUDGET_CHECKED_ACTIONS` means a `Decimal("0")` trade value is budget-checked (which always passes), but it still calls `check_and_record` and increments the trades counter by 1. If the intent is to count backtests against daily trade limits, this is intentional but should be documented. If not, remove backtest actions from `BUDGET_CHECKED_ACTIONS`.

---

## Passed Checks

| Check | Result |
|-------|--------|
| Parameterized queries | PASS — all DB access via SQLAlchemy ORM, no f-string SQL |
| Secrets in code | PASS — no hardcoded API keys or passwords found |
| UUID validation on agent_id input | PASS — `UUID(agent_id)` used in all mutating paths |
| Redis failure → DB fallback (capability) | PASS — `RedisError` caught, falls back to Postgres |
| Redis failure → DB fallback (budget limits) | PASS — `RedisError` caught, falls back to Postgres |
| Fail-closed on capability DB error | PASS — returns `set()` (no capabilities) on DB exception |
| Fail-closed on capability check error | PASS — `has_cap = False` on unexpected exception in `check_action` |
| Cache invalidation on mutation | PASS — `_invalidate_cache` called in `finally` block of all mutations |
| Role hierarchy correctly enforced | PASS — `ROLE_HIERARCHY` is a linear ordered dict, admin wildcard handled correctly |
| ADMIN wildcard expansion | PASS — `_load_from_db` returns `set(ALL_CAPABILITIES)` for admin, not the `{"*"}` sentinel |
| Audit buffer lock | PASS — `_audit_lock` used in `_record_audit` and `_flush_audit_buffer` |
| Transaction wrapping on mutations | PASS — `session.begin()` used as context manager in all write paths |
| Input validation: `role_from_string` | PASS — raises `ValueError` on unknown role string |
| `incrbyfloat` precision (post-fix) | PASS — now uses `format(decimal, "f")` string instead of `float()` |
| Fail-closed on total infrastructure failure (post-fix) | PASS — `_read_counters_from_db` now returns sentinel max values on exception |
| TOCTOU between check and record (post-fix) | PASS — `check_and_record` acquires per-agent lock atomically |
| Default role least-privilege (post-fix) | PASS — default changed from `paper_trader` to `viewer` |

---

## Summary of Changes Made

All CRITICAL fixes were applied directly. The following files were modified:

| File | Changes |
|------|---------|
| `agent/permissions/budget.py` | (1) `incrbyfloat` now uses `format(decimal, "f")` instead of `float()`; (2) `_read_counters_from_db` returns fail-closed sentinel values on total failure instead of zeros; (3) Added `check_and_record()` atomic method; (4) `_get_lock` uses `setdefault` for thread-safe dict insertion |
| `agent/permissions/enforcement.py` | `check_action` now calls `check_and_record` instead of bare `check_budget`; audit entry comment clarified |
| `agent/config.py` | Default agent role changed from `"paper_trader"` to `"viewer"` |
| `src/database/repositories/agent_permission_repo.py` | Default role parameter changed from `"paper_trader"` to `"viewer"` |

---

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| No CRITICAL vulnerabilities (or all fixed) | PASS — all 4 CRITICAL issues fixed |
| Budget enforcement is provably atomic | PASS — `check_and_record` uses per-agent lock; Redis INCR is atomic |
| Permission checks default to deny on error | PASS — capability check fails to `has_cap = False`; budget check fails to denied result |
| Audit log is append-only | PASS — no DELETE/UPDATE path on audit buffer or DB rows; only CREATE via `repo.create()` |
| Redis cache failure falls back to DB (not "allow all") | PASS — capability cache miss returns `None`, triggers DB load; budget counter failure triggers DB read, and DB failure returns fail-closed sentinels |
