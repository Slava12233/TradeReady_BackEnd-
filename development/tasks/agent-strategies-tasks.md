# Agent Trading Strategies — Development Tasks

> **Goal:** Implement 5 agent strategies to achieve 10%+ portfolio improvement
> **Report:** See `development/agent-development/agent-strategies-report.md` for full research
> **Priority:** Start with Phase A (PPO RL) — gym infrastructure already exists

---

## Phase A: PPO Reinforcement Learning Portfolio Agent (Strategy 4)

> **Why first:** `tradeready-gym` package is already built with 7 envs, 4 rewards, 3 wrappers. Fastest path to a working trained agent.
> **Expected improvement:** +8-15% vs equal-weight baseline
> **Duration:** 4-7 days

### A1. Training Pipeline Setup
- [ ] Create `agent/strategies/rl/` directory structure
- [ ] Install stable-baselines3 + torch dependencies in `agent/pyproject.toml`
- [ ] Create `agent/strategies/rl/config.py` — hyperparameter config (PPO learning_rate, clip_range, n_steps, entropy_coef, LSTM layers)
- [ ] Create `agent/strategies/rl/train.py` — training script using `TradeReady-Portfolio-v0` env
- [ ] Configure asset universe: BTC, ETH, SOL, BNB, XRP (5 assets)
- [ ] Set observation features: OHLCV + RSI + MACD + Bollinger + ADX + ATR + portfolio state
- [ ] Set reward: `SharpeReward` + `DrawdownPenaltyReward` (weighted combination)
- [ ] Apply wrappers: `FeatureEngineeringWrapper` → `NormalizationWrapper`

### A2. Data Preparation
- [ ] Identify available historical data range via `GET /api/v1/market/data-range`
- [ ] Define train/val/test split (8/2/2 months ratio)
- [ ] Verify candle data coverage for all 5 assets across the full range
- [ ] Create data validation script that checks for gaps

### A3. Training Execution
- [ ] Train PPO agent for 500K timesteps on training period
- [ ] Enable `TrainingTracker` to report episodes to platform dashboard
- [ ] Monitor learning curve via `/api/v1/training/runs/{run_id}/learning-curve`
- [ ] Validate on validation set — target: Sharpe > 1.0
- [ ] If Sharpe < 1.0: tune hyperparameters (learning_rate, clip_range, entropy_coef)
- [ ] Train 3 agents with different random seeds for ensemble robustness

### A4. Evaluation & Deployment Bridge
- [ ] Test on held-out test period — accept if Sharpe > 0.8 AND max_drawdown < 15%
- [ ] Compare vs benchmarks: (a) equal-weight rebalancing, (b) buy-and-hold BTC, (c) buy-and-hold ETH
- [ ] Create `agent/strategies/rl/deploy.py` — bridge from trained model → portfolio weight orders
- [ ] Run trained model through backtest API to generate full metrics report
- [ ] Save trained model weights to `agent/strategies/rl/models/`
- [ ] Document results: actual Sharpe, ROI, max drawdown, win rate

### A5. Testing
- [ ] Unit tests for training config and pipeline
- [ ] Integration test: train for 1000 steps, verify model saves/loads correctly
- [ ] Backtest validation: trained model produces valid orders on unseen data

---

## Phase B: Evolutionary Battle-Driven Agent (Strategy 3)

> **Why second:** Battle system provides exact tournament selection mechanism. Optimizes 15-20 strategy parameters simultaneously.
> **Expected improvement:** +10-20% over random parameters
> **Duration:** 5-8 days
> **Depends on:** Battle system functional, strategy versioning working

### B1. Genetic Algorithm Core
- [ ] Create `agent/strategies/evolutionary/` directory
- [ ] Create `agent/strategies/evolutionary/genome.py` — strategy parameter genome:
  - RSI thresholds (oversold: 20-40, overbought: 60-80)
  - MACD sensitivity, ADX threshold
  - Stop-loss % (1-5%), take-profit % (2-10%), trailing stop (0.5-3%)
  - Position size (3-20%), max hold duration (10-200 candles)
  - Pair selection (subset of available pairs)
