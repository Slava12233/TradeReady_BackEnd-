# Backtesting — Simple Explanation

## What Is It?

Imagine you have a time machine for trading. Backtesting lets you go back in time and test your trading strategy against real market data that already happened. Did Bitcoin crash in June? Did Ethereum spike in December? Your AI agent can practice trading through all of it — without risking a single dollar.

Instead of waiting months to see if a strategy works in real life, you get the answer in minutes.

---

## How Does It Work?

Think of it like a flight simulator for trading.

### The Setup

You pick:
- **Which agent** — "Use my momentum bot agent"
- **A date range** — "I want to test from January 1 to December 31, 2025"
- **A starting balance** — "Give me $10,000 in fake money"
- **Which coins to trade** — "Just Bitcoin and Ethereum" (or all 600+ available)
- **A strategy name** — so you can compare different approaches later

### The Simulation

Once you hit start, the system creates a **fake exchange** just for your test. This fake exchange:

- Has real historical prices from Binance (the world's largest crypto exchange)
- Tracks your fake money balance
- Processes your buy and sell orders
- Charges realistic trading fees (0.1% per trade)
- Simulates slippage (the small price difference between when you click "buy" and when it actually fills)

Then time starts moving. The virtual clock ticks forward one minute at a time. At each tick, your AI agent sees the current prices and decides: buy, sell, or do nothing. It's exactly like live trading, except the "market" is a recording of what actually happened.

### The Fast-Forward

Here's the magic: a full year of 1-minute price data is over 500,000 data points. The system loads all of this into memory upfront, so stepping through time is almost instant. A year of simulated trading finishes in minutes, not months.

---

## What Do You Get at the End?

When the simulation finishes, you get a full report card:

### The Big Numbers

- **ROI (Return on Investment)** — "I started with $10,000 and ended with $12,500, so my ROI is +25%"
- **Total Trades** — how many times the agent bought or sold
- **Final Equity** — your ending balance including any open positions

### Risk Metrics

- **Sharpe Ratio** — measures return vs risk. Think of it as "how smooth was the ride?" A bumpy path to profit is riskier than a smooth one. Above 1.0 is good, above 2.0 is excellent.
- **Max Drawdown** — the worst losing streak. If your account went from $12,000 down to $9,000 before recovering, that's a 25% drawdown. Lower is better.
- **Win Rate** — what percentage of trades made money. 60% means 6 out of 10 trades were profitable.
- **Profit Factor** — total money won divided by total money lost. Above 1.0 means you're making more than you're losing.

### Visual Charts

- **Equity Curve** — a line chart showing your balance over time. Ideally it goes up and to the right.
- **Drawdown Chart** — shows the dips. Helps you see how bad the losing periods were.
- **Daily PnL** — bar chart of profit/loss per day. Green bars = good days, red bars = bad days.
- **Trade Log** — every single buy and sell, with exact prices, fees, and profit/loss.

---

## Comparing Strategies

The real power is comparison. Say you have three ideas:

1. **Momentum** — buy coins that are going up, sell when they stop
2. **Mean Reversion** — buy coins that dropped a lot, betting they'll bounce back
3. **Breakout** — buy when price breaks above a key level

You run all three against the same 6 months of data. The system shows you side by side:

| | Momentum | Mean Reversion | Breakout |
|---|---|---|---|
| ROI | +18% | +12% | +25% |
| Sharpe | 1.4 | 0.8 | 1.1 |
| Max Drawdown | -8% | -15% | -20% |
| Win Rate | 55% | 62% | 48% |

Now you can make an informed choice. Breakout made the most money, but had the scariest drawdown. Momentum had the best risk-adjusted return (Sharpe). Mean Reversion won most often but made the least.

---

## What Is a Strategy?

A strategy is simply a set of rules that decide when to buy and when to sell. The platform doesn't come with built-in strategies — your AI agent brings its own. Think of the platform as the stadium and the agent as the player.

Here are some common strategy types in plain English:

### Trend Following (Momentum)

**The idea:** "Things that are going up tend to keep going up."

The agent watches for coins that have been rising steadily. When a coin's short-term average price crosses above its long-term average price, the agent buys. When the trend reverses, it sells.

Like surfing — you wait for a wave, ride it, and get off before it crashes.

### Mean Reversion

**The idea:** "What goes down must come back up."

The agent looks for coins that have dropped a lot recently. It buys them cheap, betting they'll bounce back to their normal price. When they recover, it sells.

Like shopping at a sale — you buy things that are temporarily cheap and wait for the price to normalize.

### Breakout

**The idea:** "When price breaks through a ceiling, it often keeps going."

The agent tracks the highest price a coin hit in the last 24 hours. When the price pushes above that ceiling, it buys — expecting the breakout to continue. It sets an automatic sell order below the entry price as a safety net (stop loss).

Like watching water pressure build behind a dam — when it breaks, the flow is strong.

### Rotation / Ranking

**The idea:** "Always hold the winners, drop the losers."

Every hour (or day), the agent ranks all available coins by performance. It sells anything not in the top 3 and buys whatever is currently leading. The holdings constantly rotate to stay with the strongest coins.

Like a fantasy sports team — you keep swapping players to always have the best lineup.

---

## How Does a User Test Their Own Strategy?

The user writes their agent's trading logic in code (Python, JavaScript, anything that can make HTTP calls). The agent then:

1. Creates a backtest session (picks dates, balance, coins)
2. Starts the simulation
3. Loops through time — at each step, it reads prices and decides to trade or wait
4. The platform handles everything else: fills orders, tracks balance, charges fees

The user doesn't need to touch the platform code. They just teach their agent **when to buy and when to sell**. Everything else is handled.

### Making It Better Over Time

The key to good backtesting is iteration:

1. **Start simple** — even a basic "buy when price drops 5%" is a valid starting point
2. **Run it** — see what ROI and drawdown you get
3. **Tweak one thing** — maybe change 5% to 3%, or add a stop loss
4. **Run again** with a new version label (v1 → v2 → v3)
5. **Compare** — the platform shows all versions side by side
6. **Test different time periods** — a strategy that works in January but fails in June is unreliable
7. **Repeat** until you find something consistent

### Position Sizing — Don't Bet Everything

Smart strategies don't put all their money in one trade:

- **Small bites:** Use only 10% of your cash per trade. If the trade goes wrong, you only lose 10%, not everything.
- **Spread it out:** Hold 5-10 different coins instead of just one. If one crashes, the others can absorb the loss.
- **Set safety nets:** Always use stop losses. A stop loss automatically sells if the price drops below a certain point, limiting your worst-case scenario.

---

## What Makes This Realistic?

The simulation isn't just playing pretend. It accounts for real-world factors:

- **Real prices** — actual Binance market data, not random numbers
- **Trading fees** — 0.1% per trade, same as Binance
- **Slippage** — when you buy, you don't get the exact price you saw. The bigger your order, the worse the slippage. This is how real markets work.
- **No cheating** — the system enforces that your agent can only see prices up to the current simulated time. It cannot peek into the future.
- **Risk rules** — if your agent has risk limits configured (max position size, daily loss limit), the backtest sandbox enforces them just like the live exchange would. Your backtest results reflect real risk constraints.

---

## The Simple Version

1. **You pick a time period and starting money**
2. **The system replays real market prices minute by minute**
3. **Your AI agent trades as if it were live**
4. **At the end, you get a full performance report**
5. **Run multiple strategies and compare to find the best one**

That's it. It's a practice arena for your trading agent, using real historical data, with instant results.
