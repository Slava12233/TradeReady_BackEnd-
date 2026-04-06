# Test Results Summary

> Pass/fail status for every feature tested, organized by domain.
> **53 tests run | 34 PASS | 2 PARTIAL | 17 FAIL/BUG**

---

## 1. Authentication (6/8 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 1.1 | Register new account (API only) | PASS | 2026-04-01 | Works instantly, returns api_key + api_secret |
| 1.2 | Register with email + password | PASS | 2026-04-01 | Email/password optional, enables UI login |
| 1.3 | Login with API key + secret | PASS | 2026-04-01 | `POST /auth/login` — returns JWT, 1hr expiry |
| 1.4 | Login with email + password | PASS | 2026-04-01 | `POST /auth/user-login` — returns same JWT |
| 1.5 | API Key auth on endpoints | PASS | 2026-04-01 | `X-API-Key` header works on market/account |
| 1.6 | JWT auth on agents/battles | PASS | 2026-04-01 | Works for agent CRUD, battle presets |
| 1.7 | Invalid symbol error | PASS | 2026-04-01 | Returns proper `INVALID_SYMBOL` error |
| 1.8 | Account reset | BUG | 2026-04-01 | DATABASE_ERROR — Bug #2 |

## 2. Market Data (7/10 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 2.1 | Get single price (8 coins) | PASS | 2026-04-01 | BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX all work |
| 2.2 | Get all prices | PASS | 2026-04-01 | Returns all as key-value map |
| 2.3 | Get ticker (single) | PASS | 2026-04-01 | Full 24h stats with volume, change% |
| 2.4 | Get tickers (multiple) | PARTIAL | 2026-04-01 | Works with `?symbols=` but no "get all" — Bug #12 |
| 2.5 | Get candles | PARTIAL | 2026-04-01 | Path param works (`/candles/BTCUSDT`), query param 404 — Bug #13 |
| 2.6 | Get orderbook | PASS | 2026-04-01 | 10 bids + 10 asks |
| 2.7 | Get recent trades | PASS | 2026-04-01 | Trade IDs, prices, quantities |
| 2.8 | Get trading pairs | PASS | 2026-04-01 | 439 pairs (docs say 647 — Bug #14) |
| 2.9 | Lowercase symbol | PASS | 2026-04-01 | Auto-converts (but docs say UPPERCASE required) |
| 2.10 | Invalid symbol | PASS | 2026-04-01 | Correct error response |

## 3. Trading (8/10 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 3.1 | Market buy (8 coins) | PASS | 2026-04-01 | All filled instantly, 0.01% slippage, 0.1% fee |
| 3.2 | Market sell | PASS | 2026-04-01 | Sold 0.1 ETH + 1000 DOGE |
| 3.3 | Limit buy order | PASS | 2026-04-01 | SOL @ $70 — pending, $350.35 locked |
| 3.4 | Limit sell order | PASS | 2026-04-01 | ETH @ $3000 — pending, then cancelled |
| 3.5 | Stop-loss order | PASS | 2026-04-01 | BTC @ $60k — needs `price` not `stop_price` (Bug #15) |
| 3.6 | Take-profit order | PASS | 2026-04-01 | BTC @ $80k — pending |
| 3.7 | Cancel order | PASS | 2026-04-01 | Cancelled limit sell, unlocked 0.2 ETH |
| 3.8 | Order history | PASS | 2026-04-01 | 14 orders tracked correctly |
| 3.9 | Trade history | PASS | 2026-04-01 | 10 trades with full details |
| 3.10 | Position limit enforcement | BUG | 2026-04-01 | Limit buy rejected even under 25% — Bug #16 |

## 4. Account (5/6 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 4.1 | Get balance | PASS | 2026-04-01 | 9 assets shown correctly |
| 4.2 | Get positions | PASS | 2026-04-01 | 8 positions with unrealized PnL, but `opened_at` is epoch — Bug #17 |
| 4.3 | Get portfolio | PASS | 2026-04-01 | Full summary with equity, cash, position value |
| 4.4 | Get account info | PASS | 2026-04-01 | Shows risk_profile, session info |
| 4.5 | Get PnL | PASS | 2026-04-01 | Realized: -$0.25, Unrealized: +$6.95 |
| 4.6 | Reset account | BUG | 2026-04-01 | DATABASE_ERROR — Bug #2 |

## 5. Analytics (2/3 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 5.1 | Performance metrics | PASS | 2026-04-01 | Shows sharpe, win_rate (but win_rate wrong — Bug #11) |
| 5.2 | Portfolio history | BUG | 2026-04-01 | 404 Not Found — Bug #10 |
| 5.3 | Leaderboard | PASS | 2026-04-01 | ShalomTrader rank #1 |

## 6. Backtesting (3/6 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 6.1 | Create backtest | PASS | 2026-04-01 | Works only with today's data — Bug #6 |
| 6.2 | Start backtest | PASS | 2026-04-01 | Status → running |
| 6.3 | Step through | PASS | 2026-04-01 | 15 steps done, prices for 326 pairs per step |
| 6.4 | Place backtest trade | BUG | 2026-04-01 | 404 Not Found — Bug #7 |
| 6.5 | Get equity curve | BUG | 2026-04-01 | 404 Not Found — Bug #8 |
| 6.6 | List sessions | BUG | 2026-04-01 | 404 Not Found — Bug #9 |

## 7. Multi-Agent (6/7 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 7.1 | Create agent (x3) | PASS | 2026-04-01 | AlphaTrader, BetaTrader, GammaBot created |
| 7.2 | List agents | PASS | 2026-04-01 | All 4 agents shown with avatars + colors |
| 7.3 | Clone agent | PASS | 2026-04-01 | "Copy of AlphaTrader" created |
| 7.4 | Reset agent | PASS | 2026-04-01 | BetaTrader reset successfully |
| 7.5 | Archive agent | PASS | 2026-04-01 | GammaBot archived (both POST and PUT work) |
| 7.6 | Delete agent | BUG | 2026-04-01 | DATABASE_ERROR — Bug #4 |
| 7.7 | Agent trading | PASS | 2026-04-01 | Alpha + Beta placed trades with their own API keys |

## 8. Battles (1/5 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 8.1 | List battle presets | PASS | 2026-04-01 | 8 presets returned correctly |
| 8.2 | Create live battle | BUG | 2026-04-01 | INTERNAL_ERROR — Bug #3 |
| 8.3 | Create historical battle | BUG | 2026-04-01 | INTERNAL_ERROR — Bug #3 |
| 8.4 | Create battle with preset | BUG | 2026-04-01 | INTERNAL_ERROR — Bug #3 |
| 8.5 | List battles | PASS | 2026-04-01 | Returns empty (none could be created) |

## 9. Strategies (1/4 pass)

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 9.1 | Create strategy | BUG | 2026-04-01 | INTERNAL_ERROR — Bug #5 |
| 9.2 | List strategies | PASS | 2026-04-01 | Returns empty (none could be created) |
| 9.3 | Test strategy | BLOCKED | | Can't test — creation broken |
| 9.4 | Compare strategies | BLOCKED | | Can't test — creation broken |

## 10. RL Training

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 10.1 | Start training run | NOT TESTED | | Requires working strategy system |
| 10.2 | Observe episodes | NOT TESTED | | |
| 10.3 | Learning curves | NOT TESTED | | |

## 11. WebSocket

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 11.1 | Ticker stream | NOT TESTED | | Needs interactive WebSocket client |
| 11.2 | Candle stream | NOT TESTED | | |
| 11.3 | Order updates | NOT TESTED | | |
| 11.4 | Portfolio updates | NOT TESTED | | |

## 12. Edge Cases

| # | Test | Status | Date | Notes |
|---|------|--------|------|-------|
| 12.1 | Invalid symbol | PASS | 2026-04-01 | Proper INVALID_SYMBOL error |
| 12.2 | Position limit | PASS | 2026-04-01 | Correctly rejects >25% equity |
| 12.3 | Lowercase symbol | PASS | 2026-04-01 | Auto-converts (unexpected but works) |

---

## Summary

| Domain | Pass | Fail/Bug | Total | Health |
|--------|------|----------|-------|--------|
| Authentication | 6 | 2 | 8 | OK |
| Market Data | 7 | 3 | 10 | OK |
| Trading | 8 | 2 | 10 | OK |
| Account | 5 | 1 | 6 | OK |
| Analytics | 2 | 1 | 3 | OK |
| Backtesting | 3 | 3 | 6 | PARTIAL |
| Multi-Agent | 6 | 1 | 7 | OK |
| Battles | 1 | 4 | 5 | BROKEN |
| Strategies | 1 | 3 | 4 | BROKEN |
| **Total** | **39** | **20** | **59** | |

**17 unique bugs found (3 P0, 6 P1, 5 P2, 3 P3)**

---

_Last updated: 2026-04-01_
