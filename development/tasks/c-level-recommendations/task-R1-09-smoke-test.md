---
task_id: R1-09
title: "Run smoke test (10-step validation)"
type: task
agent: "e2e-tester"
phase: 1
depends_on: ["R1-08"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
completed_at: "2026-03-23"
files:
  - agent/workflows/smoke_test.py
  - agent/logging.py
  - sdk/agentexchange/async_client.py
  - agent/.env
tags:
  - task
  - infrastructure
  - testing
  - e2e
---

# Task R1-09: Run Smoke Test

## Assigned Agent: `e2e-tester`

## Objective
Run the 10-step connectivity validation to confirm the full platform stack works end-to-end.

## Context
The smoke test validates SDK connectivity, order execution, and health endpoints without requiring an LLM. It's the definitive proof that infrastructure is operational.

## Acceptance Criteria
- [x] `python -m agent.main smoke` completes with all 10 steps passing
- [x] Output shows `status: pass` for each step
- [x] No connection errors or timeouts

## Result: PASS (10/10 steps, 0 bugs)

### Steps Completed
1. BTC price: 71046.94 USDT
2. Balance: USDT 9978.66 (SmokeBot agent)
3. Candles: 10 BTCUSDT 1h candles returned
4. Market buy: BTCUSDT 0.0001 @ 71054.04 — status=filled
5. Position: BTCUSDT 0.0004 BTC held
6. Trade history: 3 trades returned
7. Performance metrics: sharpe=0.0, win_rate=0.0, total_trades=0
8. Health: GET /health → 200, status=degraded (stale pairs; core services OK)
9. Market prices: 447 pairs returned
10. Compilation: 0 bugs found

### Fixes Applied
Three bugs were found and fixed during this run:

1. **structlog 25.5.0 incompatibility** (`agent/logging.py`): `structlog.stdlib.add_logger_name`
   requires a stdlib logger with `.name` attribute. `PrintLoggerFactory` produces `PrintLogger`
   which lacks `.name`. Removed `add_logger_name` from the processor chain.

2. **SDK agent-key fallback** (`sdk/agentexchange/async_client.py`): `AsyncAgentExchangeClient`
   always attempted JWT login via `POST /api/v1/auth/login`, which only accepts account-level
   keys. Agent keys (agent-scoped `ak_live_` keys) caused ACCOUNT_NOT_FOUND on every request.
   Added graceful fallback: when login returns `ACCOUNT_NOT_FOUND` or `INVALID_API_KEY`, the
   client sets `_api_key_only=True` and uses the persistent `X-API-Key` header for all requests.

3. **Health endpoint path** (`agent/workflows/smoke_test.py`): Step 8 called `GET /api/v1/health`
   which does not exist (returns 404). The health endpoint is mounted at `/health` (no `/api/v1`
   prefix). Fixed the path.

### agent/.env Updated
- `PLATFORM_API_KEY` now uses the SmokeBot agent key (agent-scoped, has 10,000 USDT balance)
- `MOMENTUM_AGENT_API_KEY` preserved as comment reference for the Task R1-08 provisioned agent
- `SMOKE_ACCOUNT_API_KEY` / `SMOKE_ACCOUNT_SECRET` stored for the SmokeTestAccount if needed

## Dependencies
- R1-08 (agents must be provisioned with valid API keys)

## Agent Instructions
1. Run `python -m agent.main smoke`
2. Review output for any failures
3. If failures occur, check service connectivity and agent credentials

## Estimated Complexity
Low — single command, LLM-free validation
