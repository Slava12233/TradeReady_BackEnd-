---
type: research-report
title: "Agent Trading Strategies Research Report"
status: archived
phase: agent-strategies
tags:
  - research
  - agent-strategies
---

# Agent Trading Strategies Research Report

> **Goal:** Identify the 5 best strategies for building AI trading agents on the TradeReady platform that can improve portfolio performance by 10%+. This informs what to build next and how to develop the agent system.

> **Date:** 2026-03-20

---

## Executive Summary

We evaluated five distinct agent strategy architectures, each exploiting different TradeReady platform capabilities (backtesting, strategy versioning, battles, Gymnasium RL, multi-agent). The strategies range from a single regime-adaptive agent (simplest, 3-5 days) to a hybrid ensemble combining all approaches (most robust, 12-18 days). **Our recommendation: start with Strategy 4 (RL Portfolio Agent) because the Gymnasium infrastructure is already built, then add Strategy 3 (Evolutionary) to optimize parameters via battles. These two alone should exceed the 10% target.**

---

## Platform Capabilities Summary (Agent's Perspective)

Before diving into strategies, here's what the agent can actually use:

| Surface | Capabilities | Count |
|---------|-------------|-------|
| **SDK** | Market data, trading, account, analytics, strategies, training | 37 methods |
| **MCP** | All platform tools auto-discovered | 58 tools |
| **REST API** | Backtesting, strategies, battles, full CRUD | 90+ endpoints |
| **WebSocket** | Real-time prices, orders, portfolio, battles | 5 channels |
| **Gymnasium** | RL training environments with rewards & wrappers | 7 envs, 4 rewards, 3 wrappers |

**Key feedback loop:** Observe market -> Decide -> Trade -> Risk validation (8-step) -> Execution -> Portfolio update -> Performance analytics (Sharpe, Sortino, drawdown, win rate)

---

## Strategy 1: Regime-Adaptive Technical Agent (Single Agent)

### Concept

One agent that detects market regimes (trending, mean-reverting, high-volatility, low-volatility) and switches between pre-built strategy versions accordingly. Uses the platform's `IndicatorEngine` (RSI, MACD, SMA, EMA, Bollinger Bands, ADX, ATR) for signal generation and a gradient-boosted classifier (XGBoost/LightGBM) for regime detection.

Inspired by the 2026 "Generating Alpha" paper (ComSIA 2026) which showed hybrid technical-ML systems outperforming NASDAQ-100 by 43%.

### Architecture

