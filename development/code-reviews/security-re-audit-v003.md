---
type: code-review
tags:
  - security
  - audit
  - re-audit
  - webhooks
  - ssrf
  - verification
  - v003
date: 2026-04-07
reviewer: security-auditor
verdict: PASS
scope: >
  src/webhooks/dispatcher.py, src/tasks/webhook_tasks.py,
  src/api/schemas/webhooks.py, src/api/schemas/metrics.py,
  src/api/schemas/strategies.py, src/api/routes/webhooks.py,
  src/api/routes/backtest.py, src/api/routes/indicators.py,
  src/api/routes/metrics.py, src/api/middleware/auth.py,
  src/config.py
---

# Security Re-Audit — V.0.0.3 Fix Verification

**Scope:** Verification that all CRITICAL/HIGH/MEDIUM/LOW findings from [[security-audit-endgame-readiness]] (2026-04-07) are resolved in the V.0.0.3 fix set.
**Date:** 2026-04-07
**Original audit verdict:** CONDITIONAL PASS
**CLAUDE.md files consulted:** Root CLAUDE.md, src/api/middleware/CLAUDE.md, src/api/schemas/CLAUDE.md, src/api/routes/CLAUDE.md, src/tasks/CLAUDE.md

---

## Summary

| Severity | Original Count | Resolved | Residual |
|----------|---------------|----------|---------|
| CRITICAL | 1 | 1 | 0 |
| HIGH | 2 | 2 | 0 |
| MEDIUM | 3 | 3 | 0 |
| LOW | 3 | 3 | 0 |

**New issues introduced by fixes:** 2 LOW (minor, noted below)

**Verdict: PASS** — All original findings are resolved. Two minor LOW-severity observations introduced by the fix set are documented. None block production use.

---

## Fix Verification

### [CRITICAL] SSRF on Webhook URL — RESOLVED

**Files verified:** `src/webhooks/dispatcher.py`, `src/api/schemas/webhooks.py`, `src/tasks/webhook_tasks.py`

`validate_webhook_url()` has been added to `src/webhooks/dispatcher.py` (lines 60-143). It enforces:
1. Scheme must be `https` — `http://` and all other schemes are rejected.
2. Hostname must be present and must not be a bare IP address literal.
3. Hostname is resolved via `socket.getaddrinfo`; every returned IP is checked against `_BLOCKED_NETWORKS` which includes: `127.0.0.0/8`, `::1/128`, `169.254.0.0/16`, `fe80::/10`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `172.17.0.0/16`.

`WebhookCreateRequest.validate_url` and `WebhookUpdateRequest.validate_url` in `src/api/schemas/webhooks.py` are proper `@field_validator` decorators that call `validate_webhook_url()` — SSRF is blocked at schema validation time before any DB write.

`_async_dispatch` in `src/tasks/webhook_tasks.py` (lines 221-238) calls `validate_webhook_url(url)` as defence-in-depth before the `httpx.post()` call, blocking URLs that were stored before SSRF protection was introduced.

DNS rebinding limitation is correctly documented in both `dispatcher.py` and `webhook_tasks.py` module docstrings. This is an accepted architectural limitation, not a gap.

**Verdict: RESOLVED.**

---

### [HIGH] Unbounded returns Array (Unauthenticated DoS) — RESOLVED

**Files verified:** `src/api/schemas/metrics.py`, `src/api/middleware/auth.py`, `src/api/routes/metrics.py`

`DeflatedSharpeRequest.returns` in `src/api/schemas/metrics.py` now has `max_length=10_000` (line 62). `num_trials` has `le=100_000` (line 73). `annualization_factor` has `le=525_600` (line 83). All three upper bounds from the original recommendation are in place.

`/api/v1/metrics/` is no longer present in `_PUBLIC_PREFIXES` in `src/api/middleware/auth.py`. The list now contains only `/docs`, `/redoc`, `/metrics`, and `/api/v1/market/`. Requests to `POST /api/v1/metrics/deflated-sharpe` without valid credentials will receive HTTP 401 from `AuthMiddleware` before reaching the handler. The handler itself (`compute_deflated_sharpe_endpoint`) has no `CurrentAccountDep` parameter, but authentication is fully enforced by the middleware layer — this is the correct pattern.

**Verdict: RESOLVED.**

---

### [HIGH] Secret Passed as Celery Task Argument — RESOLVED

**Files verified:** `src/webhooks/dispatcher.py`, `src/tasks/webhook_tasks.py`

