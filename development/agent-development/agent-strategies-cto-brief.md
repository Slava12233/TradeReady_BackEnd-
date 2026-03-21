---
type: research-report
title: "Agent Trading Strategies — CTO Technical Brief"
status: archived
phase: agent-strategies
tags:
  - research
  - agent-strategies
---

# Agent Trading Strategies — CTO Technical Brief

> **Audience:** CTO / Technical Leadership (not quant traders)
> **Purpose:** Understand what each strategy actually requires to build and run — agents, DB load, compute, cycles, timelines, and what can go wrong
> **Date:** 2026-03-20

---

## Why Are We Doing This?

We built a full trading platform with backtesting, battles, strategies, Gymnasium RL, and multi-agent support. Now we need to prove it works — that an AI agent can actually use these tools to improve its portfolio by 10%.

But we don't know **which approach** will work best. So instead of guessing, we test 5 different strategies. Each one exercises different platform features. The winner tells us:
- Which platform features actually matter (where to invest engineering time)
- What's missing or broken (bugs we never hit with unit tests)
- How to build the production agent system

Think of it as **dogfooding with purpose**.

---

## Quick Comparison — All 5 Strategies at a Glance

| | Strategy 1 | Strategy 2 | Strategy 3 | Strategy 4 | Strategy 5 |
|---|---|---|---|---|---|
| **Name** | Regime-Adaptive | Multi-Agent Team | Evolutionary | PPO RL Agent | Hybrid Ensemble |
| **One-liner** | Switch strategy when market changes | 3 agents with different jobs | Agents compete, best DNA survives | Train a neural network to trade | Combine all signals, vote |
| **Agents needed** | 1 | 3 | 12 per generation | 1-3 (seeds) | 4-6 |
| **DB rows created** | ~3K per backtest | ~9K per backtest | ~36K per generation | ~36K per training run | Depends on components |
| **Compute** | Low | Medium | High (batch) | Medium-High | High |
| **Build time** | 3-5 days | 7-10 days | 5-8 days | 4-7 days | 12-18 days |
| **Expected gain** | +5-8% | +3-5% | +10-20% | +8-15% | +18-35% |
| **New deps** | xgboost | None | None | stable-baselines3, torch | All of the above |
| **Platform features tested** | Strategies, indicators | Multi-agent, WebSocket | Battles, ranking | Gymnasium, training tracker | Everything |

---

## Strategy 1: Regime-Adaptive Technical Agent

### What is it in plain terms?

Markets behave differently at different times — sometimes trending up, sometimes bouncing sideways, sometimes volatile and chaotic. This agent detects which "mode" the market is in, then switches to the right trading rules for that mode.

Think of it like driving: you don't use the same gear on a highway and in a parking lot.

### How many agents?

**1 agent.** Single agent, single wallet, single API key. The simplest setup.

### How does it work step by step?

```
Every candle (e.g., every 1 hour):
  1. Agent reads last 100 candles for BTC, ETH, SOL
  2. Computes indicators: ADX (trend strength), ATR (volatility), Bollinger width
  3. XGBoost classifier says: "this is a TRENDING market" (or mean-reverting, high-vol, low-vol)
  4. Agent activates the matching strategy version (we pre-create 4 versions on the platform)
  5. Strategy version's rules decide: buy, sell, or hold
  6. If trading: places order via SDK → risk manager validates → order fills
```

### How many cycles / iterations?

- **Training the classifier:** One-time, offline. ~50K candles of labeled historical data. Takes ~5 minutes on CPU.
- **Backtesting:** 12 runs (one per month of test data). Each run = ~744 steps (1h candles, 1 month). Total: ~8,928 steps across all backtests.
- **Live operation:** 1 decision per candle interval. At 1h candles = 24 decisions/day.

### What hits the database?