- [ ] Create `agent/strategies/evolutionary/operators.py`:
  - Tournament selection (top 20% auto-advance)
  - Single-point crossover of parameter vectors
  - Gaussian mutation (perturb 1-2 params by +/- 10%)
  - Genome-to-StrategyDefinition encoder/decoder
- [ ] Create `agent/strategies/evolutionary/population.py` — population manager (initialize, evolve, track generations)

### B2. Battle Integration
- [ ] Create `agent/strategies/evolutionary/battle_runner.py`:
  - Create N agents via `/api/v1/agents` (one per genome)
  - Create historical battle via `/api/v1/battles`
  - Add all agents as participants
  - Run battle to completion
  - Extract results via `RankingCalculator`
- [ ] Define fitness function: `sharpe_ratio - 0.5 * max_drawdown_pct`
- [ ] Eliminate agents with > 15% max drawdown regardless of returns
- [ ] Support battle presets: `historical_day` (rapid screening), `historical_month` (thorough)

### B3. Evolution Loop
- [ ] Create `agent/strategies/evolutionary/evolve.py` — main evolution script:
  - Initialize population (12 agents with random genomes)
  - Run 30 generations
  - Log best/avg/worst fitness per generation
  - Save champion genome each generation as strategy version
  - Detect convergence (fitness plateau for 5+ generations)
- [ ] Add out-of-sample validation: champion tested on held-out months
- [ ] Track full evolutionary history (every genome, every fitness score)

### B4. Analysis & Reporting
- [ ] Generate evolution curve plot (fitness vs generation)
- [ ] Compare champion vs random baseline agent in a final battle
- [ ] Use `get_replay_data()` to analyze champion's trading behavior
- [ ] Extract champion's optimal parameters as the "evolved strategy"
- [ ] Document: which parameters converged, which remained variable

### B5. Testing
- [ ] Unit tests for genome encoding/decoding
- [ ] Unit tests for crossover and mutation operators
- [ ] Integration test: run 3 generations with 4 agents (small scale)
- [ ] Verify strategy versions are properly created via API

---

## Phase C: Regime-Adaptive Technical Agent (Strategy 1)

> **Why third:** Adds a rule-based signal source uncorrelated with RL — essential for ensemble.
> **Expected improvement:** +5-8% vs static baseline
> **Duration:** 3-5 days
> **Depends on:** Strategy system + IndicatorEngine working

### C1. Regime Classifier
- [ ] Create `agent/strategies/regime/` directory
- [ ] Create `agent/strategies/regime/classifier.py`:
  - Feature extraction: ADX (trend), ATR (volatility), Bollinger width (compression)
  - 4 regimes: trending, mean-reverting, high-volatility, low-volatility
  - Train XGBoost/LightGBM classifier on labeled historical data
  - Label generation: automated labeling based on regime heuristics
- [ ] Create `agent/strategies/regime/labeler.py` — auto-label historical periods:
  - Trending: ADX > 25 AND directional
  - Mean-reverting: ADX < 20 AND price within Bollinger bands
  - High-volatility: ATR > 2x average
  - Low-volatility: ATR < 0.5x average

### C2. Strategy Versions
- [ ] Create 4 strategy definitions via `/api/v1/strategies`:
  - **Trending**: MACD crossover + ADX > 25 entry, trailing stop 2x ATR exit
  - **Mean-Reverting**: RSI oversold/overbought + Bollinger bounce, mean reversion exit
  - **High-Volatility**: Tight stops (1%), 3% position size, ATR-based exit
  - **Low-Volatility**: Bollinger squeeze breakout, 10% position size, momentum exit