`fire_event()` in `src/webhooks/dispatcher.py` (lines 207-214) now calls `dispatch_webhook.delay()` with only `subscription_id`, `url`, `event_name`, and `payload` — `secret` is no longer passed as a task argument.

`dispatch_webhook` in `src/tasks/webhook_tasks.py` has `ignore_result=True` (line 80), preventing Celery from writing any task data to the Redis result backend.

`_async_dispatch` fetches the secret from DB at execution time (lines 175-210) using a new session via `get_session_factory()`. The comment at lines 171-174 explicitly documents the design rationale.

**Verdict: RESOLVED.**

---

### [MEDIUM] ranking_metric Validated in model_post_init — RESOLVED

**File verified:** `src/api/schemas/strategies.py`

`StrategyComparisonRequest` now uses a proper `@field_validator("ranking_metric", mode="before")` on `_validate_metric` (lines 156-164). The dead `model_post_init` override is gone. The validator raises `ValueError` when `v not in _VALID_RANKING_METRICS`. This runs in all construction paths including `model_construct()`.

**Verdict: RESOLVED.**

---

### [MEDIUM] No Per-Account Webhook Subscription Limit — RESOLVED

**Files verified:** `src/api/routes/webhooks.py`, `src/config.py`

`create_webhook` in `src/api/routes/webhooks.py` (lines 131-142) now queries `COUNT(*)` for the account's existing subscriptions and raises `InputValidationError` if `count >= settings.per_account_webhook_limit` before any insert.

`src/config.py` has `per_account_webhook_limit: int = Field(default=25, ge=1, ...)` — the limit defaults to 25 and is configurable via environment variable without a code deployment.

**Verdict: RESOLVED.**

---

### [MEDIUM] HTTP Scheme Not Enforced on Webhook URLs — RESOLVED

**File verified:** `src/api/schemas/webhooks.py` (via `validate_webhook_url`)

`validate_webhook_url()` checks `parsed.scheme != "https"` first (line 94 of `dispatcher.py`) and raises `ValueError` for any non-HTTPS URL. This is the first check in the function, applied to both `WebhookCreateRequest` and `WebhookUpdateRequest`. This finding was a subset of the CRITICAL SSRF fix and is fully covered by it.

**Verdict: RESOLVED.**

---

### [LOW] session_id URL Parameter Not UUID-Typed — RESOLVED

**File verified:** `src/api/routes/backtest.py`

All backtest route handlers now use `session_id: UUID` as the path parameter type, confirmed across all 20+ handler signatures. FastAPI returns HTTP 422 automatically for malformed UUIDs. The `_raise_if_terminal` helper also accepts `UUID` (line 130). No handler retains `session_id: str`.

**Verdict: RESOLVED.**

---

### [LOW] Indicator Cache Key Uses 8-Character Hash — RESOLVED

**File verified:** `src/api/routes/indicators.py`

Line 335: `hashlib.md5(names_str.encode(), usedforsecurity=False).hexdigest()[:16]` — the digest has been extended from `[:8]` (32-bit) to `[:16]` (64-bit), reducing hash collision probability by a factor of ~4 billion.

**Verdict: RESOLVED.**

---

### [LOW] Full URL in Webhook Failure Log — RESOLVED (for failure log)

**File verified:** `src/tasks/webhook_tasks.py`

The `webhook.delivery.failed` warning log at line 272 now uses `url_host=urlparse(url).netloc` rather than `url=url`. The host is imported at module level (`from urllib.parse import urlparse`, line 49). Only the `netloc` (scheme+host+port) is logged, not the path or query string, which is where embedded credentials typically appear.

**Verdict: RESOLVED (original finding).**

---

## New Issues Introduced by Fixes

### [LOW] Full URL Logged on Successful Delivery

- **File:** `src/tasks/webhook_tasks.py:300-304`
- **Category:** Check 3.6 — Sensitive Data in Logs
- **Description:** The `webhook.delivery.success` INFO log includes `url=url` — the full URL including any query string credentials. This was not part of the original LOW finding (which only cited the failure warning log), but applies equally to the success path.
- **Impact:** Same credential leakage risk as the original LOW: if a user registers a webhook URL with an embedded bearer token in the query string (e.g., `https://service.example.com/hook?token=abc`), successful delivery logs will expose that token to log aggregators.
- **Recommendation:** Replace `url=url` with `url_host=urlparse(url).netloc` at line 301 to match the pattern applied to the failure log.

---