| What | Rows | When |
|------|------|------|
| Strategy definitions | 4 rows (one per regime) | One-time setup |
| Strategy versions | 4 rows | One-time setup |
| Per backtest session | 1 `backtest_sessions` + ~50-150 `backtest_trades` + ~720 `backtest_snapshots` | Per validation run |
| Total for 12 validation backtests | ~12 sessions + ~1,800 trades + ~8,640 snapshots = **~10,500 rows** | During validation |

**Redis:** Zero additional keys. Uses existing price hash only.

### Infrastructure requirements

- **CPU:** Minimal. XGBoost inference is microseconds.
- **Memory:** ~50 MB for the classifier model + candle data buffer.
- **DB:** Negligible load. 12 backtest sessions is nothing.
- **Celery:** No special requirements. Standard beat schedule is fine.
- **New dependencies:** `xgboost` or `lightgbm` (~50 MB install).

### What can go wrong?

1. **Regime classifier is wrong** — If it thinks the market is trending when it's actually sideways, we apply the wrong strategy. Mitigation: confidence threshold — don't switch unless the classifier is 70%+ sure.
2. **Regime transitions** — Markets don't cleanly switch regimes. There's a messy transition period. Mitigation: 5-candle cooldown after any regime change.
3. **Labeling is subjective** — How do you define "trending" vs "mean-reverting"? We use heuristics (ADX > 25 = trending), but these thresholds are somewhat arbitrary.

### Bottom line

**Safest bet, lowest investment.** Won't blow anything up. Uses platform features that are well-tested (strategy versioning, indicators). Good starting point if we want quick results with minimal infrastructure.

---

## Strategy 2: Multi-Agent Trading Team

### What is it in plain terms?

Instead of one agent doing everything, we split the work across three specialists:
- **Analyst** — scans 600+ pairs, ranks the best opportunities
- **Trader** — executes trades based on the Analyst's recommendations
- **Risk Manager** — watches the whole portfolio, can veto bad trades

Like a trading desk at a bank, but with AI agents.

### How many agents?

**3 agents**, each created via `/api/v1/agents`. Each gets its own API key and wallet.

| Agent | Wallet | Role |
|-------|--------|------|
| Analyst | $0 (advisory only) | Scans markets, ranks opportunities |
| Trader | $10,000 (holds capital) | Executes entries and exits |
| Risk Manager | $0 (advisory only) | Monitors portfolio, vetoes bad trades |

Only the Trader agent has real capital. The other two are advisory — they read data but don't trade.

### How does it work step by step?

```
Every candle interval:
  1. Analyst fetches prices + indicators for top 50 pairs
  2. Analyst scores each pair (composite signal: RSI + MACD + ADX weighted)
  3. Analyst writes top 5 picks to a shared data store

  4. Risk Manager checks current portfolio:
     - Total exposure (what % of equity is in open positions?)
     - Correlation between positions (too many similar coins?)
     - Recent drawdown (is the portfolio losing too much?)
  5. Risk Manager outputs: "OK to trade" or "reduce exposure" or "halt trading"

  6. Trader reads Analyst's picks + Risk Manager's signal
  7. Trader evaluates strategy entry conditions
  8. If conditions met AND Risk Manager says OK: places order
  9. If Risk Manager says "reduce": closes weakest position instead
```

### How many cycles / iterations?

- **Per candle:** 3 sequential agent decisions (Analyst → Risk → Trader)
- **Per day at 1h candles:** 24 candles × 3 agent calls = **72 agent decisions/day**
- **Backtesting:** Same as Strategy 1 but 3x the orders since each step involves 3 agents reading data. ~2,232 API calls per 1-month backtest.

### What hits the database?

| What | Rows | When |
|------|------|------|
| Agent creation | 3 agents × 2 rows = 6 rows | One-time setup |
| Per backtest session | 1 session + ~100-300 trades + ~720 snapshots | Per run |
| Portfolio snapshots (live) | 3 agents × 1,440/day = 4,320 rows/day | Continuous (pruned to 7 days) |
| Communication overhead | 0 extra DB rows (shared via in-memory or strategy metadata) | Per candle |

