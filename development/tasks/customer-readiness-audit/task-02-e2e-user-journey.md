---
task_id: 02
title: "Live Platform Health Check — E2E User Journey"
type: task
agent: "e2e-tester"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/02-e2e-user-journey.md"
tags:
  - task
  - audit
  - e2e
  - user-journey
---

# Task 02: Live Platform Health Check — E2E User Journey

## Assigned Agent: `e2e-tester`

## Objective
Simulate a complete new-customer journey on the live production platform: register an account, create an agent, check market data, place a trade, view portfolio, and run a backtest. This validates the golden path that every customer will follow.

## Context
The platform auto-creates a default agent at registration (BUG-001 fix from QA sprint). Each agent gets an API key, starting balance of 10,000 USDT, and default risk profile. We need to verify this entire flow works end-to-end on production.

## Steps to Execute

### Step 1: Register a New Account
```bash
curl -X POST https://tradeready.io/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "audit_test_user_20260415", "password": "AuditTest2026!Secure"}'
```
Record: `account_id`, `agent_id`, `agent_api_key`, `jwt_token`

### Step 2: Login and Get JWT
```bash
curl -X POST https://tradeready.io/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "audit_test_user_20260415", "password": "AuditTest2026!Secure"}'
```
Record: `access_token`

### Step 3: Check Account Balance
```bash
curl -s https://tradeready.io/api/v1/account/balance \
  -H "X-API-Key: {agent_api_key}"
```
Verify: USDT balance = 10,000

### Step 4: Check Market Data
```bash
curl -s "https://tradeready.io/api/v1/market/price/BTCUSDT" \
  -H "X-API-Key: {agent_api_key}"
```
Verify: Returns current BTC price

### Step 5: Place a Market Buy Order
```bash
curl -X POST https://tradeready.io/api/v1/trade/order \
  -H "X-API-Key: {agent_api_key}" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.001}'
```
Record: `order_id`, execution details

### Step 6: Check Portfolio
```bash
curl -s https://tradeready.io/api/v1/account/positions \
  -H "X-API-Key: {agent_api_key}"
```
Verify: Shows BTC position

### Step 7: Place a Market Sell Order
```bash
curl -X POST https://tradeready.io/api/v1/trade/order \
  -H "X-API-Key: {agent_api_key}" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "sell", "type": "market", "quantity": 0.001}'
```
Verify: Order executed, position closed

### Step 8: Check Trade History
```bash
curl -s https://tradeready.io/api/v1/trade/history \
  -H "X-API-Key: {agent_api_key}"
```
Verify: Shows buy and sell trades

### Step 9: Check PnL
```bash
curl -s https://tradeready.io/api/v1/account/pnl \
  -H "X-API-Key: {agent_api_key}"
```
Verify: Returns PnL data

### Step 10: Create a Backtest (if historical data exists)
```bash
curl -X POST https://tradeready.io/api/v1/backtest/create \
  -H "X-API-Key: {agent_api_key}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Audit Test Backtest",
    "symbol": "BTCUSDT",
    "interval": "1h",
    "initial_balance": 10000,
    "strategy": {"type": "rule_based", "entry_conditions": [{"indicator": "rsi", "operator": "lt", "value": 30}], "exit_conditions": [{"indicator": "rsi", "operator": "gt", "value": 70}]}
  }'
```
Note: This may fail if no historical data is loaded — record this as a finding.

### Step 11: List Agents
```bash
curl -s https://tradeready.io/api/v1/agents \
  -H "Authorization: Bearer {jwt_token}" \
  -H "X-Agent-Id: {agent_id}"
```
Verify: Shows the default agent created at registration

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/02-e2e-user-journey.md`:

```markdown
# Sub-Report 02: E2E User Journey

**Date:** 2026-04-15
**Agent:** e2e-tester
**Overall Status:** PASS / PARTIAL / FAIL

## Test Account Credentials
- Username: audit_test_user_20260415
- Agent API Key: {key} (for UI verification)

## Journey Results

| Step | Action | Status | Response Time | Notes |
|------|--------|--------|---------------|-------|
| 1 | Register | PASS/FAIL | Xms | |
| 2 | Login | PASS/FAIL | Xms | |
| 3 | Check balance | PASS/FAIL | Xms | Balance: X USDT |
| 4 | Market data | PASS/FAIL | Xms | BTC price: $X |
| 5 | Buy order | PASS/FAIL | Xms | |
| 6 | Portfolio | PASS/FAIL | Xms | |
| 7 | Sell order | PASS/FAIL | Xms | |
| 8 | Trade history | PASS/FAIL | Xms | |
| 9 | PnL | PASS/FAIL | Xms | |
| 10 | Backtest | PASS/FAIL/SKIP | Xms | |
| 11 | List agents | PASS/FAIL | Xms | |

## Critical Issues
- {list any failures that block customer usage}

## UX Pain Points
- {list any confusing responses, missing data, unhelpful errors}
```

## Acceptance Criteria
- [ ] All 11 steps attempted on production
- [ ] Test account credentials recorded for UI verification
- [ ] Response times logged
- [ ] Any failure includes the full error response
- [ ] UX pain points noted (confusing errors, missing info, etc.)

## Estimated Complexity
Medium — sequential HTTP calls, but depends on production being reachable
