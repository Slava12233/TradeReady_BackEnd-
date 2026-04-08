---
type: code-review
tags:
  - security
  - audit
  - webhooks
  - ssrf
  - hmac
  - endgame
  - phase-3
date: 2026-04-07
reviewer: security-auditor
verdict: CONDITIONAL PASS
scope: >
  src/api/routes/metrics.py, src/api/routes/indicators.py,
  src/api/routes/webhooks.py, src/api/routes/strategies.py (compare endpoint),
  src/api/routes/backtest.py (step/batch/fast endpoint),
  src/webhooks/dispatcher.py, src/tasks/webhook_tasks.py,
  src/database/models.py (WebhookSubscription),
  src/api/schemas/metrics.py, src/api/schemas/indicators.py,
  src/api/schemas/webhooks.py, src/api/schemas/strategies.py
---

# Security Audit — Platform Endgame Readiness (Task 22)

**Scope:** All new endpoints and webhook system added as part of the Platform Endgame Readiness plan.
**Date:** 2026-04-07
**CLAUDE.md files consulted:** Root CLAUDE.md, src/api/middleware/CLAUDE.md, src/accounts/CLAUDE.md, src/risk/CLAUDE.md, src/api/routes/CLAUDE.md, src/tasks/CLAUDE.md, src/api/schemas/CLAUDE.md

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH     | 2 |
| MEDIUM   | 3 |
| LOW      | 3 |

**Verdict: CONDITIONAL PASS** — one CRITICAL finding (SSRF in webhook URL registration) must be fixed before production use of the webhook system. All other new endpoints are structurally sound.

---

## Findings

### [CRITICAL] No SSRF Protection on Webhook URL Field

- **File:** `src/api/schemas/webhooks.py:45-65` and `src/api/routes/webhooks.py:130-159`
- **Category:** Check 3.13 / OWASP A10 SSRF
- **Description:** The `WebhookCreateRequest.url` and `WebhookUpdateRequest.url` fields accept any string up to 2048 characters. There is no scheme check (HTTP vs HTTPS), no hostname resolution check, and no IP range validation. An authenticated user can register a webhook URL targeting internal infrastructure:
  - `http://localhost:6379` (Redis)
  - `http://127.0.0.1:5432` (PostgreSQL/TimescaleDB)
  - `http://10.0.0.1/` (VPC internal hosts)
  - `http://169.254.169.254/latest/meta-data/` (AWS/GCP metadata service)
  - `http://[::1]/` (IPv6 loopback)
  - `http://timescaledb:5432` (Docker service name — internal DNS)
  When `dispatch_webhook` executes in the Celery worker, `httpx.AsyncClient` resolves the hostname and makes a POST request with a signed JSON body. This gives an attacker a way to perform authenticated HTTP POST requests to internal services from the Celery worker's network context.
- **Impact:** Full SSRF from within the Celery worker container. Depending on what internal services are exposed, this could reach: Redis (unauthenticated in Docker), TimescaleDB, other microservices, or cloud metadata endpoints. The `httpx` call is made with a 10s timeout, receives the response body (even though it is only used for `raise_for_status`), and retries up to 3 times, meaning each registration can cause 4 outbound requests to an internal target.
- **Evidence:**
  ```python
  # src/api/schemas/webhooks.py:45
  url: str = Field(
      ...,
      max_length=2048,
      description="HTTPS endpoint that will receive webhook payloads.",
      examples=["https://example.com/webhooks"],
  )
  # No @field_validator for scheme or IP range.
  ```
  ```python
  # src/tasks/webhook_tasks.py:171-180
  async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
      response = await client.post(
          url,   # ← raw, unvalidated URL from DB
          content=payload_bytes,
          ...
      )
  ```
