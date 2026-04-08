---
type: research-report
tags:
  - c-level
  - strategy
  - roadmap
  - ai-automation
  - cto-advisory
date: 2026-04-07
status: complete
audience: C-level executives
---

# AI Strategy Automation: Endgame Vision & Build Roadmap

**CTO Advisory Document — April 7, 2026**
**Audience:** C-Level Executive Leadership
**Classification:** Internal Strategic Planning

---

## 1. Executive Summary

The platform's core mission is to help users train AI agents to trade better and smarter. We have built a simulated crypto exchange where AI agents trade virtual USDT against real Binance market data across 600+ currency pairs. The platform is production-deployed, battle-tested, and ready for the next phase.

**The endgame vision:** A user sets a goal — "achieve 10% monthly returns on BTC" — and the AI automatically discovers, tests, validates, and deploys the best strategy. No human expertise required for the search process.

**Current state assessment:**

| Layer | Status | Detail |
|-------|--------|--------|
| Infrastructure (exchange, execution, risk, data) | Complete | Production-deployed |
| AI strategy modules | 15 of 29 complete | Foundation is solid |
| Automated strategy search | Not yet built | 4–6 week sprint to build |
| User-facing manual workflow | Functional | Shippable now |

The foundation is complete. The intelligence layer — automated strategy discovery — requires a focused 4–6 week sprint. Three critical foundation modules unlock the entire automated search pipeline. This document provides the full technical picture, module-by-module breakdown, and strategic options for executive decision-making.

---

## 2. Platform Vision

### 2.1 The Manual Mode (Today)

The current workflow requires human expertise at every step:

```
User defines strategy rules
        ↓
  Runs backtest
        ↓
  Reviews results
        ↓
  Tweaks parameters
        ↓
  Re-runs backtest
        ↓
  Deploys to live trading
```

This works. Users with domain knowledge can build and deploy profitable strategies. The limitation is the human bottleneck: iteration speed is bounded by human attention, and the parameter search space is too large to explore manually.

### 2.2 The Automated Mode (Endgame)

```
User sets goal (e.g., "10% monthly on BTC")
        ↓
  AI searches parameter space automatically
  (~100 experiments overnight)
        ↓
  Statistical safety gates reject overfitting
  (Deflated Sharpe ratio — rejects >99% of false positives)
        ↓
  Walk-forward validation on unseen data
  (WFE ≥ 50% deployment gate)
        ↓
  Genetic evolution fine-tunes the winners
        ↓
  Ensemble combines best strategies
        ↓
  Deployed with monitoring, drift detection,
  and auto-retraining
```

This is inspired directly by Andrej Karpathy's Autoresearch framework (March 2026, 51.9k GitHub stars in its first week), which demonstrated that an LLM agent running ~100 experiments overnight — keeping winners, reverting losers — produces research-quality results autonomously. We are adapting this pattern specifically for trading strategy discovery.

---

## 3. What Is Already Built — 15 Production Modules

The following modules are production-ready, tested, and deployed. They form the complete foundation on which automated strategy search will be built.