- [ ] Version each strategy with proper `entry_conditions` and `exit_conditions`
- [ ] Backtest each strategy independently on matching regime periods

### C3. Regime Switching Logic
- [ ] Create `agent/strategies/regime/switcher.py`:
  - Load trained classifier
  - Every candle: classify current regime from last N candles
  - Select active strategy version based on regime
  - Minimum confidence threshold for regime switch (avoid flip-flopping)
  - Cooldown period after regime change (5 candles minimum)
- [ ] Wire into agent's decision loop

### C4. Validation
- [ ] Backtest regime-adaptive agent across 12 one-month periods
- [ ] Compare vs static momentum, static mean-reversion, and buy-and-hold
- [ ] Target: positive alpha in 8/12 months
- [ ] Run in historical battle vs Strategy 4 (PPO) agent

### C5. Testing
- [ ] Unit tests for regime labeler
- [ ] Unit tests for classifier (mock predictions)
- [ ] Integration test: full regime switch across backtest session

---

## Phase D: Risk Management Agent Overlay (Strategy 2 — Simplified)

> **Why fourth:** Adds portfolio-level risk management as a dedicated layer.
> **Expected improvement:** +3-5% from drawdown prevention
> **Duration:** 3-5 days
> **Depends on:** At least one signal strategy (Phase A or C) working

### D1. Risk Agent Core
- [ ] Create `agent/strategies/risk/` directory
- [ ] Create `agent/strategies/risk/risk_agent.py`:
  - Create dedicated agent via `/api/v1/agents` (advisory role, zero balance)
  - Monitor total portfolio exposure (sum positions / equity)
  - Check position correlation (avoid concentrated sector bets)
  - Enforce max drawdown rule: close weakest if drawdown > 5%
  - Adjust position sizing based on recent ATR

### D2. Veto Logic
- [ ] Create `agent/strategies/risk/veto.py`:
  - Input: proposed trade signal from any strategy
  - Check: portfolio heat (max 30% equity in positions)
  - Check: per-position limit (max 10% equity)
  - Check: sector concentration (max 2 positions same category)
  - Output: APPROVED, RESIZED (with new size), or VETOED (with reason)
- [ ] Create trade sizing adjustor (volatility-inverse sizing)

### D3. Integration
- [ ] Wire Risk Agent as middleware between signal generation and execution
- [ ] Test with Strategy 4 (PPO) agent as signal source
- [ ] Verify Risk Agent vetoes trigger on synthetic high-risk scenarios
- [ ] Measure drawdown reduction vs unprotected strategy

### D4. Testing
- [ ] Unit tests for veto logic (all 3 check types)
- [ ] Integration test: Risk Agent reduces position during drawdown
- [ ] Compare protected vs unprotected agent in historical battle

---

## Phase E: Hybrid Ensemble Integration (Strategy 5)

> **Why last:** Combines all components for maximum robustness.
> **Expected improvement:** +18-35% cumulative
> **Duration:** 3-5 days (incremental — components already exist from Phases A-D)
> **Depends on:** Phases A, C, D complete (Phase B is optional but recommended)

### E1. Meta-Learner
- [ ] Create `agent/strategies/ensemble/` directory
- [ ] Create `agent/strategies/ensemble/meta_learner.py`:
  - Collect signals from Strategy 1 (technical), Strategy 4 (RL), Strategy 3 (evolved)
  - Each signal: {BUY, SELL, HOLD} + confidence [0, 1]
  - Weighted vote: `final = sum(signal_i * confidence_i * weight_i)`
  - Confidence threshold: only act when combined > 0.6
  - Disagreement detection: all disagree = reduce exposure to cash

### E2. Weight Optimization
- [ ] Create `agent/strategies/ensemble/optimize_weights.py`:
  - Use battle system to test different weight configurations
  - Create 8-12 ensemble variants with different weight sets
  - Run historical battle to find optimal combination
  - Out-of-sample validation of winning weights