- **Recommendation:**
  1. Add a Pydantic `@field_validator("url")` in `WebhookCreateRequest` and `WebhookUpdateRequest` that:
     a. Rejects any URL whose scheme is not `https` (block `http://`, `ftp://`, etc.).
     b. Resolves the hostname to an IP address (using `socket.getaddrinfo`) and rejects any address in: loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`, `fe80::/10`), RFC-1918 private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and the Docker default bridge range (`172.17.0.0/16`).
     c. Rejects bare IP addresses (no hostname) to prevent trivially bypassing DNS-based checks.
  2. As defence-in-depth, also validate in `_async_dispatch` before the `httpx.post()` call (covers paths where the URL reaches the task without going through the API validator, e.g., the test endpoint).
  3. Note: DNS rebinding is not fully mitigated by point 1(b) alone — consider adding egress network policy at the container level as a complementary control.

---

### [HIGH] No Upper Bound on `returns` Array (Unauthenticated DoS)

- **File:** `src/api/schemas/metrics.py:59-67` and `src/api/routes/metrics.py:66-79`
- **Category:** Check 3.8 — Missing Input Validation / DoS
- **Description:** The `DeflatedSharpeRequest.returns` field enforces `min_length=10` but has no `max_length` constraint. The endpoint is **public** (no authentication required — listed in `_PUBLIC_PREFIXES` in `auth.py:81`). An unauthenticated caller can POST a `returns` array with millions of float values. The entire JSON body is parsed by Pydantic, then iterated by `compute_deflated_sharpe()` which computes mean, variance, skewness, kurtosis, and normal CDF over the full array. Because there is no rate limiting on unauthenticated requests (the rate limiter reads `request.state.account` which is `None` for unauthenticated callers), there is no enforcement layer protecting this computation path.
- **Impact:** A single request with a 10-million-element float array (~80 MB JSON) will consume significant CPU and memory in the API process for several seconds. Sustained by a script, this degrades API response times for all tenants.
- **Evidence:**
  ```python
  # src/api/schemas/metrics.py:59
  returns: list[float] = Field(
      ...,
      min_length=10,
      # No max_length here
      ...
  )
  ```
  ```python
  # src/api/middleware/auth.py:81
  _PUBLIC_PREFIXES: tuple[str, ...] = (
      ...
      "/api/v1/metrics/",  # Statistical metrics — pure computation, no auth required
  )
  ```
- **Recommendation:**
  1. Add `max_length=10000` (or similar reasonable bound — 10,000 daily returns covers ~40 years) to the `returns` field in `DeflatedSharpeRequest`.
  2. Add `le=100000` to `num_trials` (currently unbounded `ge=1`) to prevent the harmonic sum in the DSR formula from running excessive iterations.
  3. Consider adding `annualization_factor` an upper bound (`le=525600` for per-minute data) to guard against integer overflow in downstream math.
  4. Alternatively, require authentication on `POST /api/v1/metrics/deflated-sharpe`. The docstring says the endpoint is public "so that it can be called from the agent's strategy-testing workflow without needing an API key" — agents do have API keys, so this justification does not require unauthenticated access.

---

### [HIGH] HMAC Computed at Dispatch Time; Secret Logged in Failure Warning

- **File:** `src/tasks/webhook_tasks.py:162-196`
- **Category:** Check 3.6 — Sensitive Data in Logs
- **Description:** The `_async_dispatch` function receives `secret` as a plain-text string parameter. When delivery fails, the warning log at line 188 includes `url=url` (the target endpoint) but the broader context that reaches the log — through Celery's task metadata in the exception context — may serialise task arguments. More critically: `secret` is passed as a positional Celery task argument via `.delay(secret=sub.secret, ...)` in both `dispatcher.py:98` and `webhooks.py:354`. Celery stores task arguments in the result backend (Redis) in plaintext JSON for `result_expires=3600` (1 hour). Any process with Redis access (including other Celery workers) can read the full task argument dict, including `secret`, from the `celery-task-meta-{uuid}` key during that window.
  This is not a direct log injection, but it is plaintext secret exposure through a shared backend.
- **Impact:** An attacker with Redis read access (including other Celery workers on the same broker) can extract webhook signing secrets from the result backend, forge webhook signatures, and send arbitrary payloads that pass HMAC verification on the subscriber's side.
- **Evidence:**
  ```python
  # src/webhooks/dispatcher.py:95-101
  dispatch_webhook.delay(
      subscription_id=str(sub.id),
      url=sub.url,
      secret=sub.secret,   # ← passed as Celery task arg, stored in Redis result backend
      event_name=event_name,
      payload=payload,
  )
  ```
  ```python
  # src/tasks/celery_app.py (from CLAUDE.md)
  # result_expires=3600  ← task args (including secret) sit in Redis for 1 hour
  ```
- **Recommendation:**
  1. Do not pass the secret as a Celery task argument. Instead, pass only `subscription_id` (which is already a task argument) and have `_async_dispatch` query the database for `secret` at execution time — it already queries the DB for `failure_count`. This keeps the secret server-side only.
  2. If point 1 is not immediately feasible, set `ignore_result=True` on `dispatch_webhook` to prevent Celery from writing task arguments (and thus the secret) to the result backend. Note that `ignore_result=False` is the current setting.
  3. As defence-in-depth, consider encrypting secrets at rest in the `webhook_subscriptions` table (envelope encryption with a KMS or platform-managed DEK) rather than storing plaintext secrets in the DB.

---

### [MEDIUM] Webhook URL Accepted with `http://` Scheme (No HTTPS Enforcement)