| # | Module | Status | Location | Key Metrics |
|---|--------|--------|----------|-------------|
| 1 | PPO Reinforcement Learning | **Production** | `agent/strategies/rl/` | 500K timesteps; 30–60 min training; composite reward (Sortino 0.4 + PnL 0.3 + activity 0.2 + drawdown 0.1); 4 parallel CPU envs |
| 2 | Genetic Algorithm | **Production** | `agent/strategies/evolutionary/` | 12 genomes × 30 generations; 5-factor fitness (0.35 Sharpe + 0.25 profit_factor − 0.20 drawdown + 0.10 win_rate + 0.10 OOS_Sharpe); OOS split validation |
| 3 | Regime Detector | **Production** | `agent/strategies/regime/` | 99.92% accuracy; WFE 97.46%; XGBoost on 6 features; 4 market regimes; confidence + cooldown gates |
| 4 | Risk Overlay | **Production** | `agent/strategies/risk/` | 6-gate veto pipeline; Kelly/Hybrid/Dynamic sizing; 3 drawdown presets; correlation-aware |
| 5 | Ensemble Combiner | **Production** | `agent/strategies/ensemble/` | Weighted voting (RL 0.40, Evolved 0.35, Regime 0.25); circuit breakers; attribution-driven weights; 8h optimization cycle |
| 6 | Walk-Forward Validation | **Production** | `agent/strategies/walk_forward.py` | Rolling IS/OOS windows; WFE ≥ 50% deployment gate |
| 7 | Retraining Orchestrator | **Production** | `agent/strategies/retrain.py` | 4 schedules (ensemble 8h, regime 7d, genome 7d, PPO 30d); A/B gate |
| 8 | Drift Detection | **Production** | `agent/strategies/drift.py` | Page-Hinkley test on log-returns |
| 9 | Trading Loop | **Production** | `agent/trading/loop.py` | 8-phase cycle; DriftDetector integrated |
| 10 | Backtesting Engine | **Production** | `src/backtesting/` | Historical replay; in-memory sandbox; no look-ahead bias |
| 11 | Battle System | **Production** | `src/battles/` | Live + historical modes; ranking; replay |
| 12 | Gymnasium Environments | **Production** | `tradeready-gym/` | 7 environments (discrete/continuous/portfolio/live); 5 reward functions; 3 wrappers |
| 13 | Strategy Registry | **Production** | `src/strategies/` | CRUD; versioning; test orchestration; recommendations |
| 14 | Celery ML Tasks | **Production** | `src/tasks/retrain_tasks.py` | 5 tasks on `ml_training` queue; beat schedules |
| 15 | Monitoring | **Production** | `monitoring/` | 7 Grafana dashboards; 11 Prometheus alert rules |

---

## 4. How Each AI Component Works

### 4.1 PPO Reinforcement Learning

The RL agent learns optimal portfolio weight allocation across BTC, ETH, and SOL by interacting with a simulated market environment over millions of time steps.

**Input:** 272-dimensional observation vector — 30 candles × 9 features (OHLCV + indicators) plus current position and balance state.

**Output:** Weight vector `[BTC%, ETH%, SOL%]` — a continuous allocation signal.

**Training architecture:**
- Algorithm: Stable-Baselines3 PPO with 500K timesteps
- Parallelism: 4 environments via `SubprocVecEnv` (CPU-only, no GPU required)
- Runtime: 30–60 minutes on 4 CPU cores
- Reward function: `0.4 × Sortino + 0.3 × PnL + 0.2 × activity_bonus + 0.1 × drawdown_penalty`

**Operational lifecycle:**
- Retrain: Monthly (30-day cycle), rolling 6-month window
- Security: SHA-256 checksummed model files with strict load-time verification
- Deploy: `PPODeployBridge` with 30-candle warmup period (equal weights during warmup)

### 4.2 Genetic Algorithm

The evolutionary engine treats strategy parameters as DNA and applies natural selection to discover high-performing rule-based strategies.

**Genome:** A 17-number vector encoding 12 parameters — RSI thresholds, MACD periods, stop-loss/take-profit percentages, position sizing ratios, and pair bitmask.

**Fitness function:** `0.35 × Sharpe + 0.25 × profit_factor − 0.20 × max_drawdown + 0.10 × win_rate + 0.10 × OOS_Sharpe`

**Evolutionary process:**
1. `BattleRunner` provisions agents and runs historical battles
2. Per-agent fitness extracted from battle results
3. Tournament selection identifies the fittest genomes
4. Crossover and mutation produce the next generation
5. 30% data held out for out-of-sample validation (OOS_Sharpe term)

**Scale:** 12 genomes × 30 generations. Runtime: 2–4 hours (concurrent battles via platform API). Retrain: weekly, adding 2–3 new generations on the champion genome.

### 4.3 Regime Detection

The regime detector classifies the current market state and switches the ensemble to use the optimal pre-built strategy for that environment.

**Four market regimes:**

| Regime | Detection Criterion | Optimal Strategy Type |
|--------|--------------------|-----------------------|
| `TRENDING` | ADX > 25 | Momentum / trend-following |
| `HIGH_VOLATILITY` | ATR/close > 2× median | Volatility breakout |
| `LOW_VOLATILITY` | ATR/close < 0.5× median | Range-bound / carry |
| `MEAN_REVERTING` | Default (none of the above) | Mean reversion / stat-arb |

**Model:** XGBoost (300 estimators, depth=6) trained on 6 features — ADX, ATR/close ratio, Bollinger Band width, RSI-14, MACD histogram, and volume ratio.