### E3. Full Pipeline
- [ ] Create `agent/strategies/ensemble/run.py` — main ensemble runner:
  - Initialize all 3 signal sources
  - For each candle/step:
    1. Get technical signal (Strategy 1)
    2. Get RL signal (Strategy 4)
    3. Get evolved signal (Strategy 3, if available)
    4. Combine via meta-learner
    5. Apply Risk Agent overlay (Strategy 2)
    6. Execute final orders
  - Track which signal sources contributed to each trade

### E4. Validation
- [ ] Run ensemble vs each individual strategy in historical battle
- [ ] Target: ensemble Sharpe > max(individual Sharpe ratios)
- [ ] Test on 3 held-out months (out-of-sample)
- [ ] Measure signal agreement rate and its correlation with trade success
- [ ] Generate final comprehensive report

### E5. Testing
- [ ] Unit tests for meta-learner voting logic
- [ ] Unit tests for disagreement detection
- [ ] Integration test: full ensemble pipeline on short backtest
- [ ] Verify all 3 signal sources run without interference

---

## Milestones & Success Criteria

| Milestone | Target | How to Measure |
|-----------|--------|----------------|
| Phase A complete | Trained PPO with Sharpe > 1.0 | `TrainingTracker` learning curve converged |
| Phase B complete | Evolved champion beats random by 15%+ | Historical battle results |
| Phase C complete | Regime agent beats static strategy in 8/12 months | 12 backtests |
| Phase D complete | Drawdown reduced by 30%+ | Compare protected vs unprotected |
| Phase E complete | Ensemble Sharpe > best individual | Final historical battle |
| **10% target** | **Any single phase achieves +10% ROI** | **Backtest on held-out data** |

---

## Dependencies & Prerequisites

| Requirement | Status | Notes |
|-------------|--------|-------|
| Platform running (API + DB + Redis) | Required | `docker compose up -d` or `uvicorn` |
| Historical candle data loaded | Required | Run `scripts/backfill_history.py` |
| `tradeready-gym` package | Built | 7 envs, 4 rewards, 3 wrappers |
| Battle system functional | Built | Historical + live modes |
| Strategy system functional | Built | CRUD, versioning, testing, indicators |
| Agent system functional | Built | Multi-agent with isolated wallets |
| `stable-baselines3` | To install | Phase A dependency |
| `xgboost` or `lightgbm` | To install | Phase C dependency |
| OpenRouter API key | Required | For LLM-driven workflows (Phases C, D) |

---

## File Structure (Planned)

```
agent/strategies/                    # NEW — strategy implementations
├── __init__.py
├── rl/                              # Phase A: PPO RL Agent
│   ├── __init__.py
│   ├── config.py                    # Hyperparameters
│   ├── train.py                     # Training script
│   ├── deploy.py                    # Model → orders bridge
│   └── models/                      # Saved model weights
│       └── .gitkeep
├── evolutionary/                    # Phase B: Genetic Algorithm
│   ├── __init__.py
│   ├── genome.py                    # Parameter genome
│   ├── operators.py                 # Selection, crossover, mutation
│   ├── population.py                # Population manager
│   ├── battle_runner.py             # Battle integration
│   └── evolve.py                    # Main evolution loop
├── regime/                          # Phase C: Regime-Adaptive
│   ├── __init__.py
│   ├── classifier.py                # Regime classifier
│   ├── labeler.py                   # Auto-labeling
│   └── switcher.py                  # Strategy version switching
├── risk/                            # Phase D: Risk Agent
│   ├── __init__.py
│   ├── risk_agent.py                # Risk monitoring
│   └── veto.py                      # Veto/resize logic
└── ensemble/                        # Phase E: Hybrid Ensemble
    ├── __init__.py
    ├── meta_learner.py              # Signal combination
    ├── optimize_weights.py          # Battle-based weight tuning
    └── run.py                       # Full ensemble pipeline
```