**Redis:** Rate limit keys for 3 API keys instead of 1. ~3x the rate limit entries. Negligible memory impact.

### Infrastructure requirements

- **CPU:** Low-Medium. Three agent decisions per candle, but each is lightweight.
- **Memory:** ~100 MB (3 agent contexts in memory).
- **DB:** Slightly more than Strategy 1 due to 3x snapshot accumulation. Still manageable.
- **Celery:** Standard. No special tasks needed.
- **New dependencies:** None. Uses existing SDK and REST tools.
- **Coordination layer:** This is the hard part. We need to build a simple orchestrator that sequences Analyst → Risk → Trader and handles their communication. ~500 lines of Python.

### What can go wrong?

1. **Coordination bugs** — Agent A's output doesn't match Agent B's expected input format. Debugging requires tracing across all 3 agents.
2. **Latency** — 3 sequential agent calls per candle adds latency. At 1h candles this doesn't matter. At 1m candles it could.
3. **The Risk Manager is too conservative** — Vetoes too many trades, agent barely trades. Need to tune the thresholds.
4. **Capital efficiency** — Only 1 of 3 agents holds capital. The other 2 are "wasted" from a wallet perspective.

### Bottom line

**Best for risk management**, but the highest implementation complexity. The coordination layer between agents is custom code we'd have to build and maintain. Worth it if drawdown prevention is the priority.

---

## Strategy 3: Evolutionary Battle-Driven Agent

### What is it in plain terms?

Create 12 agents with random trading parameters. Let them fight in a historical battle. The top performers "breed" — their parameters get combined and slightly mutated to create the next generation. Repeat 30 times. It's Darwinian evolution for trading strategies.

This is the most interesting one from a platform perspective because it uses the **battle system** as the selection mechanism — exactly what we built it for.

### How many agents?

**12 agents per generation × 30 generations = 360 agent instances total.**

But we don't need 360 agents in the DB simultaneously. We can reuse agents by resetting them between generations:
- Create 12 agents once
- Each generation: reset their balances, update their strategy parameters, run the battle
- Only the champion's strategy versions are permanently saved

### How does it work step by step?

```
SETUP (once):
  1. Create 12 agents via /api/v1/agents
  2. Create 12 strategy definitions with random parameters:
     - RSI thresholds: random between 20-40 (oversold) and 60-80 (overbought)
     - Stop-loss: random between 1-5%
     - Take-profit: random between 2-10%
     - Position size: random between 3-20% of equity
     - etc. (15-20 parameters total)

FOR EACH GENERATION (30 total):
  3. Create a historical battle: POST /api/v1/battles
     - Preset: "historical_week" (7 days of 1m candles)
     - Add all 12 agents as participants
  4. Run the battle to completion
     - Each agent trades according to its strategy parameters
     - Battle engine gives each agent its own sandbox (isolated)
     - Shared price feed, deterministic, reproducible
  5. Get results: GET /api/v1/battles/{id}/results
     - RankingCalculator scores by: Sharpe ratio - 0.5 × max_drawdown
  6. Evolution:
     - Top 2 agents auto-advance (elitism)
     - Pick 10 parent pairs via tournament selection
     - Crossover: child gets 50% of parameters from each parent
     - Mutation: randomly perturb 1-2 parameters by ±10%
  7. Reset all 12 agents, update strategies with new parameters
  8. Go to step 3

AFTER 30 GENERATIONS:
  9. Champion agent's parameters = our "evolved strategy"
  10. Validate on held-out data (months the evolution never saw)
```

### How many cycles / iterations?

This is the big one:

| Metric | Value |
|--------|-------|
| Generations | 30 |
| Agents per generation | 12 |
| Steps per agent per battle | 10,080 (7 days × 1m candles) |
| Total steps across all battles | 30 × 12 × 10,080 = **3,628,800 steps** |
| Battles created | 30 |
| Total backtest sessions | 30 × 12 = **360 sessions** |
| Wall-clock time per battle (batch stepping) | ~1-3 minutes |
| Total wall-clock time | **~30-90 minutes** (battles run sequentially per generation) |

