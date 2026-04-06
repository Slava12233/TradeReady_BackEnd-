# Backtest A-Z Test Report

**Date:** 2026-04-06
**Account:** shalom@trader.com (ShalomBot agent)
**Tester:** Claude (automated)

---

## Executive Summary

Ran comprehensive A-Z testing of the backtesting system. **45 tests executed, 28 PASS, 17 FAIL/BUG.**

The backtest system works for the basic happy path (create → step → trade → results on 1h candles) but has **critical reliability issues** — after running one successful backtest, all subsequent backtest creations silently fail. Additionally, stop-loss orders don't trigger, and input validation has significant gaps.

---

## Backtest #1: BTC Momentum Strategy (COMPLETED)

| Parameter | Value |
|-----------|-------|
| Period | 2025-01-01 to 2025-06-30 |
| Interval | 1h (3600s) |
| Pairs | BTCUSDT, ETHUSDT |
| Starting Balance | $10,000 |
| Strategy Label | `btc_momentum_v1` |
| Session ID | `9a345663-fb95-4835-982a-b5d273f9a519` |

### Strategy Executed
- Jan 1: Bought 0.05 BTC @ $94,601 + 1.0 ETH @ $3,360
- Jan 1: Placed limit buy 0.02 BTC @ $90,000 (filled Feb 25 @ $88,689)
- Jan 1: Placed stop-loss sell 0.02 BTC @ $85,000 (**NEVER TRIGGERED — BUG**)
- Jan 1: Placed take-profit sell 0.5 ETH @ $4,000 (never reached)
- Jan 31: Sold 0.5 ETH @ $3,300 (weak momentum, realized PnL: -$30)
- Mar 31: Bought 0.5 ETH @ $1,822 (dip buy)
- Jun 30: Auto-closed all positions at backtest end

### Results
| Metric | Value |
|--------|-------|
| Final Equity | $10,836.78 |
| ROI | +8.37% |
| Total Trades | 7 |
| Win Rate | 33.33% |
| Profit Factor | 7.30 |
| Sharpe Ratio | 0.94 |
| Sortino Ratio | 1.04 |
| Max Drawdown | 28.25% |
| Total Fees | $22.41 |
| Duration (real) | 93 seconds |

### Price Journey (Jan-Jun 2025)
| Month | BTC | ETH | Portfolio |
|-------|-----|-----|-----------|
| Jan 1 | $94,591 | $3,360 | $10,000 |
| Jan 31 | $102,429 | $3,300 | $10,323 |
| Feb 28 | $84,349 | $2,237 | $8,797 |
| Mar 31 | $82,550 | $1,822 | $8,463 |
| Apr 30 | $94,172 | $1,793 | $9,247 |
| May 31 | $104,591 | $2,528 | $10,711 |
| Jun 30 | $107,146 | $2,485 | $10,847 |

---

## Backtest #2: Multi-pair (FAILED TO CREATE)

Every subsequent backtest creation failed immediately — see BUG-BT-01 below.

---

## Bugs Found

### P0 — Critical (Blocks Core Functionality)

#### BUG-BT-01: Backtest system breaks after initial use — all new sessions fail silently

**Severity:** P0 — **Blocks all subsequent backtesting**
**Reproduction:**
1. Create and complete one backtest successfully
2. Create any new backtest (any params, any agent, any auth method)
3. Session transitions from "created" to "failed" within seconds
4. No error message returned — `status` endpoint shows `"status": "failed"` with no details
5. Stepping returns `BACKTEST_NOT_FOUND: "is not active"`

**Tested variations (all fail):**
- Different intervals: 1m (60s), 5m (300s), 1h (3600s), 1d (86400s)
- Different date ranges: Jan, Feb, Jun, Jul, Oct 2025
- Different pair counts: 1, 2, 5 pairs
- Different agents: ShalomBot, AlphaTrader
- Different auth: API key, JWT
- After clearing stuck sessions: still fails

**Impact:** Users can only run ONE backtest per agent/account lifetime. Complete blocker for strategy iteration.

**Likely cause:** Server-side resource cleanup issue. The first backtest completes but leaves some lock or state that prevents new sessions from initializing. The `failed` status with no error details suggests an unhandled exception in the initialization path.

---

#### BUG-BT-02: Stop-loss orders never trigger in backtest

**Severity:** P0 — **Risk management non-functional**
**Reproduction:**
1. In a running backtest, place a stop-loss: `{"symbol":"BTCUSDT","side":"sell","type":"stop_loss","quantity":"0.02","stop_price":"85000"}`
2. Batch-step through a period where BTC drops below $85,000 (Feb 2025: BTC hit $84,349)
3. Stop-loss remains "pending" — never triggers
4. Order shows `"price": null` in the order list (stop_price not persisted)