**Production metrics:** 99.92% classification accuracy; WFE 97.46%; Sharpe 1.14 vs MACD baseline 0.74 (54% improvement).

**Switching logic:** Confidence threshold 0.70; cooldown of 20 candles between regime changes (prevents rapid oscillation). Retrain weekly on recent BTC 1h data.

### 4.4 Risk Overlay

Every trade signal passes through a 6-gate veto pipeline before reaching the order engine. No trade is placed unless all gates approve.

```
Signal received
      ↓
[Gate 1] HALT check — is a circuit breaker active?
      ↓
[Gate 2] Confidence — signal confidence ≥ threshold?
      ↓
[Gate 3] Max exposure — would this exceed total position limit?
      ↓
[Gate 4] Sector concentration — too many correlated positions?
      ↓
[Gate 5] Recent drawdown — within acceptable recent loss bounds?
      ↓
[Gate 6] APPROVED — compute position size
```

**Position sizing options:**
- `DynamicSizer` — volatility-adjusted (ATR-normalized)
- `KellyFractionalSizer` — Kelly Criterion with fractional scaling
- `HybridSizer` — weighted blend of Kelly and dynamic

**Drawdown presets:**

| Preset | Daily Limit | Weekly Limit | Monthly Limit |
|--------|-------------|--------------|---------------|
| AGGRESSIVE | 5% | 10% | 15% |
| MODERATE | 3% | 6% | 10% |
| CONSERVATIVE | 2% | 4% | 7% |

**Correlation gate:** Pearson r computed on 20-period log-returns across open positions. If `max|r| > 0.70`, position size is reduced to avoid concentration in correlated assets.

**Recovery state machine:** `RecoveryManager` implements a 3-state FSM (`RECOVERING → SCALING_UP → FULL`) persisted in Redis, ensuring gradual return to full sizing after a drawdown event.

### 4.5 Ensemble Combiner

The ensemble is the top-level decision maker. It aggregates signals from all three strategy sources (RL, genetic, regime-adaptive) using dynamic weighted voting.

**Default weights:** RL=0.40, Evolved=0.35, Regime=0.25. These weights are dynamic — they shift based on regime context and recent attribution analysis.

**Signal aggregation:** For each symbol, the ensemble computes a weighted confidence score across all active sources. If the aggregate confidence is below 0.55, the output is HOLD.

**Circuit breakers:**
- 3 consecutive losing trades → 24-hour pause on the offending strategy
- Weekly drawdown > 5% → 48-hour pause
- Accuracy below 40% → 25% size reduction

**Attribution and weight optimization:**
- A daily Celery task reads 7-day rolling PnL attribution per strategy source
- Weights are adjusted toward better-performing sources; negative-PnL sources are auto-paused
- Every 8 hours, a grid search across 12 weight configurations finds the current optimum

### 4.6 The Trading Loop — 8-Phase Execution Cycle

Every tick of the trading agent executes the following 8 phases in strict sequence:

```
┌─────────────────────────────────────────────────────┐
│                  TRADING LOOP TICK                  │
│                                                     │
│  Phase 1: OBSERVE   — Prices, candles, positions,   │
│                        balance from exchange        │
│  Phase 2: ANALYZE   — EnsembleRunner generates      │
│                        signals from 3 sources       │
│  Phase 3: DECIDE    — Filter by confidence +        │
│                        volume confirmation          │
│  Phase 4: CHECK     — Permissions, budget,          │
│                        risk limits (6-gate veto)    │
│  Phase 5: EXECUTE   — Place market order via SDK    │
│  Phase 6: RECORD    — Log to trading journal        │
│  Phase 7: MONITOR   — Check stop-loss / take-profit │
│                        / max-hold on open positions │
│  Phase 8: LEARN     — LLM reflection on outcomes   │
│                        (Gemini Flash, cost-optimized)│
└─────────────────────────────────────────────────────┘
```

The `DriftDetector` runs alongside this loop. If the Page-Hinkley test detects strategy drift, the retraining orchestrator is triggered before the next tick.

---

## 5. What Needs to Be Built — 14 Remaining Modules

The following modules complete the path from the current production foundation to the fully automated strategy search endgame.