### What hits the database?

This is where it gets heavy:

| What | Rows per generation | Total (30 generations) |
|------|-------------------|-----------------------|
| `battles` | 1 | 30 |
| `battle_participants` | 12 | 360 |
| `backtest_sessions` | 12 | 360 |
| `backtest_trades` | 12 × ~150 = 1,800 | ~54,000 |
| `backtest_snapshots` | 12 × ~720 = 8,640 | ~259,200 |
| `battle_snapshots` (historical) | 12 × ~168 = 2,016 | ~60,480 |
| `strategy_versions` | 12 (new params each gen) | 360 |
| **Total rows per generation** | **~12,500** | **~374,400 total** |

**That's ~374K rows for a full evolution run.** Not terrible for TimescaleDB (which handles billions), but worth knowing.

**Cleanup:** `backtest_snapshots` and `backtest_trades` older than 90 days are auto-deleted by the nightly Celery task. So this data self-prunes.

### Infrastructure requirements

- **CPU:** Medium-High during evolution runs. 12 concurrent backtest sandboxes, each doing in-memory order matching and snapshot computation. But it's batch work — you run it and walk away.
- **Memory:** ~12 active backtest sandboxes × ~43 MB each (5 pairs, 1m candles, 7 days) = **~516 MB** of in-memory price cache. Plus the BacktestEngine overhead. Total: **~600-800 MB during evolution.**
- **DB:** ~374K rows total. TimescaleDB handles this easily. The writes are bursty (all at battle completion) not sustained.
- **Redis:** No extra keys per battle (backtest sandboxes are in-memory). Rate limit keys for 12 agents = negligible.
- **Celery:** No Celery involvement for historical battles — the evolution orchestrator drives everything synchronously via REST API.
- **New dependencies:** None. Pure Python genetic algorithm code.
- **Disk:** Strategy versions accumulate (360 JSONB rows), but they're tiny (~2KB each).

### What can go wrong?

1. **Overfitting** — The evolved strategy is perfect for the training period but fails on new data. This is the #1 risk. Mitigation: always validate on held-out months the evolution never saw.
2. **Convergence to local optimum** — All 12 agents converge to similar parameters that aren't globally optimal. Mitigation: high mutation rate in early generations, lower later.
3. **Slow if we increase population size** — 12 agents × 30 generations is manageable. 100 agents × 100 generations = 10,000 battles = not fun. Keep it bounded.
4. **DB bloat if not cleaned up** — 374K rows per run × daily runs = need the cleanup tasks running.

### Bottom line

**Most exciting from a platform validation perspective.** It exercises the battle system, strategy versioning, ranking calculator, and backtest engine all at once. The genetic algorithm code is simple (~300 lines). The platform does the heavy lifting.

---

## Strategy 4: PPO Reinforcement Learning Portfolio Agent

### What is it in plain terms?

We train a neural network to manage a portfolio of 5 crypto assets. The network observes prices, indicators, and its own portfolio state, then outputs how much weight to give each asset (e.g., 40% BTC, 30% ETH, 20% SOL, 10% cash). It learns by trial and error across thousands of simulated trading episodes.

This uses the **Gymnasium environments we already built** (`tradeready-gym`). The infrastructure is ready — we just need to plug in a training algorithm.

### How many agents?

**1-3 agents** (we train 3 copies with different random seeds for robustness, then average their decisions).

### How does the training work, exactly?

Let me break down the full cycle:

