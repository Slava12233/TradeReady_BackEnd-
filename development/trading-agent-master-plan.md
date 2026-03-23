---
type: plan
title: "Trading Agent Master Plan — Achieving 10% Steady Portfolio Income"
status: active
priority: P0
tags:
  - plan
  - agent
  - trading
  - strategies
  - master-plan
created: 2026-03-22
---

# Trading Agent Master Plan — Achieving 10% Steady Portfolio Income

## Executive Summary

This is the A-Z roadmap for building an autonomous trading agent that achieves **10% steady income** on a demo environment that mirrors real markets. The plan leverages the closed-loop architecture: **the agent improves the platform, the platform improves the agent**.

### Current State (2026-03-22)

**What we have (fully built):**
- Production platform: 86+ REST endpoints, 5 WebSocket channels, 58 MCP tools, 37 SDK methods
- Agent framework: 4 workflows, 23 tools (7 SDK + 11 REST + 5 agent), conversation system, memory, permissions, trading loop
- 5 ML strategies: PPO RL, genetic algorithm, regime detection, risk overlay, ensemble combiner
- Gymnasium environments: 7 envs (single-asset, multi-asset, continuous, live)
- Full observability: structlog + 16 Prometheus metrics + 6 Grafana dashboards + 11 alert rules
- Backtesting engine with look-ahead bias prevention
- Battle system for agent-vs-agent competitions
- 2000+ tests across backend + agent + frontend

**What we DON'T have yet:**
- No trained models (PPO weights, regime classifier, evolved genomes — all require running the training pipelines)
- No historical data loaded (must run `backfill_history.py`)
- Migrations 018/019 not applied to live DB
- Agent has never executed a real trade loop end-to-end
- No walk-forward validation, no drift detection, no continuous retraining
- Key integration gaps (LogBatchWriter not wired, IntentRouter handlers not registered, WebSocket unused)
- Missing order types in agent tools (no limit orders, stop-loss, take-profit — only market orders)
- No correlation-aware risk management
- No paper trading graduation protocol

---

## Goal Definition

### Primary Goal
> Achieve **10% annualized return** on virtual USDT portfolio with **Sharpe ratio ≥ 1.5** and **max drawdown ≤ 8%** in the demo environment.

### Success Metrics

| Metric | Target | Why |
|--------|--------|-----|
| Annualized Return | ≥ 10% | Primary income goal |
| Sharpe Ratio | ≥ 1.5 | Risk-adjusted performance (quant fund standard) |
| Sortino Ratio | ≥ 2.0 | Penalizes only downside volatility |
| Max Drawdown | ≤ 8% | Capital preservation |
| Win Rate | ≥ 55% | Slightly above random = sustainable |
| Profit Factor | ≥ 1.3 | Gross profit / gross loss |
| Monthly Return Std Dev | ≤ 3% | "Steady" means low variance |
| Trades/Day | 5-20 | Not too few (missed opportunities) or too many (overtrading) |

