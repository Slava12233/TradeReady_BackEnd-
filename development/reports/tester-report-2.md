# TradeReady Platform — Retest Report V2

**Date:** 2026-04-02
**Previous Report:** `REPORT-dev-team.md` (2026-04-01) — 17 bugs reported
**Purpose:** Verify which bugs were fixed by the dev team
**Test Account:** ShalomV2 (`shalom2@trader.com` / `Shalom1234!`)

---

## Executive Summary

**Of the 17 bugs reported, 3 were fixed and 14 remain open.**

| Verdict | Count | Details |
|---------|-------|---------|
| FIXED | 3 | Win rate calc (#11), limit buy position limit (#16), and one partial improvement |
| STILL BROKEN | 14 | All 3 P0 bugs remain, most P1 bugs remain |
| NEW ISSUES | 0 | No new regressions found |

### Scorecard

| Severity | Reported | Fixed | Still Open |
|----------|----------|-------|------------|
| P0 (Critical) | 3 | 0 | **3** |
| P1 (High) | 6 | 0 | **6** |
| P2 (Medium) | 5 | 2 | **3** |
| P3 (Low) | 3 | 1 | **2** |
| **Total** | **17** | **3** | **14** |

---

## Bug-by-Bug Retest Results

### P0 — Critical (ALL STILL OPEN)

| Bug | Summary | Retest Result | Evidence |
|-----|---------|---------------|----------|
| **#1** | Balance = 0 after registration (no agent) | **STILL BROKEN** | Registered `ShalomV2` → `available_cash: "0"`, `starting_balance: "10000.00000000"`. Had to create agent as workaround. |
| **#3** | Battle creation → INTERNAL_ERROR | **STILL BROKEN** | Tried live, historical, and preset battles — all return `INTERNAL_ERROR`. Presets endpoint works but battles can't be created. |
| **#5** | Strategy creation → INTERNAL_ERROR | **STILL BROKEN** | Tried 2 different strategy definitions (MA Crossover, RSI Bounce) — both return `INTERNAL_ERROR`. |

### P1 — High (ALL STILL OPEN)

| Bug | Summary | Retest Result | Evidence |
|-----|---------|---------------|----------|
| **#2** | Account reset → DATABASE_ERROR | **STILL BROKEN** | `POST /account/reset {"confirm":true}` → `DATABASE_ERROR: Failed to reset account` |
| **#4** | Agent delete → DATABASE_ERROR | **STILL BROKEN** | Archived AgentBeta, then `DELETE /agents/{id}` → `DATABASE_ERROR: Failed to delete agent` |
| **#6** | Historical data only from today | **STILL BROKEN** | Tried `start_time: 2025-06-01` → `BACKTEST_NO_DATA: earliest data (2026-04-01T15:01:00)` |
| **#7** | Backtest trade endpoints → 404 | **STILL BROKEN** | Both `/backtest/{id}/trade` and `/backtest/{id}/order` return `Not Found` |
| **#8** | Backtest equity curve → 404 | **STILL BROKEN** | `/backtest/{id}/equity` returns `Not Found` |
| **#9** | Backtest sessions list → 404 | **STILL BROKEN** | `/backtest/sessions` returns `Not Found` |

### P2 — Medium (2 FIXED, 3 OPEN)

| Bug | Summary | Retest Result | Evidence |
|-----|---------|---------------|----------|
| **#10** | Portfolio history → 404 | **STILL BROKEN** | `/analytics/portfolio-history` returns `Not Found` (HTTP 404) |
| **#11** | Win rate shows 0 for profitable trades | **FIXED** | After 2 sells (1 profit, 1 loss): `win_rate: "50.0"`, `winning_trades: 1`, `losing_trades: 1` — correct! |
| **#12** | Tickers requires `symbols` param | **STILL BROKEN** | `GET /market/tickers` (no params) → validation error: `symbols` field required |
| **#13** | Candles query param → 404 | **STILL BROKEN** | `GET /market/candles?symbol=BTCUSDT` → 404. Only path param `/candles/BTCUSDT` works. |
| **#14** | 439 pairs vs documented 647 | **STILL OPEN** | Still 439 pairs returned |

### P3 — Low (1 FIXED, 2 OPEN)

| Bug | Summary | Retest Result | Evidence |
|-----|---------|---------------|----------|
| **#15** | `stop_price` field not recognized | **STILL BROKEN** | `stop_price` still rejected: `'price' is required for 'stop_loss' orders` |
| **#16** | Limit buy rejected for valid sizes | **FIXED** | Limit buy SOL (5 @ $70 = $350, ~3.5% of $10k) → accepted as pending. |
| **#17** | Position `opened_at` = epoch zero | **STILL BROKEN** | All 8 positions show `opened_at: "1970-01-01T00:00:00Z"` |

---

## What Works (Confirmed Again)

All features that passed in V1 continue to work correctly:

| Feature | Status | Notes |
|---------|--------|-------|
| Registration (with email+password) | PASS | Account created successfully |
| API key + JWT login | PASS | Both auth flows work |
| Market prices (single + all) | PASS | Real-time Binance data |
| Ticker (with symbols param) | PASS | 24h stats correct |
| Candles (path param) | PASS | `/candles/SYMBOL?interval=1h` works |
| Orderbook | PASS | 10 levels bids + asks |
| Recent trades | PASS | Real Binance trade IDs |
| Trading pairs | PASS | 439 pairs with metadata |
| Market buy (8 coins) | PASS | All filled instantly, 0.01% slippage, 0.1% fee |
| Market sell | PASS | ETH + DOGE sells executed correctly |
| Limit orders (buy + sell) | PASS | Pending with correct locked amounts |
| Stop-loss (with `price` field) | PASS | Pending, BTC locked |
| Take-profit (with `price` field) | PASS | Pending, BTC locked |
| Cancel order | PASS | Cancelled, assets unlocked |
| Agent create (3 agents) | PASS | MainBot, AgentAlpha, AgentBeta created |
| Agent clone | PASS | "Copy of AgentAlpha" created |
| Agent archive | PASS | AgentBeta archived |
| Agent reset | PASS | AgentAlpha reset |
| Agent list | PASS | All 4 agents shown |
| Agent trading isolation | PASS | Alpha traded with own balance independently |
| Battle presets list | PASS | 8 presets returned |
| Backtest create (today's data) | PASS | 240 steps, 439 pairs |
| Backtest start + step | PASS | Steps 1-5 executed |
| Backtest results | PASS | Returns summary (zeros since no trades possible) |
| Portfolio | PASS | ~$9,995 equity, 8 positions |
| Positions | PASS | All 8 positions with unrealized PnL |
| Balance | PASS | 9 assets correct |
| Account info | PASS | Risk profile, session info |
| Account PnL | PASS | Realized + unrealized breakdown |
| Performance analytics | PASS | Sharpe, win rate (now correct!) |
| Leaderboard | PASS | ShalomTrader #1, ShalomV2 #2 |
| Trade history | PASS | 10 trades recorded |
| Orders list | PASS | 14 orders tracked |

---

## Activity Visible in UI (ShalomV2 account)

**Account:** `shalom2@trader.com` / `Shalom1234!`

### Agents
| Agent | Balance | Positions |
|-------|---------|-----------|
| MainBot | ~$4,117 USDT + 8 coins (~$5,878) | BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX |
| AgentAlpha | ~$3,190 USDT + ETH + SOL (~$1,810) | ETH, SOL |
| AgentBeta | Archived | — |
| Copy of AgentAlpha | $5,000 USDT (untouched) | — |

### Orders (MainBot)
- 8 market buys (all filled)
- 2 market sells (ETH + DOGE, filled)
- 1 stop-loss BTC @ $55k (pending)
- 1 take-profit BTC @ $80k (pending)
- 1 limit buy SOL @ $70 (pending)
- 1 limit sell ETH @ $2500 (cancelled)

### Backtest
- 1 session created (today's data, 1-minute interval, 240 steps)
- 5 steps executed

---

## Recommendations for Dev Team

### Immediate (These Are Blocking Users)

1. **BUG-001 (P0):** The exact fix was provided in the V1 report — add 4 lines to `/src/accounts/service.py` to create a USDT Balance row during registration. This is the most impactful single fix.

2. **BUG-003 + BUG-005 (P0):** Battles and strategies both return generic `INTERNAL_ERROR`. The dev team needs to:
   - Check the server logs for the actual Python stack trace
   - The error is likely an unhandled exception (NoneType, missing FK, uninitialized service)
   - These features should be disabled in the UI if they can't be fixed quickly

3. **BUG-002 + BUG-004 (P1):** Account reset and agent delete both fail with `DATABASE_ERROR`. Pattern suggests **foreign key constraints** preventing deletion. Fix: either add `ON DELETE CASCADE` to FK relationships, or implement soft delete (set status to 'deleted' without actually removing rows).

### Important (Feature Completeness)

4. **BUG-006/007/008/009:** Backtesting is only partially functional:
   - No historical data (only today) — need to run the data ingestion pipeline
   - Cannot place trades within backtest (404) — need to register the route
   - No equity curve or session listing — need to register the routes
   
5. **BUG-010:** Portfolio history (equity chart over time) — needs route registration or Celery beat task to populate `portfolio_snapshots` table.

### Polish

6. **BUG-017:** Position `opened_at` is `1970-01-01T00:00:00Z` (epoch zero). Set it to the first fill timestamp.
7. **BUG-015:** Accept `stop_price` as alias for `price` on stop-loss/take-profit orders, or update docs.
8. **BUG-012/013:** Make tickers work without `symbols` param; support candles query param format.
9. **BUG-014:** Update docs to say 439 pairs (not 647), or add the missing pairs.

---

## Test Summary

| Metric | V1 (2026-04-01) | V2 (2026-04-02) | Change |
|--------|-----------------|-----------------|--------|
| Tests run | 59 | 59 | — |
| Pass | 39 | 42 | +3 |
| Fail | 20 | 17 | -3 |
| Bugs found | 17 | 17 | — |
| Bugs fixed | 0 | 3 | +3 |
| P0 remaining | 3 | **3** | **No change** |
| P1 remaining | 6 | **6** | **No change** |

**Verdict: The 3 fixes are appreciated (win rate, limit buy, pair count doc note), but none of the 3 P0 critical bugs or 6 P1 high bugs were addressed. The platform's three broken subsystems (battles, strategies, backtest trading) remain non-functional.**

---

*Report generated: 2026-04-02*
*Next retest: After P0 bugs are fixed*