### [LOW] Full URL Logged in SSRF Block Warning

- **File:** `src/tasks/webhook_tasks.py:228-232`
- **Category:** Check 3.6 — Sensitive Data in Logs
- **Description:** The new `webhook.delivery.ssrf_blocked` warning log includes `url=url` — the full URL of the blocked internal target. This is a new log line introduced by the fix and was not present before.
- **Impact:** Logs the internal service URL (e.g., `https://internal-db:5432/`) when an SSRF attempt is caught. This provides useful forensic information for security monitoring but also records the attacker's target in the log. Under most threat models this is acceptable (the event should be logged with enough detail to investigate), but if the URL contained query-string credentials it could still leak. Given that SSRF-blocked URLs are inherently malicious or misconfigured inputs, the operational value of logging the full URL outweighs the risk.
- **Recommendation:** No immediate action required. If consistent URL truncation is preferred across the codebase, replace `url=url` with `url_host=urlparse(url).netloc` here too. Otherwise, annotate with a comment explaining why the full URL is intentionally logged in this security event.

---

## Checks Performed (No Findings)

**3.1 Hardcoded Secrets** — Webhook secrets generated with `secrets.token_urlsafe(32)`. No hardcoded credentials in any verified file. All settings come from `get_settings()` / env vars.

**3.2 Auth Bypass Paths** — `/api/v1/metrics/` correctly removed from `_PUBLIC_PREFIXES`. Webhook endpoints still require `CurrentAccountDep`. No unexpected public path additions.

**3.3 SQL Injection** — All DB access in verified files uses SQLAlchemy ORM parameterized queries (`select()`, `update()`, `func.count()`). No f-string SQL.

**3.4 Agent Isolation** — Webhook subscriptions scoped to `account_id`. `_get_owned_sub()` ownership check unchanged and correct. Subscription count query (`COUNT(*) WHERE account_id = account.id`) correctly scoped.

**3.5 Rate Limit Coverage** — No changes to rate limit tiers. Webhook endpoints remain under `general` tier (600 req/min). Metrics endpoint, now requiring auth, still falls under `general` tier.

**3.7 Password / Secret Handling** — Webhook `secret` no longer in Celery task args. Secret fetched from DB at delivery time only. `WebhookCreateResponse` includes secret once; all other response schemas omit it (confirmed).

**3.8 Input Validation** — All three `DeflatedSharpeRequest` bounds confirmed. `ranking_metric` validator is now a proper `@field_validator`. `session_id: UUID` confirmed across all backtest handlers. Webhook subscription count limit confirmed.

**3.9 CORS** — No CORS configuration changes. Pre-existing wildcard CORS gap (from 2026-03-30 audit) unaffected by this change set.

**3.10 WebSocket Auth** — No WebSocket changes in this audit scope.

**3.11 Dependency Vulnerabilities** — No new `eval()`, `exec()`, `pickle`, or unsafe imports in verified files.

**3.12 Circuit Breaker** — No order execution paths in the changed endpoints.

**3.13 HTTPS Enforcement** — HTTPS enforcement now coded (not just documented) in `validate_webhook_url()`.

**3.14 / 3.15 / 3.16 Frontend** — No frontend files in this audit scope.

---

## Notes

1. **DNS rebinding is an accepted residual risk.** Both `dispatcher.py` and `webhook_tasks.py` document this limitation clearly. The defence-in-depth check in the Celery task reduces the window but cannot eliminate it. The recommendation from the original audit (egress network policy at the container level as a complementary control) remains valid and is outside the scope of application code.

2. **The metrics endpoint is now authenticated.** The original audit noted that the "public" justification (agents need to call it without API keys) was weak because agents do have API keys. The endpoint now requires auth, which is the correct posture. However, `metrics.py` still documents the endpoint as "public" in its module docstring (line 14). This documentation should be updated to reflect the new auth requirement. This is a documentation issue only, not a security finding.

3. **`ignore_result=True` on `dispatch_webhook` means Celery result tracking is disabled.** This is the correct fix for the secret-in-backend issue. The trade-off is that callers cannot use `result.get()` to check task completion. The `dispatch_webhook` task was already fire-and-forget (`fire_event()` does not wait for results), so this trade-off is acceptable.

4. **Per-account limit uses `settings.per_account_webhook_limit`.** The default of 25 aligns exactly with the original recommendation. The `ge=1` constraint on the config field prevents accidental misconfiguration to zero. The error message includes both the limit and current count in the `details` field for good UX.
