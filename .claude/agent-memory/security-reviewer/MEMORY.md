# Security Reviewer — Memory

## CRITICAL Fixes Applied (2026-03-20)

All four were fixed directly in `agent/permissions/`. Status: RESOLVED.

- **Float precision** (`budget.py`) — `incrbyfloat` was called with `float(decimal)`, causing drift across many trades. Fixed: use `format(decimal, "f")` string instead.
- **TOCTOU race** (`budget.py`, `enforcement.py`) — check and record were separate calls; concurrent requests could both pass the same budget check. Fixed: `check_and_record()` acquires a per-agent `asyncio.Lock` and atomically checks + records in one critical section.
- **Fail-open on dual failure** (`budget.py:_read_counters_from_db`) — when both Redis and Postgres failed, counters returned `(0, 0, 0)`, passing all limits. Fixed: returns sentinel `(sys.maxsize, 999999999999, 999999999999)` so all budget checks deny.
- **Default role grants trade access** (`agent/config.py`, `agent_permission_repo.py`) — default was `paper_trader` (has `CAN_TRADE`). Fixed: changed to `"viewer"` (read-only) in both files.

## HIGH Issues Deferred (permissions review)

Not fixed; deferred by design — fix before promotion to shared/prod infra:

- **HIGH-1** — RESOLVED (2026-03-23, task R2-01). `grant_capability`, `set_role`, and `revoke_capability` now check `ROLE_HIERARCHY[grantor_role] >= ROLE_HIERARCHY[ADMIN]` before any mutation. Lazy import of `PermissionDenied` from `enforcement.py` avoids circular imports. Fail-closed: unknown grantors (account UUIDs not in agents table) get default `viewer` role → denied. `revoke_capability` takes `granted_by: str | None = None`; `None` raises immediately. Existing test `test_revoke_sets_capability_false_in_db` tests old insecure behavior and will fail — needs update.
- **HIGH-2** — RESOLVED (2026-03-23, task R2-02). `asyncio.ensure_future` replaced with `asyncio.create_task` + tracking in `_pending_persists` set. `BudgetManager.close()` awaits all pending tasks via `asyncio.gather(return_exceptions=True)`. `AgentServer._shutdown()` calls `await self._budget_manager.close()`. `AgentServer` now holds a shared `_budget_manager` instance initialized in `_init_dependencies`.
- **HIGH-3** — RESOLVED (2026-03-23, task R2-03). `--requirepass` added to Redis command in `docker-compose.yml`. Host port binding removed entirely (Memurai occupied 6379 locally; no host exposure is stronger than 127.0.0.1 binding). All 5 consumer services verified healthy. `REDIS_PASSWORD` in `.env`, `REDIS_URL` updated to `redis://:password@redis:6379/0`.
- **HIGH-4** — "allow" audit events are not persisted to DB; only "deny" events are. Post-restart, no durable trail of authorized trades exists. Fix: create `agent_audit_log` table and persist both outcomes.

## HIGH Issues Resolved (strategies review, 2026-03-23)

- **HIGH-1** — RESOLVED (task R2-05). All four `PPO.load()` call sites already had `verify_checksum()` before loading. Added `strict: bool = True` parameter to `verify_checksum()` in `agent/strategies/checksum.py` — missing sidecar now raises `SecurityError` in strict mode instead of logging a warning. Default is `strict=True`.
- **HIGH-2** — RESOLVED (task R2-06). `agent/strategies/regime/classifier.py` already had checksum verification and full payload structure validation (checks for `model`, `label_encoder`, `label_decoder`, `feature_names`, `seed`, `backend` keys — more thorough than the task spec's `"classifier"` key check).
- **HIGH-3** — RESOLVED (task R2-07). Confirmed zero `--api-key` argparse definitions in any Python source file (`grep -rn "add_argument.*--api" agent/ src/ scripts/ --include="*.py"` returns empty). `classifier.py` already reads from `os.environ.get("PLATFORM_API_KEY", "")`. Stale CLAUDE.md doc examples updated.

## Auth Patterns in This Project

- API key format: `ak_live_<token>` (generated via `secrets.token_urlsafe(48)`)
- Auth resolution: `X-API-Key` header → check `agents` table first → fallback to `accounts` table
- JWT auth: `Authorization: Bearer <jwt>` → resolves account; agent context via `X-Agent-Id` header
- WebSocket auth: `?api_key=ak_live_...` query param (close code 4401 on failure)
- Permissions: stored in `agent_permissions` table; cached in Redis at `agent:permissions:{agent_id}` (TTL 300s)
- Budget counters: Redis `INCR`/`INCRBYFLOAT` keys, backed by Postgres for persistence

## Known Sensitive Areas

- `agent/permissions/` — budget enforcement, capability checks, audit log
- `agent/strategies/rl/`, `agent/strategies/regime/`, `agent/strategies/ensemble/` — model deserialization
- `src/api/middleware/` — auth and rate limiting middleware
- `src/order_engine/` — order execution (financial integrity)
- `src/risk/` — circuit breaker, position limits (fail-closed required)
- [project_platform_context.md](project_platform_context.md) — Platform is a simulated crypto exchange with multi-agent architecture; agent strategies layer operates above the platform API
- [findings_phase2_risk.md](findings_phase2_risk.md) — Phase 2 risk management security review findings (Tasks 16-21): key patterns found and issues fixed