```
TRAINING SETUP:
  - Asset universe: BTC, ETH, SOL, BNB, XRP (5 assets)
  - Historical data: 12 months, split 8/2/2 (train/validate/test)
  - Candle interval: 1 hour (so 1 month = 744 steps per episode)
  - Observation per step: 5 assets × (OHLCV + RSI + MACD + Bollinger + ADX + ATR) = 70 features
    + portfolio state (cash %, positions, unrealized PnL) = ~78 features total
    × 30 candle lookback window = 2,340 input dimensions

ONE TRAINING EPISODE:
  1. env.reset() → creates new backtest session via API
     - API call: POST /backtest/create
     - API call: POST /backtest/{id}/start (preloads all candle data into memory)
     - DB: 1 row in backtest_sessions

  2. For each step (744 steps in a 1-month episode at 1h candles):
     a. Agent observes: prices + indicators + portfolio state
        - API call: GET /backtest/{id}/market/candles/{symbol} × 5 pairs = 5 calls
     b. PPO network outputs: [0.35, 0.25, 0.20, 0.10, 0.10] (portfolio weights)
     c. Environment translates weights to orders (rebalancing trades)
        - API call: POST /backtest/{id}/trade/order × N orders (typically 2-5)
     d. Environment advances time:
        - API call: POST /backtest/{id}/step
     e. Environment computes reward: Sharpe ratio delta (risk-adjusted return change)
     f. PPO stores (state, action, reward) in replay buffer

  3. At episode end:
     - API call: GET /backtest/{id}/results (final metrics)
     - TrainingTracker: POST /training/runs/{id}/episodes (logs episode)
     - DB: ~50-300 backtest_trades, ~720 backtest_snapshots, 1 training_episodes

  4. After every 2-4 episodes: PPO updates its neural network weights
     (gradient descent on the collected experience — this is the actual "learning")

FULL TRAINING:
  - Total timesteps target: 500,000
  - Steps per episode: 744 (1h candles, 1 month)
  - Episodes needed: 500,000 / 744 ≈ 672 episodes
  - PPO update frequency: every 2,048 steps ≈ every 2.75 episodes
  - Total neural network updates: ~244 gradient updates
```

### Wait, 672 episodes? How long does that take?

Here's the time breakdown:

| Component | Per episode | Total (672 episodes) |
|-----------|-----------|---------------------|
| API calls per step | ~8 calls (5 candle fetches + 2-3 orders + 1 step) | 672 × 744 × 8 = ~4M API calls |
| Time per API call (localhost) | ~3-5 ms | — |
| Time per episode (API I/O) | 744 × 8 × 4ms ≈ **24 seconds** | — |
| PPO gradient update | ~2-5 seconds (CPU) / ~0.5s (GPU) | ~244 × 3s = **12 minutes** |
| Data preload per episode | ~1-2 seconds | 672 × 1.5s = **17 minutes** |
| **Total estimated time** | **~26 seconds per episode** | **~4.8 hours on CPU** |

**With 4 parallel environments:** ~1.2 hours. **With GPU for PPO updates:** ~45 minutes.

**With 1-minute candles instead** (43,200 steps/episode, only ~12 episodes needed): ~48-72 minutes total but fewer learning iterations — PPO may not converge well with only 12 updates.

**Recommended setup:** 1h candles, 500K steps, 4 parallel envs = **~1-2 hours of training time.**

### What hits the database?

| What | Per episode | Total (672 episodes) |
|------|-----------|---------------------|
| `backtest_sessions` | 1 | 672 |
| `backtest_trades` | ~50-300 | ~34,000 - 200,000 |
| `backtest_snapshots` | ~720 | ~484,000 |
| `training_episodes` | 1 | 672 |
| `training_runs` | — | 1 |
| **Total DB rows** | **~1,000** | **~520,000 - 685,000** |

With 3 seeds (3 training runs): multiply by 3 = **~1.5M - 2M rows total.**

**Important:** `backtest_snapshots` is a TimescaleDB hypertable with automatic time-based chunking. 2M rows in a hypertable is nothing — TimescaleDB handles billions. The nightly cleanup task deletes backtest detail data older than 90 days automatically.

### Memory requirements

| Component | Memory |
|-----------|--------|
| PPO neural network (MLP, 2 layers × 256 units) | ~5 MB |
| PPO replay buffer (2,048 steps × 2,340 features) | ~40 MB |
| Per backtest sandbox (price cache, 5 pairs, 1 month) | ~43 MB |
| 4 parallel envs | 4 × 43 = ~172 MB |
| PyTorch overhead | ~200 MB |
| **Total** | **~420 MB CPU / ~600 MB with GPU** |