```
┌─────────────────────────────────────────┐
│         Regime-Adaptive Agent            │
│                                          │
│  ┌──────────────┐  ┌─────────────────┐  │
│  │ Regime        │  │ Strategy        │  │
│  │ Classifier    │──│ Version Switcher│  │
│  │ (XGBoost)     │  │                 │  │
│  └──────┬───────┘  └────────┬────────┘  │
│         │                    │           │
│  ┌──────┴───────────────────┴────────┐  │
│  │     4 Strategy Versions            │  │
│  │  Trending | Mean-Rev | Hi-Vol |    │  │
│  │  Lo-Vol                            │  │
│  └────────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### How It Works

1. **Regime Detection**: Train classifier on ADX (trend strength), ATR (volatility), Bollinger width (compression) to identify market state
2. **Strategy Selection**: Each regime maps to a platform strategy version:
   - **Trending**: MACD crossover + ADX > 25, trailing stop exit
   - **Mean-Reverting**: RSI oversold/overbought + Bollinger bounce
   - **High-Volatility**: Tight stops, 3% position sizing, ATR exits
   - **Low-Volatility**: Bollinger squeeze breakout, larger positions
3. **Execution**: `StrategyExecutor.decide()` evaluates conditions per candle step

### Platform Tools Used

- **Strategy System**: 4 versioned strategies via `/api/v1/strategies`
- **Backtesting**: Validate each regime strategy on different historical periods
- **IndicatorEngine**: 7 built-in indicators (pure numpy, no TA-Lib)
- **Risk Profile**: Per-agent `risk_profile` with position limits and daily loss circuit breaker

### Risk Management

- Per-regime position sizing (3-15% of equity)
- ATR-based dynamic stop-losses (2x ATR trending, 1x ATR mean-reversion)
- Daily loss circuit breaker at 3%
- Max 3 concurrent positions
- No trading during regime transition uncertainty

### Path to 10%

Static strategies fail when market regime changes (momentum strategy in sideways market = losses). Regime switching avoids the largest drawdowns. Research shows 15-40% excess returns over static approaches.

**Validation**: 12 one-month backtests across 2024-2025. Target positive alpha in 8/12 months.

### Assessment

| Metric | Value |
|--------|-------|
| Implementation effort | 3-5 days |
| Expected improvement | +5-8% vs static baseline |
| Complexity | Medium |
| Risk of failure | Low-Medium (classifier accuracy critical) |
| Platform feature coverage | Strategy versioning, backtesting, indicators |

---

## Strategy 2: Multi-Agent Trading Team (Analyst + Trader + Risk Manager)

### Concept

Three specialized agents with distinct roles, mirroring a professional trading desk. Inspired by the TradingAgents framework (Tauric Research, 2024-2026) which demonstrated superior Sharpe ratios with role-based multi-agent systems.

### Architecture

```
┌──────────────────────────────────────────────────┐
│                 Coordination Layer                 │
│                                                    │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐ │
│  │  Analyst    │  │  Trader    │  │  Risk       │ │
│  │  Agent      │──│  Agent     │──│  Manager    │ │
│  │             │  │            │  │  Agent      │ │
│  │ Scans 600+  │  │ Executes   │  │ Monitors    │ │
│  │ pairs, ranks│  │ entries &  │  │ portfolio,  │ │
│  │ opportunities│ │ exits      │  │ vetoes bad  │ │
│  │             │  │            │  │ trades      │ │
│  └─────────────┘  └────────────┘  └─────────────┘ │
└──────────────────────────────────────────────────┘
```

### How It Works

1. **Analyst Agent** (every candle interval):
   - Computes RSI, MACD, ADX, Bollinger Bands for top 50 liquid pairs
   - Scores each pair with a composite signal (weighted indicator sum)
   - Publishes top 5 opportunities to shared strategy metadata

2. **Trader Agent** (reads analyst output):
   - Evaluates entry conditions from deployed strategy version
   - Checks if pair is already in portfolio
   - Places orders (limit for entry, market for exit)
   - Manages trailing stops and take-profits

3. **Risk Agent** (runs concurrently):
   - Monitors total exposure (position values / total equity)
   - Checks correlation between open positions
   - Enforces max drawdown rules (close weakest positions if drawdown > 5%)
   - Adjusts position sizing based on recent ATR

### Platform Tools Used

- **Multi-Agent System**: 3 agents via `/api/v1/agents`, each with own API key and wallet
- **Strategy Versioning**: Shared strategy; Analyst creates new versions when conditions change
- **Backtesting**: All 3 agents participate in backtest sessions
- **WebSocket**: Real-time price updates for Analyst's pair scanning

### Risk Management

Three-layer defense:
1. Strategy-level stops (Trader)
2. Portfolio-level limits (Risk Agent)
3. Platform-level circuit breaker (automatic)

Risk Agent has veto power. Max 30% equity in open positions. Max 10% per position. No more than 2 positions in same sector.

### Path to 10%

Separation of concerns prevents the common failure: optimizing returns while ignoring risk. Dedicated Risk Agent avoids large drawdowns that typically erode 10-20% of portfolio. The TradingAgents paper showed superior cumulative returns and Sharpe.

**Validation**: Multi-agent team vs single agent in historical battle (`historical_week` preset, `ranking_metric=sharpe_ratio`).

### Assessment

| Metric | Value |
|--------|-------|
| Implementation effort | 7-10 days |
| Expected improvement | +3-5% from risk management alone |
| Complexity | High |
| Risk of failure | Medium (coordination bugs) |
| Platform feature coverage | Multi-agent, strategies, battles, WebSocket |

---

## Strategy 3: Evolutionary Battle-Driven Agent (Genetic Algorithm)

### Concept

A population of 8-16 agents with different strategy parameters compete in historical battles. Top performers' parameters are crossed over and mutated to create the next generation. Uses the battle system as a natural selection mechanism.

Based on the CGA-Agent framework which demonstrated +29% (BTC), +550% (ETH), +169% (BNB) improvements through genetic optimization.

### Architecture

```
┌─────────────────────────────────────────────────┐
│            Evolutionary Orchestrator              │
│                                                   │
│  Generation N:                                    │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐           │
│  │Agent1│ │Agent2│ │Agent3│ │...N  │           │
│  │RSI:30│ │RSI:25│ │RSI:35│ │      │           │
│  │SL:2% │ │SL:3% │ │SL:1% │ │      │           │
│  │TP:5% │ │TP:8% │ │TP:4% │ │      │           │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘           │
│     └────────┴────────┴────────┘                 │
│                    │                              │
│                    ▼                              │
│           Historical Battle                       │
│           (HistoricalBattleEngine)                │
│                    │                              │
│                    ▼                              │
│         Rank by Sharpe (RankingCalculator)         │
│                    │                              │
│                    ▼                              │
│     Select Top K → Crossover → Mutate             │
│                    │                              │
│                    ▼                              │
│           Generation N+1                          │
└─────────────────────────────────────────────────┘
```

### How It Works

1. **Initialize**: Create N agents, each with randomized strategy parameters:
   - RSI thresholds (20-40 oversold, 60-80 overbought)
   - Stop-loss % (1-5%), take-profit % (2-10%), trailing stop (0.5-3%)
   - Position size (3-20% of equity)
   - Max hold duration (10-200 candles)
   - Which pairs to trade (subset of available)

2. **Compete**: Run historical battle with all N agents trading the same time period
   - `HistoricalBattleEngine` gives each agent its own `BacktestSandbox`
   - Shared price feed, deterministic and reproducible

3. **Rank**: `RankingCalculator.rank_participants()` scores by multi-metric fitness:
   - `fitness = sharpe_ratio - 0.5 * max_drawdown_pct`

4. **Evolve**:
   - Top 20% auto-advance (elitism)
   - Tournament selection for parents
   - Crossover: blend parameters from 2 parents
   - Mutation: perturb 1-2 parameters by +/- 10%

5. **Repeat** for 20-50 generations until convergence

### Platform Tools Used

- **Battle System**: Each generation = one historical battle
- **Strategy Versioning**: Each agent's genome = one strategy version (full audit trail)
- **RankingCalculator**: Multi-metric fitness out of the box
- **Battle Presets**: `historical_month` for thorough evaluation, `historical_day` for rapid screening
- **Replay**: `get_replay_data()` to review how top agents traded

### Risk Management

- Fitness function penalizes drawdown directly
- Agents with > 15% max drawdown eliminated regardless of returns
- Position sizing is part of the genome — evolution selects conservative sizing that survives
- Platform circuit breaker at 5% daily loss

### Path to 10%

CGA-Agent showed 29-550% improvements after genetic optimization. Conservative expectation: 15-30% over random parameters. The battle system provides exactly the tournament selection mechanism genetic algorithms need.

**Validation**: 30 generations x 12 agents on 6 different one-month periods. Champion validated on held-out months.

### Assessment

| Metric | Value |
|--------|-------|
| Implementation effort | 5-8 days |
| Expected improvement | +10-20% optimized parameters |
| Complexity | Medium-High |
| Risk of failure | Medium (overfitting to training period) |
| Platform feature coverage | Battles, strategy versioning, ranking |

---

## Strategy 4: PPO Reinforcement Learning Portfolio Agent

### Concept

Train a PPO (Proximal Policy Optimization) agent using the platform's Gymnasium environments. The agent learns optimal portfolio allocation across multiple assets, using the `SharpeReward` function to optimize risk-adjusted returns. The gym infrastructure is **already built** — this is the fastest path to a trained agent.

Based on research showing SAC achieving 2.76x returns and PPO being the most stable RL algorithm for crypto portfolio management.

### Architecture

```
┌──────────────────────────────────────────────┐
│           PPO Portfolio Agent                  │
│                                                │
│  ┌──────────────┐    ┌─────────────────────┐  │
│  │ LSTM Policy   │    │ MultiAssetTradingEnv│  │
│  │ Network       │◄──►│ (tradeready-gym)    │  │
│  │ (SB3 PPO)    │    │                     │  │
│  └──────────────┘    │ obs: OHLCV + RSI +  │  │
│                       │   MACD + BB + ADX + │  │
│                       │   portfolio state   │  │
│                       │                     │  │
│                       │ action: portfolio   │  │
│                       │   weight targets    │  │
│                       │   [0,1] per asset   │  │
│                       │                     │  │
│                       │ reward: SharpeReward│  │
│                       └─────────────────────┘  │
└──────────────────────────────────────────────┘
```

### How It Works

1. **Observation Space** (per asset, per lookback window):
   - OHLCV (5 dims), RSI (1), MACD (3), Bollinger (3), ADX (1), ATR (1)
   - Portfolio state: cash ratio, position values, unrealized PnL

2. **Action Space**: `Box(0, 1, shape=(N,))` — target portfolio weights for N assets (BTC, ETH, SOL, BNB, XRP)

3. **Reward**: `SharpeReward` (rolling Sharpe ratio delta) + `DrawdownPenaltyReward` for risk awareness

4. **Training Pipeline**:
   ```
   Select 12 months data → 8/2/2 train/val/test split
   Train PPO for 500K-1M timesteps
   Validate: Sharpe > 1.0 on validation set
   Test: Sharpe > 0.8, max_drawdown < 15% on test set
   Deploy as strategy definition
   ```

5. **Each `reset()`** creates a new backtest session. Each `step()` advances one candle, executes rebalancing orders, returns `(obs, reward, terminated, truncated, info)`.

### Platform Tools Used

- **tradeready-gym**: `TradeReady-Portfolio-v0` environment (already built)
- **Reward Functions**: `SharpeReward`, `DrawdownPenaltyReward`, `SortinoReward` (already built)
- **Wrappers**: `FeatureEngineeringWrapper`, `NormalizationWrapper`, `BatchStepWrapper` (already built)
- **TrainingTracker**: Auto-reports episodes to `/api/v1/training/*` for dashboard visibility
- **Backtesting Engine**: Gym wraps backtest API under the hood

### Risk Management

- Action clipping: weights clipped to [0,1], normalized to sum <= 1.0
- `DrawdownPenaltyReward`: negative reward proportional to drawdown
- Position limits enforced by `BacktestSandbox.risk_limits`
- Agent can go 100% cash (defensive action)
- Ensemble: train 3 PPO agents with different seeds, use mean-weight for deployment

### Path to 10%

SAC portfolio management showed 2.76x returns (176% gain). PPO is more stable. Conservative expectation: 15-30% annualized improvement over equal-weight, with better Sharpe. The RL agent learns to go to cash during drawdowns — this alone can add 10%+.

**Validation**: Train Jan-Aug 2025, validate Sep-Oct, test Nov-Dec. Monitor via `TrainingTracker`. Compare vs equal-weight rebalancing and buy-and-hold BTC.

### Assessment

| Metric | Value |
|--------|-------|
| Implementation effort | 4-7 days (gym already built) |
| Expected improvement | +8-15% vs equal-weight baseline |
| Complexity | Medium |
| Risk of failure | Medium (non-stationary markets) |
| Platform feature coverage | Gymnasium, backtesting, training tracker |

---

## Strategy 5: Hybrid Ensemble (RL + Technical + Evolutionary)

### Concept

Combines the strongest elements of Strategies 1, 3, and 4 with the risk management of Strategy 2. Three uncorrelated signal sources vote on each decision, with a meta-learner combining their outputs.

This mirrors the industry trend where hybrid approach adoption grew from 15% to 42% (2020-2025). The "Generating Alpha" paper showed hybrid systems outperforming any single method by 10-40%.

### Architecture

```
┌──────────────────────────────────────────────────────┐
│              Hybrid Ensemble System                    │
│                                                        │
│  Layer 3: Meta-Learner (Confidence-Weighted Voting)    │
│     ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│     │ Signal A  │  │ Signal B  │  │ Signal C  │         │
│     │ Regime-   │  │ PPO RL    │  │ Evolved   │         │
│     │ Adaptive  │  │ Portfolio │  │ Champion  │         │
│     │ (Strat 1) │  │ (Strat 4) │  │ (Strat 3) │         │
│     └─────┬─────┘  └─────┬─────┘  └─────┬─────┘         │
│           └───────────────┼───────────────┘              │
│                           ▼                              │
│  Layer 2: Risk Overlay (Dedicated Risk Agent)            │
│     Veto | Resize | Correlation Check                    │
│                           ▼                              │
│  Layer 1: Platform Execution                             │
│     Limit orders (entry) | Market orders (exit)          │
└──────────────────────────────────────────────────────┘
```

### How It Works

1. **Signal Generation** (parallel):
   - Technical Signal: regime classifier -> strategy version -> `StrategyExecutor.decide()`
   - RL Signal: PPO model outputs portfolio weights with confidence (action probability)
   - Evolved Signal: battle-champion agent outputs orders from optimized parameters

2. **Meta-Learner Combination**:
   - Each signal: {BUY, SELL, HOLD} with confidence [0, 1]
   - `final_signal = sum(signal_i * confidence_i * weight_i)`
   - Meta-learner weights optimized via battles (different weight configs compete)
   - Only act when combined confidence > 0.6

3. **Risk Overlay**: Dedicated Risk Agent (Strategy 2) applies portfolio-level constraints, can veto or resize

4. **Execution**: Limit orders for entries (better fills), market orders for exits (guaranteed)

### Platform Tools Used

- **Everything**: Strategies, backtesting, battles, Gymnasium, multi-agent, training tracker, WebSocket, metrics — full platform utilization

### Risk Management

Most robust of all five strategies:
1. **Method diversification**: 3 uncorrelated signals reduce simultaneous failure probability
2. **Confidence gating**: low-confidence signals filtered before execution
3. **Risk Agent veto**: portfolio-level constraints from dedicated agent
4. **Platform circuit breaker**: 3% daily loss (platform-enforced)
5. **Dynamic sizing**: inverse to recent volatility (ATR-based)
6. **Disagreement signal**: when models disagree = reduce exposure

### Path to 10%

Ensemble methods consistently outperform individuals in financial ML. By combining rule-based (low overfitting), RL (pattern discovery), and evolved (parameter optimization), the ensemble captures different alpha types while averaging out weaknesses.

**Validation**: Build components (Strategies 1, 3, 4) -> optimize meta-learner weights via battles -> ensemble vs each individual in historical battle -> target ensemble Sharpe > max(individual Sharpe).

### Assessment

| Metric | Value |
|--------|-------|
| Implementation effort | 12-18 days (builds on Strategies 1, 3, 4) |
| Expected improvement | +18-35% cumulative |
| Complexity | Very High |
| Risk of failure | Low (redundancy from ensemble) |
| Platform feature coverage | Everything (maximum ROI on platform) |

---

## Strategy Comparison Matrix

| Strategy | Effort | Expected Gain | Risk | Complexity | Platform Features Used |
|----------|--------|---------------|------|------------|----------------------|
| 1. Regime-Adaptive | 3-5 days | +5-8% | Low-Med | Medium | Strategies, backtesting, indicators |
| 2. Multi-Agent Team | 7-10 days | +3-5% (risk) | Medium | High | Multi-agent, strategies, battles, WS |
| 3. Evolutionary | 5-8 days | +10-20% | Medium | Med-High | Battles, strategies, ranking |
| 4. PPO RL Agent | 4-7 days | +8-15% | Medium | Medium | Gymnasium, backtesting, training |
| **5. Hybrid Ensemble** | **12-18 days** | **+18-35%** | **Low** | **Very High** | **Everything** |

---

## Recommended Implementation Roadmap

```
Phase A: Strategy 4 (PPO RL Agent)           ← START HERE
  Duration: 4-7 days
  Why first: Gym infrastructure already built
  Deliverable: Trained PPO model achieving Sharpe > 1.0

Phase B: Strategy 3 (Evolutionary)
  Duration: 5-8 days
  Why second: Battle system optimizes parameters
  Deliverable: Champion agent with optimized strategy params

Phase C: Strategy 1 (Regime-Adaptive)
  Duration: 3-5 days
  Why third: Adds rule-based signal (uncorrelated with RL)
  Deliverable: 4 strategy versions + regime classifier

Phase D: Strategy 2 (Risk Agent overlay)
  Duration: 3-5 days (simplified — just the Risk Agent)
  Why fourth: Adds risk management layer
  Deliverable: Risk Agent with veto logic

Phase E: Strategy 5 (Ensemble Integration)
  Duration: 3-5 days (incremental — components already exist)
  Why last: Combines everything
  Deliverable: Meta-learner with confidence voting

Total: ~20-30 days for full ensemble
10% target achievable: Phase A or B alone
```

---

## Sources

- TradingAgents: Multi-Agent LLM Financial Trading Framework (arXiv:2412.20138)
- CGA-Agent: Genetic Algorithm for Crypto Trading Strategy Optimization (arXiv:2510.07943)
- RL-Based Cryptocurrency Portfolio Management with SAC and DDPG (arXiv:2511.20678)
- Generating Alpha: Hybrid AI-Driven Trading System (ComSIA 2026, arXiv:2601.19504)
- AI Agents in Financial Markets (arXiv:2603.13942)
- Modular RL for Multi-Market Portfolio Optimization (MDPI Informatics 16/11/961)
- GeneTrader: Genetic Algorithm Optimization for Trading Strategies (GitHub)
- Deep RL PPO Portfolio Optimization (Medium)
