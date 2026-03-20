# Plan: From Code to Running Agent & Training

<!-- Created: 2026-03-20 -->

> Everything needed to go from "29 tasks complete" to "agent trading on the platform with trained models."

---

## Current State

**What exists (code-complete, not yet operational):**
- `agent/` package — 4 workflows (smoke, trade, backtest, strategy), pip-installable
- `agent/strategies/` — 5 strategies (PPO RL, evolutionary, regime, risk, ensemble), ~750 tests
- `tradeready-gym/` — Gymnasium environments for RL training
- `sdk/` — Python SDK (sync + async + WebSocket)
- Platform backend — 86+ REST endpoints, backtest engine, battle system, strategy registry

**What's missing to actually run:**
1. ML dependencies not declared in `agent/pyproject.toml`
2. No `agent/.env` file (only `.env.example`)
3. Platform services not running (Docker)
4. No historical data loaded
5. No trained models exist yet
6. Agent not containerized
7. Performance fixes not applied (8 HIGH findings)
8. Security fixes not applied (3 HIGH findings)

---

## Phase 1: Fix Dependencies & Package Config

**Goal:** `pip install -e "agent/[ml]"` installs everything needed.

### 1.1 Add ML optional deps to `agent/pyproject.toml`

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
]
ml = [
    "stable-baselines3[extra]>=2.3",
    "torch>=2.2",
    "xgboost>=2.0",
    "scikit-learn>=1.4",
    "joblib>=1.3",
    "numpy>=1.26",
    "pandas>=2.2",
]
all = [
    "tradeready-test-agent[dev,ml]",
]
```

### 1.2 Add `tradeready-gym` as a dependency

Add to `[project.dependencies]`:
```toml
"tradeready-gym",  # local: pip install -e tradeready-gym/
```

### 1.3 Install everything

```bash
pip install -e sdk/
pip install -e tradeready-gym/
pip install -e "agent/[all]"
```

### 1.4 Verify imports

```bash
python -c "from agent.strategies.rl.config import RLConfig; print('RL OK')"
python -c "from agent.strategies.regime.classifier import RegimeClassifier; print('Regime OK')"
python -c "from agent.strategies.ensemble.meta_learner import MetaLearner; print('Ensemble OK')"
python -c "from stable_baselines3 import PPO; print('SB3 OK')"
python -c "import torch; print(f'Torch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
```

---

## Phase 2: Platform Infrastructure

**Goal:** All backend services healthy and accessible.

### 2.1 Start Docker services

```bash
docker compose up -d
# Wait for health checks
docker compose ps  # all should show "healthy"
```

Services needed: `timescaledb`, `redis`, `api`, `celery`, `celery-beat`, `ingestion`

### 2.2 Run database migrations

```bash
alembic upgrade head
```

### 2.3 Seed exchange pairs

```bash
python scripts/seed_pairs.py
```

### 2.4 Create a test account + agent

```bash
# Via API or use existing credentials
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "agent_trainer", "password": "secure_password_here"}'
```

Save the returned `api_key` and `api_secret`.

### 2.5 Verify platform health

```bash
curl http://localhost:8000/api/v1/health
# Should return {"status": "healthy", ...}
```

---

## Phase 3: Load Historical Data

**Goal:** 12+ months of 1h candle data for BTC, ETH, SOL, BNB, XRP.

### 3.1 Backfill candles

```bash
# This takes 10-30 minutes depending on API rate limits
python scripts/backfill_history.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
  --interval 1h \
  --start 2024-01-01
```

### 3.2 Validate data coverage

```bash
python -m agent.strategies.rl.data_prep \
  --base-url http://localhost:8000 \
  --api-key ak_live_YOUR_KEY \
  --assets BTCUSDT,ETHUSDT,SOLUSDT \
  --interval 1h \
  --min-coverage 95
