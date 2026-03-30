# Security Auditor — Memory

## Areas Previously Audited

| Area | Date | Outcome |
|------|------|---------|
| `agent/permissions/` (roles, capabilities, budget, enforcement) | 2026-03-20 | 4 CRITICAL fixed; 4 HIGH deferred |
| `agent/strategies/` (rl, evolutionary, regime, risk, ensemble) | 2026-03-20 | 0 CRITICAL; 3 HIGH deferred; overall CONDITIONAL PASS |
| Phase 3 logging: `src/api/middleware/audit.py`, `agent/logging_writer.py`, `src/api/middleware/logging.py`, `sdk/agentexchange/async_client.py`, `agent/tools/rest_tools.py` | 2026-03-21 | 0 CRITICAL; 1 HIGH (unvalidated X-Trace-Id); 3 MEDIUM; 3 LOW; CONDITIONAL PASS |
| R2-01 through R2-08 fix verification (all HIGH recommendations) | 2026-03-23 | 0 CRITICAL; 1 HIGH (R2-04 partial — enforcement.py still routes to agent_feedback not agent_audit_log); 1 MEDIUM (pgAdmin default password); 2 LOW; CONDITIONAL PASS |
| V.0.0.2 deployment changes: `src/config.py`, `src/main.py`, `.github/workflows/deploy.yml`, `.github/workflows/test.yml`, `.env.example`, `src/mcp/tools.py`, `src/api/routes/battles.py`, `src/api/routes/agents.py`, `src/tasks/agent_analytics.py` | 2026-03-30 | 0 CRITICAL; 1 HIGH (no wildcard CORS guard); 2 MEDIUM; 2 LOW; CONDITIONAL PASS |

## Areas NOT Yet Audited (as of 2026-03-21)

- `src/api/routes/` — REST endpoint auth enforcement, input validation
- `src/api/middleware/auth.py` and `rate_limit.py` — auth middleware chain, rate limiting bypass surface
- `src/accounts/` — registration, password hashing, JWT issuance
- `src/order_engine/` — order validation, financial arithmetic
- `src/backtesting/` — sandbox isolation, look-ahead bias guards
- `src/battles/` — agent isolation during battles
- `Frontend/` — XSS surface, API key storage in browser
- `agent/conversation/`, `agent/memory/`, `agent/trading/` — newer ecosystem modules

## Auth Flow (verified)

1. Request arrives with `X-API-Key` header
2. `AuthMiddleware` checks `agents` table first (agent-scoped key)
3. Falls back to `accounts` table (legacy account key)
4. JWT path: `Authorization: Bearer` → account resolved from JWT payload; optional `X-Agent-Id` header scopes to agent
5. WebSocket: `?api_key=` query param; failure closes with code 4401

## OWASP Patterns for This Project

**Already mitigated by framework/architecture:**
- **A03 Injection** — SQLAlchemy ORM used everywhere; no f-string SQL construction found in any reviewed file. `httpx` used for HTTP calls with structured JSON bodies, not string-concatenated query params.
- **A07 XSS** — React/Next.js auto-escapes all rendered output. No `dangerouslySetInnerHTML` patterns found in reviewed code.
- **A02 Cryptographic Failures** — API keys use `secrets.token_urlsafe(48)`; passwords use bcrypt; secrets loaded from env vars / `.env` files.

**Active risk areas (require per-change review):**
- **A01 Broken Access Control** — Agent-scoped operations must check `agent_id` ownership. Permission escalation path (HIGH-1 in permissions review) is the live example.
- **A08 Insecure Deserialization** — `PPO.load()` (SB3/pickle) and `joblib.load()` in `agent/strategies/` are the known risk surface. No SHA-256 verification yet (HIGH deferred).
- **A09 Logging Failures** — Phase 3 partially addressed: `AuditMiddleware` now persists key security events. Remaining gap: X-Trace-Id header not validated before persistence (HIGH). `log_api_call` logs first 200 chars of error response body (INFO).
- **A10 SSRF** — `base_url` / `data_url` CLI args passed to `httpx.AsyncClient` without scheme validation in strategy scripts.

