---
name: Trading Agent Master Plan progress
description: Task completion status, test counts, and which CLAUDE.md files are affected by each phase group
type: project
---

As of 2026-03-22, the Trading Agent Master Plan task status is:

**25 of 37 tasks complete. Remaining 12 blocked on Docker/training.**

---

**Phase 0 Group A** (Tasks 01, 04–07) — COMPLETE
- Redis cache glob fix, LogBatchWriter singleton, IntentRouter handlers, PermissionDenied promotion, migrations validated
- 74 new tests

**Phase 1 branch starts** (Tasks 08, 10, 12) — COMPLETE
- Task 08: `regime/labeler.py` + `regime/classifier.py` — volume_ratio as 6th feature; 17 new tests, 189 total
- Task 10: `tradeready-gym/rewards/composite.py` + `rl/config.py` + `rl/train.py` — CompositeReward; 41 new tests
- Task 12: `evolutionary/evolve.py` + `evolutionary/config.py` + `evolutionary/battle_runner.py` — OOS composite fitness; 57 new tests

**Phase 2 independent** (Tasks 16–20) — COMPLETE
- Task 16: `risk/sizing.py` — KellyFractionalSizer, HybridSizer, SizingMethod; 67 new tests (93 total)
- Task 17: `risk/risk_agent.py` + `risk/veto.py` — DrawdownProfile, DrawdownTier, 3 presets; 67 new tests
- Task 18: `risk/middleware.py` — _check_correlation() gate step 5; 32 new tests (59 total)
- Task 19: `ensemble/circuit_breaker.py` + `ensemble/run.py` — StrategyCircuitBreaker, Redis-backed; 56 new tests
- Task 20: `agent/tools/sdk_tools.py` — 6 new tools (limit, stop-loss, take-profit, cancel, cancel-all, open-orders); 24 new tests (48 total)

**Phase 2 completion** (Tasks 21–22) — COMPLETE
- Task 21: `risk/recovery.py` — RecoveryManager (3-state FSM: RECOVERING→SCALING_UP→FULL), Redis persistence, ATR normalization; 53 new tests
- Task 22: Security review — 0 CRITICAL, 0 HIGH; 2 MEDIUM deferred; all risk gates confirmed fail-closed

**Phase 3 (Intelligence)** (Tasks 24, 26, 27) — COMPLETE
- Task 24: `agent/tools/sdk_tools.py` — get_ticker(), get_pnl() (15 total tools); volume confirmation filter in SignalGenerator; confidence threshold 0.55; 35 new tests
- Task 26: `agent/trading/pair_selector.py` — PairSelector (volume/spread filters, momentum tier, 1h Redis cache); 42 tests
- Task 27: `agent/trading/ws_manager.py` — WSManager (WS price buffer, order fills, REST fallback); 46 tests

**Phase 4 (Continuous Learning)** (Tasks 30, 32) — COMPLETE
- Task 30: `agent/tasks.py` — settle_agent_decisions Celery beat task (every 5 min); 16 tests
- Task 32: `agent/trading/journal.py` + `agent/memory/retrieval.py` — episodic + procedural memory save in generate_reflection(); retrieve_targeted() added; 29 tests

**Phase 5 (Platform Improvements)** (Tasks 33, 34, 35) — COMPLETE
- Task 33: `agent/tools/rest_tools.py` — 5 new REST tools (compare_backtests, get_best_backtest, get_equity_curve, analyze_decisions, update_risk_profile); 24 tests
- Task 34: `Frontend/src/components/battles/` — 9 components, 3 routes (/battles, /battles/[id], /battles/create), 2 hooks, 14 API functions, 15 types
- Task 35: `Frontend/src/components/agents/` — 4 new components (StrategyAttributionCard, EquityComparisonChart, ConfidenceHistogram, TradeMonitorTable), 2 hooks (useStrategyAttribution, useAgentDecisions)

**Phase 6 (Monitoring & Hardening)** (Tasks 36, 37) — COMPLETE
- Task 36: `monitoring/prometheus.yml` — added agent:8001 scrape job; Grafana auto-provisioning validated
- Task 37: Performance audit — 2 HIGH (ContextBuilder client churn, WSManager all-pairs subscription), 3 MEDIUM, 1 LOW identified (not yet fixed)

---

**Blocked tasks** (require Docker + training data):
02 (infra setup), 03 (data loading), 09 (regime training), 11 (PPO training), 13 (evolutionary run), 14 (ensemble weight opt), 15 (full pipeline backtest), 23 (agent provisioning), 25 (paper trading graduation), 28 (walk-forward validation), 29 (drift detection), 31 (anti-overfitting)

**Pending (not blocked):**
- ContextBuilder 30s portfolio cache (Task 37 HIGH follow-up)
- WSManager wire PairSelector output (Task 37 HIGH follow-up)
- Orphan detection for in-memory battle engines (Task 36 deferred)
- Task 3.1 dynamic ensemble weights (not yet started)
- Task 4.1 automated retraining pipeline (not yet started)
- Task 4.4 strategy attribution analytics wiring (not yet started)
- Task 4.6 anti-overfitting measures (not yet started)
- Task 5.4 training run integration into RL pipeline (not yet started)
- Task 5.6 platform feedback loop dashboard (not yet started)
- Tasks 6.4 operational dashboards + 6.5 daily report generation (not yet started)

---

**CLAUDE.md files most likely to need updates for future tasks:**
- `agent/strategies/risk/CLAUDE.md` — RecoveryManager now present
- `agent/trading/CLAUDE.md` — PairSelector, WSManager now present
- `agent/tools/CLAUDE.md` — 15 SDK tools, 5 new REST tools
- `Frontend/src/components/battles/CLAUDE.md` — now fully built (was "planned, not yet built")
- `agent/CLAUDE.md` (top-level) — test count now 1400+; new trading/ files

**Why:** Trading Agent Master Plan is the primary active development initiative. Goal is 10% steady annualized return on virtual USDT (Sharpe ≥ 1.5, max drawdown ≤ 8%).

**How to apply:** When tracking new task completions, check this memory first to know the current task sequence and which files are in scope for each phase.
