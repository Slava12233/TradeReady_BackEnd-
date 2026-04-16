# Security Audit Report — Task 06

**Scope:** Customer-facing API surface: authentication, authorization, injection prevention, rate limiting, data exposure, CORS, secrets management, WebSocket security, and dependency health.  
**Date:** 2026-04-15  
**Auditor:** security-auditor agent  
**CLAUDE.md files consulted:** `CLAUDE.md` (root), `src/api/middleware/CLAUDE.md`, `src/accounts/CLAUDE.md`, `src/api/CLAUDE.md`, `src/api/routes/CLAUDE.md`, `src/api/schemas/CLAUDE.md`, `src/backtesting/CLAUDE.md`, `src/database/CLAUDE.md`, `src/database/repositories/CLAUDE.md`, `src/api/websocket/CLAUDE.md`, `src/agents/CLAUDE.md`

**Files audited directly:**
- `src/api/middleware/auth.py`
- `src/api/middleware/rate_limit.py`
- `src/api/middleware/audit.py`
- `src/accounts/auth.py`
- `src/accounts/service.py`
- `src/agents/service.py`
- `src/config.py`
- `src/main.py`
- `src/api/routes/auth.py`
- `src/api/routes/trading.py`
- `src/api/routes/account.py`
- `src/api/routes/agents.py` (ownership-check lines)
- `src/api/routes/waitlist.py`
- `src/api/schemas/auth.py`
- `src/api/websocket/manager.py`
- `src/api/websocket/channels.py`
- `src/backtesting/data_replayer.py`
- `.gitignore`
- `.env.example`
- `requirements.txt`

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 3 |
| LOW | 4 |

**No CRITICAL findings.**  
**One HIGH finding is a launch blocker — see Finding H-1 below.**

---

## OWASP Top 10 Assessment

| # | Category | Status | Notes |
|---|----------|--------|-------|
| A01 | Broken Access Control | **PARTIAL** | H-1: JWT agent scope not ownership-checked. All other ownership checks present. |
| A02 | Cryptographic Failures | PASS | bcrypt 12 rounds, `secrets.token_urlsafe(48)`, HS256 JWT, 32+ char secret enforced. |
| A03 | Injection | PASS | SQLAlchemy ORM throughout; `text(f"...")` in DataReplayer uses only server-side constants. |
| A04 | Insecure Design | PASS | No design-level flaws found; threat model appropriate for simulated exchange. |
| A05 | Security Misconfiguration | PASS | CORS wildcard now blocked by validator. Exception handler returns generic 500. |
| A06 | Vulnerable Components | PASS | All pinned or recent versions; no known CVEs in pinned deps at audit date. |
| A07 | XSS | N/A | React/Next.js auto-escapes; no `dangerouslySetInnerHTML` found. |
| A08 | Insecure Deserialization | DEFERRED | `PPO.load()`/`joblib.load()` in `agent/strategies/` — known open issue, not customer-facing. |
| A09 | Logging Failures | PARTIAL | M-1: auth endpoints not rate-limited; M-3: X-Trace-Id unvalidated (prior open finding). |
| A10 | SSRF | PASS | Webhook SSRF resolved in V.0.0.3. No other SSRF surfaces found. |

---

## Platform-Specific Security Table