### Non-Goals
- Maximizing absolute returns (leads to unacceptable drawdowns)
- High-frequency trading (our latency model doesn't support it)
- Trading illiquid pairs (stick to top 20-30 by volume)

---

## Architecture: The Closed Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE IMPROVEMENT CYCLE                             │
│                                                                     │
│   ┌──────────────┐     ┌──────────────┐     ┌──────────────┐       │
│   │  1. OBSERVE   │────▶│  2. DECIDE   │────▶│  3. EXECUTE  │       │
│   │              │     │              │     │              │       │
│   │ Market data  │     │ Ensemble     │     │ Risk check   │       │
│   │ Portfolio    │     │ signals      │     │ Size + place │       │
│   │ Regime       │     │ Confidence   │     │ Order        │       │
│   │ Memory       │     │ Risk veto    │     │              │       │
│   └──────────────┘     └──────────────┘     └──────┬───────┘       │
│          ▲                                          │               │
│          │                                          ▼               │
│   ┌──────┴───────┐     ┌──────────────┐     ┌──────────────┐       │
│   │  6. IMPROVE  │◀────│  5. ANALYZE  │◀────│  4. RECORD   │       │
│   │              │     │              │     │              │       │
│   │ Retrain RL   │     │ Drift detect │     │ Journal      │       │
│   │ Evolve pop   │     │ Attribution  │     │ Decisions    │       │
│   │ Update regime│     │ Strategy PnL │     │ Trace IDs    │       │
│   │ Reweight ens │     │ Win/loss     │     │ API calls    │       │
│   └──────────────┘     └──────────────┘     └──────────────┘       │
│                                                                     │
│   ┌─────────────────────────────────────────────────────────┐       │
│   │              7. PLATFORM IMPROVEMENTS                    │       │
│   │  Agent discovers bugs → files feedback → we fix them     │       │
│   │  Agent needs new tools → requests features → we build    │       │
│   │  Agent finds edge cases → tests them → we harden         │       │
│   └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 0: Foundation (Must Do First)

**Goal:** Get the platform running with data loaded so the agent can start training and trading.

### Task 0.1: Infrastructure Setup
- [ ] Start Docker services (`docker compose up -d`)
- [ ] Apply Alembic migrations 018 and 019 (`alembic upgrade head`)
- [ ] Verify all services healthy (`GET /health`, Redis ping, Celery worker)
- [ ] Verify Prometheus scraping both `:8000/metrics` and `:8001/metrics`
- [ ] Import Grafana dashboards from `monitoring/dashboards/`

### Task 0.2: Historical Data Loading
- [ ] Run `python scripts/seed_pairs.py` — seed 600+ USDT pairs
- [ ] Run `python scripts/backfill_history.py` — backfill 12+ months of 1-minute OHLCV from Binance
- [ ] Verify data coverage: `python -m agent.strategies.rl.data_prep --assets BTCUSDT ETHUSDT SOLUSDT`
- [ ] Validate >95% coverage for train/val/test splits

### Task 0.3: Agent Account Provisioning
- [ ] Create a dedicated agent account via `POST /api/v1/auth/register`
- [ ] Create the trading agent via `POST /api/v1/agents` (JWT auth)
- [ ] Set agent risk profile: `max_position_pct=0.05`, `daily_loss_limit_pct=0.08`
- [ ] Configure `agent/.env` with agent API key, secret, platform URL
- [ ] Run smoke test: `python -m agent.main smoke` — all 10 steps must pass

### Task 0.4: Fix Critical Integration Gaps
- [ ] **Wire `LogBatchWriter` into the agent decision loop** — currently the batch writer exists but is not connected to `log_api_call()`. Instantiate it as a singleton in `AgentServer` and pass it into the trading loop
- [ ] **Fix `RedisMemoryCache.get_cached()` glob bug** — `redis.get()` doesn't support glob patterns. Fix to use `get_cached_for_agent(memory_id, agent_id)` instead
- [ ] **Register `IntentRouter` handlers in `AgentServer`** — all handlers return stubs. Wire real handlers for TRADE, ANALYZE, PORTFOLIO, STATUS intents
- [ ] **Add TTL to working memory** — `agent:working:{agent_id}` Redis hash has no TTL. Add 24-hour TTL as crash safety net
- [ ] **Ensure `PermissionDenied` is handled by global exception handler** — it's not a subclass of `TradingPlatformError`. Either subclass it or add explicit catch in `create_app()`

**Estimated effort:** 2-3 days
**Agents:** backend-developer, migration-helper, test-runner, context-manager

---

## Phase 1: Training Pipeline (Train All 5 Strategies)

**Goal:** Train all ML models so the ensemble has real signals to combine.

### 1.1: Regime Classifier Training
- [ ] Train XGBoost classifier on 12 months BTC 1h data: `python -m agent.strategies.regime.classifier --train`
- [ ] Validate accuracy ≥ 70% on temporal test split
- [ ] Generate SHA-256 checksum for model file
- [ ] Run switcher demo: `python -m agent.strategies.regime.switcher --demo --candles 300`
- [ ] Run 12-month validation: `python -m agent.strategies.regime.validate --months 12`
- [ ] **Enhancement:** Add 2 new features to classifier (Bollinger Band width, volume ratio) — improve regime transition detection

### 1.2: PPO Reinforcement Learning Training
- [ ] Multi-seed training: `python -m agent.strategies.rl.runner --seeds 42,123,456 --timesteps 500000`
- [ ] Use Sortino reward (`--reward sortino`) instead of default Sharpe — better aligned with "steady income"
- [ ] Evaluate all seeds: `python -m agent.strategies.rl.evaluate`
- [ ] Verify best model Sharpe > 1.0 on test split
- [ ] Generate checksums for all model files
- [ ] **Enhancement:** Add composite reward function: `0.4*sortino + 0.3*pnl + 0.2*activity_bonus + 0.1*drawdown_penalty`

### 1.3: Evolutionary Strategy Optimization
- [ ] Run evolution: `python -m agent.strategies.evolutionary.evolve --generations 30 --pop-size 12`
- [ ] Verify convergence (fitness stabilizes within 30 generations)
- [ ] Analyze results: `python -m agent.strategies.evolutionary.analyze`
- [ ] **Enhancement:** Upgrade fitness function to multi-factor with OOS component:
  ```
  fitness = 0.35*sharpe + 0.25*profit_factor - 0.20*max_drawdown + 0.10*win_rate + 0.10*oos_sharpe
  ```

### 1.4: Ensemble Weight Optimization
- [ ] Optimize weights: `python -m agent.strategies.ensemble.optimize_weights --seed 42`
- [ ] Validate ensemble vs individual strategies: `python -m agent.strategies.ensemble.validate --periods 3`
- [ ] Verify ensemble outperforms best individual strategy
- [ ] Save optimal weights to `optimal_weights.json`

### 1.5: Full Pipeline Backtest
- [ ] Run full ensemble backtest: `python -m agent.strategies.ensemble.run --mode backtest`
- [ ] Verify: Sharpe ≥ 1.0, max drawdown ≤ 10%, positive ROI
- [ ] Compare ensemble vs each strategy in isolation
- [ ] If metrics fail: adjust weights, retrain underperforming strategies

**Estimated effort:** 3-5 days (mostly compute time)
**Agents:** ml-engineer, test-runner, context-manager
**Dependencies:** Phase 0 complete

---

## Phase 2: Risk Management Hardening

**Goal:** Make the agent's risk controls robust enough for steady 10% returns with controlled drawdowns.

### 2.1: Position Sizing Overhaul
- [ ] **Reduce `max_trade_pct` from 0.05 to 0.02** — cap per-trade risk at 2% of equity
- [ ] **Implement Quarter-Kelly position sizing** in `agent/strategies/risk/sizing.py`:
  ```python
  kelly_fraction = (win_rate * avg_win_loss_ratio - (1 - win_rate)) / avg_win_loss_ratio
  position_pct = kelly_fraction / 4  # quarter Kelly
  position_pct = clamp(position_pct, 0.01, 0.05)
  ```
- [ ] **ATR-based volatility sizing**: `size = risk_amount / (ATR * 2.0)` — positions auto-shrink when volatility spikes
- [ ] Add `SizerConfig.method` field: `"atr"`, `"kelly_quarter"`, or `"hybrid"` (ATR-adjusted Kelly)

### 2.2: Graduated Drawdown Scaling
- [ ] Replace binary drawdown reduction (current: halve at 3%) with graduated curve:

  | Drawdown | Position Multiplier |
  |----------|-------------------|
  | 0-2% | 1.0x |
  | 2-5% | 0.75x |
  | 5-8% | 0.50x |
  | 8-10% | 0.25x |
  | >10% | 0x (HALT) |

- [ ] Implement in `RiskAgent.assess()` — return `REDUCE` with a `scale_factor` instead of binary HALT/OK
- [ ] Wire scale_factor through `VetoPipeline` and `DynamicSizer`

### 2.3: Correlation-Aware Portfolio Construction
- [ ] Before each trade, calculate rolling 20-period correlation between proposed asset and each open position
- [ ] If correlation > 0.7 with existing position: reduce size by `(1 - correlation)` factor
- [ ] Cap total correlated exposure at 2x single position risk budget
- [ ] Implement in `RiskMiddleware` — add `_check_correlation()` gate to the pipeline

### 2.4: Strategy-Level Circuit Breakers
- [ ] 3 consecutive losses from a strategy → pause that strategy for 24h
- [ ] Strategy drawdown > 5% in a week → pause for 48h
- [ ] Ensemble wrong on > 60% of recent 20 signals → reduce all sizes to 25%
- [ ] Track in Redis: `strategy:circuit:{strategy_name}:{agent_id}`

### 2.5: Advanced Order Types
- [ ] **Add limit order tool** — agent can place limit orders for better entry prices
- [ ] **Add stop-loss tool** — automatic stop-loss on every position (mandatory)
- [ ] **Add take-profit tool** — automated profit-taking
- [ ] **Add cancel order tool** — agent can manage pending orders
- [ ] Update `sdk_tools.py` to expose `place_limit_order()`, `place_stop_loss()`, `place_take_profit()`, `cancel_order()`, `cancel_all_orders()`, `get_open_orders()`

### 2.6: Drawdown Recovery Protocol — COMPLETE (Task 21)
- [x] After HALT trigger: wait for ATR to return to < 1.5x median before resuming
- [x] Resume at 25% position sizes
- [x] Scale up 25% per day over 4 days if no further losses
- [x] Full size only after recovering 50% of the drawdown
- [x] Implement as `RecoveryManager` class in `agent/strategies/risk/`

### 2.7: Security Review — COMPLETE (Task 22)
- [x] 0 CRITICAL, 0 HIGH findings
- [x] 2 MEDIUM deferred: StrategyCircuitBreaker Redis OOM failure mode, DrawdownProfile threshold validation gap
- [x] All risk gates confirmed fail-closed

**Estimated effort:** 4-5 days
**Agents:** backend-developer, security-reviewer, test-runner, context-manager
**Dependencies:** Phase 0 complete (Phase 1 can run in parallel)

---

## Phase 3: Agent Intelligence Upgrades

**Goal:** Make the agent smarter — better signals, smarter execution, self-aware decision making.

### 3.1: Dynamic Ensemble Weights
- [ ] Track rolling Sharpe ratio per signal source (RL, EVOLVED, REGIME) over last 50 trades
- [ ] Dynamically adjust weights: `weight[source] = base_weight * (1 + source_sharpe) / norm_factor`
- [ ] Implement in `MetaLearner` — add `update_weights(recent_outcomes)` method
- [ ] Add regime-conditional modifiers:
  - TRENDING: RL weight +30%, EVOLVED -10%
  - MEAN_REVERTING: EVOLVED weight +30%, RL -10%
  - HIGH_VOLATILITY: all sizes -50%, REGIME weight +20%
  - LOW_VOLATILITY: RL +20% (detects subtle patterns)

### 3.2: Enhanced Signal Generation — COMPLETE (Task 24)
- [x] Add `get_ticker()` to SDK tools — 24h volume/high/low/change data enriches signal quality
- [x] Add `get_pnl()` to SDK tools — agent can track its own session PnL
- [x] Add volume-weighted analysis to `SignalGenerator` — confirm signals with volume
- [x] Increase confidence threshold from 0.5 to 0.55 — fewer but higher-quality trades (0.55 not 0.6 as originally planned; 35 new tests)

### 3.3: Concept Drift Detection
- [ ] Create `agent/strategies/drift.py` — `DriftDetector` class
- [ ] Track rolling window of strategy performance (Sharpe, win rate, avg PnL)
- [ ] Use Page-Hinkley test to detect statistically significant performance drops
- [ ] When drift detected:
  - Log `REGIME_DRIFT_DETECTED` event
  - Auto-reduce position sizes by 50%
  - Trigger async retrain job for affected strategy
  - Increase REGIME strategy weight (adapts to new conditions by design)
- [ ] Wire into `TradingLoop._observe_and_learn()` cycle

### 3.4: Paper Trading Graduation
- [ ] Add `PaperTradingPhase` to `TradingLoop`:
  - Agent generates signals but doesn't execute
  - Simulates fills at market price + slippage
  - Tracks virtual PnL over configurable window (default 30 days)
- [ ] Graduation criteria: Sharpe ≥ 1.0, max drawdown ≤ 8%, positive ROI over the window
- [ ] Auto-transition to live (demo) trading when criteria met
- [ ] If performance drops below criteria during live, revert to paper trading

### 3.5: Smart Pair Selection — COMPLETE (Task 26)
- [x] Don't trade all 600+ pairs — focus on top 20-30 by daily volume
- [x] Implement `PairSelector` in `agent/trading/`:
  - Fetch 24h tickers for all pairs via `GET /api/v1/market/tickers`
  - Rank by volume, filter minimum $10M daily volume
  - Exclude pairs with >5% spread (illiquid)
  - Rotate pair universe weekly based on volume rankings (1h Redis cache)
- [x] Feed selected pairs to `SignalGenerator` and `EnsembleRunner` (42 tests)

### 3.6: WebSocket Integration — COMPLETE (Task 27)
- [x] Replace polling-based price checks with WebSocket streaming
- [x] Use `AgentExchangeWS` from SDK for real-time ticker and order updates
- [x] Subscribe to `ticker:{symbol}` for active trading pairs
- [x] Subscribe to `orders` channel for instant fill notifications
- [x] REST fallback on WS disconnect (WSManager, price buffer, 46 tests)

**Estimated effort:** 5-7 days
**Agents:** backend-developer, ml-engineer, test-runner, context-manager
**Dependencies:** Phase 1 + Phase 2 complete

---

## Phase 4: Continuous Learning & Self-Improvement

**Goal:** Make the agent continuously improve without manual intervention.

### 4.1: Automated Retraining Pipeline
- [ ] Create `agent/strategies/retrain.py` — orchestrates periodic retraining

  | Component | Strategy | Frequency |
  |-----------|----------|-----------|
  | RL models (PPO) | Full retrain on rolling 6-month window | Every 30 days |
  | Regime classifier | Incremental update with new labeled data | Weekly |
  | Ensemble weights | Online adjustment based on recent performance | Every trading session |
  | Genome population | Run 2-3 new evolutionary generations | Weekly |
  | Risk parameters | Auto-review + alerts | Monthly |

- [ ] Implement as Celery beat tasks (configurable schedules)
- [ ] Each retrain job:
  1. Train new model on recent data
  2. Backtest new model on held-out period
  3. Compare to current model via `ABTestRunner`
  4. Deploy only if new model outperforms on Sharpe + drawdown
  5. Log results to `agent_learnings` for memory

### 4.2: Walk-Forward Validation
- [ ] Replace single train/test split with rolling windows:
  - Train on months 1-6, evaluate on month 7
  - Train on months 2-7, evaluate on month 8
  - Continue rolling...
  - Final score = average of all out-of-sample evaluations
- [ ] Implement in `agent/strategies/rl/runner.py` and `evolutionary/evolve.py`
- [ ] Walk-Forward Efficiency > 50% required (otherwise strategy is overfit)

### 4.3: Decision Outcome Settlement — COMPLETE (Task 30)
- [x] Create Celery task `settle_agent_decisions` (every 5 minutes):
  - Find unresolved decisions via `AgentDecisionRepository.find_unresolved()`
  - Check if linked orders have been filled
  - Call `update_outcome(decision_id, outcome_pnl)` with realized PnL
  - This closes the feedback loop from trade outcome → learning system (16 tests)
- [x] `TradingJournal` consumes settled decisions to reinforce/weaken memories

### 4.4: Strategy Attribution Analytics
- [ ] Wire the existing `agent_strategy_attribution` Celery task (daily 02:00 UTC) to feed back into ensemble weights
- [ ] Per-strategy metrics (signal count, win rate, total PnL) → update `MetaLearner` weights
- [ ] Strategies with negative attribution over 7 days get auto-paused
- [ ] Create monthly attribution reports in `development/agent-analysis/`

### 4.5: Memory-Driven Learning — COMPLETE (Task 32)
- [x] After each trade, `TradingJournal.generate_reflection()` should:
  - Save EPISODIC memory: what happened, entry/exit prices, PnL, reasoning
  - Save PROCEDURAL memory: what worked/didn't work as a pattern
  - Reinforce matching past memories (builds confidence in repeated patterns)
- [x] Before each trade, `ContextBuilder` should:
  - Retrieve top 5 PROCEDURAL memories for this symbol/regime
  - Include in LLM prompt: "Past experience suggests..."
  - This creates a genuine learning loop where past mistakes inform future decisions (29 tests; `retrieve_targeted()` added to MemoryRetriever)

### 4.6: Anti-Overfitting Measures
- [ ] Monte Carlo simulation: after backtesting, shuffle trade order 1000x and compute outcome distribution
- [ ] If performance varies wildly with trade order → strategy is fragile → reject
- [ ] Track in-sample vs out-of-sample performance gap; if gap > 30% → overfit alert
- [ ] Minimum 3 distinct time periods must show positive returns before deploying

**Estimated effort:** 5-7 days
**Agents:** ml-engineer, backend-developer, test-runner, context-manager
**Dependencies:** Phase 1 + Phase 3 complete

---

## Phase 5: Platform Improvements (Agent-Driven)

**Goal:** The agent discovers platform gaps and we fix them, improving both sides.

### 5.1: Backtest Comparison Endpoint Usage — COMPLETE (Task 33)
- [x] Wire `GET /backtest/compare` into agent REST tools — allows comparing multiple backtest sessions
- [x] Wire `GET /backtest/best` — auto-select best backtest by metric
- [x] Wire `GET /backtest/{id}/results/equity-curve` — time-series equity analysis

### 5.2: Decision Analysis API — COMPLETE (Task 33)
- [x] Wire `GET /agents/{id}/decisions/analyze` into agent tools — self-insight into decision quality
- [x] Agent can query: "Show me all BUY decisions with negative PnL in the last 7 days"
- [x] Use analysis results to adjust strategy parameters (24 new tests total for Task 33)

### 5.3: Risk Profile Self-Tuning — COMPLETE (Task 33)
- [x] Wire `PUT /account/risk-profile` into agent tools
- [x] Agent can adjust its own risk limits based on performance:
  - Good week → slightly increase position limits
  - Bad week → tighten limits
  - But within guardrails set by the platform

### 5.4: Training Run Integration
- [ ] Wire training write endpoints (`POST /training/runs`, `/episodes`, `/complete`) into the RL training pipeline
- [ ] All training runs automatically tracked in the platform UI
- [ ] Training learning curves visible in real-time on the frontend

### 5.5: Battle System Activation — PARTIALLY COMPLETE (Task 34)
- [ ] Create multiple agent variants (different strategy mixes/risk profiles)
- [ ] Run weekly battles to compare variants
- [ ] Winner becomes the primary trading agent
- [x] Battle frontend (`Frontend/src/components/battles/`) — 9 components, 3 routes, 2 hooks, 14 API functions, 15 types built

### 5.6: Platform Feedback Loop
- [ ] Agent's `request_platform_feature()` tool creates feedback records
- [ ] Weekly review of agent feedback for platform improvements
- [ ] Track: bugs discovered, features requested, edge cases found
- [ ] Build a dashboard showing the agent's platform improvement contributions

**Estimated effort:** 4-5 days
**Agents:** backend-developer, frontend-developer, test-runner, context-manager
**Dependencies:** Phase 2 + Phase 3 complete

---

## Phase 6: Production Hardening & Monitoring

**Goal:** Make the system production-grade and operationally excellent.

### 6.1: Prometheus Scraping Fix — COMPLETE (Task 36)
- [x] Verify Prometheus scrape config includes `:8001` (agent metrics) alongside `:8000` (platform)
- [x] All 6 Grafana dashboards provisioned (auto-provisioning confirmed)
- [x] Alert rules loading validated

### 6.2: Graceful Shutdown — COMPLETE (Tasks 04, 36)
- [x] Ensure `LogBatchWriter.flush()` is called on shutdown (wired in AgentServer._shutdown())
- [x] Ensure `PermissionEnforcer.flush_audit_log()` is called on shutdown
- [x] Add TTL to all Redis working memory keys (crash safety — 24h TTL via atomic pipeline)
- [ ] Add orphan detection for in-memory battle engines (like backtests have) — deferred

### 6.3: Performance Optimization — AUDIT COMPLETE (Task 37)
- [ ] `ContextBuilder.build()` makes fresh network calls every invocation — HIGH priority; add 30-second cache (identified in audit, not yet fixed)
- [ ] `WSManager` subscribes to all pairs instead of filtered universe — HIGH priority; wire `PairSelector` output (identified in audit, not yet fixed)
- [ ] Batch API calls where possible — MEDIUM; identified
- [x] Use WebSocket for price data instead of REST polling (WSManager — Task 27)

### 6.4: Operational Dashboards
- [ ] Create a "Trading Agent Health" Grafana dashboard showing:
  - Current equity and daily PnL
  - Active positions and unrealized PnL
  - Signal confidence distribution
  - Strategy attribution (which strategy is contributing most)
  - Drawdown tracking with HALT threshold line
  - Trade frequency and win rate over time
- [ ] Set up PagerDuty/Slack alerts for critical conditions

### 6.5: Daily Report Generation
- [ ] Automated daily report (Celery beat, 00:00 UTC):
  - Day's trades, PnL, positions opened/closed
  - Strategy attribution breakdown
  - Risk metrics (current drawdown, exposure)
  - Anomalies detected (drift, unusual volume, circuit breaker triggers)
  - Saved to `development/daily/` Obsidian vault

**Estimated effort:** 3-4 days
**Agents:** backend-developer, deploy-checker, perf-checker, context-manager
**Dependencies:** Phase 4 complete

---

## Phase Execution Order

```
Phase 0 (Foundation)     ──── MUST DO FIRST ────────────────────────
     │
     ├── Phase 1 (Training)    ─── can run in parallel ──┐
     │                                                    │
     └── Phase 2 (Risk)        ─── can run in parallel ──┤
                                                          │
                                                          ▼
                                                    Phase 3
                                                  (Intelligence)
                                                          │
                                                          ▼
                                                    Phase 4
                                                  (Continuous
                                                   Learning)
                                                          │
                                              ┌───────────┼──────┐
                                              ▼           ▼      ▼
                                         Phase 5     Phase 6     │
                                        (Platform)  (Hardening)  │
                                              │           │      │
                                              └───────────┴──────┘
                                                          │
                                                          ▼
                                                    OPERATIONAL
                                                  (Continuous cycle)
```

---

## Strategy Deep Dive: How to Achieve 10% Steady Returns

### Why 10% Is Achievable But Not Trivial

Professional quant funds average 12.8% annual returns with Sharpe ratios of 1-2. Our advantage: zero transaction costs beyond simulated fees, no market impact on large orders, 24/7 crypto markets. Our disadvantage: single asset class (crypto), higher volatility.

### The Ensemble Approach (Our Primary Strategy)

```
Candle data arrives
    │
    ├── PPO RL Agent ────────────────► weight vector [BTC, ETH, SOL]
    │   (trained on Portfolio-v0)        ↓
    │                              MetaLearner.rl_weights_to_signals()
    │
    ├── Evolved Genome ──────────────► RSI/MACD based signal
    │   (12 params optimized by GA)      ↓
    │                              MetaLearner.genome_to_signals()
    │
    └── Regime Classifier ───────────► regime + strategy_id
        (XGBoost on 7 features)          ↓
                                   MetaLearner.regime_to_signals()
                                         │
                                         ▼
                                   MetaLearner.combine_all()
                                   (dynamic weighted voting)
                                         │
                                         ▼
                                   RiskMiddleware
                                   (veto pipeline + dynamic sizing)
                                         │
                                         ▼
                                   ExecutionDecision
                                   (APPROVED / RESIZED / VETOED)
```

### Key Trading Rules

1. **Never risk more than 2% of equity on a single trade**
2. **Always set a stop-loss** (2x ATR below entry for longs)
3. **Take profit at 3x ATR** (1.5:1 risk-reward minimum)
4. **No more than 3 correlated positions** (correlation > 0.7)
5. **Maximum 80% portfolio exposure** (always keep 20% cash)
6. **HALT trading if drawdown exceeds 10%** — wait for recovery
7. **Require ≥ 60% ensemble confidence** to enter a trade
8. **Require ≥ 2 of 3 strategies to agree** (majority vote)

### Pair Universe

Focus on liquid pairs with established price history:

| Tier | Pairs | Volume Requirement | Max Allocation |
|------|-------|-------------------|----------------|
| Core | BTCUSDT, ETHUSDT | Always traded | 30% each |
| Major | SOLUSDT, BNBUSDT, XRPUSDT | >$100M daily | 15% each |
| Active | Top 15 by volume | >$50M daily | 5% each |

### Expected Performance Breakdown

| Source | Expected Contribution | Basis |
|--------|----------------------|-------|
| RL (PPO) | 3-4% annual | Trend following + portfolio allocation |
| Evolved Strategy | 2-3% annual | Technical rule optimization |
| Regime Adaptation | 2-3% annual | Avoid wrong-regime trades |
| Risk Management | +2-3% annual | Drawdown prevention saves capital |
| **Ensemble Total** | **~10-13% annual** | **Sum > parts due to diversification** |

---

## Metrics & Monitoring Plan

### Real-Time Metrics (Agent Port :8001)
- `agent_trade_pnl_usd` — per-trade PnL distribution
- `agent_decisions_total` — trade count by direction
- `agent_strategy_signal_confidence` — signal quality tracking
- `agent_budget_usage_ratio` — position sizing utilization
- `agent_consecutive_errors` — error streak monitoring

### Daily Analytics (Celery Tasks)
- Strategy attribution (which strategy drove PnL)
- Memory effectiveness (are learnings being applied)
- Platform health report (API latency trends)

### Weekly Reviews
- Walk-forward performance vs backtest expectations
- Regime transition analysis
- Genetic population diversity check
- Model staleness check (retrain if needed)

### Monthly Reviews
- Full performance report vs 10% target
- Risk parameter review
- Strategy weight optimization
- Compare to buy-and-hold benchmarks

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Model overfitting to historical data | High | High | Walk-forward validation, Monte Carlo testing, OOS requirement |
| Regime shift invalidates trained models | Medium | High | Drift detection + auto-retrain + REGIME strategy adapts natively |
| Correlation spike causes cascading losses | Medium | High | Correlation-aware sizing, max correlated exposure cap |
| Platform bug causes incorrect fills | Low | High | Smoke test before each trading session, audit trail via trace_id |
| Redis/DB outage halts trading | Low | Medium | Graceful degradation, circuit breaker, health checks |
| LLM API downtime | Medium | Low | Degraded mode without LLM analysis, strategies run on pure signals |
| Overtrading burns through fee budget | Medium | Medium | Trade frequency limits in BudgetManager (50/day cap) |
| Flash crash in crypto market | Low | High | Stop-loss on every position, 10% drawdown HALT |

---

## Open Questions for CTO

> These questions will shape the next steps. Please answer what you can — we'll proceed with reasonable defaults for anything left open.

### Strategy & Goals

1. **Return target clarity:** Is 10% **monthly** or **annualized**? (The plan assumes annualized — 10% monthly would require much higher risk tolerance and different strategy mix)

2. **Risk appetite:** What's the maximum acceptable drawdown? The plan uses 8% — would you accept 15% if it meant higher expected returns?

3. **Trading pairs:** Should the agent trade only BTC/ETH/SOL, or expand to top 20-30 pairs? More pairs = more diversification but more complexity.

4. **Rebalancing frequency:** How often should the agent trade? Options:
   - Conservative: 2-5 trades/day (lower fees, less noise)
   - Moderate: 5-20 trades/day (balanced)
   - Active: 20-50 trades/day (more opportunities, more fees)

### Infrastructure

5. **Compute budget for training:** PPO training needs GPU for speed (though CPU works). Do we have GPU access? Training takes ~2h on GPU vs ~12h on CPU for 500K timesteps.

6. **OpenRouter API budget:** LLM calls cost money (Sonnet ~$3/$15 per M tokens). How much per day/month is acceptable? The agent currently uses LLM for signal generation — should we make it purely algorithmic (no LLM) for cost efficiency?

7. **How many concurrent agents?** Should we run multiple agents with different strategies and battle them, or focus on one optimal agent?

### Operations

8. **Monitoring preferences:** Do you use Grafana actively? Should we set up Slack/Telegram alerts for critical events (HALT triggers, large drawdowns)?

9. **Manual intervention policy:** Should the agent be fully autonomous, or should certain actions (like deploying a new model, changing risk parameters) require human approval?

10. **Data retention:** How long should we keep tick-level data? Trade history? Strategy signals? This affects storage costs.

### Development

11. **Development priority:** Should we focus on getting a basic trading loop running ASAP (even with simple strategies) and iterate, or build the full ensemble system first?

12. **Frontend needs:** The battle frontend is empty and the trading dashboard could show more agent-specific data. Is UI development a priority, or should we focus on the backend/agent first?

13. **Multiple exchanges:** You have CCXT with 110+ exchange support. Should we stay on Binance only, or train across multiple exchanges for robustness?

14. **Live trading (future):** Is the long-term goal to eventually trade real money? This affects how seriously we take slippage modeling and risk management.

---

## Appendix A: Complete File Inventory for Changes

### Phase 0 Files
- `agent/.env` — configure API keys, model, platform URL
- `src/database/models.py` — verify migration 018/019 models
- `agent/memory/redis_cache.py:get_cached()` — fix glob bug
- `agent/server.py` — wire IntentRouter, LogBatchWriter, working memory TTL
- `src/utils/exceptions.py` — add PermissionDenied as subclass of TradingPlatformError

### Phase 2 Files
- `agent/strategies/risk/sizing.py` — add KellyFractionalSizer, hybrid method
- `agent/strategies/risk/middleware.py` — add correlation check gate
- `agent/strategies/risk/risk_agent.py` — graduated drawdown scaling (new `scale_factor` field)
- `agent/strategies/risk/veto.py` — accept scale_factor from RiskAgent
- `agent/tools/sdk_tools.py` — add 6 new tools (limit, stop-loss, take-profit, cancel, cancel-all, open-orders)
- New: `agent/strategies/risk/recovery.py` — RecoveryManager class

### Phase 3 Files
- `agent/strategies/ensemble/meta_learner.py` — dynamic weights, regime-conditional modifiers
- `agent/tools/sdk_tools.py` — add get_ticker, get_pnl tools
- `agent/trading/signal_generator.py` — volume-weighted analysis, higher confidence threshold
- New: `agent/strategies/drift.py` — DriftDetector class
- New: `agent/trading/pair_selector.py` — PairSelector class
- `agent/server.py` — WebSocket integration

### Phase 4 Files
- New: `agent/strategies/retrain.py` — automated retraining orchestrator
- `agent/strategies/rl/runner.py` — walk-forward validation
- `agent/strategies/evolutionary/evolve.py` — walk-forward validation
- `src/tasks/celery_app.py` — new beat tasks (settle_decisions, retrain triggers)
- `agent/strategies/ensemble/validate.py` — Monte Carlo simulation

### Phase 5 Files
- `agent/tools/rest_tools.py` — add backtest comparison, decision analysis, risk profile tools
- `Frontend/src/components/battles/` — battle system UI (new)
- New: daily report generation task

### Phase 6 Files
- Docker/Prometheus config — scrape `:8001`
- `monitoring/dashboards/` — trading agent health dashboard
- `agent/conversation/context.py` — add caching layer

---

## Appendix B: Key Research Findings

### RL Best Practices (2024-2025)
- PPO + SAC ensemble outperforms either alone
- Sortino reward > Sharpe reward for steady income goals
- Curriculum learning improves PPO stability
- 8-feature observation space is optimal (OHLCV + RSI + MACD + BB width + volume ratio + position state)
- Retrain every 30 days on rolling 6-month window

### Risk Management (Industry Standard)
- Quarter-Kelly position sizing is the consensus for production trading
- ATR-based stops are more adaptive than fixed percentage stops
- Graduated drawdown response outperforms binary HALT
- Correlation-aware sizing prevents "diversification illusion"
- 90% of strategies that work in backtesting fail live — use 2x expected slippage

### Ensemble Methods
- Dynamic weight adjustment based on recent per-source Sharpe is state-of-the-art
- Regime-conditional weighting significantly improves ensemble performance
- Disagreement between sources is itself an informative signal (reduce exposure)
- Hierarchical ensembles (signal → allocation → execution) outperform flat voting

### Genetic Algorithms
- 12-15 parameters is the sweet spot for strategy genomes
- Multi-factor fitness with OOS component prevents overfitting
- Walk-forward efficiency > 50% indicates robustness
- Diversity pressure prevents premature convergence

---

## Appendix C: Trading Agent Skill File (`docs/skill.md`)

The agent's skill file should be updated to include:
- Full list of available tools (current 23 + planned 6 new = 29)
- Trading rules (the 8 key rules listed above)
- Risk parameters and their rationale
- Strategy descriptions and expected contributions
- Pair universe and allocation limits

This file is loaded by `ContextBuilder` on every reasoning cycle, so keeping it current is essential.

---

*Plan created: 2026-03-22*
*Status: Awaiting CTO answers to proceed with Phase 0*
*Next review: After CTO Q&A*