**Impact:** AI agents cannot implement risk management strategies. Stop-loss is fundamental to any trading system.

**Note:** Limit buy orders DO trigger correctly (the $90K limit buy filled at $88,689).

---

### P1 — High

#### BUG-BT-03: End date before start date accepted — creates session with negative steps

**Severity:** P1
**Reproduction:**
```json
POST /backtest/create
{"start_time": "2025-06-01T00:00:00Z", "end_time": "2025-01-01T00:00:00Z", ...}
```
**Response:** `{"total_steps": -3624, "status": "created"}`
**Expected:** Validation error rejecting invalid date range.

---

#### BUG-BT-04: `by_pair` always returns empty array

**Severity:** P1
**Reproduction:** `GET /backtest/{sid}/results` on a completed session with multiple pairs traded.
**Response:** `"by_pair": []` — always empty.
**Expected:** Per-pair breakdown showing trades, win_rate, net_pnl for each symbol.
**Impact:** Users can't evaluate which pairs contributed to performance.

---

#### BUG-BT-05: Fake agent_id returns INTERNAL_ERROR instead of proper error

**Severity:** P1
**Reproduction:**
```json
POST /backtest/create
{"agent_id": "00000000-0000-0000-0000-000000000000", ...}
```
**Response:** `{"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}}`
**Expected:** `{"error": {"code": "AGENT_NOT_FOUND", "message": "Agent not found"}}`

---

#### BUG-BT-06: Non-standard candle intervals silently accepted

**Severity:** P1
**Reproduction:** `{"candle_interval": 999}` — accepted, creates session.
**Expected:** Validation error. Available intervals are 60, 300, 3600, 86400 (1m, 5m, 1h, 1d).
**Impact:** Session will have no data and fail at initialization.

---

### P2 — Medium

#### BUG-BT-07: Invalid symbol in `pairs` silently accepted

**Severity:** P2
**Reproduction:** `{"pairs": ["FAKECOINUSDT"]}` — accepted, `estimated_pairs: 0`.
**Expected:** Validation error: symbol not found.

---

#### BUG-BT-08: Compare silently ignores non-existent session IDs

**Severity:** P2
**Reproduction:** `GET /backtest/compare?sessions=valid_id,fake_id` — returns results for valid_id only, no warning.
**Expected:** Error or warning about missing session.

---

#### BUG-BT-09: Compare accepts single session

**Severity:** P2
**Reproduction:** `GET /backtest/compare?sessions=single_id` — returns "comparison" of 1 session.
**Expected:** Require minimum 2 sessions for comparison.

---

#### BUG-BT-10: Best endpoint accepts invalid metrics without error

**Severity:** P2
**Reproduction:** `GET /backtest/best?metric=fake_metric` — returns `"value": "N/A"`.
**Expected:** Validation error listing valid metrics (roi_pct, sharpe_ratio, etc.).

---

#### BUG-BT-11: Best by sharpe returns "N/A" despite valid data

**Severity:** P2
**Reproduction:** `GET /backtest/best?metric=sharpe_ratio` — returns `"value": "N/A"`.
**Actual data:** Completed backtest has `sharpe_ratio: "0.9400"`.
**Expected:** Should return `"value": "0.9400"`.

---

#### BUG-BT-12: No upper limit on starting_balance

**Severity:** P2
**Reproduction:** `{"starting_balance": 1000000000}` — accepted (1 billion USDT).
**Expected:** Reasonable upper limit (e.g., 1,000,000) to prevent potential overflow/precision issues.

---

### P3 — Low

#### BUG-BT-13: Cancelled sessions show max_drawdown: 100% and sharpe: 0

**Severity:** P3
**Reproduction:** View results for a cancelled session in compare endpoint.
**Response:** `"max_drawdown_pct": "100"`, `"sharpe_ratio": "0"`
**Expected:** `null` for incomplete data, or actual partial values.

---

#### BUG-BT-14: Failed session shows final_equity: 0

**Severity:** P3
**Reproduction:** `GET /backtest/{failed_session}/results`
**Response:** `"final_equity": "0"`
**Expected:** Should show starting_balance since no trades occurred.

---

#### BUG-BT-15: Error message for completed/failed backtest is misleading

**Severity:** P3
**Reproduction:** `POST /backtest/{completed_sid}/step`
**Response:** `"Backtest session is not active"` 
**Expected:** `"Backtest session is already completed"` or `"already failed"` — more specific.

