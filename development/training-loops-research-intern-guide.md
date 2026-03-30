---
type: research-report
tags:
  - training
  - retraining
  - costs
  - schedule
  - intern-guide
date: 2026-03-23
status: complete
audience: intern (beginner-friendly)
---

# How All Training Loops Work Together — Intern Guide

> **What this document explains:** We have multiple "training loops" — processes that teach our trading strategies to get better. This doc explains what each one does, how they connect, how long they take, and how much they cost. Everything in plain English.

---

## Table of Contents

1. [The Big Picture: Why Do We Need Training Loops?](#1-the-big-picture)
2. [All 7 Training Loops Explained](#2-all-7-training-loops-explained)
3. [How They Connect (The Flow)](#3-how-they-connect)
4. [The Schedule: What Runs When](#4-the-schedule)
5. [Costs: What Does All This Cost?](#5-costs)
6. [A Typical Week (Play-by-Play)](#6-a-typical-week)
7. [A Typical Month (Play-by-Play)](#7-a-typical-month)
8. [The Autoresearch Loop (Future)](#8-the-autoresearch-loop)
9. [Total Cost Summary](#9-total-cost-summary)
10. [What Can Go Wrong](#10-what-can-go-wrong)

---

## 1. The Big Picture

### Why Do We Need Training Loops?

**Analogy:** Imagine you're a basketball player. You don't just practice once and then play forever. You:
- Practice shooting every day (small adjustments)
- Review game film every week (learn from mistakes)
- Go to training camp every month (bigger improvements)
- Rethink your whole game every season (major changes)

Our trading system works the same way. Markets change constantly, so our strategies need to keep learning and adapting. We have different training loops that run at different speeds:

| Loop | Frequency | Analogy | What It Does |
|------|-----------|---------|-------------|
| **Ensemble weight tuning** | Every 8 hours | Adjusting your grip on the bat between innings | Fine-tune how much we trust each strategy |
| **Regime classifier retrain** | Every 7 days | Reviewing game film on weekends | Re-learn what market "seasons" look like |
| **Genome evolution** | Every 7 days | Weekly practice drills | Breed better trading rules through competition |
| **PPO RL retrain** | Every 30 days | Monthly training camp | Full neural network retraining on fresh data |
| **Drift detection** | Every trade (continuous) | Coach watching the game live | Spot when a strategy is starting to fail |
| **Walk-forward validation** | Before any deployment | Physical exam before the season | Prove a strategy works on data it's never seen |
| **Autoresearch** | On-demand (future) | Overnight robot practice | AI tests 100+ strategy variations while we sleep |

### The Key Idea: Layers of Learning

```
FAST (every few hours):
  └── Ensemble weights adjust — "trust Strategy A more today"

MEDIUM (every week):
  ├── Regime classifier relearns — "the market mood has shifted"
  └── Genetic algorithm evolves — "breed better trading rules"

SLOW (every month):
  └── PPO RL retrains — "rebuild the neural network brain"

ALWAYS WATCHING:
  └── Drift detection — "something's wrong, trigger emergency retrain!"

BEFORE DEPLOYING ANYTHING:
  └── Walk-forward validation — "prove it works on unseen data"
```

---

## 2. All 7 Training Loops Explained

### Loop 1: Ensemble Weight Tuning

**What it is:** We have three strategy advisors (RL, Genetic, Regime). Each has a "trust weight" — how much we listen to their opinion. This loop adjusts those weights based on recent performance.

**Analogy:** You have three friends who give you stock tips. Over the past week, Friend A was right 80% of the time, Friend B was right 50%, and Friend C was right 70%. You'd start listening more to Friend A, right? That's what this does.

**How it works:**
1. Look at the last 7 days of actual trading results
2. Check which strategy was most accurate
3. Try 12 different weight combinations in backtests
4. Pick the combination that would have performed best
5. If it beats the current weights by at least 1% → use the new weights
6. If not → keep the old weights (don't fix what isn't broken)

**The 12 weight combinations it tests:**

| Config | RL Weight | Genetic Weight | Regime Weight |
|--------|-----------|---------------|---------------|
| 1 | 40% | 35% | 25% |
| 2 | 50% | 30% | 20% |
| 3 | 30% | 40% | 30% |
| ... | (9 more variations) | ... | ... |

**Time:** ~30-60 minutes (runs 12 backtests)
**Cost:** $0 (pure CPU math, no AI calls)
**Runs:** Every 8 hours (3 times per day)

---

### Loop 2: Regime Classifier Retrain

**What it is:** The "Weather Forecaster" that tells us what market season we're in (trending, volatile, calm, or ranging). Every week it relearns from fresh data.

**Analogy:** A weather app that updates its prediction model every Sunday using the last year of weather data.

**How it works:**
1. Download the last 12 months of Bitcoin 1-hour candles (8,760 candles)
2. Calculate 6 measurements for each candle (trend strength, volatility, momentum, etc.)
3. Label each candle with its "regime" using simple rules (ADX > 25 = trending, etc.)
4. Train an XGBoost machine learning model on 80% of the data
5. Test on the remaining 20% (data it hasn't seen)
6. If accuracy > 70% → save the new model
7. If it beats the old model by at least 1% → deploy it

**The 6 measurements (features) it learns from:**

| Feature | What It Measures | Analogy |
|---------|-----------------|---------|
| ADX | Trend strength | "How fast is the wind blowing?" |
| ATR/Close | Volatility relative to price | "How choppy are the waves?" |
| Bollinger Width | Price range width | "How wide is the road?" |
| RSI-14 | Overbought/oversold | "Is everyone buying or selling?" |
| MACD Histogram | Momentum direction | "Is the car speeding up or slowing down?" |
| Volume Ratio | Current vs average volume | "Is the store busier than usual?" |

**Time:** ~30 seconds (XGBoost is incredibly fast — 300 decision trees train in about 5 seconds on a modern CPU. The rest is downloading candles.)
**Cost:** $0 (pure CPU, no AI calls)
**Runs:** Every Sunday at 4:00 AM UTC
**Current accuracy:** 99.92% (nearly perfect)

---

### Loop 3: Genetic Algorithm Evolution

**What it is:** The "Horse Breeder" that evolves trading rules through competition. Every week it breeds 2 new generations of strategies.

**Analogy:** Like a weekly dog show. The best dogs from last week breed, their puppies compete this week, and the best puppies become next week's parents.

**How it works (weekly refresh):**
1. Take the current champion genome (12 trading rules)
2. Create a population of 12 variations (mutations + crossover)
3. Run historical battles — each genome trades a 7-day replay
4. Score each genome using the 5-factor fitness formula
5. Keep the top 20% unchanged (elites)
6. Breed the rest from winners
7. Repeat for 2 generations (weekly refresh is small — full run is 30 generations)
8. If the new champion beats the old one by at least 1% → deploy

**What happens in a battle (per genome):**
1. Create a trading agent with the genome's rules
2. Two battles run: one on the first 70% of the week (in-sample), one on the last 30% (out-of-sample)
3. Calculate Sharpe ratio, profit factor, drawdown, win rate on both periods
4. Compute fitness score

**API calls per weekly refresh:**
- 12 genomes × 2 battles each = 24 battle API calls
- Plus battle creation, status polling, result fetching
- Total: ~50-80 API calls to our own platform (free — it's our own server)

**Time:** ~10-20 minutes for 2 generations
**Cost:** $0 (battles run on our own platform, no external API calls)
**Runs:** Every Wednesday at 5:00 AM UTC

---

### Loop 4: PPO Reinforcement Learning Retrain

**What it is:** The "Gamer Brain" — a neural network that learns to trade by playing a simulated trading game hundreds of thousands of times. This is the biggest, slowest training loop.

**Analogy:** Like resetting a video game and replaying it 500,000 times to learn the optimal strategy. Except the game world (market data) gets updated with the latest 6 months.

**How it works:**
1. Collect the last 6 months of hourly candle data for BTC, ETH, SOL
2. Create 4 parallel training simulators (like 4 copies of the game running side by side)
3. The robot plays 500,000 total steps across all 4 simulators
4. Every 20,000 steps, it pauses and checks: "am I getting better?"
5. Every 10,000 steps, it saves a checkpoint (like a save point)
6. After all 500,000 steps, test the final model on a 30-day held-out period
7. Compare Sharpe ratio with the old model
8. If improvement ≥ 0.01 → deploy the new model
9. If not → keep the old model

**Training parameters (the knobs):**

| Parameter | Value | What It Means |
|-----------|-------|---------------|
| Total timesteps | 500,000 | How many "game moves" the robot makes |
| Parallel environments | 4 | How many copies of the game run simultaneously |
| Learning rate | 0.0003 | How big each learning step is (smaller = more careful) |
| Batch size | 64 | How many experiences it learns from at once |
| Epochs per update | 10 | How many times it re-studies each batch |
| Network size | 2 layers × 256 neurons | The "brain size" of the robot |
| Reward type | Composite | Mix of Sortino, PnL, activity, drawdown penalty |

**Data needed:**
- 6 months × 720 candles/month × 3 coins = ~12,960 candles
- Plus a 30-day evaluation window (2,160 more candles)

**Time:** 30-60 minutes on a modern CPU
**Cost:** $0 (runs on our own computer/server, no cloud needed)
**Runs:** 1st of every month at 3:00 AM UTC
**Output file:** `ppo_portfolio_final.zip` (~1-2 MB) + a security checksum file

---

### Loop 5: Drift Detection (Always Running)

**What it is:** A watchdog that monitors every trade and sounds the alarm if a strategy starts performing badly.

**Analogy:** Like a smoke detector. It doesn't DO anything most of the time — it just watches. But when it detects smoke (performance dropping), it triggers an alarm (emergency retrain).

**How it works:**
1. After every trade, it receives three numbers: Sharpe ratio, win rate, average PnL
2. It combines them into a single "health score": `0.40 × Sharpe + 0.35 × win_rate + 0.25 × normalized_PnL`
3. It uses a math trick called the "Page-Hinkley test" to detect if the score is trending downward
4. For the first 30 trades, it just watches and learns what "normal" looks like (warmup)
5. After warmup, if the score drops significantly → DRIFT DETECTED!

**What happens when drift is detected:**
1. Position sizes get cut in half immediately (safety first!)
2. Regime strategy weight gets boosted to 0.6 (trust the "weather forecaster" more)
3. An emergency ensemble retrain is triggered
4. A Prometheus metric is incremented (shows up on the dashboard)
5. A 1-hour cooldown starts (so it doesn't trigger over and over)

**Recovery:** If performance improves for 10 consecutive trades → drift flag cleared, back to normal.

**Time:** Microseconds per check (trivially fast — just arithmetic)
**Cost:** $0
**Runs:** Continuously (every trade)

---

### Loop 6: Walk-Forward Validation (Before Deployment)

**What it is:** The final exam. Before ANY strategy gets deployed to production, it must prove it works on data it has NEVER seen. This is the most important quality gate.

**Analogy:** Before a new medicine is sold to the public, it goes through clinical trials. Walk-forward is our clinical trial for strategies.

**How it works:**
1. Take 18 months of historical data
2. Split into rolling windows:
   - Window 1: Train on months 1-6, test on month 7
   - Window 2: Train on months 2-7, test on month 8
   - Window 3: Train on months 3-8, test on month 9
   - ... (12 windows total)
3. For each window, train the strategy and record how well it does on the test month
4. Calculate WFE (Walk-Forward Efficiency): `average test performance / average training performance`
5. If WFE ≥ 0.50 (50%) → strategy is deployable
6. If WFE < 0.50 → strategy is overfitting, REJECTED

**Why 0.50 (50%)?** If a strategy scores 2.0 Sharpe in training but only 1.0 Sharpe on unseen data, that's WFE = 0.50 = "it retains half its performance on new data." Below 50% means it's mostly memorizing rather than learning.

**Time for RL walk-forward:** 12 windows × 30-60 min per window = **6-12 hours total**
**Time for Regime walk-forward:** 12 windows × ~5 seconds each = **~1 minute total**
**Cost:** $0 (pure CPU)
**Runs:** Manual — before deploying any new model. NOT on a schedule.

---

### Loop 7: The A/B Gate (Built Into Everything)

**What it is:** Every training loop has a built-in "quality check" before deploying a new model. The new model must BEAT the current one by a meaningful margin.

**Analogy:** Before replacing a star player on your team, the replacement must clearly outperform them in tryouts. A tie isn't enough — they need to be noticeably better.

**How it works:**
1. Train a new (candidate) model
2. Backtest it on a 30-day held-out period
3. Backtest the current (incumbent) model on the same period
4. Calculate: `improvement = candidate_score - incumbent_score`
5. If `improvement ≥ 0.01` → deploy the candidate
6. If `improvement < 0.01` → keep the incumbent

**The minimum improvement by component:**

| Component | Metric Compared | Min Improvement |
|-----------|----------------|-----------------|
| Ensemble weights | Ensemble accuracy | +0.01 (1%) |
| Regime classifier | Classification accuracy | +0.01 (1%) |
| Genetic genome | Composite fitness score | +0.01 |
| PPO RL model | Sharpe ratio | +0.01 |

**Why 0.01?** Small enough to catch real improvements, big enough to filter out noise. If the candidate is only 0.005 better, that might just be luck — not worth risking a model swap.

**Time:** Included in each training loop's time
**Cost:** $0

---

## 3. How They Connect

### The Full Picture

Here's how all 7 loops work together as one system:

```
┌─────────────────────────────────────────────────────────────┐
│                    THE TRAINING SYSTEM                        │
│                                                              │
│  ALWAYS RUNNING:                                             │
│  ┌─────────────────────────┐                                │
│  │    DRIFT DETECTION       │                                │
│  │  Watches every trade     │──── ALARM! ──────┐            │
│  │  Page-Hinkley test       │                   │            │
│  └─────────────────────────┘                   │            │
│                                                 │            │
│  EVERY 8 HOURS:                                │            │
│  ┌─────────────────────────┐                   │            │
│  │  ENSEMBLE WEIGHT TUNING  │◄─── also triggered by alarm   │
│  │  12 backtest configs     │                                │
│  │  ~30-60 min              │                                │
│  │  A/B gate: +0.01        │                                │
│  └─────────────────────────┘                                │
│                                                              │
│  EVERY WEEK:                                                │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │  REGIME CLASSIFIER       │  │  GENETIC EVOLUTION       │  │
│  │  XGBoost on 12mo data   │  │  2 generations × 12 pop  │  │
│  │  ~30 seconds             │  │  ~10-20 min              │  │
│  │  A/B gate: +0.01        │  │  A/B gate: +0.01        │  │
│  │  Sunday 4:00 AM         │  │  Wednesday 5:00 AM       │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                              │
│  EVERY MONTH:                                               │
│  ┌─────────────────────────┐                                │
│  │  PPO RL RETRAIN          │                                │
│  │  500K steps, 4 envs      │                                │
│  │  ~30-60 min              │                                │
│  │  A/B gate: +0.01        │                                │
│  │  1st of month 3:00 AM   │                                │
│  └────────────┬────────────┘                                │
│               │                                              │
│               ▼                                              │
│  ┌─────────────────────────┐                                │
│  │  WALK-FORWARD VALIDATION │ ◄── Manual, before deployment │
│  │  12 windows              │                                │
│  │  WFE ≥ 0.50 required    │                                │
│  │  6-12 hours (RL)        │                                │
│  └─────────────────────────┘                                │
│                                                              │
│  ALL LOOPS SHARE:                                           │
│  • Same 30-day backtest evaluation window                   │
│  • Same A/B gate logic (min_improvement = 0.01)             │
│  • Results saved to agent/strategies/retrain_results/       │
│  • All run on the ml_training Celery queue                  │
└─────────────────────────────────────────────────────────────┘
```

### What Triggers What?

```
Normal Operation:
  Celery beat schedule → triggers each loop on its schedule

Drift Detected:
  Drift detector → emergency ensemble retrain (1-hour cooldown)
  (Does NOT trigger RL, regime, or genome — those are too slow for emergencies)

Manual Trigger:
  Developer runs CLI command → any loop can be triggered manually

Retraining Cycle (every 8 hours):
  The "master" task checks: is anything OVERDUE?
  → Ensemble overdue? → retrain ensemble
  → Regime overdue? → retrain regime (only if >7 days since last)
  → Genome overdue? → retrain genome (only if >7 days since last)
  → RL overdue? → retrain RL (only if >30 days since last)
  All overdue items run CONCURRENTLY (at the same time, not one after another)
```

### Dependencies (What Needs What)

```
PPO RL Training NEEDS:
  ├── Platform API running (for backtest sessions)
  ├── Historical candle data in TimescaleDB (6 months minimum)
  ├── torch + stable-baselines3 installed
  └── tradeready-gym package installed

Genetic Evolution NEEDS:
  ├── Platform API running (for battles)
  ├── JWT authentication working (battles require login)
  └── Historical candle data (7 days minimum)

Regime Classifier NEEDS:
  ├── Platform API running (for candle data)
  └── xgboost or scikit-learn installed

Ensemble Weight Tuning NEEDS:
  ├── Recent trading results (last 7 days of AttributionLoader data)
  ├── Backtest API working
  └── All three strategy components (RL, Genetic, Regime) deployed

Drift Detection NEEDS:
  ├── TradingLoop running (feeds data in real-time)
  └── At least 30 completed trades (warmup period)

Walk-Forward Validation NEEDS:
  ├── 18 months of historical data
  └── Whichever training loop it's validating must work
```

---

## 4. The Schedule

### Weekly Calendar View

| Time | Monday | Tuesday | Wednesday | Thursday | Friday | Saturday | Sunday |
|------|--------|---------|-----------|----------|--------|----------|--------|
| **00:00** | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble |
| **03:00** | | | | | | | |
| **04:00** | | | | | | | **Regime** |
| **05:00** | | | **Genome** | | | | |
| **08:00** | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble |
| **16:00** | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble | Ensemble |
| **All day** | Drift ↻ | Drift ↻ | Drift ↻ | Drift ↻ | Drift ↻ | Drift ↻ | Drift ↻ |

- **Ensemble** runs 3× daily (00:00, 08:00, 16:00 — every 8 hours)
- **Regime** runs once on Sunday at 4:00 AM
- **Genome** runs once on Wednesday at 5:00 AM
- **Drift detection** runs continuously (every trade)
- **PPO RL** runs once per month (1st of month at 3:00 AM) — not shown in weekly view

### Monthly Calendar View

| Week | Ensemble × 3/day | Regime (Sun) | Genome (Wed) | PPO RL | Walk-Forward |
|------|-----------------|-------------|-------------|--------|-------------|
| Week 1 | 21 runs | 1 run | 1 run | **1 run (1st)** | Manual |
| Week 2 | 21 runs | 1 run | 1 run | - | - |
| Week 3 | 21 runs | 1 run | 1 run | - | - |
| Week 4 | 21 runs | 1 run | 1 run | - | - |
| **TOTAL** | **84 runs** | **4 runs** | **4 runs** | **1 run** | **As needed** |

---

## 5. Costs

### The Great News: Almost Everything Is Free

Here's the surprising thing: **almost all of our training loops cost $0 in external fees.** They run on our own computer using our own data. The only thing that costs money is LLM (AI language model) API calls.

### Cost Breakdown By Loop

| Loop | Runs Per Month | Time Per Run | CPU Cost | LLM Cost | Total Monthly |
|------|---------------|-------------|----------|----------|---------------|
| **Ensemble weights** | 84× | 30-60 min | $0 (our server) | $0 (no LLM) | **$0** |
| **Regime classifier** | 4× | 30 seconds | $0 | $0 | **$0** |
| **Genome evolution** | 4× | 10-20 min | $0 | $0 | **$0** |
| **PPO RL retrain** | 1× | 30-60 min | $0 | $0 | **$0** |
| **Drift detection** | Continuous | Microseconds | $0 | $0 | **$0** |
| **Walk-forward (if run)** | 1-2× | 6-12 hours | $0 | $0 | **$0** |
| **Trading journal (LLM)** | Daily | Seconds | $0 | ~$0.01/day | **~$0.30** |
| **Daily summary (LLM)** | Daily | Seconds | $0 | ~$0.001/day | **~$0.03** |
| **Weekly review (LLM)** | 4× | Seconds | $0 | ~$0.005 each | **~$0.02** |
| | | | | | |
| **TOTAL MONTHLY** | | | **$0** | **~$0.35** | **~$0.35/month** |

**Yes, you read that right. The entire training system costs about 35 cents per month.**

### Why Is It So Cheap?

1. **All ML training runs on CPU** — no expensive GPU cloud needed
2. **XGBoost trains in 5 seconds** — absurdly fast for what it does
3. **PPO trains in 30-60 minutes** on a regular computer — no cloud required
4. **Battles run on our own platform** — we're just talking to our own server
5. **LLM calls use Gemini Flash** ($0.10 per million input tokens) — the cheapest good model available

### LLM Cost Details

We use two AI language models:

| Model | What It's Used For | Price per Call | Calls per Day | Daily Cost |
|-------|-------------------|----------------|---------------|------------|
| **Gemini 2.0 Flash** (cheap) | Journal reflections, daily summaries, weekly reviews | ~$0.0002 | ~20-50 | **$0.004-$0.01** |
| **Claude Sonnet 4.6** (expensive) | Manual strategy analysis (rare, only when dev triggers it) | ~$0.006-$0.01 | 0-5 | **$0-$0.05** |

**The $5/day LLM budget from the project goals?** We use less than 1% of it on training-related tasks. Even if we added 500 journal calls per day, it would cost ~$0.10. The budget is incredibly generous.

### What About Cloud Server Costs?

If we run all of this on a cloud server instead of our own computer:

| Cloud Option | Specs | Monthly Cost | Can It Handle Everything? |
|-------------|-------|-------------|--------------------------|
| **Our own computer** | Whatever we have | $0 | Yes, if it has 8+ CPU cores and 10GB+ RAM |
| **AWS t3.xlarge** | 4 CPU, 16GB RAM | ~$120/month | Yes, but PPO will be slow |
| **AWS c5.2xlarge** | 8 CPU, 16GB RAM | ~$245/month | Yes, comfortable |
| **DigitalOcean** | 8 CPU, 16GB RAM | ~$96/month | Yes, good value |
| **Hetzner** | 8 CPU, 16GB RAM | ~$35/month | Yes, best value in Europe |

**Bottom line:** The training loops themselves are free. The server to run them on is the only real cost ($0-$245/month depending on whether it's your own machine or cloud).

---

## 6. A Typical Week (Play-by-Play)

Let's follow a typical week to see how everything works together:

### Monday

```
00:00 — Ensemble weight tuning fires (scheduled)
         → Runs 12 backtest configurations
         → Best config: RL=45%, Genetic=30%, Regime=25%
         → Old config: RL=40%, Genetic=35%, Regime=25%
         → Improvement: +0.02 Sharpe → PASSES A/B gate → Deploy new weights
         → Time: 42 minutes
         → Cost: $0

08:00 — Ensemble fires again
         → Best config same as current → no change
         → Time: 38 minutes
         → Cost: $0

All day — Drift detection runs after every trade
           → 15 trades completed today
           → Health scores: 0.72, 0.68, 0.71, 0.69, 0.73...
           → All within normal range → no alarm
           → Cost: $0

All day — Trading journal (LLM)
           → 15 reflections generated via Gemini Flash
           → Cost: $0.003

16:00 — Ensemble fires again → no change
```

### Wednesday

```
00:00 — Ensemble fires → no change

05:00 — Genetic evolution fires (scheduled)
         → Creates 12 genome variations from current champion
         → Runs 24 battles (12 genomes × 2 battles each)
         → New champion fitness: 1.47
         → Old champion fitness: 1.43
         → Improvement: +0.04 → PASSES A/B gate → Deploy new genome
         → Time: 14 minutes
         → Cost: $0

08:00 — Ensemble fires with new genome weights → adjusts slightly

All day — Normal drift detection + trading + journal
```

### Sunday

```
04:00 — Regime classifier retrain fires (scheduled)
         → Downloads 8,760 BTC 1h candles from platform API
         → Trains XGBoost (300 trees) on 80% of data
         → Tests on 20%: accuracy = 99.91%
         → Old accuracy: 99.92%
         → Improvement: -0.01 → FAILS A/B gate → Keep old model
         → Time: 28 seconds
         → Cost: $0

All day — Normal operations
```

### Weekly Totals

| What Happened | Count | Total Time | Total Cost |
|---|---|---|---|
| Ensemble weight runs | 21 | ~14 hours | $0 |
| Genetic evolution | 1 | 14 min | $0 |
| Regime classifier | 1 | 28 sec | $0 |
| Drift checks | ~100 | Negligible | $0 |
| Journal reflections (LLM) | ~100 | Negligible | ~$0.02 |
| Daily summaries (LLM) | 7 | Negligible | ~$0.007 |
| **Weekly total** | | **~14 hours CPU** | **~$0.03** |

**Note:** The 14 hours of ensemble runs happen in the background — they don't block anything. Your computer (or server) does other things at the same time.

---

## 7. A Typical Month (Play-by-Play)

### Month at a Glance

| Component | Runs | Total Time | Deployments (avg) |
|-----------|------|-----------|-------------------|
| Ensemble weights | 84 | ~50 hours | ~10-20 (when improvement found) |
| Regime classifier | 4 | ~2 minutes | ~1-2 (most weeks the old model wins) |
| Genetic evolution | 4 | ~1 hour | ~2-3 |
| PPO RL retrain | 1 | ~45 minutes | ~0-1 (often the old model wins) |
| Drift events | 0-3 | Instant | 0-3 emergency ensemble retrains |
| Walk-forward (if needed) | 0-1 | 6-12 hours | Gate for PPO deploy |

### The 1st of the Month (The Big Day)

This is the most active day because PPO RL retrains:

```
03:00 — PPO RL retrain fires (monthly)
         → Downloads 6 months of BTC/ETH/SOL 1h candles
         → Creates 4 parallel training environments
         → Starts training: 500,000 timesteps
         → Progress: 10,000... 20,000... (checkpoint saved)...
         → Training completes at ~03:45
         → Evaluates on 30-day held-out period
         → Candidate Sharpe: 1.82
         → Incumbent Sharpe: 1.75
         → Improvement: +0.07 → PASSES A/B gate

03:50 — Developer decides to run walk-forward validation
         → 12 windows, each trains a full PPO model
         → Window 1: train months 1-6, test month 7 → Sharpe 1.65
         → Window 2: train months 2-7, test month 8 → Sharpe 1.72
         → ...
         → Window 12: train months 12-17, test month 18 → Sharpe 1.58
         → WFE = 0.67 (67%) → PASSES (≥ 0.50 required) → Deploy!

~10:00 — Walk-forward completes. New PPO model deployed.
          → SHA-256 checksum saved for security
          → Old model kept as backup
```

### Monthly Cost Summary

| Item | Cost |
|------|------|
| All training loops (CPU) | $0 |
| LLM calls (Gemini Flash) | ~$0.10 |
| LLM calls (Claude Sonnet, if manual analysis triggered) | ~$0-$1.50 |
| **Total monthly training cost** | **~$0.10 - $1.60** |

---

## 8. The Autoresearch Loop (Future — Not Built Yet)

### What It Would Add

When we build the autoresearch integration, it adds a NEW training loop on top of the existing ones:

```
EXISTING LOOPS (keep running as-is):
  Ensemble (8h) + Regime (weekly) + Genome (weekly) + PPO (monthly) + Drift (continuous)

NEW LOOP:
  AUTORESEARCH (on-demand, typically weekends)
  → AI agent modifies strategy.py
  → Runs backtest
  → Checks score
  → Keep or revert
  → Repeat 100× overnight
```

### Autoresearch Cost Estimate

| Component | Cost Per Overnight Run | Notes |
|-----------|----------------------|-------|
| **LLM calls** (AI reasoning about strategy changes) | $1-$5 using Claude Sonnet, or $0.10-$0.50 using Gemini Flash | ~100 experiments × ~2000 tokens each |
| **CPU** (running backtests) | $0 on own machine | Each backtest takes 1-5 minutes |
| **Total per overnight run** | **$0.10 - $5.00** | Depends on which LLM we use |
| **Monthly (weekends only)** | **$0.40 - $40** | 4-8 overnight runs per month |

**Best approach:** Use Gemini Flash for the autoresearch reasoning (cheap but good enough for "what if I change RSI from 14 to 10?"). Save Claude Sonnet for final analysis of the best results.

### How Autoresearch Fits With Existing Loops

```
Weekend:
  Autoresearch runs overnight → discovers promising strategy variation

Monday:
  Walk-forward validation on the best candidate → proves it works on unseen data

Wednesday:
  Genetic algorithm uses the new variation as a seed genome → evolves it further

Next cycle:
  Ensemble weight tuning picks up the improved component → adjusts weights

Ongoing:
  Drift detection monitors the deployed strategy → triggers retrain if it decays
```

---

## 9. Total Cost Summary

### Monthly Operating Costs (Everything Running)

| Category | Low Estimate | High Estimate | Notes |
|----------|-------------|---------------|-------|
| **ML Training (CPU)** | $0 | $0 | All runs on our server |
| **LLM — Trading Journal** | $0.10 | $0.30 | Gemini Flash, 50-200 reflections/month |
| **LLM — Manual Analysis** | $0 | $1.50 | Claude Sonnet, only when dev triggers |
| **LLM — Autoresearch** (future) | $0.40 | $20 | 4-8 weekend runs, Gemini Flash or Sonnet |
| **Server** (if cloud) | $0 | $245 | $0 if own machine, $35-245 if cloud |
| | | | |
| **TOTAL (own machine)** | **$0.50/month** | **$22/month** | Nearly free |
| **TOTAL (cloud server)** | **$35/month** | **$267/month** | Mostly server cost |

### Comparison With Budget

| Budget Item | Allocated | Actual Usage | Verdict |
|-------------|-----------|-------------|---------|
| LLM budget ($5/day = $150/month) | $150/month | ~$0.50-$22/month | **Using 0.3%-15% of budget** |
| Compute | Not specified | $0 (own machine) | **Free** |

### Time Budget

| Loop | Monthly CPU Hours | Blocks Other Work? |
|------|------------------|-------------------|
| Ensemble (84 runs) | ~50 hours | No (background) |
| Regime (4 runs) | ~2 minutes | No |
| Genome (4 runs) | ~1 hour | No |
| PPO RL (1 run) | ~1 hour | No |
| Walk-forward (0-1 run) | 0-12 hours | No (background) |
| Drift detection | Negligible | No |
| **Total** | **~52 hours/month** | **All background** |

**52 hours of CPU time per month** sounds like a lot, but it all runs in the background. Your computer (or server) handles it alongside normal operations. It's like your phone doing automatic updates overnight — you don't notice it.

---

## 10. What Can Go Wrong

### Common Issues and What Happens

| Problem | What Happens | How It's Handled |
|---------|-------------|-----------------|
| **Platform API is down during training** | RL can't create backtest sessions; genome can't run battles | Training fails gracefully, retries next cycle |
| **No historical data for a time period** | Walk-forward can't run that window | Window gets `NaN` and is excluded from WFE |
| **New model is worse than old one** | A/B gate catches it | Old model stays, new one discarded |
| **All strategies start failing** | Drift detector fires for all three | Emergency ensemble retrain + position sizes halved |
| **Celery worker crashes** | Scheduled tasks stop running | Hard time limit (65 min) kills stuck tasks; Celery beat retries next cycle |
| **Model file gets corrupted** | SHA-256 checksum won't match | `SecurityError` raised, old model stays, alert fires |
| **Training takes too long** | Exceeds 1-hour soft limit | Task gets SIGTERM, logs partial results, Celery reclaims worker |

### The Safety Net Stack

```
Layer 1: A/B Gate
  → New model must beat old one. Bad model? Never deployed.

Layer 2: Walk-Forward Validation
  → Must work on unseen data. Overfit model? Never deployed.

Layer 3: Drift Detection
  → Deployed model starting to fail? Caught in real-time.

Layer 4: Circuit Breaker
  → 3 losses in a row? Strategy paused automatically.

Layer 5: Recovery Manager
  → After a bad period? Gradual return to full sizing, not a sudden jump.

Layer 6: SHA-256 Checksums
  → Model file tampered with? Caught and blocked.
```

**Bottom line:** It's really hard for a bad model to make it into production AND stay there without being caught. Multiple overlapping safety systems ensure that.

---

## Quick Reference Card

### "I Just Need to Know..."

**How much does it cost?**
→ ~$0.50/month on your own machine. Almost free.

**How long does training take?**
→ The longest single run is PPO RL at 30-60 minutes, once a month. Everything else is minutes or seconds.

**Does training block normal trading?**
→ No. Everything runs in the background on a separate Celery worker queue.

**What if a training run produces a bad model?**
→ The A/B gate rejects it automatically. The old model keeps running.

**What if the market changes and our strategy stops working?**
→ Drift detection catches it within ~30 trades, halves position sizes, and triggers emergency retraining.

**When do we need a human to step in?**
→ Walk-forward validation before major deployments. The autoresearch review in the morning. Everything else is automated.

**What's the most expensive thing?**
→ If using Claude Sonnet for autoresearch: ~$5 per overnight run. If using Gemini Flash: ~$0.50. The training loops themselves cost $0.

---

*Research compiled 2026-03-23. All costs based on March 2026 API pricing. All time estimates from actual source code analysis.*
