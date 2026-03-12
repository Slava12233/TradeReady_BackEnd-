# Backtesting Guide — How It Works A-Z

## What is Backtesting?

Backtesting lets you replay historical market data and test a trading strategy against it. Instead of waiting 30 real days to see if your strategy works, you can simulate 30 days of trading in minutes. Your trading code (buy/sell orders) works identically in backtest and live mode.

---

## The Big Picture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Your Agent  │────>│   REST API   │────>│   Backtest   │
│  (any code)  │<────│  /backtest/* │<────│    Engine    │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                          ┌───────────────────────┼───────────────────────┐
                          │                       │                       │
                   ┌──────┴──────┐   ┌────────────┴──────┐   ┌──────────┴──────┐
                   │    Time     │   │     Sandbox       │   │     Data        │
                   │  Simulator  │   │  (fake exchange)  │   │    Replayer     │
                   │             │   │                   │   │                 │
                   │ Ticks the   │   │ Handles orders,   │   │ Loads prices    │
                   │ virtual     │   │ balances,         │   │ from DB into    │
                   │ clock       │   │ positions,        │   │ memory          │
                   │ forward     │   │ fees, slippage    │   │                 │
                   └─────────────┘   └───────────────────┘   └─────────────────┘
```

---

## Step-by-Step Lifecycle

### 1. Check What Data You Have

```
GET /market/data-range
```

Returns the earliest and latest dates with historical price data, how many trading pairs are available, and what candle intervals exist (1m, 5m, 1h, 1d). You can only backtest within this range.

### 2. Create a Session

```
POST /backtest/create
{
  "start_time": "2025-06-01T00:00:00Z",
  "end_time": "2025-07-01T00:00:00Z",
  "starting_balance": 10000,
  "candle_interval": "1m",
  "strategy_label": "my_strategy_v1",
  "pairs": ["BTCUSDT", "ETHUSDT"]   ← optional, null = all pairs
}
```

This creates a database record for the session but doesn't start anything yet. The response tells you the `session_id` and `total_steps` (how many candles to simulate).

**What happens internally:**
- A `BacktestSession` row is inserted in TimescaleDB with status `"created"`
- `total_steps` is calculated: `(end - start) / candle_interval`
  - 30 days at 1-minute candles = 43,200 steps

### 3. Start the Session

```
POST /backtest/{session_id}/start
```

This is where the heavy lifting begins. The engine:

1. **Creates the TimeSimulator** — a virtual clock starting at `start_time` that ticks forward by `candle_interval` on each step
2. **Creates the Sandbox** — a fake exchange that runs entirely in memory with your starting balance
3. **Preloads ALL price data** — one big SQL query loads every candle close price for all pairs across the entire date range into an in-memory dictionary. This is the key performance optimization — no more DB queries needed during stepping.
4. **Takes an initial equity snapshot** at `start_time`
5. Sets status to `"running"`

After this call, the session is ready to step through.

### 4. Step Forward (The Core Loop)

This is where your agent does its work. On each step:

```
POST /backtest/{session_id}/step          ← one candle forward
POST /backtest/{session_id}/step/batch    ← N candles forward
{ "steps": 1000 }
```

**What happens on each step:**

```
Virtual clock: 2025-06-01 00:00 → 00:01 → 00:02 → ...

For each tick:
  1. Clock advances by candle_interval (e.g. 1 minute)
  2. Prices loaded from memory cache (instant, no DB)
  3. Pending limit/stop orders checked against new prices
  4. Equity snapshot taken (every 60 steps to save memory)
  5. DB progress updated (every 500 steps to reduce writes)
```

The step response gives your agent everything it needs:

```json
{
  "virtual_time": "2025-06-01T00:01:00Z",
  "step": 1,
  "total_steps": 43200,
  "progress_pct": "0.00",
  "prices": {
    "BTCUSDT": "67500.30",
    "ETHUSDT": "3450.20"
  },
  "orders_filled": [],
  "portfolio": {
    "total_equity": "10000.00",
    "available_cash": "10000.00",
    "position_value": "0.00",
    "unrealized_pnl": "0.00",
    "realized_pnl": "0.00"
  },
  "is_complete": false,
  "remaining_steps": 43199
}
```

### 5. Place Orders (Your Strategy)

Between steps, your agent reads the prices and decides to trade:

```
POST /backtest/{session_id}/trade/order
{
  "symbol": "BTCUSDT",
  "side": "buy",
  "type": "market",
  "quantity": "0.1"
}
```

**Supported order types:**
- `market` — fills immediately at current price + slippage
- `limit` — fills when price reaches your target
- `stop_loss` — triggers a sell when price drops below threshold
- `take_profit` — triggers a sell when price rises above threshold

**What the Sandbox does on a market buy:**
1. Calculates slippage (0.01% to 10% based on order size)
2. Applies the executed price = close price × (1 + slippage)
3. Deducts 0.1% trading fee
4. Deducts total cost (price × quantity + fee) from your USDT balance
5. Adds the position to your portfolio
6. Returns the fill confirmation

**What happens with limit/stop orders:**
- They sit as "pending" in the sandbox
- On each `step()`, pending orders are checked against the new prices
- When a limit buy's price is reached (price ≤ limit), it fills
- When a stop loss is triggered (price ≤ stop price), it fills
- Filled orders appear in the step response's `orders_filled` array

### 6. Check Your State

At any time during a running backtest, you can query:

```
GET /backtest/{session_id}/market/prices        ← all current prices
GET /backtest/{session_id}/market/price/BTCUSDT  ← single price
GET /backtest/{session_id}/market/candles/BTCUSDT ← OHLCV history
GET /backtest/{session_id}/account/balance       ← USDT balance
GET /backtest/{session_id}/account/positions     ← open positions
GET /backtest/{session_id}/account/portfolio     ← equity summary
GET /backtest/{session_id}/trade/orders          ← all orders
GET /backtest/{session_id}/trade/orders/open     ← pending orders
```

### 7. Completion (Automatic)

When the last step is reached (`is_complete: true`), the engine **automatically**:

1. **Closes all open positions** at current market prices
2. **Takes a final equity snapshot**
3. **Computes performance metrics** (see below)
4. **Saves everything to the database:**
   - Final equity, PnL, ROI
   - All trades (with timestamps, prices, fees, PnL)
   - All equity snapshots (for charts)
   - Metrics JSON blob
5. **Sets status to `"completed"`**
6. **Removes the session from memory**

You can also cancel early:
```
POST /backtest/{session_id}/cancel
```

---

## Performance Metrics Computed

After completion, the engine calculates:

| Metric | What It Means |
|--------|--------------|
| **ROI %** | Total return on starting balance |
| **Sharpe Ratio** | Risk-adjusted return (annualized). > 1 is good, > 2 is great |
| **Sortino Ratio** | Like Sharpe but only penalizes downside volatility |
| **Max Drawdown %** | Largest peak-to-trough equity drop. Lower is better |
| **Max DD Duration** | How many days the worst drawdown lasted |
| **Win Rate %** | Percentage of trades that made money |
| **Profit Factor** | Gross profit / gross loss. > 1 means profitable |
| **Avg Win / Avg Loss** | Average profit on winning vs losing trades |
| **Best / Worst Trade** | Single best and worst trade PnL |
| **Trades per Day** | How active the strategy was |

---

## Viewing Results

After completion, the results endpoints serve data for the UI:

```
GET /backtest/{session_id}/results              ← full summary + metrics
GET /backtest/{session_id}/results/equity-curve  ← equity snapshots for charts
GET /backtest/{session_id}/results/trades        ← full trade log
GET /backtest/list                               ← all your backtests
GET /backtest/compare?sessions=id1,id2           ← side-by-side comparison
GET /backtest/best?metric=roi_pct                ← best session by metric
```

---

## How the Price Data Works

The system uses two data sources:

| Source | What | Coverage |
|--------|------|----------|
| `candles_1m` | Live 1-minute candles from Binance WebSocket | Recent data only (since ingestion started) |
| `candles_backfill` | Historical klines downloaded from Binance API | Goes back years, available in 1h and 1d intervals |

When you start a backtest, the engine loads **all** available data for your date range in one query:

```sql
SELECT bucket, symbol, close FROM candles_1m WHERE bucket BETWEEN start AND end
UNION ALL
SELECT bucket, symbol, close FROM candles_backfill WHERE bucket BETWEEN start AND end
```

This gets cached in a Python dictionary. During stepping, prices are looked up via binary search — no database queries at all.

**If your date range only has hourly data** (no 1-minute candles), the backtest still works. The price stays the same for each 1-minute step within an hour until the next hourly candle arrives. This means less price granularity but the simulation still runs correctly.

---

## The Sandbox — Your Fake Exchange

The sandbox is a pure in-memory simulation of the real exchange. It tracks:

- **USDT balance** — starts at your `starting_balance`
- **Positions** — symbol, quantity, average entry price, realized PnL
- **Orders** — pending limit/stop orders waiting to fill
- **Trades** — every executed trade with price, fee, slippage, PnL
- **Snapshots** — periodic equity readings for the equity curve

Key behaviors that match the real exchange:
- **0.1% trading fee** on every fill
- **Slippage** between 0.01% and 10% based on order size
- **Position averaging** — buying more of the same symbol adjusts your average entry price
- **Realized PnL** — calculated when you sell: `(sell_price - avg_entry) × quantity - fees`

---

## Typical Agent Flow

```python
# 1. Create
session = POST /backtest/create { start, end, balance, strategy }

# 2. Start
POST /backtest/{session_id}/start

# 3. Loop: step and trade
while not is_complete:
    result = POST /backtest/{session_id}/step/batch { steps: 100 }

    prices = result.prices
    portfolio = result.portfolio

    # Your strategy logic here
    if should_buy(prices):
        POST /backtest/{session_id}/trade/order { symbol, side: "buy", ... }
    if should_sell(prices):
        POST /backtest/{session_id}/trade/order { symbol, side: "sell", ... }

# 4. Results (auto-saved on completion)
results = GET /backtest/{session_id}/results
```

---

## Building Your Own Strategy

The platform provides the market and the sandbox — **you provide the brain**. Your strategy is the decision logic that runs between steps: read prices, decide buy/sell/hold, place orders.

### What You Can Read at Each Step

| Data | How to Get It |
|------|--------------|
| Current close price for any pair | `result["prices"]["BTCUSDT"]` from step response |
| Full OHLCV candle history | `GET /backtest/{sid}/market/candles/BTCUSDT?limit=200` |
| Your USDT balance | `result["portfolio"]["available_cash"]` |
| Your open positions | `GET /backtest/{sid}/account/positions` |
| Your total equity | `result["portfolio"]["total_equity"]` |
| Pending orders | `GET /backtest/{sid}/trade/orders/open` |
| 24h stats (high/low/volume) | `GET /backtest/{sid}/market/ticker/BTCUSDT` |

### What You Can Do

| Action | API Call |
|--------|---------|
| Buy at market price | `POST /backtest/{sid}/trade/order {"symbol":"BTCUSDT","side":"buy","type":"market","quantity":"0.1"}` |
| Sell at market price | Same with `"side":"sell"` |
| Place a limit buy | `{"type":"limit","price":"60000","side":"buy",...}` — fills when price drops to 60000 |
| Set a stop loss | `{"type":"stop_loss","price":"58000","side":"sell",...}` — auto-sells if price drops to 58000 |
| Set a take profit | `{"type":"take_profit","price":"70000","side":"sell",...}` — auto-sells if price rises to 70000 |
| Cancel a pending order | `DELETE /backtest/{sid}/trade/order/{order_id}` |

### Example Strategies

**1. Simple Moving Average Crossover**

Track short-term (10-period) and long-term (50-period) moving averages. Buy when short crosses above long, sell when it crosses below.

```python
prices_history = []

while True:
    result = POST /backtest/{sid}/step  # one step at a time
    price = float(result["prices"]["BTCUSDT"])
    prices_history.append(price)

    if len(prices_history) < 50:
        continue  # need at least 50 data points

    short_ma = sum(prices_history[-10:]) / 10
    long_ma  = sum(prices_history[-50:]) / 50

    if short_ma > long_ma and not holding:
        POST /backtest/{sid}/trade/order {buy}
        holding = True
    elif short_ma < long_ma and holding:
        POST /backtest/{sid}/trade/order {sell}
        holding = False
```

**2. RSI Mean Reversion**

Buy when RSI drops below 30 (oversold), sell when RSI rises above 70 (overbought).

```python
# Compute RSI from last 14 price changes
gains = [max(0, changes[i]) for i in range(14)]
losses = [abs(min(0, changes[i])) for i in range(14)]
rs = avg(gains) / avg(losses)
rsi = 100 - (100 / (1 + rs))

if rsi < 30 and not holding:  BUY
if rsi > 70 and holding:      SELL
```

**3. Breakout with Stop Loss and Take Profit**

Buy when price breaks above the 24-hour high. Protect with automatic exit orders.

```python
ticker = GET /backtest/{sid}/market/ticker/BTCUSDT
high_24h = ticker["high"]
current_price = result["prices"]["BTCUSDT"]

if current_price > high_24h and not holding:
    POST /backtest/{sid}/trade/order {buy market}
    entry = current_price
    POST /backtest/{sid}/trade/order {stop_loss at entry * 0.98}   # -2% stop
    POST /backtest/{sid}/trade/order {take_profit at entry * 1.05}  # +5% target
```

**4. Multi-Pair Momentum Rotation**

Every hour, rank all pairs by 24h performance. Hold the top 3 risers.

```python
while True:
    result = POST /backtest/{sid}/step/batch {"steps": 60}  # skip to next hour

    rankings = []
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", ...]:
        ticker = GET /backtest/{sid}/market/ticker/{symbol}
        rankings.append((symbol, ticker["price_change_pct"]))

    rankings.sort(by=price_change_pct, descending)
    top_3 = rankings[:3]

    # Sell anything not in top 3
    # Buy equal portions of top 3 you don't already hold
```

### Step Batching for Speed

Match your batch size to your strategy timeframe:

| Strategy Timeframe | Batch Size | API Calls for 1 Year |
|---|---|---|
| Every candle (scalping) | `steps: 1` | 525,600 |
| Hourly signals | `steps: 60` | 8,760 |
| Daily signals | `steps: 1440` | 365 |
| Weekly rebalancing | `steps: 10080` | 52 |

Pending limit/stop orders still check against every candle during a batch, so your stop losses work correctly even when fast-forwarding.

### Position Sizing

Don't put all your money in one trade:

- **Fixed percentage:** Use 10% of cash per trade
  `quantity = (available_cash * 0.10) / current_price`
- **Equal weight:** Divide evenly across N positions
  `quantity = (total_equity / N) / current_price`
- **Risk-based:** Size based on stop loss distance
  `risk = total_equity * 0.02` (risk 2% per trade)
  `quantity = risk / (entry_price - stop_price)`

### Iterating on Your Strategy

1. **Start simple.** Get a basic version running first.
2. **Label versions.** `strategy_label: "momentum_v1"` → `"momentum_v2"` etc.
3. **Change one thing at a time.** Tweak one parameter, re-run, compare.
4. **Test multiple time periods.** Works on Jan? Test on June too. If it fails, it's overfitting.
5. **Use the compare endpoint.** `GET /backtest/compare?sessions=id1,id2,id3`
6. **Watch Sharpe, not just ROI.** Smooth 20% beats bumpy 50%.

---

## Performance Notes

- **1 year at 1-minute candles** = 525,600 steps
- Price data is preloaded into memory at start — stepping is CPU-only, no DB queries
- Equity snapshots are taken every 60 steps (hourly) to save memory
- DB progress is updated every 500 steps to reduce write overhead
- A year-long backtest should complete in minutes, not hours

---

## Comparing Strategies

Run the same date range with different strategies using `strategy_label`:

```
POST /backtest/create { ..., strategy_label: "momentum_v1" }
POST /backtest/create { ..., strategy_label: "momentum_v2" }
POST /backtest/create { ..., strategy_label: "mean_reversion_v1" }
```

Then compare:
```
GET /backtest/compare?sessions=id1,id2,id3
```

Returns side-by-side metrics and tells you which strategy had the best ROI, Sharpe ratio, and lowest drawdown.