---

#### BUG-BT-16: Missing agent_id silently defaults to user's default agent

**Severity:** P3
**Reproduction:** Omit `agent_id` from create request.
**Response:** Creates successfully using default agent.
**Expected:** Could be by design, but docs say `agent_id` is required.

---

#### BUG-BT-17: stop_price not reflected in order list

**Severity:** P3
**Reproduction:** Place stop-loss/take-profit with `stop_price`, then list orders.
**Response:** `"price": null` — the trigger price is lost.
**Expected:** Should display `stop_price` or `trigger_price` field.

---

## What Works Well

| Feature | Status | Notes |
|---------|--------|-------|
| Create backtest (first time) | PASS | Returns session_id, total_steps, estimated_pairs |
| Start backtest | PASS | Auto-starts on create |
| Single step | PASS | Returns prices, portfolio, progress correctly |
| Batch step (60, 672, 720, 744, 1000) | PASS | All batch sizes work, progress tracking accurate |
| Market buy/sell in sandbox | PASS | Fills instantly with slippage simulation |
| Limit buy | PASS | Triggers when price crosses level |
| Cancel order | PASS | Cleans up pending order |
| Sandbox balance endpoint | PASS | Shows locked/available correctly |
| Sandbox positions endpoint | PASS | Tracks avg_entry_price, quantity |
| Sandbox portfolio endpoint | PASS | Equity, unrealized/realized PnL, position details |
| Sandbox open orders | PASS | Lists pending orders |
| Sandbox market price | PASS | Returns virtual-time price |
| Sandbox all prices | PASS | Returns all watched pair prices |
| Auto-close at completion | PASS | Positions automatically liquidated at end |
| Results endpoint | PASS | ROI, Sharpe, Sortino, drawdown, fees, win rate |
| Equity curve | PASS | Time-series snapshots showing portfolio journey |
| Trade log | PASS | Full trade history with fees, slippage, PnL |
| List backtests | PASS | Filters by status, strategy_label, sort_by |
| Compare sessions | PASS | Side-by-side metrics with recommendation |
| Best by metric | PASS | Finds top session |
| Cancel running backtest | PASS | Saves partial results |
| Status endpoint | PASS | Shows progress, config, timestamps |
| Slippage simulation | PASS | 0.01% applied to all trades |
| Fee calculation | PASS | 0.1% fee on all trades |
| Date validation (too old) | PASS | Rejects dates before data range |
| Balance validation (0/negative) | PASS | Rejects properly |
| Interval validation (0) | PASS | Requires minimum 60s |

---

## Test Summary

| Category | Pass | Fail | Total |
|----------|------|------|-------|
| Session lifecycle | 5 | 2 | 7 |
| Stepping | 5 | 0 | 5 |
| Order types in sandbox | 3 | 1 | 4 |
| Sandbox endpoints | 7 | 0 | 7 |
| Results/metrics | 4 | 3 | 7 |
| List/compare/best | 3 | 3 | 6 |
| Input validation | 4 | 5 | 9 |
| **Total** | **28** | **17** | **45** |

---

## Recommendations for Dev Team

### Must Fix (Sprint 1)
1. **BUG-BT-01:** Investigate why backtests fail after first use. Likely a resource leak, lock file, or Redis state issue. Add proper error logging to capture the initialization failure reason.
2. **BUG-BT-02:** Stop-loss order trigger logic. Verify that pending stop-loss orders are evaluated during batch stepping. The `stop_price` may not be persisted correctly (shows null in orders).

### Should Fix (Sprint 2)
3. **BUG-BT-03:** Add date range validation (end > start).
4. **BUG-BT-04:** Implement `by_pair` breakdown in results.
5. **BUG-BT-05:** Catch agent lookup failures and return proper error.
6. **BUG-BT-06:** Validate candle_interval against supported values.

### Nice to Fix (Sprint 3)
7. Input validation: invalid symbols, single-session compare, invalid metrics.
8. Better error messages for completed/failed sessions.
9. Upper limit on starting_balance.
10. Failed session should show starting_balance as final_equity.

---

## What the User Will See in UI

When you log into the UI at `shalom@trader.com`:
- **1 completed backtest** (`btc_momentum_v1`) with full results, equity curve, and trade log
- **2 cancelled backtests** from previous testing (partial results)
- **12+ failed backtests** — these may clutter the UI
- **ShalomBot agent** with live positions (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, XRP)

---

*Generated: 2026-04-06*
