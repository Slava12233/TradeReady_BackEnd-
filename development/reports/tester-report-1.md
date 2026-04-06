# TradeReady Platform — QA Bug Report

**Date:** 2026-04-01
**Tester:** QA Team (automated + manual via API)
**Environment:** Production (`https://api.tradeready.io/api/v1`)
**Scope:** Full A-Z platform test — 59 tests across 12 domains

---

## Executive Summary

We performed a comprehensive end-to-end test of the TradeReady platform covering authentication, market data, trading, account management, analytics, backtesting, multi-agent, battles, strategies, and edge cases.

**Results: 39 PASS | 20 FAIL — 17 unique bugs discovered**

| Severity | Count | Impact |
|----------|-------|--------|
| P0 (Critical) | 3 | Three entire subsystems are broken or unusable |
| P1 (High) | 6 | Major features fail, some with workarounds |
| P2 (Medium) | 5 | Incorrect data, missing endpoints |
| P3 (Low) | 3 | Documentation mismatches, minor UX issues |

### Platform Health by Domain

| Domain | Tests | Pass | Fail | Verdict |
|--------|-------|------|------|---------|
| Authentication | 8 | 6 | 2 | OK |
| Market Data | 10 | 7 | 3 | OK |
| Trading | 10 | 8 | 2 | OK |
| Account | 6 | 5 | 1 | OK |
| Analytics | 3 | 2 | 1 | OK |
| Backtesting | 6 | 3 | 3 | PARTIAL |
| Multi-Agent | 7 | 6 | 1 | OK |
| Battles | 5 | 1 | 4 | **BROKEN** |
| Strategies | 4 | 1 | 3 | **BROKEN** |

**Bottom line:** Core trading loop works (register, create agent, buy/sell, check portfolio). But three advanced subsystems — **battles, strategies, and backtest trading** — are completely non-functional in production. These should not be advertised until fixed.

---

## P0 — Critical Bugs (Fix Immediately)

### BUG-001: New accounts have zero balance — cannot trade after registration

**Severity:** P0 (blocks entire user onboarding flow)
**Domain:** Account / Registration
**Endpoint:** `POST /auth/register` + `GET /account/portfolio`

**Steps to reproduce:**
```bash
# 1. Register a new account
curl -s -X POST "https://api.tradeready.io/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "TestUser", "starting_balance": "10000.00"}'

# 2. Check portfolio (use returned api_key)
curl -s "https://api.tradeready.io/api/v1/account/portfolio" \
  -H "X-API-Key: <returned_api_key>"
```

**Expected:** `available_cash: "10000.00"`, `total_equity: "10000.00"`
**Actual:** `available_cash: "0"`, `total_equity: "0"`, `starting_balance: "10000.00000000"`

**Impact:** Every new user sees $0 balance despite the registration confirming $10,000. All trade orders fail with `ORDER_REJECTED: insufficient_balance`. Tested on 3 separate accounts — 100% reproducible.

**Root cause (confirmed via code review):**
`AccountService.register()` in `/src/accounts/service.py` (line ~196) creates the Account row with `starting_balance` metadata but **does not create a USDT Balance row** in the `balances` table. The code comment at line 198-200 says: *"Balance and TradingSession creation is handled by AgentService.create_agent()"*. This means the balance only exists when an agent is created.

**Workaround:** Create an agent immediately after registration — this triggers `AgentService.create_agent()` which creates the Balance row.

**Recommended fix:**
Add USDT Balance row creation inside `AccountService.register()` after the Account is persisted:
```python
# In /src/accounts/service.py, after line 196 (session.flush)
initial_balance = Balance(
    account_id=account.id,
    asset="USDT",
    available=balance_amount,
    locked=Decimal("0"),
)
self._session.add(initial_balance)
await self._session.flush()
```

---

### BUG-003: Battle creation fails with INTERNAL_ERROR — entire battle system broken

**Severity:** P0 (entire feature unusable)
**Domain:** Battles
**Endpoints:** `POST /battles`

**Steps to reproduce:**
```bash
# Get JWT first (required for battle endpoints)
JWT=$(curl -s -X POST ".../auth/login" -d '{"api_key":"...","api_secret":"..."}' | ...)

# Try creating a live battle
curl -s -X POST "https://api.tradeready.io/api/v1/battles" \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Battle","type":"live","agent_ids":["<id1>","<id2>"],"duration_minutes":5}'

# Try with a preset
curl -s -X POST ".../battles" -d '{"name":"Quick","preset":"quick_1h","agent_ids":["<id1>","<id2>"]}'

# Try historical
curl -s -X POST ".../battles" -d '{"name":"Historical","type":"historical","agent_ids":["<id1>","<id2>"],"start_date":"2025-01-15","end_date":"2025-01-20"}'
```