| ID | Module | Priority | Dependencies | Est. Effort | Description |
|----|--------|----------|--------------|-------------|-------------|
| A | Unified Feature Pipeline | **Critical** — Phase 1 | None | 2–3 days | Centralizes all indicator computation (RSI, MACD, Bollinger, ATR, ADX, etc.) into one shared `FeatureEngine`. Currently computed in 3 separate places — this creates inconsistencies and makes new strategy development harder. |
| B | Pluggable Signal Interface | **Critical** — Phase 1 | None | 2–3 days | Plugin system allowing new strategies to register as signal sources without modifying ensemble core. Currently hardwired to exactly 3 sources — any new strategy requires editing the ensemble itself. |
| C | Deflated Sharpe Ratio | **Critical** — Phase 1 | None | 1 day | Statistical safety gate that adjusts the Sharpe ratio for the number of trials conducted. Rejects >99% of overfitted backtests. Without this gate, autoresearch will converge on strategies that look good but fail in production. This is the single most important safety mechanism. |
| D | Volume Spike Detector | **High** — Phase 2 | Module A | 2–3 days | New signal source: identifies high-volume breakout signals. Complements the existing momentum strategy. |
| E | Cross-Sectional Momentum | **High** — Phase 2 | Modules A, B | 3–4 days | New signal source: relative strength ranking across pairs. Pairs are selected dynamically based on momentum scores. |
| F | Mean Reversion Strategy | **High** — Phase 2 | Modules A, B | 3–4 days | New signal source: cointegration-based z-score mean reversion. Pairs with the current regime-adaptive strategy. |
| G | Autoresearch Harness | **High** — Phase 3 | Module C | 1 week | The Karpathy loop adapted for trading. LLM generates strategy code → backtest → score → keep/revert → repeat. Targets ~8–12 experiments per hour, ~100 overnight, ~500 over a weekend. |
| H | Strategy Template System | **High** — Phase 3 | Module G | 1 week | LLM-driven code generation for new strategy candidates. Templates and structural constraints ensure generated strategies are safe to execute (no external calls, no side effects, bounded computation). |
| I | Pairs Trading / Stat-Arb | **High** — Phase 4 | Module A | 3–4 days | Cointegrated pairs trading, calendar spreads, and ratio trading. Adds a fundamentally different signal type to the ensemble. |
| J | Walk-Forward for Ensemble | **Done** | — | — | Walk-forward validation for the full ensemble was completed 2026-03-22. |
| K | LLM Sentiment Signal | **Medium** — Phase 5 | Module B | 1 week | News and social sentiment processed by LLM to generate directional signals. Adds a non-price-action signal type. |
| L | Funding Rate Monitor | **Medium** — Phase 5 | None | 2–3 days | Perpetual futures carry trade signal based on funding rate extremes. Data already available via the exchange layer. |
| M | External Data Connectors | **Medium** — Phase 5 | Modules K, L | 1 week | Integrations for news APIs, on-chain data feeds, and order flow. Provides raw inputs for K and L. |
| N | Transformer Price Prediction | **Lower** — Phase 6 | Modules A, B | 2 weeks | Attention-based price forecasting model. Computationally heavier but potentially the highest alpha generator. |
| O | Synthetic Data Generator | **Lower** — Phase 6 | Module A | 1 week | GAN/VAE for generating training data under new market regimes — useful for training RL agents on rare events. |
| P | Order Flow Analysis | **Lower** — Phase 6 | Modules A, B | 1 week | Microstructure signals from order book imbalance and trade tape. High-frequency signal with short-duration predictive horizon. |

---

## 6. Build Roadmap — 6 Phases Over 10+ Weeks

### Phase Overview

| Phase | Weeks | Modules | Milestone |
|-------|-------|---------|-----------|
| 1 — Foundation | 1–2 | A, B, C | Feature pipeline, plugin system, overfitting gate |
| 2 — First New Strategies | 3–4 | D, E, F | 3 new signal sources in ensemble |
| 3 — Autoresearch | 5–6 | G, H | Overnight automated strategy search live |
| 4 — Statistical Arbitrage | 7–8 | I | Pairs trading signal in ensemble |
| 5 — Data & Sentiment | 9–10 | K, L, M | External data signals |
| 6 — Advanced ML | 11+ | N, O, P | Transformer prediction, synthetic data |

### Dependency Graph (ASCII)