### Infrastructure requirements

- **CPU:** Medium-High during training. 4 parallel envs making concurrent API calls. After training: minimal (inference is microseconds).
- **GPU:** Optional but helpful. PPO training on CPU works fine for this scale. GPU cuts gradient updates from ~3s to ~0.5s but the bottleneck is API I/O anyway.
- **Memory:** ~420 MB during training. Minimal after.
- **DB:** ~685K rows per training run. Bursty writes at episode boundaries. TimescaleDB handles it.
- **API server:** 4 parallel envs × 8 calls/step = 32 concurrent requests during training. Recommend `uvicorn --workers 4` for this workload.
- **Redis:** No extra keys. Backtest sandboxes are in-memory.
- **Celery:** No Celery involvement (backtest engine runs in-process, not via Celery tasks).
- **New dependencies:** `stable-baselines3` (~50 MB), `torch` (~800 MB CPU / ~2 GB GPU). This is the heaviest new dependency.
- **Disk:** Trained model weights: ~5-10 MB per model. Three seeds = ~30 MB.

### What can go wrong?

1. **Non-stationary markets** — The model learns patterns from historical data, but crypto markets change. A model trained on bull market data may fail in a bear market. Mitigation: train on diverse market conditions, retrain periodically.
2. **Reward hacking** — The agent finds a loophole in the reward function (e.g., holding cash indefinitely scores zero Sharpe, which avoids negative Sharpe). Mitigation: add a small trading frequency bonus to the reward.
3. **API bottleneck during training** — 32 concurrent API calls might overwhelm a single-worker uvicorn. Mitigation: run uvicorn with 4 workers, or use `BatchStepWrapper` to reduce call frequency.
4. **PyTorch dependency is heavy** — ~800 MB-2 GB install. Might conflict with other Python packages. Mitigation: separate virtualenv for the agent.
5. **Black box decisions** — The neural network outputs portfolio weights, but we can't easily explain *why*. Mitigation: log the observation features alongside each decision for post-hoc analysis.

### How do we know it's working?

The `TrainingTracker` sends episode metrics to the platform dashboard in real-time:

```
GET /api/v1/training/runs/{run_id}/learning-curve
```

You'll see a chart of:
- **Episode reward** (should trend upward and stabilize)
- **Sharpe ratio** per episode (should improve from ~0 to >1.0)
- **Max drawdown** per episode (should decrease over time)
- **Win rate** (should improve from ~50% toward 55-65%)

**Convergence signal:** When the learning curve flattens for 50+ episodes, training is done.

### Bottom line

**Best ROI on existing infrastructure.** The Gymnasium package (`tradeready-gym`) already has 7 environments, 4 reward functions, 3 wrappers, and a training tracker. We literally just need to:
1. Pick hyperparameters
2. Run `model.learn(total_timesteps=500_000)`
3. Wait 1-2 hours
4. Validate on held-out data

The platform does 90% of the work. This is why it's the recommended starting point.

---

## Strategy 5: Hybrid Ensemble

### What is it in plain terms?

Take the best parts of Strategies 1, 3, and 4, plus the Risk Manager from Strategy 2. Run them all in parallel. Each one produces a trading signal. A "meta-learner" combines their votes — if 2 out of 3 say "buy BTC," and the Risk Manager approves, we buy.

It's like having three different experts advise you, then making a decision based on the consensus.

### How many agents?

**4-6 agents total:**

| Agent | From | Role |
|-------|------|------|
| Regime-Adaptive Agent | Strategy 1 | Technical signal |
| PPO RL Agent | Strategy 4 | Neural network signal |
| Evolved Champion | Strategy 3 | Battle-optimized signal |
| Risk Manager | Strategy 2 | Veto / resize |
| Meta-Learner | New | Combines signals |
| (Optional) Execution Agent | New | Places final orders |