| Check | Status | Notes |
|-------|--------|-------|
| API key format + length validation | PASS | `ak_live_` prefix + 64-char length enforced in `authenticate_api_key` |
| API key stored as plaintext + bcrypt hash | PASS | O(1) lookup pattern; documented design decision |
| API secret never stored plaintext | PASS | Only bcrypt hash persisted |
| Bcrypt on event loop | PASS | All bcrypt calls dispatched via `run_in_executor` |
| JWT claims validated | PASS | `sub`, `iat`, `exp` required; `sub` parsed as UUID |
| JWT secret length | PASS | Minimum 32 chars enforced by `@field_validator` |
| JWT expiry | PASS | Default 1h; max 168h (configurable) |
| Agent isolation — API key path | PASS | Agent resolved by DB lookup on `agents.api_key`; account resolved from `agent.account_id` |
| Agent isolation — JWT path | **FAIL** | `X-Agent-Id` header resolved without ownership check (H-1) |
| Agent isolation — agents.py mutations | PASS | All mutations check `agent.account_id != account.id` |
| Agent isolation — trading queries | PARTIAL | Repos filter by `account_id + agent_id` (safe); JWT path can inject foreign agent_id (H-1) |
| CORS wildcard prevention | PASS | `@field_validator` raises `ValueError` if `*` in origins |
| CORS credentials | PASS | `allow_credentials=True` with explicit origins only |
| Registration rate limiting | **FAIL** | No rate limiting on `/api/v1/auth/*` (M-1) |
| Login rate limiting | **FAIL** | No rate limiting on `/api/v1/auth/*` (M-1) |
| Error responses — secret leakage | PASS | Generic 500 handler; no stack traces in responses |
| SQL injection | PASS | No user data interpolated into SQL strings |
| Secrets in source / git | PASS | `.env` in `.gitignore`; no hardcoded credentials found |
| Default credentials in `.env.example` | PASS (noted) | `change_me` placeholders present — operator must replace before production (L-2) |
| WebSocket auth — close code | PASS | Close code 4401 on failure |
| WebSocket auth — account ownership | PASS | `accounts` table lookup; status checked |
| WebSocket agent isolation | PARTIAL | WS resolves account only; no agent scoping on private channels (M-2) |
| Prometheus `/metrics` endpoint | PASS | Publicly accessible (intended scrape endpoint) |
| Dependency dangerous patterns | PASS | No `eval`, `exec`, `pickle.loads`, `subprocess`, `yaml.load` with user data |
| Password max length | MEDIUM | No upper bound on password field — bcrypt truncates silently at 72 bytes (M-3 note) |

---

## Findings

### [HIGH] H-1: JWT Agent Scope Bypass — Missing Ownership Check on X-Agent-Id

- **File:** `src/api/middleware/auth.py:439`
- **Category:** 3.4 Agent Isolation Violations / 3.2 Auth Bypass Paths
- **Description:** The `get_current_agent` dependency, when authenticating via JWT (`Authorization: Bearer`), resolves the agent from the `X-Agent-Id` request header by calling `agent_repo.get_by_id(agent_uuid)` — which is a plain lookup by UUID with no verification that the returned agent belongs to the authenticated account. A JWT-authenticated attacker who knows (or guesses) another account's agent UUID can set `X-Agent-Id: <victim_agent_uuid>` on any request to scope their session to that agent.

  The relevant code path:
  ```python
  # auth.py line 435-439
  session_factory = get_session_factory()
  async with session_factory() as session:
      agent_repo = AgentRepository(session)
      try:
          return await agent_repo.get_by_id(agent_uuid)  # no ownership check
  ```

  This differs from the API-key path, where `_resolve_account_from_api_key` correctly resolves the agent by its API key and then verifies `agent.account_id` matches the owning account.

