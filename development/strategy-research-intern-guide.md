---

## type: research-report
tags:
  - strategy
  - research
  - autoresearch
  - ml
  - trading
  - roadmap
  - intern-guide
date: 2026-03-23
status: complete
audience: intern (beginner-friendly)

# Complete Strategy Research Report — Intern Edition

> **Who is this for?** You! If you're new to trading, AI, or this project, this guide explains everything from scratch. Same content as the senior report, just in plain English.
>
> **Our goal is simple:** Find the ONE BEST trading strategy. We have a massive toolkit — backtesting, battles, machine learning, autoresearch — and we use all of it to search, test, and refine until we find a winning approach. Then we run that.

---

## Table of Contents

1. [What Is This Project?](#1-what-is-this-project)
2. [The Strategies We Already Have](#2-the-strategies-we-already-have)
3. [The Tools We Already Built](#3-the-tools-we-already-built)
4. [What Is Autoresearch? (The Karpathy Loop)](#4-what-is-autoresearch-the-karpathy-loop)
5. [How We Plan to Use Autoresearch for Trading](#5-how-we-plan-to-use-autoresearch-for-trading)
6. [Strategy Ideas We Want to Test](#6-strategy-ideas-we-want-to-test)
7. [New Tools and Libraries to Add](#7-new-tools-and-libraries-to-add)
8. [New Data Sources We Need](#8-new-data-sources-we-need)
9. [How the Search Process Works](#9-how-the-search-process-works)
10. [How We Prevent Cheating (Overfitting)](#10-how-we-prevent-cheating-overfitting)
11. [Step-by-Step Plan (What We Do and When)](#11-step-by-step-plan-what-we-do-and-when)
12. [The Big Picture Vision](#12-the-big-picture-vision)

---

## 1. What Is This Project?

### The Simple Version

Imagine a science lab where we test hundreds of different trading strategies to find the one that works best — kind of like a chef testing 500 recipes to find the PERFECT cookie recipe. We trade cryptocurrency (digital money like Bitcoin) using **real prices from Binance** (the world's biggest crypto exchange), but the money is **virtual** — no one loses real cash while we're experimenting.

**Our goal: find the single best strategy that makes 10% profit every month, consistently, without taking crazy risks.**

We're not trying to run hundreds of robots at once. We're using hundreds of experiments to find the ONE robot worth running.

### Think of It Like This


| Lab Equipment                              | What It Does For Us                                            |
| ------------------------------------------ | -------------------------------------------------------------- |
| **The Stadium** (our platform)             | The place where experiments happen                             |
| **Test Subjects** (AI agents)              | Robots that test different trading strategies for us           |
| **Recipes** (strategies)                   | Different rules for when to buy, sell, and how much            |
| **The Referee** (risk management)          | Stops any strategy from blowing up during testing              |
| **The Scoreboard** (monitoring dashboards) | Shows which strategies are winning                             |
| **The Time Machine** (backtesting)         | Test a strategy on old data to see if it WOULD have worked     |
| **The Arena** (battles)                    | Make two strategies compete head-to-head to find the winner    |
| **The Cookie Loop** (autoresearch)         | An AI that tests 100+ strategy tweaks overnight, automatically |


### The Numbers (Our Lab Equipment)


| What                               | How Many                                      |
| ---------------------------------- | --------------------------------------------- |
| Crypto coins we can test on        | 600+                                          |
| Agents we CAN run for testing      | Up to 1,000 (but the goal is to find THE one) |
| Training simulators                | 7 different practice environments             |
| Strategy approaches already built  | 5                                             |
| API tools available                | 58                                            |
| Tests (making sure nothing breaks) | 4,000+                                        |
| Monitoring dashboards              | 7                                             |


---

## 2. The Strategies We Already Have

A "strategy" is a set of rules: WHEN to buy, WHEN to sell, and HOW MUCH to bet. Think of it as a recipe for trading.

We currently have 5 strategy approaches. They work together like a team of advisors giving opinions to one decision-maker:

### How They Work Together

```
Market data comes in (prices changing every second)
        |
        v
  Advisor #1 (RL Brain) says:      "Buy Bitcoin, 80% sure"
  Advisor #2 (Evolved Rules) says:  "Sell Bitcoin, 60% sure"
  Advisor #3 (Regime Reader) says:  "Market is trending — so buy"
        |
        v
  The Decision Maker (Ensemble) weighs all opinions
  → Two out of three say buy, and they're more confident
  → Decision: BUY
        |
        v
  The Safety Officer (Risk Overlay) checks:
  "Is this trade too dangerous? Are we betting too much?"
        |
        v
  If approved → Place the trade
  If too risky → Skip it
```

Now let's understand each advisor:

### Strategy #1: PPO Reinforcement Learning (The Gamer)

**Analogy:** Imagine teaching a robot to play a video game. It starts knowing nothing, makes random moves, and slowly learns what works by getting "rewards" (profit) and "penalties" (losses). After hundreds of thousands of rounds, it gets really good.

**What it does:**

- The robot plays a trading "game" (a training simulator)
- It decides how to split money between Bitcoin, Ethereum, and Solana
- It trains for 500,000 steps (like playing 500,000 rounds)
- After training, it says things like: "Put 40% in BTC, 35% in ETH, 25% in SOL"

**How it's scored during training (the reward):**

- 40% — Did it make money without taking big downside risks? (Sortino ratio)
- 30% — Did it actually make money? (raw profit)
- 20% — Is it actively trading, not just sitting there? (activity bonus)
- 10% — Did it avoid scary drops? (drawdown penalty)

**How often it relearns:** Every 30 days it retrains on fresh data.

### Strategy #2: Genetic Algorithm (The Evolver)

**Analogy:** Imagine breeding racing horses. You take the fastest horses, breed them together, and hope the babies are even faster. Over many generations, you get champion horses. That's exactly what this does, but with trading rules instead of horses.

**What it does:**

- Each "horse" (called a genome) is a set of 12 trading rules:
  - When is a coin "oversold" or "overbought"?
  - When is a trend strong enough to follow?
  - When to cut losses? (e.g., sell if you're down 2%)
  - When to take profits? (e.g., sell if you're up 5%)
  - How much to bet per trade?
  - Which coins to trade?
- We start with 12 random sets of rules
- They compete in **battles** (trading competitions)
- The winners "breed" (their rules get mixed)
- Some random changes happen (mutations — like nature)
- After 30 generations, we have a champion

**How winners are picked (fitness score):**

- 35% — Sharpe ratio: "How much money did you make compared to how much risk you took?"
- 25% — Profit factor: "Total wins divided by total losses"
- 20% — Penalty for big drawdowns: "How badly did you crash at your worst point?"
- 10% — Win rate: "What percentage of trades were profitable?"
- 10% — Out-of-sample performance: "Does it still work on data it's NEVER seen?"

**Retrains:** Every 7 days — 2 new generations bred on top of the current champion.

### Strategy #3: Market Regime Detection (The Weather Forecaster)

**Analogy:** You wouldn't wear the same clothes in summer and winter. Markets have "seasons" too. Sometimes prices trend in one direction. Sometimes they bounce around in a range. This strategy figures out which "season" it is and picks the right approach.

**The 4 market "seasons":**


| Regime              | What It Looks Like                   | What We Do                                      |
| ------------------- | ------------------------------------ | ----------------------------------------------- |
| **TRENDING**        | Prices moving strongly one direction | Follow the trend — buy when going up            |
| **HIGH VOLATILITY** | Prices swinging wildly               | Be careful — tight safety stops                 |
| **LOW VOLATILITY**  | Prices barely moving                 | Patient, slow strategies                        |
| **MEAN REVERTING**  | Prices bouncing between two levels   | Buy at the bottom, sell at the top of the range |


**How it detects which season:** It measures 6 things about the current market (trend strength, volatility, momentum, volume, etc.) and feeds them into a machine learning model that says: "I'm 85% confident we're in TRENDING mode."

**Retrains:** Every 7 days on fresh Bitcoin data. Currently **99.92% accurate**.

### Strategy #4: Risk Management (The Safety Officer)

**Analogy:** Even the best race car driver needs seatbelts and a pit crew that yells "slow down!" on a wet track.

**6 safety checks before any trade:**


| Check | What It Asks                                           | If Failed              |
| ----- | ------------------------------------------------------ | ---------------------- |
| 1     | "Have we lost too much today?"                         | Trade BLOCKED          |
| 2     | "Is the signal confident enough?"                      | Trade BLOCKED          |
| 3     | "Would this put too much money in one coin?"           | Trade SIZE REDUCED     |
| 4     | "Do we already have too many positions in one sector?" | Trade BLOCKED          |
| 5     | "Have we been on a losing streak?"                     | Trade SIZE CUT IN HALF |
| 6     | All checks passed                                      | Trade APPROVED         |


**Recovery system:** After a losing streak, the strategy doesn't jump back to big bets. It goes:

1. **RECOVERING** — tiny bets, very careful
2. **SCALING UP** — medium bets, getting confident again
3. **FULL** — back to normal

### Strategy #5: Ensemble (The Decision Maker)

**Analogy:** You're choosing where to eat. You ask three friends:

- Friend A says "Pizza!" (80% sure)
- Friend B says "Sushi!" (60% sure)
- Friend C says "Pizza!" (70% sure)

You go with pizza because two friends said it and they were more confident. The Ensemble does exactly this with trading signals.

**How it weighs opinions:**

- RL strategy = 40% influence
- Genetic strategy = 35% influence
- Regime strategy = 25% influence

**Smart adjustment:** The weights change based on market conditions:

- TRENDING market → RL gets +30% weight (it's good at trends)
- MEAN REVERTING → Genetic gets +30% (it's good at ranges)
- HIGH VOLATILITY → Everyone gets -50% (dangerous, be cautious)

**Emergency stop (circuit breaker):**

- 3 losses in a row → pause that strategy for 24 hours
- Weekly loss > 5% → pause for 48 hours

Think of it like a coach benching a player having a bad game.

---

## 3. The Tools We Already Built

### Data (The Raw Material)


| What We Have            | How It Works                                                                   |
| ----------------------- | ------------------------------------------------------------------------------ |
| **Real-time prices**    | Every trade on Binance → we get the price instantly (<1 second delay)          |
| **Historical data**     | Years of past prices stored in our database — what robots practice on          |
| **600+ coins**          | Bitcoin, Ethereum, and hundreds more, all tracked live                         |
| **Multiple timeframes** | 1-minute, 5-minute, 1-hour, and daily candles (like zooming in/out on a chart) |


### The Order Engine (How Trades Happen)


| Order Type       | What It Does                              | Real-Life Example                               |
| ---------------- | ----------------------------------------- | ----------------------------------------------- |
| **Market order** | Buy/sell NOW at current price             | "Give me a coffee — whatever it costs"          |
| **Limit order**  | Buy/sell only at a specific price         | "I'll buy that jacket, but only if it hits $50" |
| **Stop-loss**    | Auto-sell if price drops, to limit losses | "If I'm losing 5%, sell automatically"          |
| **Take-profit**  | Auto-sell when price hits a profit target | "If I'm up 10%, sell and lock in the gain"      |


### Backtesting (The Time Machine)

**Analogy:** What if you could go back in time and test whether your strategy would have worked?

1. Pick a time period (e.g., all of 2024)
2. The robot "replays" history, seeing prices one by one
3. It makes trades based on its rules
4. At the end: did it make money? How risky was it?

**Critical rule:** The robot can NEVER peek ahead. It only sees past and present prices — never the future. Like a test where you can't flip ahead to see the answers.

### Battles (The Arena)

**Analogy:** Like a Pokemon battle for trading robots.

- Two strategies start with equal virtual money
- They trade at the same time, seeing the same prices
- After a set period: whoever has more money wins
- We use this to find out which strategy is genuinely better

**Two modes:**

- **Live:** Uses real-time prices happening right now
- **Historical:** Replays past data (same result every time — fully scientific)

### Walk-Forward Validation (The Real Test)

This is the most important test we have. Here's why:

**The problem:** A strategy might score 100% on practice data just by memorizing it — like a student who memorizes a practice test's answers. They'd fail a different test.

**The solution — walk forward:**

1. Train the strategy on January–June
2. Test it on July (data it's NEVER seen)
3. Train on February–July
4. Test on August (again, never seen)
5. Repeat, sliding the window forward

If it works EVERY time on unseen data, it's probably real. If it only works on the training data, it's memorizing — and we throw it out.

**Our threshold:** The strategy must score at least 50% as well on unseen data as on training data (called WFE ≥ 0.5). Below that = overfitting = rejected.wha t

### Monitoring (The Control Room)

Like a NASA mission control with 7 screens showing everything live:


| Dashboard                | What It Shows                                        |
| ------------------------ | ---------------------------------------------------- |
| **Agent Overview**       | What each robot is doing right now                   |
| **Strategy Performance** | Which signals are being generated, confidence levels |
| **LLM Usage**            | How much we're spending on AI language models        |
| **Ecosystem Health**     | Overall platform health, budget, success rates       |
| **Retraining**           | When strategies last retrained, drift detection      |


Plus **11 automatic alerts** — like smoke detectors. If something goes wrong, we get notified.

---

## 4. What Is Autoresearch? (The Karpathy Loop)

### Who Made It?

Andrej Karpathy — one of the most famous AI researchers alive. He was AI director at Tesla (self-driving cars) and helped create OpenAI (ChatGPT). In March 2026, he released "autoresearch" — a tool that lets AI run experiments by itself, all night, without any human help.

**51,900 stars on GitHub** (like 51,900 "likes" from programmers — incredibly popular).

### What Does It Do?

**The cookie analogy:** Imagine you're baking cookies. You start with a basic recipe, then:

1. Change ONE thing (a little more sugar)
2. Bake a batch
3. Taste — better or worse?
4. Better → keep the change. Worse → undo it.
5. Change ONE more thing (different temperature)
6. Repeat ALL NIGHT LONG

By morning, you've tested 100 variations and your cookies are amazing. That's autoresearch.

### The Loop Step by Step

```
START
  |
  v
1. Look at the current strategy and past results
  |
  v
2. Think: "What if I change X?" (e.g., "What if I make the stop-loss tighter?")
  |
  v
3. Edit the strategy code
  |
  v
4. Save to Git (like a "save point" in a video game)
  |
  v
5. Run a backtest (test the strategy on historical data)
  |
  v
6. Check the score — did it get better?
  |
  v
7a. YES → Keep the change! Log it as a win.
7b. NO  → Undo the change. Log it as a fail.
  |
  v
8. Go back to step 1. Never stop.
```

### The Speed


| Timeframe           | Experiments Done |
| ------------------- | ---------------- |
| 1 hour              | ~12              |
| Overnight (8 hours) | ~100             |
| Weekend (48 hours)  | ~500+            |


That's like having a tireless research assistant who never sleeps, never eats, and tests ideas around the clock.

### The Critical Rules

1. **The scoring system is LOCKED.** The AI can change the strategy but NEVER the way we measure success. This prevents cheating — like a student who changes the answer key instead of studying.
2. **Each experiment has a time budget.** Forces efficiency — can't just run forever.
3. **Git saves everything.** Every experiment is saved. We can always go back and see what worked and what didn't.
4. **No human needed.** It runs 24/7 while you sleep.

---

## 5. How We Plan to Use Autoresearch for Trading

### The Big Idea

We take the cookie-baking loop and apply it to our trading strategies. The AI tries hundreds of variations automatically, keeping the improvements and throwing away the failures.

### What the AI Is Allowed to Change

Each experiment, the AI picks ONE thing to tweak:

- **Indicator settings:** "What if RSI uses 10 periods instead of 14?"
- **Entry rules:** "What if we also require high volume before buying?"
- **Exit rules:** "What if we use a trailing stop instead of a fixed one?"
- **Position sizing:** "What if we risk 5% per trade instead of 3%?"
- **Coin selection:** "What if we only trade the top 20 coins by volume?"
- **Timeframe:** "What if we use 5-minute candles instead of 1-hour?"
- **Completely new ideas:** "What if we add a Bollinger Band squeeze filter?"

### What's LOCKED (Can Never Be Changed)

- The historical price data (can't pick favorable time periods)
- The fee and slippage simulation (can't pretend trades are free)
- The scoring formula (can't game the metric)
- The walk-forward validation (MUST prove it works on unseen data)

### How We Score Each Experiment

We can't just use raw profit, because a strategy that makes 100% but risks losing everything is terrible. We use a **composite score:**

```
Score = Sharpe Ratio x (1 - Max Drawdown / 50%)
```

**Automatic failures (score = -999, thrown out immediately):**

- Max drawdown > 30% → too risky, rejected
- Sharpe ratio < 0 → lost money overall, rejected
- Less than 50 trades → not enough evidence, could be luck

**What these mean in plain English:**

- **Sharpe Ratio:** "How much profit did you make compared to how much risk you took?" Higher = better. A Sharpe of 2.0 means you earned 2x more return than the risk you took.
- **Max Drawdown:** "What was your biggest dip from your highest point?" If your $10,000 portfolio dropped to $7,000, that's a 30% drawdown. Lower = better.
- **Win Rate:** "What percentage of trades made money?" 60% means 6 out of 10 trades were winners.

### The Plan

**Week 1:** Build the locked backtest harness (the untouchable scoring system) and the modifiable strategy template.

**Week 2:** First overnight run. Start with our existing 12-parameter genetic genome. Let the AI try ~100 variations. Next morning: review what worked.

**Week 3-4:** Scale to 5 parallel research tracks:

- Track 1: Optimize indicator parameters (RSI, MACD settings)
- Track 2: Discover new entry/exit rules
- Track 3: Tune risk parameters (stop-loss, take-profit)
- Track 4: Optimize ensemble weights
- Track 5: Improve coin selection

**Ongoing:** Run autoresearch every weekend. Feed winning ideas back into our main strategy. The best single result becomes our production strategy.

---

## 6. Strategy Ideas We Want to Test

We have a massive list of strategies to try. The autoresearch loop and backtesting engine will test all of them. We're looking for the ONE that performs best.

### Top Priority: Test These First

#### Cross-Sectional Momentum ("Ride What's Hot")

**Analogy:** At school, some students get more popular over a semester. If you notice someone's popularity rising fast, it usually keeps rising for a while. Momentum trading is the same: coins that have been going up tend to keep going up (for a while).

**How it works:**

1. Every hour, rank all 600+ coins by how much they've gained recently
2. Buy the ones rising fastest
3. Sell when they slow down

**Why it's a top candidate:** With 600+ coins to scan, we have a massive pool. Most traders only watch a handful of coins. We can find momentum across ALL of them.

#### Mean Reversion ("Rubber Band Effect")

**Analogy:** A rubber band stretched too far snaps back. Some coins that drop too fast bounce back, and coins that rise too fast pull back.

**How it works:**

1. Calculate the "normal" price range for each coin
2. When a coin drops way below normal → buy (expecting a bounce)
3. When it rises way above normal → sell (expecting a pullback)

**The trick:** This only works in MEAN REVERTING markets. Our regime detector tells us when! In trending markets, we turn this OFF and use momentum instead.

#### Pairs Trading ("Two Things That Move Together")

**Analogy:** Imagine Coca-Cola and Pepsi stock. They usually move together. If Coke suddenly drops but Pepsi stays the same, something is off — and they'll likely re-sync. You bet on them reconnecting.

**How it works with crypto:**

1. Find pairs of coins that historically move together (e.g., ETH and SOL)
2. When they temporarily split apart → bet they'll come back together
3. Buy the cheap one, sell the expensive one → profit when they reconnect

**The math:** 600 coins = 180,000 possible pairs to test. (600 x 599 / 2.) No human could check all these, but our system can.

#### Volume Spike Detection ("Something Big Is Happening!")

**Analogy:** You're in a quiet library. Suddenly everyone starts talking loudly — something happened. Same in trading: when a coin that normally has low volume suddenly gets TONS of activity, a big move often follows.

**How it works:**

1. Track normal volume for each coin
2. When volume spikes 3-5x above normal → alert!
3. Combine with price direction to decide: buy or sell?

**Why it's easy:** We already collect volume data. This is just math on data we already have.

#### LLM Sentiment ("What Are People Saying?")

**Analogy:** Before buying a video game, you check reviews. If everyone says "this game is amazing!", you're more confident buying it. We do the same: an AI reads crypto news and tells us if the mood is positive or negative.

**How it works:**

1. Big news event happens
2. Our AI language model reads it and says: "BULLISH with 80% confidence" or "BEARISH"
3. That signal feeds into our strategy as extra information

#### Funding Rate Arbitrage ("Collecting Rent")

**Analogy:** Two banks. Bank A pays 5% interest. Bank B charges 0%. Borrow from B, deposit in A, pocket the 5%. That's arbitrage — earning money from a gap.

**How it works in crypto:**

- "Perpetual futures" have a fee called "funding rate" paid every 8 hours between traders
- When the rate is very high (e.g., 0.1% per 8 hours = 136% per year!), we can collect it
- We hedge (protect) our risk by holding the opposite position
- Result: relatively safe, consistent income

### More Ideas to Test After That


| Strategy                      | Simple Explanation                                                                                  | Priority |
| ----------------------------- | --------------------------------------------------------------------------------------------------- | -------- |
| **Transformer Prediction**    | The same type of AI that powers ChatGPT, but reading price charts instead of text                   | HIGH     |
| **Synthetic Data Testing**    | AI generates fake-but-realistic market scenarios to stress-test our strategy                        | HIGH     |
| **Graph Neural Network**      | Maps how coins influence each other — "When Bitcoin moves, Ethereum follows 2 min later"            | MEDIUM   |
| **Social Sentiment Pipeline** | Scan Twitter/Reddit for hype about coins before prices move                                         | MEDIUM   |
| **Order Flow Analysis**       | Study actual buy/sell pressure from the order book                                                  | MEDIUM   |
| **Meta-Learning**             | AI that learns to adapt to new situations FAST — like a student who's good at learning new subjects | LOWER    |
| **Factor Models**             | Break down "why did this coin go up?" into specific reasons (momentum, size, volume)                | LOWER    |


### Meme Coin Strategies (High Risk)


| Strategy                  | What It Does                                  | Risk                         |
| ------------------------- | --------------------------------------------- | ---------------------------- |
| **Social Hype Detection** | Scan social media for viral coin mentions     | HIGH — lots of fake hype     |
| **Pump Detection**        | Spot when a coin is being artificially pumped | VERY HIGH — could lose big   |
| **New Listing Snipe**     | Buy coins the instant they're listed          | HIGH — extremely competitive |


**Important:** Meme coin strategies are like playing with fire. We'd only test them with tiny amounts and never make them the core strategy.

---

## 7. New Tools and Libraries to Add

### What Are Libraries?

**Analogy:** Libraries in programming are like LEGO sets. Instead of building every piece from scratch, you use pre-made pieces built by smart people. Need a wheel? Grab the LEGO wheel.

### What to Add


| Library                      | What It Does                                        | Why We Need It                                                        |
| ---------------------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| **VectorBT**                 | Runs thousands of backtests super fast, in parallel | Test hundreds of strategy variations quickly — powers the search      |
| **FinRL**                    | More RL training algorithms (A2C, DDPG, TD3, SAC)   | Our current PPO might not be the best RL approach — test more options |
| **statsmodels**              | Statistical tests (cointegration)                   | Find which coins move together for pairs trading                      |
| **scipy**                    | More statistical tools                              | Additional math for strategy analysis                                 |
| **HuggingFace Transformers** | Build Transformer AI models                         | Price prediction using the same tech behind ChatGPT                   |


### What We Already Have (No Need to Add)


| Library                    | What It Does For Us               |
| -------------------------- | --------------------------------- |
| **Stable-Baselines3**      | PPO reinforcement learning        |
| **PyTorch**                | Neural network foundation         |
| **scikit-learn / XGBoost** | Our regime classifier             |
| **CCXT**                   | Connects to 110+ crypto exchanges |
| **FastAPI**                | Our web server                    |
| **Redis**                  | Super-fast price cache            |
| **TimescaleDB**            | Historical price database         |
| **Celery**                 | Background task scheduler         |


---

## 8. New Data Sources We Need

### What We Have Now

All our data comes from **Binance** — real-time prices and historical candles for 600+ coins. That's great for price data, but it's like only having one of your five senses. Adding more data sources is like gaining hearing, touch, and smell.

### Data to Add (In Order of Priority)

#### Free / Cheap (Add First)


| Source                    | What It Tells Us                    | Analogy                                 |
| ------------------------- | ----------------------------------- | --------------------------------------- |
| **Binance Funding Rates** | Cost of holding leveraged positions | "What's the rent in this neighborhood?" |
| **Fear & Greed Index**    | Overall market mood (0-100 scale)   | A thermometer for crypto sentiment      |
| **DeFiLlama**             | How much money is in DeFi protocols | "How crowded is this restaurant?"       |
| **CoinGecko**             | Market cap, supply data, categories | A phone book for every cryptocurrency   |


#### Costs Some Money (Add Later If Strategy Needs It)


| Source            | What It Tells Us                | Analogy                                    | Cost             |
| ----------------- | ------------------------------- | ------------------------------------------ | ---------------- |
| **LunarCrush**    | Social media buzz per coin      | Trending topics for crypto                 | Free tier exists |
| **Twitter/X API** | Real-time tweets about crypto   | Reading every crypto tweet live            | ~$100/month      |
| **CryptoQuant**   | Whale movements, exchange flows | Tracking where "big fish" move their money | $99-399/month    |


We only add paid sources if the strategy we find actually NEEDS that data to work. No point paying for data we don't use.

---

## 9. How the Search Process Works

### The Core Idea

We're not trying to run 1000 strategies at once. We're using our platform as a **search engine for the best strategy.** Think of it like this:


| What People Think We Do                  | What We Actually Do                                |
| ---------------------------------------- | -------------------------------------------------- |
| Run 1000 robots trading at the same time | Test 1000 strategy VARIATIONS to find the best ONE |
| Keep all the robots                      | Keep only the champion                             |
| More robots = more profit                | Better search = better champion = more profit      |


### The Search Funnel

Imagine a funnel. We pour in hundreds of ideas at the top. At each stage, we filter out the bad ones. At the bottom, only the best survives.

```
WIDE: Hundreds of strategy ideas
  |
  | Autoresearch tests ~100 variations overnight
  | Genetic algorithm evolves 30 generations
  | We try momentum, mean reversion, pairs trading, etc.
  |
  v
FILTER 1: Backtesting
  "Does it make money on historical data?"
  (Most ideas fail here — maybe 80% eliminated)
  |
  v
FILTER 2: Walk-Forward Validation
  "Does it STILL work on data it's never seen?"
  (Another 50-70% eliminated — they were overfitting)
  |
  v
FILTER 3: Deflated Sharpe Ratio
  "Is this result real, or just luck from testing so many ideas?"
  (More eliminated — statistical flukes removed)
  |
  v
FILTER 4: Battle Tournament
  "Does it beat our current best strategy head-to-head?"
  (Only the genuine improvement survives)
  |
  v
NARROW: The ONE best strategy
  → Deploy it
  → Monitor it
  → When it starts to decay, run the search again
```

### Why This Approach Is Better

**The wrong approach:** Pick a strategy, hope it works, get frustrated when it stops working.

**Our approach:** Systematically test every idea, prove what works, deploy only the winner, and have a pipeline ready to find the NEXT winner when the current one decays.

**Every strategy has an expiration date.** Like milk, it goes bad. Other traders find the same edge, and it stops working. This is called "alpha decay." The key isn't finding one strategy that works forever (it doesn't exist) — it's being fast at finding the next one.

---

## 10. How We Prevent Cheating (Overfitting)

### What Is Overfitting?

**Analogy:** Imagine you have a test with 10 questions. You memorize the exact answers: "A, B, C, A, D, B, A, C, D, B." You get 100% on THAT test. But on a different test? You fail — because you memorized answers instead of actually learning.

Overfitting in trading = a strategy that "memorizes" past prices and looks amazing in backtesting but fails completely on new, real data.

### Why It's Extra Dangerous When Searching Hard

Here's the scary math:

If you test **1 strategy** and it has a Sharpe of 2.0 → impressive!
If you test **100 strategies** and pick the best → a Sharpe of 2.0 might just be luck.
If you test **1,000 variations** and pick the best → you'd expect to see a Sharpe of ~3.7 **purely by chance.**

**That's like flipping 1,000 coins and being impressed that one of them landed heads 10 times in a row.** It's not magic — it's statistics.

So the more strategies we test, the HIGHER our bar needs to be to trust a result.

### Our Anti-Overfitting Defenses


| Defense                          | What It Does                                     | Analogy                                                                           |
| -------------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------- |
| **Walk-Forward Validation**      | Test on data the strategy has NEVER seen         | "Pop quiz with new questions"                                                     |
| **Out-of-Sample Testing**        | Split data into train/validate/test              | "Practice test → mock exam → real exam"                                           |
| **A/B Gate**                     | New strategy must clearly beat the old one       | "New hire must outperform current employee"                                       |
| **Deflated Sharpe Ratio**        | Adjusts score for how many strategies we tested  | "Grading curve based on class size"                                               |
| **Minimum Trade Count**          | Need ≥50 trades to trust the result              | "One lucky day doesn't count"                                                     |
| **Transaction Cost Stress Test** | Re-run with 2x–3x fees — still profitable?       | "Still profitable if gas prices doubled?"                                         |
| **Regime Check**                 | Must work in ALL market conditions, not just one | "Must pass in summer AND winter"                                                  |
| **Complexity Penalty**           | Simpler strategies score higher (tie-breaker)    | "If two students get the same grade, the one who studied less is the smarter one" |


### The Deflated Sharpe Ratio (Most Important)

This formula answers: "Given that we tested N strategies, should we actually be impressed by this result?"

- Test 1 strategy → Sharpe of 1.5 is great!
- Test 10 strategies → Sharpe of 1.5 is still solid
- Test 100 strategies → Sharpe of 1.5 is meh
- Test 1,000 strategies → Sharpe of 1.5 is meaningless (expected by luck alone)

**We MUST use this before trusting any strategy found through mass testing.** It's the difference between real alpha and a statistical mirage.

---

## 11. Step-by-Step Plan (What We Do and When)

### Phase 1: Quick Wins (Week 1-2)

Things we can do RIGHT NOW with tools we already have:


| #   | What                                                                            | Time   | Why First?                                                  |
| --- | ------------------------------------------------------------------------------- | ------ | ----------------------------------------------------------- |
| 1   | **Volume Spike Detection** — alert when any coin's volume goes 3x+ above normal | 2 days | Easy, uses existing data, helps everything else             |
| 2   | **Cross-Sectional Momentum** — rank 600+ coins, buy the rising ones             | 3 days | Proven approach, our 600+ pair coverage is a huge advantage |
| 3   | **Mean Reversion + Regime** — buy oversold coins during ranging markets         | 2 days | Perfect complement to momentum                              |
| 4   | **Deflated Sharpe Ratio** — the "is this luck?" calculator                      | 1 day  | CRITICAL safety tool before mass testing                    |


### Phase 2: Autoresearch Integration (Week 3-4)

Build the automatic strategy search machine:


| #   | What                                                                                           | Time              | Result                                           |
| --- | ---------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------ |
| 5   | **Build the backtest harness** — the locked scoring system                                     | 3 days            | Foundation for autoresearch                      |
| 6   | **First overnight run** — AI iterates on our strategy template                                 | 1 day + overnight | ~100 experiments, real data on what works        |
| 7   | **5 parallel research tracks** — indicators, entry/exit, risk, weights, coin selection         | 2 days setup      | 5x search speed                                  |
| 8   | **Integration pipeline** — automatically test winning ideas through our full validation funnel | 2 days            | Discovery → validation → deployment, closed loop |


### Phase 3: Pairs Trading + Advanced Search (Week 5-6)


| #   | What                                                               | Time   | Result                             |
| --- | ------------------------------------------------------------------ | ------ | ---------------------------------- |
| 9   | **Cointegration scanner** — find all coin pairs that move together | 3 days | Map of 180,000+ pair relationships |
| 10  | **Pairs trading backtest** — test spread convergence strategies    | 4 days | Potential Sharpe 1.5-3.0           |
| 11  | **Funding rate monitor** — spot arbitrage opportunities            | 2 days | Safe, consistent income potential  |


### Phase 4: ML Upgrades (Week 7-10)


| #   | What                                                                       | Time   | Result                               |
| --- | -------------------------------------------------------------------------- | ------ | ------------------------------------ |
| 12  | **LLM sentiment signal** — AI reads news and scores bullish/bearish        | 5 days | Event-driven trading signals         |
| 13  | **Transformer prediction** — deep learning price forecasting               | 1 week | New signal type to test              |
| 14  | **Synthetic data generation** — AI creates fake markets for stress testing | 1 week | Much stronger overfitting protection |


### Phase 5: Advanced (Month 3-4)


| #   | What                                                        | Time    | Result                   |
| --- | ----------------------------------------------------------- | ------- | ------------------------ |
| 15  | **Graph Neural Network** — map coin influence relationships | 2 weeks | Predict "ripple effects" |
| 16  | **Social sentiment pipeline** — scan Twitter/Reddit live    | 2 weeks | Hype detection           |
| 17  | **Order flow analysis** — study buy/sell pressure           | 2 weeks | Deep market insight      |
| 18  | **On-chain analytics** — track blockchain movements         | 2 weeks | Whale detection          |


### The Key Point

Each phase produces strategy candidates. Every candidate goes through the full validation funnel (backtest → walk-forward → deflated Sharpe → battle). Only the overall champion gets deployed. When it starts decaying, we search again.

---

## 12. The Big Picture Vision

### Where We Are Now

```
5 strategy types → 1 ensemble → makes trades → we watch
```

### Where We're Going

```
Autoresearch + Genetic Evolution + Backtesting + Battles
                    |
                    v
        Test hundreds of ideas
                    |
                    v
        Validate through 4-stage funnel
                    |
                    v
        Find the ONE best strategy
                    |
                    v
        Deploy it → Monitor it → When it decays, search again
```

### The Secret

**Our advantage isn't any single strategy. It's HOW FAST we can find the next winning strategy.**

Every trading edge has an expiration date. The strategy that works today will stop working in weeks or months as other traders find the same pattern. The winning approach isn't finding one perfect strategy (it doesn't exist). It's building a machine that:

1. **Searches** for new strategies constantly (autoresearch + genetic algo + backtesting)
2. **Validates** them ruthlessly (walk-forward + deflated Sharpe + battles)
3. **Deploys** the champion
4. **Monitors** for decay (drift detection)
5. **Replaces** it when needed (back to step 1)

The cycle never stops. We don't need to be the smartest. We need to be the fastest at adapting.

### What Success Looks Like


| Metric                            | Target          | What It Means                                        |
| --------------------------------- | --------------- | ---------------------------------------------------- |
| Autoresearch experiments per day  | 100+            | We're searching hard                                 |
| Walk-forward validated candidates | 10+ at any time | We always have backup strategies ready               |
| Strategy replacement time         | <1 week         | When the current champ decays, the next one is ready |
| Portfolio Sharpe ratio            | >2.0            | Good risk-adjusted performance                       |
| Maximum drawdown                  | <15%            | We never lose more than 15% from our peak            |
| Monthly return                    | 10%             | The bottom line goal                                 |
| Time to detect decay              | <48 hours       | We catch problems fast                               |


---

## Glossary (Key Terms)


| Term                       | Meaning                                                                         |
| -------------------------- | ------------------------------------------------------------------------------- |
| **Alpha**                  | Your trading "edge" — the extra profit beyond what everyone else makes          |
| **Alpha decay**            | When your edge gradually disappears as others find the same pattern             |
| **Arbitrage**              | Risk-free profit from a price difference (buy cheap here, sell expensive there) |
| **Backtesting**            | Testing a strategy on old data — "would this have worked?"                      |
| **Bollinger Bands**        | Lines above and below a price showing the "normal range"                        |
| **Circuit breaker**        | Emergency stop that pauses trading when things go wrong                         |
| **Cointegration**          | Two things that tend to move together over time                                 |
| **Composite metric**       | A single score combining multiple measurements                                  |
| **Drawdown**               | How much you've lost from your peak (like dropping from 1st to 5th in a race)   |
| **Ensemble**               | Combining multiple strategies together (averaging expert opinions)              |
| **Funding rate**           | Fee traders pay each other in futures markets                                   |
| **Genetic algorithm**      | Finding better solutions by "breeding" good ones and "mutating"                 |
| **MACD**                   | Moving Average Convergence/Divergence — shows trend direction                   |
| **Mean reversion**         | Prices tend to return to their average over time                                |
| **Momentum**               | Things going up tend to keep going up (for a while)                             |
| **Overfitting**            | Memorizing the past instead of learning general rules                           |
| **PPO**                    | Proximal Policy Optimization — a way to train RL agents                         |
| **Regime**                 | The current "mood" of the market (trending, volatile, calm, ranging)            |
| **Reinforcement Learning** | Training AI with rewards (good move) and penalties (bad move)                   |
| **RSI**                    | Relative Strength Index — 0-100 number: >70 = overbought, <30 = oversold        |
| **Sharpe ratio**           | Return / Risk — higher = better performance per unit of risk                    |
| **Slippage**               | The difference between expected price and actual price you get                  |
| **Sortino ratio**          | Like Sharpe, but only penalizes losing money, not upside swings                 |
| **Walk-forward**           | Train on old data, test on newer data, slide forward, repeat                    |
| **WFE**                    | Walk-Forward Efficiency — how well training performance transfers to real data  |
| **Z-score**                | How unusual something is — ±2 means "very unusual"                              |


---

*Research compiled 2026-03-23. Written for the intern team. The mission: find the one best strategy using every tool we've got.*