**Expected:** Battle created with battle_id returned
**Actual:** `{"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred."}}` for ALL formats

**Impact:** The battle system is a headline feature (agent vs agent competitions). It is 100% broken. The presets endpoint (`GET /battles/presets`) works and returns 8 presets, but none can be used. The UI shows battle functionality that simply doesn't work.

**Recommended investigation:**
- Check `/src/api/routes/battles.py` for the create endpoint handler
- Look for unhandled exceptions (likely a NoneType error, missing DB relation, or uninitialized service)
- Check server logs for the actual stack trace behind `INTERNAL_ERROR`
- The generic error message suggests the exception is being caught by a global handler without specific error mapping

---

### BUG-005: Strategy creation fails with INTERNAL_ERROR — entire strategy system broken

**Severity:** P0 (entire feature unusable, also blocks RL training)
**Domain:** Strategies
**Endpoint:** `POST /strategies`

**Steps to reproduce:**
```bash
# Tried 3 different payload formats — all fail identically

# Format 1: entry/exit conditions with definition wrapper
curl -s -X POST ".../strategies" -H "X-API-Key: ..." \
  -d '{"name":"MA Crossover","description":"...","definition":{"entry_conditions":[...],"exit_conditions":[...]}}'

# Format 2: simplified definition
curl -s -X POST ".../strategies" -d '{"name":"RSI","description":"...","definition":{"type":"rule_based","indicators":["rsi"],"entry":{"rsi_below":30},"exit":{"rsi_above":70}}}'

# Format 3: empty definition
curl -s -X POST ".../strategies" -d '{"name":"Test","description":"test","definition":{}}'
```

**Expected:** Strategy created with strategy_id
**Actual:** `{"error":{"code":"INTERNAL_ERROR","message":"An unexpected error occurred."}}` for ALL formats

**Impact:** Cannot create, test, compare, or deploy any strategies. RL training depends on the strategy system, so it is also blocked. This removes two major platform differentiators.

**Recommended investigation:**
- Check `/src/api/routes/strategies.py` for the create handler
- Verify the Pydantic schema for `StrategyCreateRequest` matches what the frontend sends
- Check for missing DB migrations or uninitialized tables
- Look for the stack trace in server logs

---

## P1 — High Priority Bugs

### BUG-002: Account reset returns DATABASE_ERROR

**Endpoint:** `POST /account/reset`
**Payload:** `{"confirm": true}` (with or without `starting_balance`)
**Response:** `{"error":{"code":"DATABASE_ERROR","message":"Failed to reset account."}}`
**Impact:** Users cannot reset their paper trading account to start fresh. This is important for the learning/experimentation use case.
**Recommendation:** Check the reset handler — likely a foreign key constraint issue when trying to delete trades/orders/positions that reference other tables.

---

### BUG-004: Agent deletion returns DATABASE_ERROR

**Endpoint:** `DELETE /agents/{agent_id}`
**Response:** `{"error":{"code":"DATABASE_ERROR","message":"Failed to delete agent."}}`
**Impact:** Cannot clean up agents. Archive works as a workaround but doesn't free resources.
**Recommendation:** Same foreign key issue pattern as BUG-002. The `agents` table likely has FK references from `balances`, `orders`, `trades`, `positions` that prevent cascade delete. Add `ON DELETE CASCADE` or implement soft delete.

---

### BUG-006: Historical backtest data unavailable — only today's data exists

**Endpoint:** `POST /backtest/create`
**Payload:** `{"symbol":"BTCUSDT","start_time":"2025-01-15T00:00:00Z","end_time":"2025-01-20T00:00:00Z","interval":"1h","starting_balance":"10000.00"}`
**Response:** `{"error":{"code":"BACKTEST_NO_DATA","message":"Start time 2025-01-15T00:00:00+00:00 is before earliest data (2026-04-01T15:01:00+00:00)."}}`
**Impact:** Documentation claims data from 2025-01-01 to 2026-02-22 (647 pairs, 6 intervals). Actual earliest data is only from today. The entire backtesting value proposition (test against historical data) is severely limited.
**Recommendation:** Either load historical candle data into TimescaleDB or update documentation to reflect actual data availability. This is likely a data ingestion issue — the `ticks` hypertable may only contain data since the last deployment.