```
Phase 1 (Foundation — no external deps)
  ┌──────────────────────────────────────────────────┐
  │  [A] Feature Pipeline   [B] Signal Interface     │
  │        └──────────────────────┘                  │
  │  [C] Deflated Sharpe (standalone)                │
  └──────────────────────────────────────────────────┘
                         ↓
Phase 2 (First New Strategies — needs A and B)
  ┌──────────────────────────────────────────────────┐
  │  [D] Volume Spike ──── needs A                   │
  │  [E] Cross-Sec Mom ─── needs A, B                │
  │  [F] Mean Reversion ── needs A, B                │
  └──────────────────────────────────────────────────┘
                         ↓
Phase 3 (Autoresearch — needs C)
  ┌──────────────────────────────────────────────────┐
  │  [G] Autoresearch Harness ─── needs C            │
  │  [H] Template System ──────── needs G            │
  └──────────────────────────────────────────────────┘
                         ↓
Phase 4 (Stat-Arb — needs A)
  ┌──────────────────────────────────────────────────┐
  │  [I] Pairs Trading / Stat-Arb ─── needs A        │
  └──────────────────────────────────────────────────┘
                         ↓
Phase 5 (Data & Sentiment)
  ┌──────────────────────────────────────────────────┐
  │  [L] Funding Rate ──── standalone                │
  │  [K] LLM Sentiment ─── needs B                  │
  │  [M] Ext Connectors ── needs K, L                │
  └──────────────────────────────────────────────────┘
                         ↓
Phase 6 (Advanced ML — needs A, B)
  ┌──────────────────────────────────────────────────┐
  │  [N] Transformer ────── needs A, B               │
  │  [O] Synthetic Data ─── needs A                  │
  │  [P] Order Flow ──────── needs A, B              │
  └──────────────────────────────────────────────────┘
```

**Critical path to autoresearch:** A → C → G. These three modules are the minimum viable path to automated strategy discovery. Modules B, D, E, F expand the search space but are not blockers for the first autoresearch run.

---

## 7. The Autoresearch Vision — Technical Detail

### 7.1 Concept

Karpathy's insight applied to trading: instead of a human researcher iterating on strategy ideas, an LLM agent runs the iteration loop automatically. The key design principle is the **separation of the modifiable strategy from the immutable evaluation harness**.

```
strategy.py         ← LLM can modify this
backtest_harness.py ← IMMUTABLE — never modified by the LLM
experiments.tsv     ← Log of all experiments: hash, score, delta
```

The evaluation harness is sacred. If the LLM could modify it, it could optimize the metric artificially rather than improving the actual strategy. Immutability of the harness is the single most important architectural constraint.

### 7.2 The Loop

```
┌─────────────────────────────────────────────────────────┐
│                   AUTORESEARCH LOOP                     │
│                                                         │
│  Step 1: LLM reads current strategy.py                  │
│          + reads experiments.tsv (past results)         │
│          + reads backtest_harness.py (constraints)      │
│                                                         │
│  Step 2: LLM hypothesizes ONE change                    │
│          (parameter tweak, new indicator,               │
│           different entry/exit logic)                   │
│                                                         │
│  Step 3: LLM modifies strategy.py                       │
│                                                         │
│  Step 4: git commit (experiment is logged in history)   │
│                                                         │
│  Step 5: Run backtest_harness.py                        │
│          (fixed time budget per experiment)             │
│                                                         │
│  Step 6: Extract composite_score                        │
│          = Deflated_Sharpe × (1 − max_drawdown / 0.5)  │
│                                                         │
│  Step 7: Log to experiments.tsv                         │
│          [timestamp, git_hash, score, delta, hypothesis]│
│                                                         │
│  Step 8: If score improved → KEEP                       │
│          Else → git revert to previous commit           │
│                                                         │
│  GOTO Step 1                                            │
└─────────────────────────────────────────────────────────┘
```

### 7.3 Throughput

| Period | Experiments | Expected Outcome |
|--------|-------------|-----------------|
| 1 hour | 8–12 | Initial exploration |
| 1 overnight run | ~100 | Meaningful parameter space coverage |
| 1 weekend | ~500 | Deep search with regime-specific variants |

At 100 experiments with a Deflated Sharpe gate, approximately 1–5 strategies will pass all safety checks. This is a reasonable hit rate — comparable to traditional quant research but achieved autonomously.

### 7.4 Single Optimization Metric

The autoresearch loop optimizes one composite metric to prevent metric gaming:

```
composite_score = Deflated_Sharpe × (1 − max_drawdown / 0.5)
```

