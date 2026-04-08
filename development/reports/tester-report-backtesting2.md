# Backtest A-Z Retest Report

**Date:** 2026-04-06 (evening session)
**Account:** shalom@trader.com + bttest@trader.com (fresh)
**Previous report:** `REPORT-backtest-az.md` (17 bugs found)

---

## Executive Summary

Retested all 17 backtest bugs. **10 FIXED, 1 PARTIALLY FIXED, 3 NOT FIXED, 3 BLOCKED (cannot verify).**

**Critical blocker:** The backtest engine is **completely down platform-wide**. Every new session immediately transitions from "created" to "failed" regardless of account, agent, interval, or date range. This blocks retesting of 3 bugs (stop-loss triggers, by_pair population, stop_price display) that require a running backtest.

---

## Bug-by-Bug Verification

### FIXED (10 bugs)

| Bug | Severity | What Changed |
|-----|----------|-------------|
| **BT-03** | P1 | End-before-start dates now rejected: `"end_time must be after start_time"` |
| **BT-05** | P1 | Fake agent_id now returns `"Agent not found"` (was `INTERNAL_ERROR`) |
| **BT-06** | P1 | Non-standard intervals rejected: `"must be one of [60, 300, 3600, 86400]"` |
| **BT-08** | P2 | Compare with fake session now returns `"Sessions not found"` error |
| **BT-09** | P2 | Compare requires minimum 2 sessions: `"At least 2 session IDs required"` |
| **BT-10** | P2 | Invalid metric now shows valid options: `['max_drawdown_pct', 'profit_factor', 'roi_pct', 'sharpe_ratio', ...]` |
| **BT-11** | P2 | Best by sharpe now returns actual value `"0.9400"` (was `"N/A"`) |
| **BT-12** | P2 | Balance capped at 10,000,000 (was unlimited) |
| **BT-14** | P3 | Failed sessions show starting_balance as final_equity `"10000.00000000"` (was `"0"`) |
| **BT-15** | P3 | Error messages now specific: `"has already completed"` / `"has already failed"` (was generic `"not active"`) |

### PARTIALLY FIXED (1 bug)

| Bug | Severity | What Changed |
|-----|----------|-------------|
| **BT-13** | P3 | Cancelled sessions: results endpoint shows `null` for incomplete metrics (correct). Compare endpoint shows `"0"` instead of `null` (improved from `"100%"` drawdown, but `"0"` is also wrong — should be `null`) |

### NOT FIXED (3 bugs)

| Bug | Severity | Current Behavior |
|-----|----------|-----------------|
| **BT-01** | **P0** | **BACKTEST ENGINE DOWN** — every new session fails immediately. Tested with: 3 agents (ShalomBot, AlphaTrader, BacktestBot), 2 accounts (shalom@trader.com, bttest@trader.com), all 4 intervals, multiple date ranges, both auth methods. All fail. |
| **BT-07** | P2 | Invalid symbols still accepted (`"FAKECOINUSDT"` → `estimated_pairs: 0`). Should reject upfront. |
| **BT-16** | P3 | Missing `agent_id` still defaults to user's agent silently. Should either error or document this behavior. |

### CANNOT VERIFY (3 bugs — require running backtest)

| Bug | Severity | Why Blocked |
|-----|----------|-------------|
| **BT-02** | **P0** | Stop-loss trigger requires stepping through price movements — needs running backtest |
| **BT-04** | P1 | `by_pair` fix may only apply to newly completed backtests — old data shows empty. Needs new completed backtest. |
| **BT-17** | P3 | `stop_price` field in order list — needs running backtest with pending stop orders |

---

## New Observations

### Improved Error Messages
The error reporting has been significantly improved:
- `"Backtest session has already failed"` (was `"not active"`)
- `"Backtest session has already completed"` (was `"not active"`)
- `"Cannot start backtest in 'failed' state"` with `details.current_status` and `details.required_status`
- `"Agent {id} not found"` (was `"unexpected error"`)
- `"end_time must be after start_time"` (was silently accepted)
- `"candle_interval must be one of [60, 300, 3600, 86400]"` (was silently accepted)