```

Should show 95%+ coverage for train/val/test splits. Exit code 0 = ready.

---

## Phase 4: Configure Agent Environment

**Goal:** `agent/.env` fully configured.

### 4.1 Create agent/.env

```bash
cp agent/.env.example agent/.env
```

### 4.2 Fill in credentials

```env
# Required
OPENROUTER_API_KEY=sk-or-v1-YOUR_KEY
PLATFORM_BASE_URL=http://localhost:8000
PLATFORM_API_KEY=ak_live_YOUR_AGENT_KEY
PLATFORM_API_SECRET=sk_live_YOUR_AGENT_SECRET

# LLM models
AGENT_MODEL=openrouter:anthropic/claude-sonnet-4-5
AGENT_CHEAP_MODEL=openrouter:google/gemini-2.0-flash-001
```

### 4.3 Run smoke test

```bash
python -m agent.main smoke
```

Should complete 10/10 steps with `status: pass`. This validates:
- SDK connectivity
- Price data flowing
- Order execution working
- Platform health endpoint responding

---

## Phase 5: Run Agent Workflows (V1 Agent)

**Goal:** Validate the V1 testing agent works end-to-end.

### 5.1 Trading workflow

```bash
python -m agent.main trade
```

LLM analyzes market → generates signal → executes trade → closes position → reports.

### 5.2 Backtest workflow

```bash
python -m agent.main backtest
```

Creates 7-day MA-crossover backtest, runs trading loop, LLM analyzes results.

### 5.3 Strategy workflow

```bash
python -m agent.main strategy
```

Creates V1 strategy → tests → LLM reviews → builds V2 → tests → compares.

### 5.4 Full validation

```bash
python -m agent.main all
# Output: agent/reports/platform-validation-YYYYMMDD_HHMMSS.json
```

---

## Phase 6: Train the Regime Classifier (Strategy 3)

**Goal:** Trained XGBoost/RF model for market regime detection.

**Why first:** No RL training needed, fast (<2 min), provides the regime signal for the ensemble.

### 6.1 Train classifier

```bash
python -m agent.strategies.regime.classifier \
  --train \
  --data-url http://localhost:8000
```

Fetches 12 months of BTC 1h candles, labels regimes, trains XGBoost (or RF fallback), saves model to `agent/strategies/regime/models/regime_classifier.joblib`.

### 6.2 Verify accuracy

Output should show:
- Accuracy > 70%
- Confusion matrix for 4 regimes
- Model saved to disk

### 6.3 Test regime switching demo

```bash
python -m agent.strategies.regime.switcher --demo
```

---

## Phase 7: Train PPO Agent (Strategy 1)

**Goal:** 3 trained PPO models with Sharpe > 1.0.

**Estimated time:** 1-2 hours with 4 parallel envs, per seed.

### 7.1 Run training (seed 42)

```bash
python -m agent.strategies.rl.runner \
  --seeds 42 \
  --timesteps 500000 \
  --target-sharpe 1.0 \
  --api-key ak_live_YOUR_KEY \
  --base-url http://localhost:8000
```

### 7.2 If Sharpe < 1.0, enable auto-tuning

```bash
python -m agent.strategies.rl.runner \
  --seeds 42 \
  --timesteps 500000 \
  --target-sharpe 1.0 \
  --tune \
  --max-tune-attempts 3
```

Tuning adjusts: ent_coef → 0.05, learning_rate → 1e-4, timesteps → 750K.

### 7.3 Train remaining seeds

```bash
python -m agent.strategies.rl.runner \
  --seeds 42,123,456 \
  --timesteps 500000
```

### 7.4 Evaluate on held-out test data

```bash
python -m agent.strategies.rl.evaluate \
  --model-dir agent/strategies/rl/models/