- **Deflated Sharpe** penalizes the Sharpe ratio based on the number of trials — a strategy that looks good across many trials is penalized more than one that is immediately strong
- **The drawdown term** ensures that high-Sharpe strategies with catastrophic drawdowns are not selected
- A strategy scoring 0.8 Deflated Sharpe with 20% max drawdown scores: `0.8 × (1 − 0.20/0.5) = 0.8 × 0.60 = 0.48`
- A strategy scoring 0.5 Deflated Sharpe with 5% max drawdown scores: `0.5 × (1 − 0.05/0.5) = 0.5 × 0.90 = 0.45`

This metric naturally selects for robustness over raw performance.

---

## 8. Compute & Resource Requirements

### 8.1 Resource Table

| Component | CPU Cores | RAM | Duration | Notes |
|-----------|-----------|-----|----------|-------|
| Platform (minimal) | 2 | 2 GB | Always-on | API, order engine, auth |
| Price Ingestion | 1 | 1 GB | Always-on | 600+ pair Binance WS feed |
| Redis | 1 | 512 MB | Always-on | Cache, pub/sub, recovery state |
| TimescaleDB | 2 | 4 GB | Always-on | 5+ years historical tick data |
| Celery Worker | 1 | 1 GB | Always-on | Beat tasks, attribution, analytics |
| RL Training (500K steps) | 4 | 4–8 GB | 30–60 min | Monthly; `SubprocVecEnv` |
| GA Evolution (30 gen) | 2 | 4–6 GB | 2–4 hours | Weekly; concurrent battles |
| Regime Training | 1 | 2–3 GB | 5–10 min | Weekly; XGBoost on 1h candles |
| Walk-Forward Validation | 4 | 6–8 GB | 1–2 hours | On-demand before deploy |
| Autoresearch Loop | 2 | 4 GB | Continuous (overnight) | LLM + backtest per cycle |
| **Total minimum** | **8 cores** | **10 GB** | — | Concurrent load peak |

**GPU:** Not required. All training is CPU-based. An optional GPU provides a 2–3× speedup for PPO training (reducing 60 min → 20 min) but is not on the critical path.

### 8.2 Data Requirements

| Data Type | Minimum | Preferred | Current Status |
|-----------|---------|-----------|----------------|
| OHLCV (1h candles) | 2 years | 5+ years | Loaded for BTC, ETH, SOL |
| Tick data | 6 months | 1+ year | TimescaleDB hypertable |
| Order book snapshots | 1 month | 3 months | Redis cache (recent only) |

Data quality note: TimescaleDB with gap-fill is production-deployed. The gap-fill infrastructure ensures training data has no discontinuities that could introduce look-ahead bias.

---

## 9. Risk Analysis

### 9.1 Technical Risks

| Risk | Severity | Current Mitigation | Residual Gap |
|------|----------|-------------------|--------------|
| Overfitting to historical data | High | Walk-forward validation (WFE ≥ 50% gate) | Deflated Sharpe not yet built (Module C) |
| Strategy model degradation over time | High | Page-Hinkley drift detection + auto-retraining | Retrain orchestrator deployed |
| Single strategy failure | Medium | Ensemble with 3 independent sources | Ensemble circuit breakers deployed |
| Training cost overrun | Low | All CPU-based; ~$0.35/month compute | No LLM cost for strategy training |
| Autoresearch metric gaming | High | Immutable backtest harness (architectural) | Requires strict code review on harness |

### 9.2 Strategic Risks

**Market regime change:** The regime detector was explicitly designed for this. It classifies the current regime and routes to the appropriate pre-built strategy. A new regime type would require retraining the XGBoost classifier, which takes under 10 minutes.

**Strategy crowding:** When too many market participants use similar strategies, the edge disappears. Walk-forward validation and OOS testing catch strategies that only work because they exploit patterns that have already been discovered by the market. The genetic algorithm's OOS fitness term (10% of composite score) specifically guards against this.

**Autoresearch generating economically meaningless strategies:** The Deflated Sharpe gate rejects strategies that appear statistically significant but are not. This is the most critical safety mechanism. Without it, the autoresearch loop will reliably find strategies that overfit the backtest period.

### 9.3 Scenario Planning — What Could Go Wrong