- **File:** `src/api/schemas/webhooks.py:45-65`
- **Category:** Check 3.13 — HTTPS Enforcement
- **Description:** The `url` field description says "HTTPS endpoint" but there is no validator enforcing the `https://` scheme. A user can register `http://example.com/webhook` and deliveries will succeed over plaintext HTTP. This exposes the signed HMAC payload to network eavesdroppers who can capture the signature and replay it (HMAC provides authentication, not confidentiality; over HTTP the payload and signature are visible in transit).
- **Impact:** Signature capture and replay attacks become possible for subscribers using HTTP endpoints. An MITM attacker on the path to the subscriber's server can also read event data (backtest results, strategy deployments, battle outcomes).
- **Evidence:** `url: str = Field(..., max_length=2048, description="HTTPS endpoint...")` — description only, no code enforcement.
- **Recommendation:** Enforce HTTPS in the `@field_validator("url")` also added for the SSRF fix above. Reject any URL where `parsed.scheme != "https"` with a clear error message. This is a subset of the CRITICAL SSRF fix.

---

### [MEDIUM] `ranking_metric` Validated in `model_post_init`, Not `@field_validator`

- **File:** `src/api/schemas/strategies.py:156-171`
- **Category:** Check 3.8 — Missing Input Validation
- **Description:** `StrategyComparisonRequest.ranking_metric` is validated via a `model_post_init` hook and a dead `@classmethod _validate_metric` that is never called by Pydantic (it is not decorated with `@field_validator`). If Pydantic v2 ever changes when `model_post_init` is invoked relative to field construction (e.g., in partial model builds or `model_construct()` calls used in some test patterns), the validation would be bypassed. More immediately: Pydantic v2 raises `ValueError` from `model_post_init` as a `ValidationError`, but the `_validate_metric` classmethod is unreachable dead code, creating confusion about which validation path is active.
- **Impact:** Low direct risk — `model_post_init` does execute in normal request handling. However, `model_construct()` skips validators and `model_post_init`, so test code or internal code that uses `model_construct()` bypasses the check entirely, potentially allowing an arbitrary `ranking_metric` string into `StrategyService.compare_strategies()`. If the service passes `ranking_metric` to a dynamic sort key, it could cause a `KeyError` or unexpected sort behaviour.
- **Evidence:**
  ```python
  @classmethod
  def _validate_metric(cls, v: str) -> str:
      """Ensure ranking_metric is one of the supported values."""  # Never called by Pydantic
      ...
  
  def model_post_init(self, __context: object) -> None:
      if self.ranking_metric not in _VALID_RANKING_METRICS:
          raise ValueError(...)  # Only active path
  ```