---

### BUG-007: Backtest trade/order endpoints return 404

**Endpoints:** `POST /backtest/{session_id}/trade`, `POST /backtest/{session_id}/order`
**Response:** `{"detail":"Not Found"}`
**Impact:** Backtests can be created and stepped through, but no trades can be placed during a backtest. This makes the backtest engine useless since results will always show zero PnL.
**Recommendation:** These routes may not be registered in the FastAPI router. Check `/src/api/routes/backtest.py` for missing route decorators or commented-out endpoints.

---

### BUG-008: Backtest equity curve endpoint returns 404

**Endpoint:** `GET /backtest/{session_id}/equity`
**Response:** `{"detail":"Not Found"}`
**Recommendation:** Likely same root cause as BUG-007 — route not registered.

---

### BUG-009: Backtest sessions list endpoint returns 404

**Endpoint:** `GET /backtest/sessions`
**Response:** `{"detail":"Not Found"}`
**Note:** Backtest create is at `POST /backtest/create` (not `/backtest/sessions`), so the listing endpoint may use a different path. Check the actual registered routes.

---

## P2 — Medium Priority Bugs

### BUG-010: Portfolio history endpoint returns 404

**Endpoint:** `GET /analytics/portfolio-history`
**Response:** `{"detail":"Not Found"}`
**Impact:** Users cannot view their equity curve over time in the UI. The `portfolio_snapshots` hypertable may not be populated by the Celery beat task, or the route is not registered.

---

### BUG-011: Win rate calculation is incorrect

**Endpoint:** `GET /analytics/performance`
**Observation:** After executing 2 sell trades (1 ETH sell at profit, 1 DOGE sell at profit), the response shows:
```json
{
  "win_rate": "0.0",
  "winning_trades": 0,
  "losing_trades": 2,
  "best_trade": "-0.04855000",
  "worst_trade": "-0.20559930"
}
```
**Problem:** Both sells should show as winning trades (sold above cost), but the system counts them as losses. The PnL calculation may be comparing against the wrong reference price or not accounting for the buy cost basis correctly.
**Recommendation:** Review the trade PnL calculation in `/src/portfolio/tracker.py` or `/src/metrics/` — it may be using realized PnL after fees, which could make small-profit trades appear as losses.

---

### BUG-012: Tickers endpoint requires `symbols` parameter

**Endpoint:** `GET /market/tickers` (without parameters)
**Response:** `{"detail":[{"type":"missing","loc":["query","symbols"],"msg":"Field required"}]}`
**Expected:** Return all tickers when no `symbols` param is provided (like `/market/prices` does)
**Recommendation:** Make `symbols` optional with a default of "return all" or a sensible subset.

---

### BUG-013: Candles endpoint only accepts path parameter, not query parameter

**Working:** `GET /market/candles/BTCUSDT?interval=1h&limit=3`
**Not working:** `GET /market/candles?symbol=BTCUSDT&interval=1h&limit=3` (404)
**Impact:** API inconsistency — other endpoints like `/market/price/SYMBOL` use path params, but the docs/skill reference uses query params. Frontend may be using the wrong format.
**Recommendation:** Support both, or update all documentation to match the actual path-param style.

---

### BUG-014: Pair count mismatch (439 vs documented 647)

**Endpoint:** `GET /market/pairs`
**Actual:** 439 pairs
**Documented:** 647 pairs
**Recommendation:** Update docs or investigate why 208 pairs are missing (possibly delisted or filtered by volume/status).

---

## P3 — Low Priority / Documentation Issues

### BUG-015: Stop-loss/take-profit field name inconsistency

**Documented field:** `stop_price`
**Actual required field:** `price`
**Error when using `stop_price`:** `"Value error, 'price' is required for 'stop_loss' orders."`
**Recommendation:** Either accept `stop_price` as an alias, or update all documentation and SDK examples.

---

### BUG-016: Limit buy rejected with position_limit_exceeded for valid sizes

**Scenario:** Account with $10,000 equity. Placed a limit buy for 0.01 BTC (~$680, which is 6.8% of equity — well under the 25% limit).
**Response:** `ORDER_REJECTED: position_limit_exceeded`
**Note:** This may be because the account already had a BTC position from market buys, and the combined position would exceed 25%. But the error message doesn't explain this — it should say "combined position would exceed limit" with current + requested amounts.
**Recommendation:** Improve error message to include current position size, requested addition, and the limit.

---