```

Compares PPO vs equal-weight vs BTC-hold vs ETH-hold. Report saved to `agent/reports/`.

### 7.5 Stop-early check (per run-tasks.md)

> If PPO Sharpe > 1.0 and ROI > 10% on out-of-sample → consider this sufficient.

---

## Phase 8: Run Evolutionary Training (Strategy 2)

**Goal:** Evolved champion genome that outperforms random strategies.

**Estimated time:** 30 gen × ~5 min/battle = ~2.5 hours.

**Prerequisite:** Verify battle historical mode works:
```bash
# Quick test — create a 2-agent historical battle
curl -X POST http://localhost:8000/api/v1/battles \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "mode": "historical"}'
```

If this returns 500, the battle historical mode bug (noted 2026-03-18) needs fixing first.

### 8.1 Run evolution (small test first)

```bash
python -m agent.strategies.evolutionary.evolve \
  --generations 3 \
  --pop-size 4 \
  --convergence-threshold 2
```

### 8.2 Run full evolution

```bash
python -m agent.strategies.evolutionary.evolve \
  --generations 30 \
  --pop-size 12 \
  --seed 42
```

Output:
- `agent/strategies/evolutionary/results/evolution_log.json`
- `agent/strategies/evolutionary/results/champion.json`
- Champion saved as platform strategy version

### 8.3 Analyze results

```bash
python -m agent.strategies.evolutionary.analyze \
  --log-path agent/strategies/evolutionary/results/evolution_log.json
```

Report saved to `agent/reports/evolution-report-*.json`.

---

## Phase 9: Validate Individual Strategies

**Goal:** Each strategy tested independently before ensemble.

### 9.1 Regime validation (12-month backtests)

```bash
python -m agent.strategies.regime.validate \
  --base-url http://localhost:8000 \
  --api-key ak_live_YOUR_KEY \
  --months 12
```

### 9.2 PPO deploy bridge test (backtest mode)

```bash
python -m agent.strategies.rl.deploy \
  --model agent/strategies/rl/models/ppo_seed42.zip \
  --mode backtest \
  --session-id SESSION_FROM_API
```

---

## Phase 10: Optimize Ensemble Weights (Strategy 5)

**Goal:** Find optimal weights for combining 3 signals.

### 10.1 Run weight optimization

```bash
python -m agent.strategies.ensemble.optimize_weights \
  --base-url http://localhost:8000 \
  --api-key ak_live_YOUR_KEY
```

Tests 12 weight configs (4 fixed + 8 random), ranks by Sharpe.

### 10.2 Run ensemble validation

```bash
python -m agent.strategies.ensemble.validate \
  --base-url http://localhost:8000 \
  --api-key ak_live_YOUR_KEY \
  --periods 3
```

Compares Ensemble vs PPO-only vs Evolved-only vs Regime-only.

### 10.3 Run full ensemble pipeline

```bash
python -m agent.strategies.ensemble.run \
  --mode backtest \
  --base-url http://localhost:8000 \
  --api-key ak_live_YOUR_KEY
```

---

## Phase 11: Apply Performance & Security Fixes

**Goal:** Address HIGH findings before production use.

### 11.1 Performance fixes (8 HIGH)

| # | Fix | Files | Effort |
|---|-----|-------|--------|
| 1 | `asyncio.gather` for agent setup/reset/assign | `battle_runner.py` | Low |
| 2 | `asyncio.gather` for participant registration | `battle_runner.py` | Low |
| 3 | `asyncio.gather` for data validation | `data_prep.py` | Low |
| 4 | `asyncio.gather` for multi-symbol candle fetch | `run.py`, `deploy.py` | Low |
| 5 | `run_in_executor` for `model.predict()` | `deploy.py`, `run.py` | Low |
| 6 | `run_in_executor` for classifier `.fit()` | `run.py` | Low |
| 7 | Cache regime features by candle timestamp | `switcher.py` | Low |
| 8 | Cap `_step_history` and `regime_history` with `deque(maxlen=500)` | `run.py`, `switcher.py` | Low |

### 11.2 Security fixes (3 HIGH)

| # | Fix | Approach |
|---|-----|----------|
| 1 | Pickle deserialization (SB3 `.zip`) | Add checksum verification before `PPO.load()` |
| 2 | Joblib deserialization (regime model) | Add checksum verification before `joblib.load()` |
| 3 | CLI `--api-key` exposure | Remove `--api-key` args, require env var or `.env` only |

---

## Phase 12: Dockerize the Agent (Optional)

**Goal:** Agent runs as a Docker service alongside the platform.

### 12.1 Create `agent/Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY sdk/ /app/sdk/
COPY tradeready-gym/ /app/tradeready-gym/
COPY agent/ /app/agent/
RUN pip install -e /app/sdk/ && \
    pip install -e /app/tradeready-gym/ && \
    pip install -e "/app/agent/[all]"