- **Recommendation:** Replace `model_post_init` with a proper `@field_validator("ranking_metric", mode="before")` decorator on `_validate_metric`. Remove the dead `model_post_init` override. This makes the validation canonical and ensures it runs in all construction paths including `model_construct()`.

---

### [MEDIUM] No Per-Account Limit on Webhook Subscription Count

- **File:** `src/api/routes/webhooks.py:107-159`
- **Category:** Check 3.5 — Rate Limit Coverage / Abuse Prevention
- **Description:** Any authenticated account can create an unlimited number of webhook subscriptions. The `POST /api/v1/webhooks` endpoint falls under the `general` tier (600 req/min), but there is no check on how many subscriptions already exist for the account before creating a new one. An attacker with a valid account can create thousands of subscriptions for a single, frequently-firing event (e.g., `backtest.completed`), causing the `fire_event()` dispatcher to enqueue thousands of Celery tasks per event. Each task makes an outbound HTTP request with retries.
- **Impact:** Resource exhaustion in the Celery worker pool. Each subscription for a high-frequency event multiplies Celery task volume linearly. With 10,000 subscriptions all targeting a slow endpoint, a single backtest completion could saturate the worker pool with 30,000 HTTP requests (3 retries each) and block legitimate task processing including the limit order monitor.
- **Evidence:**
  ```python
  # src/api/routes/webhooks.py:112-158
  async def create_webhook(body, account, db):
      # No subscription count check before insert
      sub = WebhookSubscription(account_id=account.id, ...)
      db.add(sub)
      await db.commit()
  ```
- **Recommendation:**
  1. Add a subscription count check before creating: query `COUNT(*) WHERE account_id = account.id`, reject with HTTP 429 or 422 if count >= threshold (suggested: 25 per account).
  2. Add a `per_account_subscription_limit` setting to `src/config.py` so the limit can be adjusted without a code deployment.

---

### [LOW] `session_id` in Backtest Routes Accepts Arbitrary Strings (No UUID Validation)

- **File:** `src/api/routes/backtest.py:212-286`
- **Category:** Check 3.8 — Missing Input Validation
- **Description:** Several backtest route handlers accept `session_id: str` as a path parameter rather than `session_id: UUID`. This bypasses FastAPI's automatic UUID format validation. The `_raise_if_terminal` helper internally calls `UUID(session_id)` which will raise `ValueError` on non-UUID input, but the exception is not caught — it would propagate as an unhandled 500 error rather than a clean 422. The `step_batch_fast_backtest` handler has this same pattern.
- **Impact:** Low — an attacker sending a malformed session ID (e.g., `../../../../etc/passwd`) will get an HTTP 500 (not path traversal, since the value is used only as a UUID constructor argument, not as a filesystem path). However, it exposes unhandled `ValueError` to the global exception handler, which returns a generic 500 rather than a useful 422 validation error.
- **Evidence:**
  ```python
  @router.post("/backtest/{session_id}/step/batch/fast")
  async def step_batch_fast_backtest(
      request: Request,
      session_id: str,   # ← should be UUID
      ...
  ```
- **Recommendation:** Change `session_id: str` to `session_id: UUID` across all backtest route handlers. FastAPI will automatically return HTTP 422 for malformed UUIDs and pass a valid `UUID` object to the handler, eliminating the manual `UUID(session_id)` conversion in `_raise_if_terminal`.

---

### [LOW] Indicator Cache Key Uses MD5 for Hash (Non-Security Use, Acceptable; but Flag)