### How does it work step by step?

```
Every candle:
  1. [PARALLEL] All 3 signal agents analyze the market:
     - Regime agent: "BUY BTC (confidence: 0.8)"
     - RL agent: "BUY BTC weight 35% (confidence: 0.7)"
     - Evolved agent: "HOLD (confidence: 0.6)"

  2. Meta-learner combines:
     - BUY signals: 2 out of 3 (weighted: 0.8×0.3 + 0.7×0.4 + 0.0×0.3 = 0.52)
     - Combined confidence: 0.52 < 0.6 threshold → SKIP THIS TRADE

     Next candle, all 3 agree:
     - BUY BTC: 3 out of 3 (weighted: 0.85×0.3 + 0.9×0.4 + 0.7×0.3 = 0.82)
     - Combined confidence: 0.82 > 0.6 → PROCEED

  3. Risk Manager evaluates:
     - Portfolio exposure: 15% (under 30% limit) ✅
     - Correlation: only 1 existing position, low correlation ✅
     - Recent drawdown: 2% (under 5% limit) ✅
     - Verdict: APPROVED, position size: 8% of equity

  4. Execute: place limit buy for BTC, 8% of equity
```

### How many cycles to build this?

This strategy is built **incrementally** on top of the others:

| Phase | What | Cycles/Iterations | Time |
|-------|------|-------------------|------|
| Build Strategy 4 (PPO) | 672 training episodes | ~500K RL steps | 1-2 hours training |
| Build Strategy 3 (Evolutionary) | 30 generations × 12 agents | ~3.6M backtest steps | ~1-2 hours evolution |
| Build Strategy 1 (Regime) | 12 validation backtests | ~9K steps | ~10 minutes |
| Build Risk Agent | Testing | ~5K steps | ~5 minutes |
| Optimize meta-learner weights | 8-12 ensemble variants in battle | ~120K steps | ~30 minutes |
| **Total** | | **~4.2M steps** | **~3-5 hours compute** |

### What hits the database?

Everything from Strategies 1, 3, and 4 combined, plus:

| What | Rows |
|------|------|
| From Strategy 4 (PPO training) | ~685K |
| From Strategy 3 (Evolution) | ~374K |
| From Strategy 1 (Regime validation) | ~10K |
| Meta-learner weight optimization (12 battle variants) | ~150K |
| **Grand total** | **~1.2M rows** |

Again — TimescaleDB with auto-cleanup. This is fine.

### Infrastructure requirements (all components running)

| Resource | During build | In production (after training) |
|----------|-------------|-------------------------------|
| **CPU** | High (training + evolution + backtests) | Low (inference only) |
| **Memory** | ~1.5 GB peak (PPO + parallel backtests) | ~200 MB (3 models in memory) |
| **GPU** | Optional (PPO training) | Not needed |
| **DB writes** | ~1.2M rows (bursty) | Minimal (live trading only) |
| **API load** | 32+ concurrent requests during training | 15-20 per candle (3 agents reading) |
| **New deps** | stable-baselines3, torch, xgboost | Same |

### What can go wrong?

1. **Over-engineering** — The ensemble might not beat the best individual strategy by enough to justify the complexity. Mitigation: only build the ensemble if individual strategies already show 10%+ improvement.
2. **Signal conflict** — When all 3 models disagree all the time, the ensemble barely trades. Mitigation: track agreement rate — if it's below 30%, one model is broken.
3. **Debugging nightmare** — When the ensemble makes a bad trade, which model was responsible? Mitigation: log each signal source's contribution to every decision.
4. **Dependency chain** — Strategy 5 breaks if Strategy 1, 3, or 4 breaks. It inherits all their bugs. Mitigation: build and validate each component independently first.

### Bottom line

**The endgame.** Don't start here. Build Strategies 1, 3, and 4 first. If any individual strategy hits 10%, you might not even need the ensemble. But if you want maximum robustness and the best possible Sharpe ratio, this is the architecture.

