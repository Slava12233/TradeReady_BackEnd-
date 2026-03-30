---
type: research-report
tags:
  - strategy
  - research
  - autoresearch
  - ml
  - trading
  - roadmap
date: 2026-03-23
status: complete
---

# Complete Strategy Research Report: AiTradingAgent Platform

> **Date:** 2026-03-23 | **Scope:** Full A-Z research — current state, strategy landscape, autoresearch integration, tools, and improvement roadmap

---

## Table of Contents

1. [Current Platform State](#1-current-platform-state)
2. [Current Strategy System](#2-current-strategy-system)
3. [Infrastructure & Tools We Have](#3-infrastructure--tools-we-have)
4. [The Karpathy Autoresearch Loop](#4-the-karpathy-autoresearch-loop)
5. [Adapting Autoresearch for Trading](#5-adapting-autoresearch-for-trading)
6. [New Strategies to Implement](#6-new-strategies-to-implement)
7. [Tools & Libraries to Add](#7-tools--libraries-to-add)
8. [Data Sources to Integrate](#8-data-sources-to-integrate)
9. [Multi-Agent Strategy Factory](#9-multi-agent-strategy-factory)
10. [Overfitting Prevention](#10-overfitting-prevention)
11. [Prioritized Implementation Roadmap](#11-prioritized-implementation-roadmap)
12. [Architecture Vision](#12-architecture-vision)

---

## 1. Current Platform State

### What We Have (Production-Deployed)

| Component | Status | Details |
|-----------|--------|---------|
| **Exchange Data** | LIVE | 600+ USDT pairs via Binance WebSocket, real-time ticks + 1m/5m/1h/1d candles in TimescaleDB |
| **Order Engine** | LIVE | Market/Limit/Stop-Loss/Take-Profit orders with slippage simulation |
| **Backtesting Engine** | LIVE | Historical replay with in-memory sandbox, no look-ahead bias (`WHERE bucket <= virtual_clock`) |
| **Battle System** | LIVE | Agent vs agent competitions, live + historical modes, ranking system |
| **Multi-Agent Architecture** | LIVE | Per-agent wallets, API keys, risk profiles — used for parallel strategy testing |
| **5-Strategy Ensemble** | LIVE | PPO RL + Genetic Algorithm + Regime Detection + Risk Overlay + Ensemble Combiner |
| **Walk-Forward Validation** | LIVE | Rolling IS/OOS windows, WFE threshold (≥0.5 required for deployment) |
| **Automated Retraining** | LIVE | 4-component schedule via Celery (8h/7d/7d/30d), A/B gate with min improvement |
| **Drift Detection** | LIVE | Page-Hinkley test on composite metric, auto-triggers regime retraining |
| **Risk Management** | LIVE | Two layers: platform per-order (8-step validation) + agent portfolio-level (6-gate veto pipeline) |
| **Monitoring** | LIVE | 7 Grafana dashboards, 11 Prometheus alerts, structured logging |
| **Python SDK** | LIVE | 37 REST methods (sync+async), WebSocket streaming, 10 typed exceptions |
| **MCP Server** | LIVE | 58 trading tools over stdio transport |
| **Frontend** | LIVE | Next.js 16, full dashboard, backtest/battle observation, strategy management |
| **Gymnasium Environments** | LIVE | 7 envs (discrete+continuous+portfolio+live), 5 reward functions, 3 wrappers |
| **Agent Memory** | LIVE | PostgresMemoryStore + RedisMemoryCache, 4-factor scored retrieval |
| **Agent Permissions** | LIVE | 4 roles, 8 capabilities, budget limits, audit logging |
| **Celery Tasks** | LIVE | 16 beat tasks including ML retraining, snapshot capture, cleanup |
| **Docker Deployment** | LIVE | 9 services, health checks, resource limits |

### Key Numbers

- **600+** tradeable USDT pairs with real-time data
- **1000** agents can run in parallel
- **7** Gymnasium RL environments
- **5** strategy components in the ensemble
- **58** MCP trading tools
- **100+** REST API endpoints
- **27** database models
- **4,000+** tests (platform + agent + frontend)
- **16** Celery scheduled tasks
- **7** Grafana monitoring dashboards

---

## 2. Current Strategy System

### Architecture

```
Incoming candles (from platform REST/SDK)
        │
        ├── rl/deploy.py (PPODeployBridge)      → PPO portfolio weight vector
        ├── evolutionary/ (StrategyGenome)       → RSI/MACD rule-based signals
        └── regime/ (RegimeSwitcher)             → regime → directional bias
                │
                ▼
        ensemble/meta_learner.py (MetaLearner)   → weighted confidence voting
                │
                ▼
        risk/middleware.py (RiskMiddleware)       → 5-stage veto + sizing pipeline
                │
                ▼
        ExecutionDecision → platform SDK (order placement)
```

### Strategy Details

#### 2a. PPO Reinforcement Learning

- **Engine:** Stable-Baselines3 PPO on `TradeReady-Portfolio-v0` environment
- **Output:** Portfolio weight vector across BTC/ETH/SOL
- **Training:** 500K timesteps, 4 parallel envs, CPU-only
- **Reward:** Composite = 0.4×sortino + 0.3×PnL + 0.2×activity + 0.1×drawdown_penalty
- **Deploy:** `PPODeployBridge` with 30-candle warmup, equal weights during warmup
- **Retrain:** Monthly (30d cycle), rolling 6-month window
- **Security:** SHA-256 checksummed model files, strict verification

#### 2b. Genetic Algorithm (Evolutionary)

- **Genome:** 12-parameter vector (RSI thresholds, MACD periods, stop/take-profit, position sizing, pair bitmask)
- **Fitness:** 5-factor composite = 0.35×Sharpe + 0.25×profit_factor - 0.20×max_drawdown + 0.10×win_rate + 0.10×OOS_Sharpe
- **Operators:** Tournament selection, SBX crossover, Gaussian mutation
- **Evaluation:** Battle-based (through platform API), dual IS/OOS (70/30 split)
- **Population:** 12 genomes, 30 generations full run
- **Retrain:** Weekly (7d), 2 new generations on champion

#### 2c. Market Regime Detection

- **4 Regimes:** TRENDING (ADX>25), HIGH_VOLATILITY (ATR/close>2×median), LOW_VOLATILITY (ATR/close<0.5×median), MEAN_REVERTING (else)
- **Classifier:** XGBoost/RandomForest on 6 features (ADX, ATR/close, BB width, RSI-14, MACD histogram, volume ratio)
- **Switcher:** 0.7 confidence threshold, 20-candle cooldown between switches
- **4 Pre-built strategies** matched to each regime (trend-following, mean-reversion, breakout, slow SMA crossover)
- **Performance:** 99.92% accuracy, WFE 97.46%, Sharpe 1.14 vs MACD baseline 0.74
- **Retrain:** Weekly (7d) on recent BTC 1h data

#### 2d. Risk Management Overlay

- **RiskAgent:** Verdicts (OK/REDUCE/HALT) based on daily PnL and portfolio drawdown
- **VetoPipeline:** 6 sequential gates — HALT check → confidence check → max exposure → sector concentration → recent drawdown → APPROVED
- **3 DrawdownProfile presets:** AGGRESSIVE (5/10/15%), MODERATE (3/6/10%), CONSERVATIVE (2/4/7%)
- **Sizing:** DynamicSizer (volatility-adjusted) + KellyFractionalSizer + HybridSizer
- **Correlation gate:** Pearson r on 20-period log-returns, reduces size if max|r|>0.70
- **RecoveryManager:** 3-state FSM (RECOVERING→SCALING_UP→FULL), Redis-persisted

#### 2e. Ensemble Combiner

- **Weights:** RL=0.4, Evolved=0.35, Regime=0.25 (dynamic, regime-conditional)
- **MetaLearner:** Weighted confidence voting, combined_confidence threshold 0.55
- **Dynamic weight adjustment:** Per-source rolling Sharpe (deque maxlen=50) + regime modifiers
- **Circuit breaker:** 3 consecutive losses → 24h pause; weekly drawdown >5% → 48h pause; accuracy <40% → 25% size cut
- **Attribution:** Daily Celery task reads 7-day performance, adjusts weights, auto-pauses negative-PnL strategies
- **Retrain:** Every 8h, grid search over 12 weight configurations

#### 2f. Supporting Systems

| System | Purpose | Status |
|--------|---------|--------|
| **Drift Detection** | Page-Hinkley test on composite metric; triggers regime retraining + size reduction | LIVE |
| **Walk-Forward** | Rolling train/OOS windows, WFE≥0.5 required, reports in JSON | LIVE |
| **Retrain Orchestrator** | 4-schedule manager (8h/7d/7d/30d), A/B gate (min_improvement=0.01) | LIVE |
| **Trading Loop** | 8-phase cycle (observe→analyse→decide→check→execute→record→monitor→learn) | LIVE |
| **Signal Generator** | Ensemble adapter, 50-candle fetch, confidence + volume filters | LIVE |
| **Position Monitor** | Stop-loss 5%, take-profit 20%, max-hold 24h | LIVE |
| **Trading Journal** | LLM-powered reflections (Gemini Flash), episodic/procedural memory | LIVE |
| **Pair Selector** | Volume≥$10M, spread≤5%, ranked by volume + momentum, 1h TTL | LIVE |
| **A/B Testing** | Round-robin between strategy variants, min 30 trades per variant | LIVE |

---

## 3. Infrastructure & Tools We Have

### Data Pipeline

| Layer | Technology | Capability |
|-------|-----------|------------|
| **Real-time prices** | Binance WebSocket → Redis HSET | Sub-millisecond lookups, 600+ pairs |
| **Tick storage** | asyncpg COPY → TimescaleDB `ticks` hypertable | High-throughput time-series |
| **Candle aggregation** | Celery continuous aggregates | 1m, 5m, 1h, 1d candles auto-refreshed every 60s |
| **Historical backfill** | `scripts/backfill_history.py` | Multi-month OHLCV from Binance, resumable |
| **Multi-exchange** | CCXT adapter, `ADDITIONAL_EXCHANGES` env var | 110+ exchanges supported |
| **Pub/sub broadcast** | Redis pub/sub `price_updates` | Real-time price distribution |

### Execution Infrastructure

| Tool | What It Does |
|------|-------------|
| **Order Engine** | Market/Limit/Stop-Loss/Take-Profit with slippage model |
| **Risk Manager** | 8-step per-order validation (circuit breaker, position limits, etc.) |
| **Backtest Sandbox** | In-memory exchange replica, Decimal arithmetic, 0.1% fees |
| **Battle Engine** | Live + Historical modes, wallet isolation, deterministic replay |
| **Gymnasium Envs** | 7 environments (discrete/continuous/portfolio/live) |

### Compute & Scaling

| Resource | Capacity |
|----------|---------|
| **Agents** | 1000 in parallel (each with own wallet, API key, risk profile) |
| **Celery workers** | Configurable concurrency, separate `ml_training` queue |
| **Docker services** | 9 containers, 8+ CPU cores, 10+ GB RAM minimum |
| **Backtests** | Concurrent sessions with singleton engine |
| **Battles** | Concurrent live + historical battles |

### Monitoring & Observability

| Tool | Coverage |
|------|---------|
| **7 Grafana dashboards** | Agent overview, API calls, LLM usage, memory, strategy, ecosystem health, retraining |
| **11 Prometheus alerts** | Error rates, latency, budget, permission denials, cache hits, signal confidence |
| **Structured logging** | JSON logs with trace IDs, request correlation |
| **Agent activity log** | JSONL event stream (`development/agent-activity-log.jsonl`) |
| **Health endpoint** | Redis + DB + price ingestion probes |

### API Surface

| Interface | Endpoints/Tools |
|-----------|----------------|
| **REST API** | 100+ endpoints under `/api/v1/` |
| **WebSocket** | 5 channels (ticker, candles, orders, portfolio, battle) |
| **Python SDK** | 37 methods (sync + async), WebSocket streaming |
| **MCP Server** | 58 tools over stdio |

---

## 4. The Karpathy Autoresearch Loop

### What It Is

Autoresearch (released March 2026, 51.9k GitHub stars) is Andrej Karpathy's framework for **autonomous ML experiment loops**. An LLM coding agent (e.g., Claude Code) independently:

1. **Examines** current code and past results
2. **Hypothesizes** a change ("what if I increase depth to 12?")
3. **Modifies** the training code
4. **Commits** to git
5. **Runs** a 5-minute training experiment
6. **Evaluates** a single metric (validation bits-per-byte)
7. **Decides:** metric improved → KEEP; otherwise → REVERT
8. **Repeats** indefinitely without human intervention

This yields **~12 experiments/hour, ~100 overnight, ~700 over 2 days.**

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Separation of concerns** | `train.py` (modifiable) vs `prepare.py` (fixed evaluation — NEVER modified) |
| **Single metric optimization** | `val_bpb` (validation bits-per-byte) — one number to minimize |
| **Git as experiment log** | Each experiment is a commit; kept experiments form the branch history |
| **Fixed time budget** | 5 minutes per experiment — forces efficiency |
| **No human intervention** | Agent runs indefinitely; `program.md` instructs "never pause" |
| **Simplicity bias** | Code deletion that maintains performance is valued — penalizes complexity |
| **Reproducibility** | Fixed data, fixed evaluation, git history = full reproducibility |

### Repository Structure

```
autoresearch/
  prepare.py       -- FIXED: data download, BPE tokenizer, dataloader, evaluation
  train.py         -- MODIFIABLE: GPT model, optimizer, hyperparameters, training loop
  program.md       -- Agent instructions: rules, constraints, the loop protocol
  analysis.ipynb   -- Post-hoc: loads results.tsv, plots progress, computes stats
  results.tsv      -- Experiment log: commit | val_bpb | memory_gb | status | description
```

### The Critical Insight

**The evaluation harness is sacred and immutable.** The agent can only modify the strategy, never the scoring system. This prevents metric gaming and ensures genuine improvement.

---

## 5. Adapting Autoresearch for Trading

### Direct Mapping

| Autoresearch Concept | Trading Adaptation |
|---|---|
| `train.py` (modifiable) | `strategy.py` — entry/exit logic, indicators, position sizing, risk params |
| `prepare.py` (fixed) | `backtest_harness.py` — fixed backtesting engine, data loading, metric calculation |
| `program.md` (instructions) | `research_prompt.md` — agent instructions for strategy research |
| `val_bpb` (single metric) | Composite score: Sharpe × (1 - max_drawdown/0.5) with hard constraints |
| 5-minute time budget | Fixed backtest window (e.g., 2 years of 1h candles) |
| `results.tsv` | `experiments.tsv` — commit, sharpe, max_drawdown, win_rate, total_return, description |
| Git commits | Same — each strategy variant is a commit, kept or reverted |

### The Trading Autoresearch Loop

```
┌──────────────────────────────────────────────────────────┐
│                  THE TRADING RESEARCH LOOP                │
│                                                          │
│  1. Read current strategy.py + past experiments.tsv      │
│  2. Hypothesize: "what if I add RSI divergence filter?"  │
│  3. Modify strategy.py                                   │
│  4. git commit -m "add RSI divergence filter"            │
│  5. Run: python backtest_harness.py > run.log 2>&1       │
│  6. Extract: grep "composite_score" run.log              │
│  7. Log to experiments.tsv                               │
│  8. If score improved → KEEP; else → git revert          │
│  9. GOTO 1 (never stop)                                  │
│                                                          │
│  Yield: ~8-12 strategy variants per hour                 │
│  Overnight: ~100 experiments                             │
│  Weekend: ~500+ experiments                              │
└──────────────────────────────────────────────────────────┘
```

### What the Agent Would Modify (strategy.py)

- Technical indicator parameters (MA periods, RSI thresholds, ADX levels)
- Entry/exit signal logic (add new conditions, remove weak ones)
- Position sizing rules (fixed, Kelly, volatility-scaled)
- Stop-loss / take-profit levels and trailing stop logic
- Timeframe selection (1m, 5m, 15m, 1h, 4h)
- Pair selection logic (volume filters, momentum filters, sector rotation)
- Risk parameters (max positions, max exposure, correlation limits)
- Ensemble weights between sub-strategies
- New indicator combinations the agent discovers

### What Stays Fixed (backtest_harness.py)

- Historical data loading (prevents cherry-picking favorable periods)
- Order execution simulation with realistic slippage and fees
- Walk-forward validation (mandatory OOS evaluation)
- Performance metric calculation (prevents gaming)
- Hard constraints (reject any strategy with >30% drawdown or <0 Sharpe)
- Transaction cost model (0.1% fee + slippage model)

### Critical Adaptations for Trading

1. **Composite metric instead of single value:**
   ```python
   score = sharpe_ratio * (1 - max_drawdown / 0.50)
   # Hard rejects:
   if max_drawdown > 0.30: score = -999  # >30% drawdown = rejected
   if sharpe_ratio < 0.0: score = -999   # negative Sharpe = rejected
   if num_trades < 50: score = -999      # too few trades = overfit risk
   ```

2. **Mandatory walk-forward validation:**
   - In-sample: train/optimize the strategy
   - Out-of-sample: the metric the agent sees (prevents overfitting)
   - WFE ≥ 0.5 required (already in our codebase)

3. **Regime-decomposed results:**
   - Show performance broken down by TRENDING/MEAN_REVERTING/HIGH_VOL/LOW_VOL
   - Reject strategies that only work in one regime

4. **Complexity penalty:**
   - Count parameters/conditions in the strategy
   - `adjusted_score = score - 0.01 * num_parameters`
   - Simpler strategies with same performance are preferred

### Integration with Our Platform

| Our Component | Role in Autoresearch Loop |
|---|---|
| `src/backtesting/engine.py` | The fixed evaluation harness |
| `agent/strategies/` | The modifiable strategy code |
| `agent/strategies/walk_forward.py` | OOS validation within the harness |
| `agent/strategies/ensemble/meta_learner.py` | The weights to optimize |
| `agent/trading/journal.py` | Experiment logging and reflection |
| `tradeready-gym/` | Alternative evaluation via RL episodes |
| TimescaleDB candles | Historical data source (immutable) |
| Git | Experiment version control |

### Implementation Plan for Autoresearch Integration

**Phase 1: Build the harness (1 week)**
- Create `autoresearch/backtest_harness.py` — fixed evaluation script
- Create `autoresearch/strategy.py` — modifiable strategy template
- Create `autoresearch/research_prompt.md` — agent instructions
- Create `autoresearch/experiments.tsv` — results log
- Wire into our existing backtest engine for execution

**Phase 2: First autonomous run (1 week)**
- Start with the 12-param genetic algorithm genome as the strategy template
- Run overnight: let Claude Code iterate on parameters and logic
- Analyze results: which changes improved performance? What patterns emerge?

**Phase 3: Scale to multiple research tracks (2 weeks)**
- Track 1: Indicator optimization (RSI, MACD, Bollinger parameters)
- Track 2: Entry/exit logic discovery (new signal combinations)
- Track 3: Risk parameter tuning (stop-loss, take-profit, sizing)
- Track 4: Ensemble weight optimization
- Track 5: Pair selection strategy
- Run all 5 tracks in parallel on separate branches

**Phase 4: Continuous research pipeline (ongoing)**
- Integrate winning strategies into the ensemble
- Feed autoresearch discoveries into the genetic algorithm as new genome templates
- Use autoresearch to continuously improve the regime classifier
- Monthly "research sprints" — 48h autonomous runs exploring new strategy families

---

## 6. New Strategies to Implement

### Tier 1: HIGH Priority (Direct alpha, uses existing infrastructure)

#### Cross-Sectional Momentum
- **What:** Rank all 600+ pairs by recent returns, go long top decile
- **Why HIGH:** Well-documented alpha source in crypto, directly leverages our 600+ pair universe
- **How:** Each agent specializes in a momentum sub-strategy (3h, 12h, 24h, 7d lookbacks)
- **Integration:** New signal source for ensemble combiner
- **Expected Sharpe:** 1.0-2.0

#### Mean Reversion with Regime Switching
- **What:** Bollinger/z-score reversion during MEAN_REVERTING regime, disabled otherwise
- **Why HIGH:** Perfect complement to momentum — the regime classifier already knows when to switch
- **How:** Activate when `RegimeSwitcher` outputs MEAN_REVERTING
- **Integration:** Already wired via regime strategy definitions
- **Expected Sharpe:** 0.8-1.5

#### Statistical Arbitrage / Pairs Trading
- **What:** Find cointegrated pairs among 600+ assets, trade spread convergence
- **Why HIGH:** 600 choose 2 = ~180,000 potential pairs — massive opportunity space
- **How:** Engle-Granger cointegration tests, Kalman filter hedge ratios, z-score entry/exit
- **Integration:** New strategy component in ensemble, or dedicated pair-trading agents
- **Expected Sharpe:** 1.5-3.0

#### Volume Spike Detection
- **What:** Monitor volume z-scores across all pairs, flag >3σ anomalies
- **Why HIGH:** Easy to implement, high signal-to-noise, uses existing data pipeline
- **How:** Rolling z-score on USDT volume, filter by price action confirmation
- **Integration:** Pre-filter signal for all other strategies
- **Expected Sharpe:** N/A (filter, not standalone)

#### LLM Sentiment Integration
- **What:** News/social sentiment scoring using OpenRouter LLM calls
- **Why HIGH:** Already have OpenRouter integration and $5/day LLM budget
- **How:** Event-driven: major news → LLM classifies bullish/bearish/neutral → adjust ensemble weights
- **Integration:** Additional signal source in ensemble, or sentiment-based risk overlay
- **Research:** Multi-agent LLM framework achieved 21.75% return, Sharpe 1.08 for BTC

#### Funding Rate Arbitrage
- **What:** Capture interest rate differentials in perpetual futures
- **Why HIGH:** One of the most reliable quant strategies in crypto
- **How:** Short perps + long spot when funding positive (or vice versa)
- **Requirement:** Perpetual futures access via CCXT (check if available)
- **Expected Sharpe:** 2.0-4.0 (when properly hedged)

### Tier 2: MEDIUM-HIGH Priority (Strong alpha, moderate effort)

#### Transformer-Based Price Prediction
- **What:** Temporal Fusion Transformer capturing long-range dependencies
- **How:** Train on TimescaleDB candles, OHLCV + RSI + MACD + volume features
- **Integration:** New prediction signal for ensemble (alongside RL/evolved/regime)
- **Library:** HuggingFace Transformers or PyTorch custom
- **Research:** Hybrid Transformer+GRU models outperform standalone architectures

#### Multi-Agent Reinforcement Learning (MARL)
- **What:** Multiple RL agents learning simultaneously in shared environment
- **How:** Extend battle system into a full MARL training environment
- **Integration:** Natural evolution of PPO RL + genetic algorithm + battles
- **Research:** StockMARL and ABIDES-MARL frameworks show promising results
- **Your edge:** Battle infrastructure already exists for evaluating competing RL approaches

#### Diffusion Models for Synthetic Data
- **What:** Generate realistic synthetic market scenarios for training/testing
- **How:** Train diffusion model on historical candles, generate novel scenarios
- **Integration:** Augment walk-forward validation with synthetic OOS periods
- **Research:** TRADES framework shows 3.48x improvement over previous state-of-art

#### Graph Neural Networks for Lead-Lag Detection
- **What:** Learn which pairs influence which, predict contagion/lead-lag effects
- **How:** Build correlation graph of 600+ pairs, train GNN on temporal patterns
- **Integration:** New signal source: "ETH moved, SOL will follow in N minutes"
- **Research:** Bi-LSTM + GNN outperforms both in isolation

#### Order Flow Analysis
- **What:** Analyze bid/ask imbalances and large order detection
- **How:** Consume Binance depth stream, calculate Order Flow Imbalance
- **Integration:** Additional feature for ML models and ensemble signals
- **Start with:** Top-50 pairs by volume

### Tier 3: MEDIUM Priority (Specialized, longer implementation)

#### Meta-Learning for Regime Adaptation (MAML)
- Train a base model that fine-tunes to new regimes in 5-10 gradient steps
- Graceful degradation during black swan events

#### VWAP/TWAP Execution Algorithms
- Reduce slippage for large position entries
- More valuable as execution optimization than standalone alpha

#### Factor Models
- Decompose returns into momentum, value, size, volume, volatility factors
- Useful for portfolio construction and risk decomposition

#### Market Microstructure
- Spread dynamics, Kyle's lambda, PIN estimation
- Mainly relevant for market making (not currently supported)

#### On-Chain Analytics
- Whale tracking, exchange flows, miner behavior
- Requires CryptoQuant/Glassnode/Nansen integration

### Tier 4: Meme Coin Specific

#### Social Sentiment Pipeline
- Twitter/X, Reddit, Telegram ingestion → NLP scoring → "hype velocity" metric
- High alpha potential but complex infrastructure (API costs, scraping reliability)

#### Pump Detection
- Volume spike + sentiment surge + price momentum = "pump probability score"
- Strict risk management: 2-5% max position, 30-50% stop-losses
- High false-positive rate — use as signal within ensemble, never standalone

#### New Listing Detection
- Monitor exchange listing announcements, auto-buy on trading open
- Low priority for Binance CEX (competitive, anti-bot measures)
- Better suited for DEX integration (future)

---

## 7. Tools & Libraries to Add

### Strategy Development

| Library | Purpose | Priority |
|---------|---------|----------|
| **VectorBT** | Vectorized backtesting — test thousands of strategies simultaneously | HIGH |
| **FinRL** | Expand RL repertoire beyond PPO (A2C, DDPG, TD3, SAC) | HIGH |
| **PyTorch Geometric** | GNN for market structure analysis | MEDIUM |
| **HuggingFace Transformers** | Temporal Fusion Transformer for price prediction | MEDIUM-HIGH |
| **statsmodels** | Cointegration tests for pairs trading | HIGH |
| **NautilusTrader** | Execution optimization concepts (Rust-native core) | MEDIUM |
| **Freqtrade** | Reference for FreqAI ML module patterns | LOW (reference only) |

### ML/Data Science

| Library | Purpose | Priority |
|---------|---------|----------|
| **scikit-learn** | Already used (regime classifier) — extend for factor models | HAVE |
| **XGBoost** | Already used (regime classifier) — extend for new classifiers | HAVE |
| **Stable-Baselines3** | Already used (PPO) — add SAC, TD3, A2C | HAVE |
| **PyTorch** | Already used (PPO) — extend for Transformers, diffusion | HAVE |
| **scipy** | Statistical tests (cointegration, Granger causality) | HIGH |
| **networkx** | Graph construction for GNN input | MEDIUM |
| **diffusers** | Diffusion models for synthetic data generation | MEDIUM |

### Data Sources to Integrate

| Source | Type | Priority | Cost |
|--------|------|----------|------|
| **CryptoQuant** | On-chain analytics | HIGH | $99-399/mo |
| **LunarCrush** | Social sentiment metrics | HIGH | Free tier available |
| **Glassnode** | On-chain metrics (HODL waves, SOPR, MVRV) | MEDIUM | $39-799/mo |
| **Santiment** | Alternative data (dev activity, social) | MEDIUM | Free tier available |
| **DeFiLlama** | DeFi TVL and protocol health | LOW | Free |
| **CoinGecko API** | Supplementary market data | LOW | Free tier available |
| **Twitter/X API** | Real-time social sentiment | HIGH | $100/mo (Basic) |
| **Binance Depth Stream** | Order book data | MEDIUM | Free (already connected) |

---

## 8. Data Sources to Integrate

### Current Data (What We Have)

| Source | Data Type | Storage | Freshness |
|--------|-----------|---------|-----------|
| Binance WebSocket | Real-time ticks, all 600+ USDT pairs | Redis + TimescaleDB | Sub-second |
| Binance REST (via CCXT) | Historical OHLCV, order book snapshots | TimescaleDB | On-demand |
| Candle aggregates | 1m, 5m, 1h, 1d candles | TimescaleDB continuous aggregates | 60s refresh |
| Backfill history | Multi-month historical klines | TimescaleDB `candles_backfill` | Batch |

### Data We Should Add

#### Tier 1: Free / Low-Cost, High Impact

| Source | Data | Use Case | Integration Effort |
|--------|------|----------|-------------------|
| **Binance Funding Rates** | 8h funding rates for perpetual futures | Funding rate arbitrage strategy | LOW — CCXT `fetch_funding_rate()` |
| **Binance Depth Stream** | Real-time order book snapshots | Order flow analysis, liquidity monitoring | LOW — already have WS infra |
| **Fear & Greed Index** | Daily market sentiment (0-100) | Regime classification feature, risk overlay | LOW — simple REST call |
| **DeFiLlama** | TVL per protocol, chain flows | DeFi token correlation with TVL | LOW — free REST API |
| **CoinGecko** | Market cap, supply data, categories | Factor model inputs, sector classification | LOW — free tier |

#### Tier 2: Moderate Cost, Strong Alpha

| Source | Data | Use Case | Integration Effort |
|--------|------|----------|-------------------|
| **LunarCrush** | Social volume, engagement, galaxy score | Sentiment signal for ensemble | MEDIUM — REST API integration |
| **Twitter/X API** | Real-time tweets about crypto tokens | NLP sentiment pipeline | MEDIUM — streaming + NLP |
| **CryptoQuant** | Exchange flows, whale alerts, miner data | On-chain signals for large-cap pairs | MEDIUM — REST API + data pipeline |
| **Binance Announcements** | Listing/delisting notices | New listing detection strategy | LOW — RSS/API polling |

#### Tier 3: Higher Cost, Specialized

| Source | Data | Use Case | Integration Effort |
|--------|------|----------|-------------------|
| **Glassnode** | SOPR, MVRV, HODL waves, realized cap | Macro cycle timing, BTC-specific signals | MEDIUM — REST API |
| **Nansen** | Labeled wallets (500M+ addresses) | Smart money tracking | HIGH — complex data model |
| **Santiment** | Dev activity, social trends | Long-term project health signals | MEDIUM — REST API |
| **Kaiko** | Institutional-grade market data | Cross-exchange price feeds | HIGH — expensive, complex |

---

## 9. The Strategy Search Process

### The Vision: Finding the ONE Best Strategy

The goal is not to run hundreds of agents simultaneously. It's to use our platform as a **strategy search engine** — testing hundreds of variations to find the single best approach, then deploying that.

Agents are test subjects, not the product. We run many experiments to find one champion.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    STRATEGY SEARCH ARCHITECTURE                      │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  AUTORESEARCH │    │   GENETIC    │    │  BACKTESTING │          │
│  │    LOOP       │    │  ALGORITHM   │    │    ENGINE    │          │
│  │              │    │              │    │              │          │
│  │ LLM explores │    │ Evolves 12-  │    │ Test ideas   │          │
│  │ strategy     │    │ param genome │    │ on historical│          │
│  │ variations   │    │ via battles  │    │ data         │          │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘          │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              CANDIDATE STRATEGY POOL                      │      │
│  │  (momentum, mean-reversion, stat-arb, ML-based, etc.)    │      │
│  └──────────────────────────┬───────────────────────────────┘      │
│                             │                                       │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              WALK-FORWARD VALIDATION GATE                 │      │
│  │  WFE ≥ 0.5 required │ OOS Sharpe > 0 │ DD < 30%         │      │
│  └──────────────────────────┬───────────────────────────────┘      │
│                             │                                       │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              BATTLE TOURNAMENT                            │      │
│  │  Candidates compete head-to-head against current best     │      │
│  │  Win → new champion │ Lose → discard or iterate           │      │
│  └──────────────────────────┬───────────────────────────────┘      │
│                             │                                       │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              DEPLOY THE CHAMPION                          │      │
│  │  One agent runs the winning strategy                      │      │
│  │  Circuit breaker + drift detection monitors performance   │      │
│  └──────────────────────────┬───────────────────────────────┘      │
│                             │                                       │
│                             ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │              CONTINUOUS MONITORING                        │      │
│  │  Drift detection → champion is decaying                   │      │
│  │  Alpha decay confirmed → back to SEARCH (top of funnel)  │      │
│  └──────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

### The Search Funnel

Agents exist to TEST strategies, not to run them all permanently:

| Stage | What Happens | Survival Rate |
|-------|-------------|---------------|
| **Discovery** | Autoresearch (~100/night), genetic evolution (30 generations), manual ideas | 100% enter |
| **Backtesting** | Does it profit on historical data? | ~20% survive |
| **Walk-Forward** | Does it STILL work on unseen data? | ~30-50% of survivors |
| **Deflated Sharpe** | Is the result statistically significant, not luck? | ~50% of survivors |
| **Battle Tournament** | Does it beat the current champion head-to-head? | Only the best |
| **Deployment** | **ONE strategy runs in production** | 1 champion |

### Strategy Lifecycle

Every strategy has an expiration date (alpha decay). The search process is continuous:

1. **Search** constantly using autoresearch + genetic algorithm + backtesting
2. **Validate** ruthlessly through the 4-stage funnel
3. **Deploy** only the champion
4. **Monitor** for decay (drift detection, attribution tracking)
5. **Replace** when it decays — the next candidate from the pipeline takes over
6. **Repeat** forever — the cycle never stops

### How Multiple Agents Help the Search (Not Production)

We use multiple agents during the SEARCH phase, not for permanent deployment:

- **Battle candidates against each other** to find the genuine best
- **Run parallel backtests** across different strategy families simultaneously
- **A/B test** the top 2-3 candidates in paper trading before committing to one
- Once the champion is found, **one agent runs it** in production

---

## 10. Overfitting Prevention

### The Core Challenge

When testing hundreds of strategy variations (via autoresearch, genetic evolution, and backtesting), some will look good by pure chance. We must distinguish genuine alpha from statistical noise.

### Anti-Overfitting Framework

| Defense | Current State | Action Needed |
|---------|--------------|---------------|
| **Walk-Forward Validation** | HAVE (WFE ≥ 0.5) | Extend to all new strategies |
| **Out-of-Sample Testing** | HAVE (train/val/test splits) | Add purged cross-validation |
| **A/B Gate** | HAVE (min_improvement=0.01) | Increase to 0.03 for high-variance strategies |
| **Deflated Sharpe Ratio** | MISSING | Adjust for multiple testing (critical when testing hundreds of variations) |
| **Transaction Cost Sensitivity** | PARTIAL | Re-run all backtests at 2x and 3x costs |
| **Regime Decomposition** | HAVE (4 regimes) | Reject single-regime strategies |
| **Minimum Trade Count** | PARTIAL | Enforce ≥50 trades per OOS window |
| **Complexity Penalty** | MISSING | Penalize parameter count in fitness function |
| **Synthetic Stress Testing** | MISSING | Diffusion model scenarios for tail events |
| **Alpha Decay Monitoring** | PARTIAL (drift detection) | Add rolling Sharpe decay rate tracking |

### Deflated Sharpe Ratio (Critical Addition)

When testing N strategies, the expected best Sharpe by chance alone is:

```
E[max(SR)] ≈ √(2 × ln(N))
```

For N=1000 experiments: `E[max(SR)] ≈ √(2 × ln(1000)) ≈ 3.72`

This means **any backtest Sharpe < 3.72 could be luck when testing 1000 strategies.** The Deflated Sharpe Ratio adjusts for this:

```python
def deflated_sharpe(observed_sr, num_trials, skewness, kurtosis, track_record_years):
    """Bailey & López de Prado (2014) deflated Sharpe ratio."""
    expected_max_sr = sqrt(2 * log(num_trials))
    se = sqrt((1 - skewness * observed_sr + (kurtosis - 1) / 4 * observed_sr**2) / track_record_years)
    test_stat = (observed_sr - expected_max_sr) / se
    return norm.cdf(test_stat)  # p-value; > 0.95 means significant
```

**Action:** Implement `deflated_sharpe()` in `agent/strategies/` and require p-value > 0.95 before deploying any strategy discovered through mass screening.

### Walk-Forward Validation Enhancements

Current WFE threshold of 0.5 is good but should be complemented:

1. **Combinatorial Purged Cross-Validation (CPCV):** Preserves temporal structure while reducing variance. Better than simple train/test split for time series.
2. **Anchored expanding window:** Always start training from the beginning, grow test window. Catches strategies that only work on recent data.
3. **Multiple WFE windows:** Require WFE ≥ 0.5 across ALL windows, not just the mean. One bad window = deployment blocked.

---

## 11. Prioritized Implementation Roadmap

### Phase 1: Quick Wins (Week 1-2)

| # | Task | Effort | Expected Impact |
|---|------|--------|----------------|
| 1 | **Volume Spike Detection** — z-score alert across all pairs | 2 days | Pre-filter for all strategies |
| 2 | **Cross-Sectional Momentum** — rank+allocate across 600+ pairs | 3 days | New alpha source, Sharpe 1.0-2.0 |
| 3 | **Mean Reversion + Regime** — activate during MEAN_REVERTING regime | 2 days | Complements momentum |
| 4 | **Deflated Sharpe Ratio** — prevent mass-screening overfitting | 1 day | Critical safety gate |

### Phase 2: Autoresearch Integration (Week 3-4)

| # | Task | Effort | Expected Impact |
|---|------|--------|----------------|
| 5 | **Build autoresearch harness** — fixed backtest_harness.py + modifiable strategy.py | 3 days | Enables autonomous research |
| 6 | **First overnight run** — iterate on 12-param genome | 1 day setup + overnight | ~100 experiment data points |
| 7 | **5 parallel research tracks** — indicators, entry/exit, risk, weights, pairs | 2 days setup | 5x research throughput |
| 8 | **Integration pipeline** — winning strategies → ensemble deployment | 2 days | Close the loop |

### Phase 3: Statistical Arbitrage (Week 5-6)

| # | Task | Effort | Expected Impact |
|---|------|--------|----------------|
| 9 | **Cointegration scanner** — test all 180K pair combinations | 3 days | Pairs trading opportunity map |
| 10 | **Pairs trading agent** — Kalman filter + z-score entry/exit | 4 days | Sharpe 1.5-3.0 |
| 11 | **Funding rate monitor** — track rates across exchanges | 2 days | Arb opportunity detection |

### Phase 4: ML Upgrades (Week 7-10)

| # | Task | Effort | Expected Impact |
|---|------|--------|----------------|
| 12 | **LLM sentiment signal** — OpenRouter-powered news scoring | 5 days | Event-driven alpha |
| 13 | **Transformer prediction** — TFT on historical candles | 1 week | New ensemble signal |
| 14 | **MARL training** — extend battles into learning environment | 2 weeks | Agent co-evolution |
| 15 | **Synthetic data generation** — diffusion model for stress testing | 1 week | Better validation |

### Phase 5: Advanced Infrastructure (Month 3-4)

| # | Task | Effort | Expected Impact |
|---|------|--------|----------------|
| 16 | **GNN for lead-lag** — graph neural network on 600+ pair correlations | 2 weeks | Novel signal source |
| 17 | **Social sentiment pipeline** — Twitter/Reddit ingestion + NLP | 2 weeks | Meme coin alpha |
| 18 | **Order flow analysis** — depth stream processing for top 50 pairs | 2 weeks | Microstructure signals |
| 19 | **On-chain analytics** — CryptoQuant/Glassnode integration | 2 weeks | Macro cycle timing |
| 20 | **Meta-learning** — MAML for rapid regime adaptation | 3 weeks | Robustness improvement |

---

## 12. Architecture Vision

### Where We Are Now (March 2026)

```
5 strategies → 1 ensemble → 1 agent → trades
```

### Where We're Going (Q3 2026)

```
Autoresearch + Genetic Evolution + Backtesting + Battles
    ↓
Hundreds of strategy variations tested
    ↓
Walk-forward gate → Deflated Sharpe → Battle tournament
    ↓
ONE champion strategy deployed
    ↑                            ↓
    └── drift detection → decay confirmed → SEARCH AGAIN ←──┘
```

### The Meta-Strategy

**Our competitive advantage is not any single strategy. It's how fast we can find the NEXT winning strategy when the current one decays.**

1. **Search:** Autoresearch loop + genetic algorithm + backtesting generate hundreds of candidates
2. **Validate:** Walk-forward + deflated Sharpe + battle tournaments eliminate overfitting and luck
3. **Deploy:** The single champion runs in production
4. **Monitor:** Drift detection + attribution tracking watch for decay
5. **Replace:** When the champion decays, the next validated candidate takes over
6. **Repeat:** The search cycle never stops

### Key Metrics to Track

| Metric | Target | Current |
|--------|--------|---------|
| Autoresearch experiments per day | 100+ | 0 (not yet built) |
| Walk-forward-validated candidates ready | 10+ | ~5 |
| Strategy replacement time | <1 week | Manual |
| Champion Sharpe ratio | >2.0 | TBD (first live runs pending) |
| Max drawdown | <15% | TBD |
| Monthly return target | 10% | 10% (goal) |
| Alpha decay detection time | <48h | ~7d (weekly retrain) |

---

## Summary

We have an exceptionally well-built platform with production-grade infrastructure for backtesting, battles, walk-forward validation, and automated retraining. The gap is not in tools — it's in **search velocity** and **strategy diversity of candidates**.

The three highest-leverage actions are:

1. **Implement the Autoresearch loop** — turn our platform into a 24/7 strategy discovery machine
2. **Add cross-sectional momentum and pairs trading** — immediate alpha candidates from our 600+ pair universe
3. **Deploy the Deflated Sharpe Ratio** — prevent overfitting when mass-testing strategy variations

Everything else builds on these foundations. The goal: always have the best single strategy running, with a pipeline of validated replacements ready.

---

*Research compiled 2026-03-23. Sources: codebase analysis, Karpathy autoresearch repository, academic literature, industry reports.*