- **File:** `src/api/routes/indicators.py:335`
- **Category:** Check 3.11 — Dependency Vulnerabilities / Weak Cryptography
- **Description:** The cache key builder uses `hashlib.md5(..., usedforsecurity=False)` to create an 8-character hex digest of the indicator names. MD5 is appropriate here (the comment explicitly flags `usedforsecurity=False` and it is only used for cache key deduplication, not for authentication or integrity). However, 8 hex characters (32 bits of key space) creates a meaningful collision probability when many indicator subsets are active. If two different indicator subsets hash to the same 8 chars for the same symbol, one subset will serve stale cached results for the other.
- **Impact:** Incorrect indicator values returned to callers when a hash collision occurs (probability ~1 in 4 billion combinations per symbol — low but non-zero in high-traffic). Not a security vulnerability, but a correctness issue surfaced during this review.
- **Evidence:**
  ```python
  indicator_hash = hashlib.md5(names_str.encode(), usedforsecurity=False).hexdigest()[:8]
  return f"indicators:{symbol}:{indicator_hash}"
  ```
- **Recommendation:** Increase the hash digest length from `[:8]` to `[:16]` (64-bit key space). Alternatively, use `hashlib.sha256` with the same `[:8]` truncation — the collision probability is identical but avoids any future audit friction around MD5 usage even with the `usedforsecurity=False` flag.

---

### [LOW] `url` Field Included in Failure Warning Log (Information Disclosure to Log Consumers)

- **File:** `src/tasks/webhook_tasks.py:188-196`
- **Category:** Check 3.6 — Sensitive Data in Logs
- **Description:** On delivery failure, the `webhook.delivery.failed` warning log includes `url=url` — the full webhook endpoint URL including any query parameters or embedded credentials (e.g., `https://service.example.com/hook?token=abc123`). If users register URLs with bearer tokens or API keys in the query string (a common pattern for simple webhook receivers), those credentials will appear in structured log output aggregated by Grafana Loki, CloudWatch, Datadog, etc.
- **Impact:** Credential leakage to log consumers who have read access to the log aggregation system but should not have access to user webhook credentials.
- **Evidence:**
  ```python
  logger.warning(
      "webhook.delivery.failed",
      ...
      url=url,   # ← could include query-string credentials
      ...
  )
  ```
- **Recommendation:** Log only the URL scheme and host (e.g., `url_host=urlparse(url).netloc`) rather than the full URL. This retains operationally useful information (which host is failing) without exposing path or query parameters.

---

## Checks Passed

The following checks from the standard checklist were performed and found no issues:

**3.1 Hardcoded Secrets** — No hardcoded credentials, API keys, or tokens found in any audited file. Webhook secrets are generated with `secrets.token_urlsafe(32)`. All other secrets come from `get_settings()` / environment variables.

**3.2 Auth Bypass Paths** — All webhook endpoints (`POST/GET/PUT/DELETE /api/v1/webhooks*`) correctly require `CurrentAccountDep`. The metrics endpoint (`POST /api/v1/metrics/deflated-sharpe`) and indicators endpoints (`GET /api/v1/market/indicators/*`) are intentionally public and correctly listed in `_PUBLIC_PREFIXES`. The new `/api/v1/metrics/` prefix was explicitly added to the auth middleware public list. No unexpected auth bypasses introduced.

**3.3 SQL Injection** — All DB access uses SQLAlchemy ORM parameterized queries. The one raw SQL query in `indicators.py:409-417` (`_fetch_candles`) uses `text()` with bound parameters (`{"symbol": symbol, "limit": lookback}`), not f-string interpolation. Symbol is validated against `_SYMBOL_RE` before reaching the query. No injection risk.

**3.4 Agent Isolation** — Webhook subscriptions are scoped to `account_id` in all queries. `_get_owned_sub()` verifies `sub.account_id == account_id` before any mutation. The dispatcher `fire_event()` takes `account_id` as a parameter and filters subscriptions with `WHERE account_id = :account_id`. No cross-account data leak path identified.

**3.5 Rate Limit Coverage** — New webhook endpoints fall under the `general` tier (600 req/min). Indicator endpoints fall under the `market_data` tier (1200/min) via the `/api/v1/market/` prefix. Metrics endpoint falls under the `general` tier. The backtest fast-batch endpoint falls under the `backtest` tier (6000/min). All tiers are appropriate for their endpoint characteristics.