### Validation Improvements
- Candle interval now whitelisted: only 60, 300, 3600, 86400 accepted
- Balance range: 1 to 10,000,000
- Date ordering enforced
- Agent existence validated with proper error code
- Compare minimum 2 sessions enforced
- Best metric validated with list of options

### Fresh Account Registration
- New registration flow works: `bttest@trader.com` created with auto-agent
- Returns `agent_id` and `agent_api_key` in response
- Fresh account has same backtest failure — confirms platform-wide issue

---

## Test Matrix

| Test | V1 Result | V2 (Retest) | Status |
|------|-----------|-------------|--------|
| Create 1h backtest | PASS | FAIL (engine down) | REGRESSION |
| Create 5m backtest | FAIL | FAIL | NOT FIXED |
| Create 1m backtest | FAIL | FAIL | NOT FIXED |
| Create 1d backtest | FAIL | FAIL | NOT FIXED |
| Step single candle | PASS (was) | BLOCKED | — |
| Batch step | PASS (was) | BLOCKED | — |
| Market order in sandbox | PASS (was) | BLOCKED | — |
| Limit order trigger | PASS (was) | BLOCKED | — |
| Stop-loss trigger | FAIL | BLOCKED | — |
| Take-profit trigger | UNTESTED | BLOCKED | — |
| Cancel order in sandbox | PASS (was) | BLOCKED | — |
| Sandbox balance | PASS (was) | BLOCKED | — |
| Sandbox positions | PASS (was) | BLOCKED | — |
| Sandbox portfolio | PASS (was) | BLOCKED | — |
| Sandbox market price | PASS (was) | BLOCKED | — |
| Results endpoint | PASS | PASS | OK |
| Equity curve | PASS | PASS | OK |
| Trade log | PASS | PASS | OK |
| List with filters | PASS | PASS | OK |
| Compare 2+ sessions | PASS | PASS | OK |
| Compare 1 session | BUG | FIXED | FIXED |
| Compare fake session | BUG | FIXED | FIXED |
| Best by metric | PASS | PASS | OK |
| Best invalid metric | BUG | FIXED | FIXED |
| Best sharpe N/A | BUG | FIXED | FIXED |
| Cancel running backtest | PASS (was) | BLOCKED | — |
| End before start dates | BUG | FIXED | FIXED |
| Dates before data range | PASS | PASS | OK |
| Zero/negative balance | PASS | PASS | OK |
| Fake agent_id | BUG | FIXED | FIXED |
| Non-standard interval | BUG | FIXED | FIXED |
| Invalid symbol | BUG | NOT FIXED | OPEN |
| Huge balance | BUG | FIXED | FIXED |
| Missing agent_id | BUG | NOT FIXED | OPEN |
| Failed session equity | BUG | FIXED | FIXED |
| Error messages | BUG | FIXED | FIXED |
| by_pair breakdown | BUG | BLOCKED | — |

---

## Priority Actions for Dev Team

### URGENT (must fix before any testing can continue)
1. **BUG-BT-01: Backtest engine is down.** Every new session fails immediately on all accounts. This is a server-side/infrastructure issue. Check:
   - Celery worker health (backtests likely use async task processing)
   - Redis connection (session state management)
   - TimescaleDB query performance (historical data loading)
   - Application logs for unhandled exceptions during backtest initialization
   - Memory/resource limits on worker processes

### After engine is fixed
2. **BUG-BT-02:** Verify stop-loss orders trigger during batch stepping
3. **BUG-BT-04:** Verify `by_pair` populates on newly completed backtests
4. **BUG-BT-07:** Validate symbol names against available pairs
5. **BUG-BT-16:** Document or enforce agent_id requirement

---

## Accounts Created During Testing

| Account | Email | Agent |
|---------|-------|-------|
| BacktestTester | bttest@trader.com | 308cd56c (auto-created) |
| BacktestBot (agent) | — | 85b55a8b (under shalom@trader.com) |

---

*Generated: 2026-04-06*
