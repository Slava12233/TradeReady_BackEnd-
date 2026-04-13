---
task_id: C-06
title: "Verify trade in DB + API"
type: task
agent: "e2e-tester"
track: C
depends_on: ["C-05"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: []
tags:
  - task
  - e2e
  - validation
  - trading
---

# Task C-06: Verify trade in DB + API

## Assigned Agent: `e2e-tester`

## Objective
Confirm the executed trade from C-05 appears correctly in the database and is accessible through the API.

## Acceptance Criteria
- [ ] Trade exists in `trades` table: `SELECT * FROM trades WHERE agent_id = '<agent_id>' ORDER BY created_at DESC LIMIT 1;`
- [ ] Position updated in `positions` table for the traded pair
- [ ] Balance deducted correctly in `account_balances`
- [ ] Trade visible via API: `GET /api/v1/trades?agent_id=<agent_id>`
- [ ] Trade details match expected values (pair, side, size, price)
- [ ] No orphaned or duplicate records

## Dependencies
- **C-05**: Trade must have been executed

## Agent Instructions
Run database queries to verify:
```sql
-- Check trade
SELECT id, agent_id, symbol, side, quantity, price, status, created_at 
FROM trades WHERE agent_id = '<agent_id>' ORDER BY created_at DESC LIMIT 5;

-- Check position
SELECT * FROM positions WHERE agent_id = '<agent_id>';

-- Check balance
SELECT * FROM account_balances WHERE account_id = '<account_id>';
```
Also verify via API:
```bash
curl -H "Authorization: Bearer <api_key>" http://localhost:8000/api/v1/trades
curl -H "Authorization: Bearer <api_key>" http://localhost:8000/api/v1/portfolio
```

## Estimated Complexity
Low — verification queries.