**3.7 Password / Secret Handling** — `secrets.token_urlsafe(32)` is used for webhook secret generation (256-bit entropy, URL-safe base64). The secret is returned only once at creation time (`WebhookCreateResponse` includes `secret`; `WebhookResponse` does not). The `_sub_to_response()` helper omits the secret field. Confirmed: secret is not returned on GET, PUT, or list endpoints.

**3.8 Input Validation (partial)** — Pydantic v2 validation is present on all request bodies. Symbol format is validated with `_SYMBOL_RE = re.compile(r"^[A-Z]{2,10}USDT$")`. Indicator names are validated against `_ENGINE_KEY_MAP`. The `events` field in `WebhookCreateRequest` and `WebhookUpdateRequest` validates against `SUPPORTED_EVENTS` via `@field_validator`. Strategy comparison uses `min_length=2, max_length=10` on `strategy_ids`. Backtest fast-batch uses `le=100000` on `steps`. The unbounded `returns` array is flagged separately under HIGH findings.

**3.9 CORS** — No changes to CORS configuration in audited files. Pre-existing wildcard CORS gap (noted in previous audit 2026-03-30) remains unaddressed but is not introduced by this change set.

**3.10 WebSocket Auth Bypass** — No WebSocket changes in this audit scope.

**3.11 Dependency Vulnerabilities** — No `eval()`, `exec()`, `pickle`, `yaml.load()`, or `subprocess` with user input found in any audited file. `httpx` is used for outbound HTTP in the webhook task (correct — no user-controlled shell arguments). MD5 usage flagged under LOW.

**3.12 Circuit Breaker Bypass** — No order execution paths in the new endpoints. Metrics, indicators, webhooks, and strategy comparison are read-only or administrative. The fast-batch backtest endpoint delegates to `engine.step_batch_fast()` which operates within the existing backtest sandbox (not live order execution) — circuit breaker is not applicable.

**3.13 HTTPS Enforcement** — Flagged as MEDIUM (enforcement missing in code; only in documentation).

**3.14 / 3.15 / 3.16 Frontend** — No frontend files in this audit scope.

---

## Notes

1. **HMAC is signing-only, not verification** — The webhook system only signs outbound payloads with HMAC-SHA256. There is no server-side HMAC verification path (webhooks are outbound only). The concern about `hmac.compare_digest()` vs `==` mentioned in the task spec is not applicable here — there is no inbound signature verification in this codebase. Outbound signing with `hmac.new(...).hexdigest()` is correct.

2. **Secret stored in plaintext** — The `WebhookSubscription.secret` column stores the HMAC signing key in plaintext. This is architecturally similar to how `api_key` is stored in plaintext for O(1) lookup (documented platform trade-off). However, unlike API keys which are used for inbound authentication (high-frequency lookups justify plaintext), webhook secrets are only needed once per outbound delivery — the plaintext storage is not justified by a lookup performance requirement. The HIGH finding about Celery result backend exposure makes this worse; fixing that finding (don't pass secret as a task argument) would also reduce the exposure surface.

3. **`fire_event()` is fire-and-forget with no backpressure** — If 100 subscriptions match an event, 100 Celery tasks are enqueued synchronously inside the request handler. There is no concurrency limit on how many tasks can be enqueued per event. This is acceptable for the current 4-event catalog with low expected subscriber counts, but should be revisited if the event catalog expands or subscriber counts grow. The subscription count cap (MEDIUM finding) partially addresses this.

4. **`dispatch_webhook` uses `asyncio.run()` inside a sync Celery task** — This is the standard project pattern for Celery tasks and is correct. The Celery worker process is not running an event loop at the point of task execution, so `asyncio.run()` creates a fresh event loop safely.

5. **No webhook delivery audit trail** — Successful and failed deliveries are logged to `structlog` but not persisted to the `audit_log` table. Consider adding webhook delivery outcomes to the audit log (at least failures) for compliance and debugging.