- **Impact and scope:** After the `get_current_agent` dependency returns a foreign agent, all trading route handlers extract `agent_id = agent.id if agent is not None else None` and pass it to repository queries. The affected data paths are:

  1. **Order listing / trade history read (cross-agent data leak):** `order_repo.list_by_account(account.id, agent_id=<foreign>)` filters by BOTH `account_id` AND `agent_id`. Since the foreign agent's `account_id` differs from `account.id`, this query returns zero rows — no cross-account order data is exposed. The same holds for `trade_repo.list_by_account`. The JOIN predicate inadvertently provides a second defense layer.

  2. **Single order read (`GET /trade/order/{id}`):** `order_repo.get_by_id(order_id, account_id=account.id)` enforces ownership via `account_id`. If the order doesn't belong to the authenticated account, it raises `OrderNotFoundError`. Safe.

  3. **Order placement (`POST /trade/order`):** `engine.place_order(account.id, request, agent_id=<foreign>)`. The order is written with both `account_id=account.id` (the attacker's account) AND `agent_id=<foreign agent's id>`. This creates an order **attributed to a foreign agent** but charged to the attacker's balance. This is the most meaningful risk: the attacker can plant orders under another account's agent identity — the foreign agent's order history and trade metrics would be polluted, and risk controls (per-agent open order count, circuit breaker) would be applied against the wrong agent's counters.

  4. **Cancel all open orders (`DELETE /trade/orders/open`):** `order_repo.list_open_by_agent(agent_id)` fetches orders **only by agent_id, without account_id filter**. If the attacker passes a foreign agent_id, this lists all that agent's open orders across all accounts. The subsequent `engine.cancel_all_orders(account.id, agent_id=agent_id)` may then cancel the foreign agent's orders (needs confirmation based on engine internals, but the risk exists).

- **Evidence:**
  ```python
  # src/api/middleware/auth.py lines 424-441
  agent_id_raw = request.headers.get("X-Agent-Id", "").strip()
  if agent_id_raw:
      try:
          agent_uuid = _UUID(agent_id_raw)
      except ValueError:
          return None
      session_factory = get_session_factory()
      async with session_factory() as session:
          agent_repo = AgentRepository(session)
          try:
              return await agent_repo.get_by_id(agent_uuid)  # ← no ownership check
          except AgentNotFoundError:
              return None
  ```

- **Recommendation:** After `agent_repo.get_by_id(agent_uuid)` returns, add an ownership check:
  ```python
  agent = await agent_repo.get_by_id(agent_uuid)
  # Resolve account from JWT token (already on request.state)
  account = getattr(request.state, "account", None)
  if account is not None and agent.account_id != account.id:
      return None  # reject cross-account agent scoping
  return agent
  ```
  The `request.state.account` is set by `AuthMiddleware` before this dependency runs (middleware order: Auth → AuditMiddleware → RateLimit → route), so it is available here. This single-line check closes all variants of the finding.

**LAUNCH BLOCKER — fix before public release.**

---

### [MEDIUM] M-1: No Rate Limiting on Authentication Endpoints

- **File:** `src/api/middleware/rate_limit.py:70-77` and `src/api/routes/auth.py`
- **Category:** 3.5 Rate Limit Coverage
- **Description:** The rate limiter's `_PUBLIC_PREFIXES` list includes `/api/v1/auth/`, which causes `_is_public_path()` to return `True` for all auth endpoints. Combined with the fact that unauthenticated requests have no `account` on `request.state` (which is the second bypass condition), neither registration nor login is ever rate-limited. An attacker can:
  1. Flood `POST /api/v1/auth/register` to exhaust database connections, send bcrypt CPU load to 100%, or fill the accounts table with garbage.
  2. Brute-force `POST /api/v1/auth/user-login` (email/password) without any throttle. The endpoint is designed for human users who use weak passwords.
  3. Brute-force `POST /api/v1/auth/login` (API key + secret) — less practical given 64-char random keys, but not impossible for leaked partial keys.
  4. Enumerate which emails are registered via timing differences between "invalid email" and "wrong password" responses. (The current implementation returns `"Invalid email or password."` for both, partially mitigating this, but timing differences remain from the DB lookup on the email path.)

  The waitlist endpoint `POST /api/v1/waitlist/subscribe` also has no rate limiting and is unauthenticated.

- **Impact:** Account enumeration, brute-force login, bcrypt CPU exhaustion, DB connection pool saturation.
- **Evidence:**
  ```python
  # rate_limit.py lines 70-77
  _PUBLIC_PREFIXES: Final[tuple[str, ...]] = (
      "/api/v1/auth/",   # ← all auth endpoints bypass rate limiting
      "/health",
      "/docs",
      "/redoc",
      "/openapi.json",
      "/metrics",
  )
  ```
- **Recommendation:** Implement IP-based rate limiting for public auth endpoints. Since there is no `account` to key on, the rate limiter must use the client IP address. A pragmatic approach: in `RateLimitMiddleware.dispatch()`, add a separate IP-based check for paths starting with `/api/v1/auth/` and `/api/v1/waitlist/`. Suggested limits: 10 registration attempts / IP / minute, 30 login attempts / IP / minute (or use a sliding window with exponential backoff). Alternatively, deploy a WAF rule upstream (nginx `limit_req_zone`).

---

### [MEDIUM] M-2: WebSocket Private Channels Use Account-Level Isolation, Not Agent-Level

- **File:** `src/api/websocket/manager.py:461-503`, `src/api/websocket/channels.py`
- **Category:** 3.10 WebSocket Auth Bypass / 3.4 Agent Isolation Violations
- **Description:** WebSocket authentication (`_authenticate`) resolves the `account_id` only — it does NOT resolve or validate any agent context. The `orders` and `portfolio` private channels broadcast to all connections belonging to the `account_id` via `broadcast_to_account(account_id, payload)`. This means:
  - A connection authenticated with Agent A's API key will receive order and portfolio updates for ALL agents under the same account (including Agent B, Agent C).
  - Conversely, there is no way to subscribe to only a specific agent's order stream via WebSocket.

  In the current single-agent-per-account model this is low-risk. However, the REST API is already fully agent-scoped, and the platform supports multiple agents per account. If a customer runs multiple independent agent strategies, they cannot currently isolate their WebSocket feeds by agent.

- **Impact:** In a multi-agent account, one agent's WebSocket connection leaks order fill and portfolio events for sibling agents. This is a confidentiality concern if agents are operated by different parties (e.g., a strategy vendor and the account owner).
- **Evidence:** `manager.py:483-484` — `_authenticate` returns only `account.id`; agent resolution is absent.
- **Recommendation:** This is a design limitation of the current WebSocket architecture. For launch, document that WebSocket private channels are account-scoped (all agents). For a future release, add optional `agent_id` filtering: clients can pass `?api_key=<agent_key>` (which already includes an agent), and `broadcast_to_account` can check whether the subscribed connection's agent filter matches the event's `agent_id`.

---

### [MEDIUM] M-3: No Upper Bound on Password Field (bcrypt Silent Truncation)

- **File:** `src/api/schemas/auth.py:70-74` and `src/api/schemas/auth.py:207-210`
- **Category:** 3.8 Missing Input Validation
- **Description:** The `RegisterRequest.password` and `UserLoginRequest.password` fields have `min_length=8` but no `max_length`. The bcrypt library silently truncates input at 72 bytes. This creates two issues:
  1. **DoS vector:** A client can send an arbitrarily large password (e.g., 10 MB) which will be read into memory and passed to bcrypt. While bcrypt ignores bytes beyond 72, the memory allocation and string handling occur before truncation — repeated large-password submissions can exhaust memory.
  2. **Semantic surprise:** Users who set passwords longer than 72 bytes will be authenticated by any password that matches the first 72 bytes, creating silent security downgrade for very long passwords.

  This is a medium rather than high because: (a) the auth endpoint lacks rate limiting anyway (M-1), so the constraint would need to be fixed together with M-1 to be effective; (b) the practical impact on most users is zero since 72-byte passwords are extremely uncommon.

- **Evidence:**
  ```python
  # auth.py:70-74
  password: str | None = Field(
      default=None,
      min_length=8,
      # ← no max_length
  )
  ```
- **Recommendation:** Add `max_length=128` to both `RegisterRequest.password` and `UserLoginRequest.password`. This is safe and follows bcrypt best practices (some implementations recommend `max_length=72` to match bcrypt's limit exactly, but 128 is a common industry standard that provides a DoS boundary without being overly restrictive).

---

### [LOW] L-1: JWT Expiry Configurable Up to 168 Hours (7 Days)

- **File:** `src/config.py:78`
- **Category:** 3.1 Hardcoded Secrets / Auth
- **Description:** `jwt_expiry_hours: int = Field(default=1, ge=1, le=168)` allows JWT tokens to be configured to live up to 7 days. There is no token revocation mechanism (no server-side blacklist or refresh token pattern). A token issued with `JWT_EXPIRY_HOURS=168` that is later compromised cannot be invalidated without rotating the `JWT_SECRET` (which invalidates all issued tokens).

  The default of 1 hour is appropriate. The concern is that an operator might set a higher value for convenience without understanding the risk.

- **Impact:** Extended token validity window if a token is stolen or leaked.
- **Recommendation:** Consider reducing `le=168` to `le=24` in the validator, or adding documentation in `.env.example` that explains the token-revocation trade-off. For production, recommend keeping `JWT_EXPIRY_HOURS=1` and using refresh tokens if longer sessions are needed.

---

### [LOW] L-2: Default Weak Credentials in Config Defaults and `.env.example`

- **File:** `src/config.py:30`, `src/config.py:115`, `.env.example:29,47`
- **Category:** 3.1 Hardcoded Secrets
- **Description:** Two config fields have weak defaults that will be used if the operator does not override them:
  - `postgres_password: str = Field(default="change_me_in_production")` — if `POSTGRES_PASSWORD` is not set, the database uses this default password.
  - `grafana_admin_password: str = Field(default="change_me")` — if `GRAFANA_ADMIN_PASSWORD` is not set, Grafana uses this default.
  - `.env.example` sets `JWT_SECRET=change_me_to_random_64_char_string` — a new operator who copies the example file without changing this value will have a predictable JWT signing key.

  The `JWT_SECRET` field has a `@field_validator` enforcing a minimum of 32 characters — this catches the placeholder value if it is shorter than 32 chars, but `"change_me_to_random_64_char_string"` is 34 characters and would pass the length check.

- **Impact:** If deployed without changing defaults, the platform would have a predictable JWT secret, known database password, and known Grafana admin password.
- **Recommendation:** 
  1. For `jwt_secret`, add a validator that rejects the literal string `"change_me_to_random_64_char_string"` (or any string that does not appear random, e.g., contains spaces or common phrases). Alternatively, add a startup check that warns if `JWT_SECRET` matches known placeholder patterns.
  2. For `postgres_password` and `grafana_admin_password`, consider removing the default entirely (or using `None`) so the application fails to start if not configured, rather than silently using a weak default.
  3. Add a deploy-time check in `deploy.yml` (or a startup assertion) that validates `JWT_SECRET != "change_me_to_random_64_char_string"`.

---

### [LOW] L-3: X-Forwarded-For Trusted Without Proxy Validation (IP Spoofing in Audit Logs)

- **File:** `src/api/middleware/audit.py:103-108`, `src/api/middleware/logging.py` (shared pattern)
- **Category:** 3.6 Sensitive Data in Logs
- **Description:** `_client_ip(request)` trusts the first value in the `X-Forwarded-For` header without verifying that the request came from a trusted reverse proxy. An attacker connecting directly to the API can set `X-Forwarded-For: 1.2.3.4` to spoof any IP address in audit logs and rate-limit Redis keys. This was noted in a prior audit (Phase 3 logging review, 2026-03-21) and remains open.

  Rate limiting uses `account.api_key` as the key (not IP), so the rate limiter is not affected. The audit log is affected: spoofed IPs reduce the forensic value of audit records.

- **Impact:** IP address in `audit_log` table can be forged, reducing post-incident forensic value.
- **Recommendation:** If the platform runs behind a known reverse proxy (e.g., nginx, Cloudflare), configure trusted proxy IP validation. Only accept `X-Forwarded-For` from known proxy addresses; fall back to the TCP peer address for all other requests. FastAPI/Starlette supports `TrustedHostMiddleware` and `ProxyHeadersMiddleware` for this purpose.

---

### [LOW] L-4: Unvalidated X-Trace-Id Header Persisted to Audit Log

- **File:** `src/api/middleware/audit.py:218-220`, `src/api/middleware/logging.py` (prior finding)
- **Category:** 3.6 Sensitive Data in Logs / 3.8 Missing Input Validation
- **Description:** The `X-Trace-Id` header value is read from the request and stored in `request.state.trace_id`, then included in audit log `details` JSONB if non-empty. No format validation is performed. A malicious client can set `X-Trace-Id` to an arbitrarily long string or one containing special characters, which will be persisted to the `audit_log` table.

  PostgreSQL's JSONB storage provides some protection (no SQL injection possible), but the column has no length constraint and an unbounded value could cause large rows.

  This was a HIGH finding in the Phase 3 logging audit (2026-03-21). It has been downgraded to LOW here because: (a) the audit log is not exposed via any API endpoint; (b) the primary write path goes through ORM `session.add()` with JSONB, which prevents injection; (c) the main residual risk is oversized audit log rows rather than security compromise.

- **Impact:** Oversized audit log rows if `X-Trace-Id` contains arbitrary long strings; minor JSONB pollution.
- **Recommendation:** Add a length and format check on `X-Trace-Id` in `LoggingMiddleware`. Accept only hex strings up to 32 characters (matching the agent-generated format `uuid4().hex[:16]`). Reject or truncate values that do not match.

---

## Checks Passed (No Findings)

- **3.1 Hardcoded Secrets** — No hardcoded API keys, passwords, or JWTs found in `src/`. `.env` is gitignored. All secrets loaded from environment.
- **3.3 SQL Injection** — All queries use SQLAlchemy ORM. `text(f"...")` in `DataReplayer` interpolates only server-side constants from fixed dictionaries; user data flows through bound parameters.
- **3.4 Agent Isolation (API key path)** — Correct: agent resolved by API key lookup; account resolved from `agent.account_id`.
- **3.7 Insecure Password Handling** — bcrypt 12 rounds; constant-time via `checkpw`; API secret never stored; bcrypt offloaded to thread pool.
- **3.9 CORS Misconfiguration** — `@field_validator` blocks `*` in CORS origins; `allow_credentials=True` safe with explicit origins.
- **3.11 Dependency Vulnerabilities** — No `eval`, `exec`, `pickle.loads`, `subprocess`, `yaml.load()` with user data. All pinned versions recent; no known CVEs in pinned deps at audit date.
- **3.12 Circuit Breaker Bypass** — Circuit breaker is per-account; cannot be reset by creating a new agent (new agents increment against the account's daily PnL).
- **3.13 HTTPS Enforcement** — No hardcoded `http://` URLs found outside `localhost`. Production `api_base_url` defaults to `https://`.
- **3.2 Auth Bypass (public paths)** — Public path whitelist is correctly scoped; no new sensitive endpoints added to public lists.
- **3.5 Rate Limiting (trading and general endpoints)** — `/api/v1/trade/` correctly hits the 100/min `orders` tier; all other authenticated endpoints hit `general` (600/min) or appropriate tiers.
- **3.10 WebSocket Auth** — Close code 4401 on failure; account status checked; channel subscription cap enforced (10/connection).
- **5 Data Exposure** — `RegisterResponse` and `TokenResponse` do not include password hash, internal IDs, or stack traces. The global exception handler returns `{"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}}` for all unhandled exceptions.

---

## Notes

### On the HIGH Finding's Practical Exploitability

The HIGH finding (H-1) requires an attacker to possess:
1. A valid JWT token (obtained by registering their own account and authenticating).
2. A target agent UUID from another account.

Agent UUIDs are PostgreSQL `gen_random_uuid()` UUIDs — 122 bits of entropy. They are not directly enumerable through any public API endpoint. However, they may be visible in:
- Battle participant listings (`GET /battles/{id}` is JWT-only but any authenticated user can view battle details if they know the battle ID)
- Leaderboard entries (`GET /analytics/leaderboard` returns agent metrics — check if `agent_id` is included in the response schema)

Even without enumeration, the finding should be fixed because: (a) the correct behavior is trivially implementable (one-line ownership check); (b) any future feature that exposes agent UUIDs to other authenticated users would elevate this to a more severe cross-account read vulnerability; (c) the `cancel_all_orders` path with `list_open_by_agent(agent_id)` (no account_id filter) is a direct operational impact if an agent UUID is known.

### On Registration as an Open Endpoint

`POST /api/v1/auth/register` is intentionally public and unauthenticated. The lack of rate limiting (M-1) means a competitor or malicious actor can create thousands of accounts, consuming starting balances (virtual, so no real cost) and potentially affecting leaderboard rankings. If account creation is meant to be restricted (e.g., invite-only for beta), an email verification or invite code mechanism should be added before launch.

### Areas Not Covered by This Audit

The following areas are outside the scope of this task and have not been audited:
- `src/order_engine/` — financial arithmetic, order matching logic
- `src/backtesting/` — engine sandbox isolation beyond DataReplayer
- `src/battles/` — battle service layer isolation
- `Frontend/` — client-side XSS, API key storage in localStorage
- `agent/conversation/`, `agent/memory/`, `agent/trading/` — AI agent ecosystem (not customer-facing API)

---

## Verdict

**CONDITIONAL PASS — one HIGH finding must be fixed before customer launch.**

The platform demonstrates solid security fundamentals: bcrypt with proper rounds, no hardcoded secrets, parameterized queries throughout, a working CORS wildcard guard, correctly scoped ownership checks on all agent mutation endpoints, and a working exception handler that does not leak internals. The SSRF, Celery secret, and metrics endpoint findings from prior audits are all resolved.

The single HIGH finding (JWT agent isolation bypass) is a low-complexity fix with a clear remediation path. The three MEDIUM findings (no auth rate limiting, WS account-level channels, password max length) are quality-of-life improvements that reduce attack surface but do not enable immediate data breach. The four LOW findings are hardening suggestions.

**Recommended pre-launch actions (ordered by priority):**
1. Fix H-1: Add `agent.account_id == account.id` check in `get_current_agent` (JWT path).
2. Fix M-1: Add IP-based rate limiting for `/api/v1/auth/` and `/api/v1/waitlist/` endpoints.
3. Fix M-3: Add `max_length=128` to password fields in auth schemas.
4. Fix L-2: Add startup check / stricter validator for `JWT_SECRET` placeholder detection.