WORKDIR /app/agent
CMD ["python", "-m", "agent.main", "all"]
```

### 12.2 Add to docker-compose.yml

```yaml
agent:
  build:
    context: .
    dockerfile: agent/Dockerfile
  depends_on:
    api:
      condition: service_healthy
  env_file: agent/.env
  volumes:
    - ./agent/reports:/app/agent/reports
    - ./agent/strategies/rl/models:/app/agent/strategies/rl/models
    - ./agent/strategies/regime/models:/app/agent/strategies/regime/models
```

---

## Phase 13: Run All Tests

**Goal:** Verify everything works together.

### 13.1 Platform tests

```bash
pytest tests/unit/ -v --tb=short
pytest tests/integration/ -v --tb=short
```

### 13.2 Agent tests

```bash
cd agent && pytest tests/ -v --tb=short
# Expected: ~900+ tests passing
```

### 13.3 Gym tests

```bash
cd tradeready-gym && pytest tests/ -v --tb=short
```

---

## Execution Order (Quick Reference)

```
Phase 1: Fix deps          ← 10 min (edit pyproject.toml, pip install)
Phase 2: Start platform    ← 5 min (docker compose up, migrations, seed)
Phase 3: Load data         ← 30 min (backfill 12 months of candles)
Phase 4: Configure agent   ← 5 min (create .env, smoke test)
Phase 5: V1 agent test     ← 15 min (smoke + trade + backtest + strategy)
Phase 6: Train regime      ← 5 min (XGBoost classifier)
Phase 7: Train PPO         ← 2-6 hours (500K steps × 3 seeds)
Phase 8: Run evolution     ← 2-3 hours (30 gen × 12 agents)
Phase 9: Validate          ← 30 min (regime backtests, PPO deploy test)
Phase 10: Ensemble         ← 1 hour (weight optimization + validation)
Phase 11: Fix issues       ← 2 hours (perf + security)
Phase 12: Dockerize        ← 1 hour (optional)
Phase 13: Full test suite  ← 15 min
```

**Total estimated wall-clock: ~8-14 hours** (mostly training time).

**Phases 1-5 can be done in under 1 hour** to get the V1 agent running.

---

## Known Risks & Blockers

| Risk | Impact | Mitigation |
|------|--------|------------|
| Battle historical mode 500 error (noted 2026-03-18) | Blocks Phase 8 (evolution) | Test early in Phase 2; fix if broken |
| GPU not available for PyTorch | PPO training ~5x slower on CPU | SB3 works on CPU; just takes longer |
| Insufficient candle data coverage | Training fails mid-run | Phase 3 validation catches this |
| OpenRouter rate limits | LLM-based workflows throttled | Use `--model` to switch providers |
| Platform API rate limits (429) | Training envs overwhelmed | Reduce `n_envs` from 4 to 2 |

---

## Success Criteria

- [ ] Smoke test passes (10/10 steps)
- [ ] V1 agent completes all 4 workflows
- [ ] Regime classifier accuracy > 70%
- [ ] At least 1 PPO model with Sharpe > 1.0
- [ ] Evolution champion improves over generations
- [ ] Ensemble outperforms individual strategies in 2/3 test periods
- [ ] All ~900 agent tests pass
- [ ] No CRITICAL security findings