### BUG-017: Position `opened_at` timestamp is epoch zero

**Endpoint:** `GET /account/positions`, `GET /account/portfolio`
**Observation:** All positions show `"opened_at": "1970-01-01T00:00:00Z"` instead of the actual trade timestamp.
**Recommendation:** Set `opened_at` to the first trade's `filled_at` timestamp when creating a position, or the earliest trade timestamp when aggregating.

---

## Additional Observations & Recommendations

### What Works Well

1. **Market data** is fast and accurate — real Binance prices via WebSocket ingestion
2. **Trading engine** fills market orders instantly with realistic slippage + fees
3. **Agent isolation** is properly implemented — each agent has independent balances and positions
4. **Error responses** use a consistent format: `{"error": {"code": "X", "message": "Y", "details": {...}}}`
5. **Authentication** is solid — bcrypt(12), JWT with proper expiry, API key/secret separation
6. **SVG avatar generation** for agents is a nice touch
7. **API response times** are consistently under 500ms

### Architecture Concerns

1. **DATABASE_ERROR pattern:** Three different endpoints (account reset, agent delete, backtest operations) return the same generic `DATABASE_ERROR`. This suggests foreign key constraints are not properly handled. Consider:
   - Adding `ON DELETE CASCADE` where appropriate
   - Implementing soft deletes (set `status = 'deleted'` instead of actual deletion)
   - Returning specific error messages ("cannot delete agent with open positions")

2. **INTERNAL_ERROR pattern:** Both battles and strategies return generic `INTERNAL_ERROR`. This usually means an unhandled Python exception. These errors should:
   - Be logged with full stack traces (check if they are)
   - Return more specific error codes
   - Not expose "An unexpected error occurred" to users — this erodes trust

3. **Missing 404 routes:** Multiple documented endpoints return 404 (backtest trade/equity/sessions, portfolio-history). This suggests either:
   - Routes were written but not registered in the FastAPI router
   - The router file was not included in `main.py`'s `app.include_router()` calls
   - The endpoints exist but under different paths than documented

### Documentation vs Reality

| Item | Documentation Says | Reality |
|------|--------------------|---------|
| Historical data range | 2025-01-01 to 2026-02-22 | Only today's data available |
| Pair count | 647 | 439 |
| Stop-loss field | `stop_price` | `price` |
| Symbols | Must be UPPERCASE | Lowercase auto-converts |
| Slippage | Dynamic based on order size | Flat 0.01% |
| Backtest create field | `start_date` / `end_date` | `start_time` / `end_time` |
| Candles endpoint | Query param `?symbol=X` | Path param `/candles/X` |

### Recommended Fix Priority

**Sprint 1 (This Week) — Unblock Users:**
1. Fix BUG-001 (balance at registration) — 30 min fix, code change identified
2. Fix BUG-002 + BUG-004 (database delete errors) — likely FK cascade issue
3. Fix BUG-017 (opened_at timestamp) — quick model fix

**Sprint 2 (Next Week) — Restore Features:**
4. Fix BUG-003 (battles) — debug INTERNAL_ERROR, check server logs
5. Fix BUG-005 (strategies) — debug INTERNAL_ERROR, check server logs
6. Fix BUG-007/008/009 (backtest endpoints) — register missing routes

**Sprint 3 — Data & Polish:**
7. Fix BUG-006 (load historical data) — data ingestion task
8. Fix BUG-010/011/012/013 (analytics, tickers, candles) — medium effort
9. Fix BUG-014/015/016 (docs, error messages) — low effort
10. Update all documentation to match actual API behavior

---

## Test Environment Details

**Account used:** ShalomTrader (`shalom@trader.com`)
**Account ID:** `edf27381-190c-4b02-91dd-72952ad3a711`
**Agents created:** ShalomBot, AlphaTrader, BetaTrader, GammaBot (+ 1 clone)
**Orders placed:** 14 total (10 filled, 3 pending, 1 cancelled)
**Total spent:** ~$7,465 across 8 cryptocurrencies
**Backtests run:** 1 session, 15 steps
**Battle attempts:** 3 (all failed)
**Strategy attempts:** 3 (all failed)

**Tools used:** `curl` + bash scripts against the production API.
**Codebase reviewed:** `/src/accounts/service.py`, `/src/portfolio/tracker.py`, `/src/api/routes/`, `/src/database/models.py` in the AiTradingAgent repository.

---

*Report generated: 2026-04-01*
*Next review: After Sprint 1 fixes are deployed*