---

## Database Impact Summary (Everything Combined)

If we run all 5 strategies through their full training/validation cycles:

| Table | Rows Added | Auto-Cleanup |
|-------|-----------|-------------|
| `backtest_sessions` | ~1,100 | Cleaned after 90 days |
| `backtest_trades` | ~290,000 | Cleaned after 90 days |
| `backtest_snapshots` | ~750,000 | Cleaned after 90 days (hypertable) |
| `battle_snapshots` | ~60,000 | Cleaned after 90 days (hypertable) |
| `battles` | ~45 | Never cleaned (small) |
| `battle_participants` | ~400 | Never cleaned (small) |
| `strategy_versions` | ~380 | Never cleaned (small, ~2KB each) |
| `training_episodes` | ~700 | Never cleaned (small) |
| `training_runs` | ~5 | Never cleaned (tiny) |
| `agents` | ~15 | Reused across strategies |
| **Total** | **~1.1M rows** | **Self-prunes to ~200K steady state** |

**Disk estimate:** ~1.1M rows × ~200 bytes avg = ~220 MB before compression. TimescaleDB compression typically achieves 90%+ compression on time-series data → **~22 MB on disk.**

This is nothing. Our `ticks` table from the Binance price feed generates more data in a single day.

---

## Redis Impact Summary

| Strategy | Extra Redis Keys | Extra Memory |
|----------|-----------------|-------------|
| 1 (Regime) | Rate limits for 1 agent | ~1 KB |
| 2 (Multi-Agent Team) | Rate limits for 3 agents | ~3 KB |
| 3 (Evolutionary) | Rate limits for 12 agents | ~12 KB |
| 4 (PPO RL) | Rate limits for 1-3 agents | ~3 KB |
| 5 (Ensemble) | Rate limits for 4-6 agents | ~6 KB |

**Backtest sandboxes use zero Redis.** All backtest state is in-memory in the `BacktestEngine._active` dict.

**Current Redis baseline:** ~500 KB (prices + tickers for 600 pairs). Adding all strategies: still under 1 MB.

---

## Celery Impact Summary

No strategy requires new Celery tasks. The existing 11 beat tasks handle everything:

| Task | Impact from Strategies |
|------|----------------------|
| `limit_order_monitor` (1s) | Only affects live trading (Strategy 2). Backtest orders are in-memory. |
| `capture_battle_snapshots` (5s) | Only for live battles. Historical battles write snapshots at completion. |
| `capture_minute_snapshots` (60s) | More agents = more snapshot rows, but auto-pruned to 7 days. |
| `cleanup_backtest_detail_data` (daily) | **Critical for Strategy 4.** Must be running to prune RL training backtest data. |
| All others | No impact. |

**Recommendation:** Make sure `cleanup_backtest_detail_data` is running. If it's not, Strategy 4 alone will add ~685K rows that never get cleaned up.

---

## My Recommendation as Development Path

```
Week 1:  Strategy 4 (PPO RL Agent)
         - Fastest to build (gym exists)
         - 1-2 hours training time
         - If Sharpe > 1.0 → we already have a winner

Week 2:  Strategy 3 (Evolutionary)
         - Battle system validates our competition infrastructure
         - 1-2 hours evolution time
         - Champion agent may beat the RL agent

Week 3:  Strategy 1 (Regime-Adaptive)
         - Low-risk, adds interpretable signal
         - Quick to build (3-5 days)
         - Now we have 3 uncorrelated signals

Week 4:  Strategy 2 (Risk overlay) + Strategy 5 (Ensemble)
         - Only if individual strategies show promise
         - Risk agent prevents drawdowns
         - Ensemble combines everything

STOP EARLY IF:
  - Any single strategy hits 10% on out-of-sample data
  - Focus on deploying that strategy to production instead of building the ensemble
```

**The 10% target is achievable with Strategy 4 alone.** Everything else is optimization and robustness. Don't over-build.