## Rate Limiting Pattern

- Redis key: `rate_limit:{api_key}:{endpoint}:{minute}`
- Operations: `INCR` + `EXPIRE 60` (sliding per-minute window)
- Limit headers returned on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- No rate limiting on `request_escalation` (LOW issue from permissions review)

## R2-04 Remaining Gap (as of 2026-03-23)

`enforcement.py._persist_audit_entries()` still writes to `AgentFeedback` (not `AgentAuditLog`). The `AgentAuditLogRepository` exists but is not wired. Allow events are silently dropped via `continue` on line 438 regardless of the `audit_allow_events` constructor flag. Fix requires: import `AgentAuditLog` + `AgentAuditLogRepository`, map `AuditEntry.result` → `outcome`, persist both outcomes, honor `self._audit_allow_events`.

## CORS Configuration Pattern (verified 2026-03-30)

- `cors_origins` field in `Settings` is a plain `str` (comma-separated); no `@field_validator` prevents wildcard `*`
- `src/main.py` splits on commas and passes list to `CORSMiddleware(allow_origins=_origins, allow_credentials=True)`
- **If `CORS_ORIGINS=*` is set in env, browsers will reject credentialed responses** (RFC violation) — but the server will still send the `*` origin, which is wrong. No server-side guard exists.
- `.env.example` shows only localhost values; production must explicitly set `CORS_ORIGINS` to the real frontend domain.
- `pg_dump` in `deploy.yml` runs inside the container via `docker compose exec -T timescaledb pg_dump -U agentexchange` — no password passed on the command line; relies on PostgreSQL local trust auth (running as the postgres user inside the container). This is standard and correct: no credential exposure in logs.
- `ResourceNotFoundError` does NOT exist in `src/utils/exceptions.py`; replacing it with `HTTPException` was the correct fix. However, the `HTTPException` error format (`{"detail": "..."}`) differs from the platform standard format (`{"error": {"code": ..., "message": ...}}`).

## Passed Checks (stable — no need to re-audit unless code changes)

- Parameterized queries in all DB access (SQLAlchemy ORM)
- No hardcoded secrets in any reviewed file
- UUID format validated before use as DB/cache keys in permission paths
- Redis failure → DB fallback (capability + budget)
- Fail-closed on unexpected exceptions in `check_action` (`has_cap = False`)
- Cache invalidated in `finally` block on all permission mutations
- `eval()` / `exec()` / `__import__` with user data: none found
- `subprocess` with user-supplied arguments: none found
- API keys not present in any log statement in reviewed files
- `LogBatchWriter` deques are bounded (`maxlen=10_000`) — no OOM risk
- `LogBatchWriter` uses `asyncio.Lock` (cooperative) — no deadlock possible in asyncio event loop
- `AuditMiddleware` reads `request.state.account` after response — cannot bypass auth
- DB writes in `AuditMiddleware` and `LogBatchWriter` use ORM `session.add()` — no injection risk

## Key Patterns (Phase 3 Logging)

- **Middleware execution order (with AuditMiddleware):** `LoggingMiddleware → AuthMiddleware → AuditMiddleware → RateLimitMiddleware → route handler`
- **Audit log scoping:** `account_id` (not `agent_id`) — accounts own agents; account is the correct audit boundary
- **IP extraction:** Both `audit.py` and `logging.py` use the same `_client_ip()` — trusts first hop of `X-Forwarded-For` without proxy validation
- **Trace ID format:** Agent generates 16-char hex (`uuid4().hex[:16]`); no server-side format validation on inbound `X-Trace-Id` header (HIGH finding)
- **`audit_log` table:** BIGSERIAL PK (preserves insertion order), JSONB `details`, INET `ip_address` (PostgreSQL validates IP syntax at DB level)