**Scenario 1: All strategies become correlated**
- How it happens: Regime detector routes everything to the same strategy; ensemble weights concentrate on one source
- Detection: Correlation-aware risk middleware flags `max|r| > 0.70` across positions
- Response: Circuit breakers pause correlated strategies; ensemble diversity metric triggers rebalancing

**Scenario 2: Black swan market event**
- How it happens: 40%+ drawdown in a single session, unprecedented volatility
- Detection: Circuit breakers and daily loss limit in the HALT gate (Gate 1 of the veto pipeline)
- Response: `RecoveryManager` enters `RECOVERING` state; position sizes scale to near-zero; `HALT` flag prevents new entries

**Scenario 3: Autoresearch produces syntactically valid but worthless strategies**
- How it happens: LLM generates code that backtests well by pure chance across 100 trials
- Detection: Deflated Sharpe ratio accounts for the number of trials in the search
- Response: Gate rejects; experiment logged; LLM learns from the failure in the next iteration

---

## 10. Strategic Options

### Option A: Foundation First (Recommended)

**Approach:** Build Modules A, B, and C (2 weeks) first, then build the autoresearch harness G and H (2 weeks). This reaches automated strategy search in approximately 4 weeks.

**Why this is recommended:** The three foundation modules are prerequisites for autoresearch regardless of which path is chosen. Building them first creates the infrastructure for all subsequent work. The Deflated Sharpe gate (Module C) is a 1-day build with outsized safety value — not having it makes autoresearch dangerous.

**Risk level:** Low. Each module is well-defined with no novel research required.

**Timeline to autoresearch:** ~4 weeks.

---

### Option B: Connect Existing AI to the User Interface

**Approach:** Wire the RL training, genetic evolution, and regime classifier training to the frontend dashboard. Users could trigger training runs, monitor progress, and deploy results — all from the UI.

**What this delivers:** Users get access to the 3 existing AI training systems without any new strategy discovery. The automation is in the workflow, not the research.

**When to choose this:** If the priority is giving users value from the existing systems before building new ones. This is approximately a 2-week project.

**Risk level:** Low. No new ML work, primarily API and frontend integration.

**Timeline to autoresearch:** Does not advance the autoresearch roadmap.

---

### Option C: Ship Manual Mode Now

**Approach:** The strategy creation, backtesting, and deployment workflow already functions end-to-end. Ship this to users immediately and build automation in parallel.

**What this delivers:** Revenue generation from day one. Users who already have strategy ideas can test and deploy them. This is the platform's current capability.

**When to choose this:** When time-to-revenue matters more than time-to-full-automation. The manual mode is production-ready and has been validated.

**Risk level:** Minimal. No new code required.

**Timeline to autoresearch:** Parallel; does not conflict with Options A or B.

---

### Option D: Full Autoresearch Sprint

**Approach:** Prioritize the autoresearch loop above all else. Go directly from the current state to the full automated search system in 6 weeks.

**What this delivers:** The complete endgame vision — users set goals and the AI searches overnight.

**Risk level:** Medium-High. Modules A, B, C are still prerequisites; cutting corners on them introduces safety risks in the autoresearch loop.

**Timeline to autoresearch:** ~6 weeks, with A/B/C built in the first 2 weeks regardless.

---

### Recommendation

**Option A combined with Option C.** Build the foundations (A, B, C) while users generate value from the existing manual mode. This maximizes parallel value delivery: users get a working product now, and the automated search system is ready in 4 weeks.

This is the lowest-risk path to the endgame with the earliest possible revenue start.

---

## 11. Key Performance Indicators

Once the automated system is running, the following metrics define operational health and research quality:

### Research Quality

| KPI | Target | Measurement Frequency |
|-----|--------|-----------------------|
| Experiments per day (autoresearch) | ≥ 100 overnight | Daily |
| % passing Deflated Sharpe gate | 1–5% (healthy) | Per run |
| Walk-Forward Efficiency scores (deployable) | ≥ 50% | Per candidate |
| Overfitting rejection rate | > 95% | Weekly aggregate |

### Deployed System Health

| KPI | Target | Measurement Frequency |
|-----|--------|-----------------------|
| Live ensemble Sharpe ratio (rolling 30d) | ≥ 1.0 | Daily |
| Max drawdown (deployed ensemble) | < 10% | Continuous |
| Drift detection events | < 2/week | Weekly |
| Circuit breaker activations | < 1/week | Weekly |

### Operational Efficiency

