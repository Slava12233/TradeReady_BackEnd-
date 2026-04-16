---
task_id: 01
title: "Live Platform Health Check — API & Services"
type: task
agent: "deploy-checker"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/01-live-platform-health.md"
tags:
  - task
  - audit
  - infrastructure
  - health-check
---

# Task 01: Live Platform Health Check — API & Services

## Assigned Agent: `deploy-checker`

## Objective
Hit the production TradeReady API to verify all core services are running, responding, and healthy. This is the foundational check — if the API is down, nothing else matters.

## Context
The platform is deployed in production at tradeready.io. We need to verify it's actually working before assessing customer readiness. Last known status: deployed with CI/CD, but Track A (data loading) was blocked and Docker had port conflicts.

## Checks to Perform

### 1. Health Endpoint
```bash
curl -s https://tradeready.io/api/v1/health | python -m json.tool
```
- **Pass:** Returns `{"status": "healthy"}` with component statuses (DB, Redis, ingestion)
- **Fail:** Returns error, timeout, or unhealthy components

### 2. API Documentation
```bash
curl -s -o /dev/null -w "%{http_code}" https://tradeready.io/docs
curl -s -o /dev/null -w "%{http_code}" https://tradeready.io/redoc
```
- **Pass:** HTTP 200 for both
- **Fail:** 404 or 500

### 3. Market Data Flowing
```bash
curl -s https://tradeready.io/api/v1/market/pairs | python -m json.tool | head -20
curl -s https://tradeready.io/api/v1/market/prices | python -m json.tool | head -20
```
- **Pass:** Returns non-empty list of pairs and current prices
- **Fail:** Empty response, error, or stale prices (check timestamps)

### 4. WebSocket Connectivity
Test if WebSocket endpoint accepts connections:
```bash
# Use wscat or python websocket-client
python -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('wss://tradeready.io/ws/v1') as ws:
        await ws.send(json.dumps({'action': 'subscribe', 'channel': 'ticker', 'symbol': 'BTCUSDT'}))
        msg = await asyncio.wait_for(ws.recv(), timeout=10)
        print('WS OK:', msg[:100])
asyncio.run(test())
"
```
- **Pass:** Receives ticker data within 10s
- **Fail:** Connection refused, timeout, or error

### 5. Database Migration Status
```bash
# Via SSH to production server
docker compose exec -T api alembic current
# Should show: head at 023
```

### 6. Docker Service Status
```bash
# Via SSH to production server
docker compose ps
# All services should show "healthy" or "running"
```

### 7. Response Times
For each endpoint tested, record response time. Flag any >500ms.

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/01-live-platform-health.md`:

```markdown
# Sub-Report 01: Live Platform Health Check

**Date:** 2026-04-15
**Agent:** deploy-checker
**Overall Status:** PASS / PARTIAL / FAIL

## Results

| Check | Status | Response Time | Notes |
|-------|--------|---------------|-------|
| Health endpoint | PASS/FAIL | Xms | |
| API docs | PASS/FAIL | Xms | |
| Market pairs | PASS/FAIL | Xms | N pairs returned |
| Market prices | PASS/FAIL | Xms | N prices, freshness |
| WebSocket | PASS/FAIL | Xms | |
| Migration head | PASS/FAIL | — | Current: 0XX |
| Docker services | PASS/FAIL | — | N/N healthy |

## Critical Issues
- {list any failures}

## Recommendations
- {list any fixes needed}
```

## Acceptance Criteria
- [ ] All 7 checks attempted
- [ ] Response times recorded for each HTTP check
- [ ] Sub-report written with clear PASS/FAIL per check
- [ ] Critical issues identified with severity
- [ ] If API is unreachable, report immediately as P0 blocker

## Estimated Complexity
Medium — straightforward HTTP requests but requires production access
