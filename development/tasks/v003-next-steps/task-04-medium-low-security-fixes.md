---
task_id: 4
title: "Medium/Low security fixes (5 items)"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1, 3]
status: "pending"
priority: "medium"
board: "[[v003-next-steps/README]]"
files:
  - "src/api/schemas/strategies.py"
  - "src/api/routes/webhooks.py"
  - "src/config.py"
  - "src/api/routes/backtest.py"
  - "src/api/routes/indicators.py"
  - "src/tasks/webhook_tasks.py"
tags:
  - task
  - security
  - quick-fixes
---

# Task 04: Medium/Low Security Fixes (5 items)

## Assigned Agent: `backend-developer`

## Objective
Fix the 5 remaining medium/low security audit findings in a single pass.

## Context
Security audit found 3 MEDIUM and 3 LOW issues. These are quick fixes that can be batched together.

## Files to Modify/Create

### 4a. Fix `ranking_metric` validator — `src/api/schemas/strategies.py`
- Replace dead `model_post_init` with `@field_validator("ranking_metric", mode="before")`
- Remove orphaned `_validate_metric` classmethod

### 4b. Per-account webhook limit — `src/api/routes/webhooks.py` + `src/config.py`
- Before `db.add(sub)`, query `COUNT(*) WHERE account_id = account.id`
- Reject with HTTP 422 if count >= 25
- Add `per_account_webhook_limit: int = 25` to settings in `src/config.py`

### 4c. Upgrade session_id to UUID — `src/api/routes/backtest.py`
- Change `session_id: str` to `session_id: UUID` in ALL backtest route handlers
- FastAPI auto-validates format, returns 422 for invalid

### 4d. Increase cache key hash — `src/api/routes/indicators.py`
- Change `hexdigest()[:8]` to `hexdigest()[:16]`

### 4e. Redact URL in logs — `src/tasks/webhook_tasks.py`
- Replace `url=url` with `url_host=urlparse(url).netloc` in failure warning log
- Add `from urllib.parse import urlparse` import

## Acceptance Criteria
- [ ] 4a: `ranking_metric` validated via `@field_validator`, `model_post_init` removed
- [ ] 4b: Webhook creation rejected when account has >= 25 subscriptions
- [ ] 4c: All backtest `session_id` params are `UUID` type, invalid UUIDs return 422
- [ ] 4d: Indicator cache key uses 16-char hex digest
- [ ] 4e: Webhook failure logs show `url_host` not full URL
- [ ] `ruff check` passes
- [ ] Existing tests still pass

## Dependencies
- **Task 1** (SSRF fix modifies `webhooks.py`) — avoid merge conflicts
- **Task 3** (secret fix modifies `webhook_tasks.py`) — avoid merge conflicts

## Agent Instructions
1. These are 5 independent micro-fixes — do them sequentially in one pass
2. For 4b: use existing settings pattern from `src/config.py` — grep for `Settings` class
3. For 4c: import UUID from `uuid` module, update all handlers in backtest.py
4. Run `ruff check` after all changes

## Estimated Complexity
Low — 5 trivial changes, each under 10 lines.