| KPI | Target | Measurement Frequency |
|-----|--------|-----------------------|
| Retraining success rate | > 95% | Per event |
| Regime detection latency | < 1 second | Per tick |
| End-to-end trading loop latency | < 500ms | Per tick |
| Strategy deployment lead time (discovery → live) | < 24 hours | Per deployment |

---

## 12. Summary Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                      DATA LAYER                                  │
│  Binance WS (600+ pairs) → Price Ingestion → TimescaleDB + Redis │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────┐
│                    FEATURE LAYER  [Module A — to build]          │
│  Unified FeatureEngine: RSI, MACD, Bollinger, ATR, ADX, vol      │
└──────────┬────────────────────┬──────────────────────────────────┘
           │                    │
┌──────────▼──────┐   ┌─────────▼──────────────────────────────────┐
│  REGIME         │   │  SIGNAL SOURCES  [Module B — plugin layer] │
│  DETECTOR       │   │                                             │
│  (XGBoost)      │   │  ┌─────────┐  ┌─────────┐  ┌──────────┐  │
│  99.92% acc     │   │  │  PPO RL │  │Genetic  │  │ [D,E,F,I]│  │
│  4 regimes      │   │  │  (SB3)  │  │Algorithm│  │ New Strats│  │
└────────┬────────┘   │  └────┬────┘  └────┬────┘  └────┬─────┘  │
         │            └───────┼────────────┼─────────────┼────────┘
         │                    │            │             │
┌────────▼────────────────────▼────────────▼─────────────▼────────┐
│                    ENSEMBLE COMBINER                             │
│  Weighted voting (RL 0.40, Evolved 0.35, Regime 0.25)           │
│  Dynamic weights via attribution | Circuit breakers             │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────┐
│                   RISK OVERLAY (6-Gate Veto Pipeline)            │
│  HALT → Confidence → Exposure → Concentration → Drawdown → APPROVED│
│  Kelly/Hybrid sizing | RecoveryManager FSM | Correlation gate    │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────┐
│                 ORDER ENGINE + TRADING LOOP (8 phases)           │
│  Observe → Analyze → Decide → Check → Execute →                  │
│  Record → Monitor → Learn                                        │
└──────────────────────────────────────────────────────────────────┘

  QUALITY GATES                    AUTOMATION
  ┌────────────────────┐           ┌─────────────────────────────┐
  │ Walk-Forward WFE≥50│           │ Autoresearch [Modules G, H] │
  │ Deflated Sharpe [C]│           │ LLM generates → backtest →  │
  │ Drift Detection    │           │ score → keep/revert         │
  │ A/B Gate           │           │ ~100 experiments/night      │
  └────────────────────┘           └─────────────────────────────┘
```

---

## 13. Conclusion

The platform has world-class infrastructure for AI-driven trading strategy development. The 15 production modules provide a complete foundation: real-time data ingestion, order execution, risk management, three independent AI strategy sources, walk-forward validation, drift detection, auto-retraining, monitoring, and a battle system for strategy comparison.

**The gap to the automated endgame is precisely defined:**

1. **Module A** — Unified Feature Pipeline (2–3 days): eliminates the technical debt of three separate indicator implementations
2. **Module B** — Pluggable Signal Interface (2–3 days): makes the ensemble extensible without surgery
3. **Module C** — Deflated Sharpe Ratio (1 day): the statistical safety gate that makes autoresearch safe
4. **Module G** — Autoresearch Harness (1 week): the Karpathy loop adapted for trading
5. **Module H** — Strategy Template System (1 week): LLM-driven strategy code generation

**Total time to the automated endgame:** 4–6 weeks of focused development.

The path is well-defined, the risks are mitigated by the existing safety infrastructure, and the compute costs are low (~$0.35/month, all CPU-based). The foundation work done to date has been executed with production-quality standards — the intelligence layer can be built on top with confidence.

The recommendation is to ship the manual mode to users now (Option C) while the development team builds the three foundation modules (Option A). This combination delivers user value immediately while closing the gap to the vision that differentiates this platform: AI that autonomously discovers and deploys the best trading strategies.

---

*Document prepared by the CTO office. For questions on technical implementation details, refer to `development/implementation-plan-a-to-z.md`. For current system status, refer to `development/context.md`.*

*Next review: Upon completion of Phase 1 (Modules A, B, C).*
