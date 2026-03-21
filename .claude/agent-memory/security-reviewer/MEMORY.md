# Security Reviewer — Memory

## CRITICAL Fixes Applied (2026-03-20)

All four were fixed directly in `agent/permissions/`. Status: RESOLVED.

- **Float precision** (`budget.py`) — `incrbyfloat` was called with `float(decimal)`, causing drift across many trades. Fixed: use `format(decimal, "f")` string instead.
- **TOCTOU race** (`budget.py`, `enforcement.py`) — check and record were separate calls; concurrent requests could both pass the same budget check. Fixed: `check_and_record()` acquires a per-agent `asyncio.Lock` and atomically checks + records in one critical section.
- **Fail-open on dual failure** (`budget.py:_read_counters_from_db`) — when both Redis and Postgres failed, counters returned `(0, 0, 0)`, passing all limits. Fixed: returns sentinel `(sys.maxsize, 999999999999, 999999999999)` so all budget checks deny.
- **Default role grants trade access** (`agent/config.py`, `agent_permission_repo.py`) — default was `paper_trader` (has `CAN_TRADE`). Fixed: changed to `"viewer"` (read-only) in both files.

## HIGH Issues Deferred (permissions review)

Not fixed; deferred by design — fix before promotion to shared/prod infra:

- **HIGH-1** — `grant_capability` / `set_role` accept any UUID as `granted_by` with no privilege check on the grantor. Any caller with access to `CapabilityManager` can escalate any agent to ADMIN. Fix: check grantor role is ADMIN before mutating.
- **HIGH-2** — `asyncio.ensure_future(_maybe_persist)` in `record_trade`/`record_loss` can be cancelled on shutdown, losing the last counter snapshot. Fix: track futures and `await gather()` in `close()`.
- **HIGH-3** — Redis cache at `agent:permissions:{agent_id}` has no auth; write access allows temporary capability elevation for up to 300s (cache TTL). Fix: `requirepass` on Redis + bind to internal Docker network only.
- **HIGH-4** — "allow" audit events are not persisted to DB; only "deny" events are. Post-restart, no durable trail of authorized trades exists. Fix: create `agent_audit_log` table and persist both outcomes.

## HIGH Issues Deferred (strategies review)

- **HIGH-1** — `PPO.load()` uses pickle internally (SB3 `.zip` files). No checksum verification before loading. Impact: malicious model file = arbitrary code execution. Fix: SHA-256 manifest check before `PPO.load`.
- **HIGH-2** — `joblib.load()` for regime classifier has same pickle risk. Fix: checksum verify + payload structure check after load.
- **HIGH-3** — `--api-key` CLI argument in 8 strategy scripts exposes `ak_live_...` keys in process list (`ps aux`) and shell history. Fix: read from env var only; `pydantic-settings` already supports this.

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
