---
type: plan
tags:
  - v0.0.3
  - deployment
  - rl-training
  - frontend
  - backup
  - onboarding
  - recommendations
  - c-level
date: 2026-04-08
status: active
audience: development team
source: "[[C-level_reports/report-2026-04-08]]"
---

# Recommendations Execution Plan

> Detailed execution plan for the 5 recommendations from the C-level executive report dated 2026-04-08. Each recommendation includes objective, prerequisites, numbered steps, verification, effort estimate, agent assignment, dependencies, and risk analysis.

**Source:** `development/C-level_reports/report-2026-04-08.md` (Section 11)
**Context:** `development/v0.0.3-next-steps.md`, `development/context.md`, `development/platform-endgame-readiness-plan.md`

---

## Execution Timeline

```
Day 0 (Now)        Day 1               Day 2-3             Day 4-7            Day 8-14
    |                  |                   |                   |                   |
    v                  v                   v                   v                   v
[R1: Deploy V.0.0.3] -+                                                          
    |                  |                                                          
    +-- [R4: DB Backups] (parallel with R1 prep, activate post-deploy)            
    |                  |                                                          
    +--- (R1 done) ---+-> [R3: Frontend Integration - 4 components] ------------>
                       |                                                          
                       +-> [R2: RL Model Training] ----------------------------->
                       |                                                          
                       +-> [R5: Onboarding Docs] ------>                          
```

### Parallel Execution Groups

| Group | Recommendations | Constraint |
|-------|----------------|------------|
| **A** (Day 0-1) | R1 (Deploy) + R4 (Backup script) | R4 script can be written while R1 deploys; cron activates after R1 |
| **B** (Day 1-7) | R2 (RL Training) + R3 (Frontend) + R5 (Docs) | All three are independent; start after R1 completes |

### Dependency Graph (Critical Path)

```
R1: Deploy V.0.0.3 ──────────────────────> R3: Frontend Integration
        │                                         (needs live API)
        │
        ├──> R2: RL Model Training (needs DB with candle data + migration 023)
        │
        ├──> R4: Scheduled Backups (cron activated post-deploy)
        │
        └──> R5: Onboarding Docs (needs live platform for screenshot/validation)

Critical path: R1 → R3 (longest downstream dependency)
```

### Quick Wins (Under 1 Hour Each)

| Quick Win | Est. Time | Part Of |
|-----------|-----------|---------|
| Write the `scripts/backup_db.sh` script | 20 min | R4 |
| Add backup cron to `docker-compose.yml` or host crontab | 15 min | R4 |
| Add webhook/indicator/strategy-compare/batch API functions to `Frontend/src/lib/api-client.ts` | 30 min | R3 |
| Add webhook/indicator/strategy-compare/batch TypeScript types to `Frontend/src/lib/types.ts` | 20 min | R3 |
| Trigger deploy by merging to `main` (CI/CD handles the rest) | 5 min | R1 |

---

## R1: Deploy V.0.0.3 to Production

### Objective

Apply migration 023 (webhook_subscriptions table), deploy all V.0.0.3 code (7 endgame improvements + 9 security fixes), and verify the new endpoints are live. Success = `/health` returns OK, migration head is 023, all new endpoints respond correctly in Swagger UI.

### Prerequisites

- [x] All 9 security findings resolved (re-audit verdict: PASS)
- [x] Migration 023 validated by `migration-helper` agent (production-safe, additive-only)
- [x] 5,132+ tests passing
- [x] Ruff lint: 0 new errors
- [x] Code on `main` branch (or ready to merge)

### Steps

**1. Pre-flight validation (local)**

```bash
# Verify migration chain is clean
alembic history | head -5
# Expected: 023 (head), 022, 021, ...

# Run the full test suite one final time
pytest tests/unit/ -x -q
pytest tests/integration/ -x -q

# Lint and type check
ruff check src/ tests/
mypy src/
```

**Agent:** `deploy-checker`

**2. Trigger deployment**

Push to `main` (if not already there) to trigger the GitHub Actions deploy workflow at `.github/workflows/deploy.yml`. The workflow automatically:
- Runs lint + test job
- SSHs into the production server
- Takes a `pg_dump` backup (excluding hypertable data)
- Pulls latest `main`
- Builds Docker images for `api`, `ingestion`, `celery`
- Runs `alembic upgrade head` (applies migration 023)
- Rolling restart of all app services
- Health check with automatic rollback on failure

```bash
git push origin main
```

If the branch is already `main` and up to date, the deploy was triggered on the last push. Check GitHub Actions for status.

**3. Monitor deployment**

Watch the GitHub Actions deploy job. Key checkpoints:

| Checkpoint | Expected |
|------------|----------|
| Lint & Test | All pass |
| `pg_dump` backup | Saved to `~/backups/pre-deploy-YYYYMMDD-HHMMSS.sql.gz` |
| `alembic upgrade head` | Applies 023 (022 -> 023) |
| Health check | `curl http://localhost:8000/health` returns `{"status": "ok"}` |

**4. Post-deploy verification**

```bash
# SSH into production server
ssh $SERVER_USER@$SERVER_HOST

# Verify migration head
docker compose exec api alembic current
# Expected output: 023 (head)

# Verify webhook_subscriptions table exists
docker compose exec timescaledb psql -U $POSTGRES_USER -d $POSTGRES_DB \
  -c "SELECT count(*) FROM webhook_subscriptions;"
# Expected: 0 (empty table, no error)

# Verify new API endpoints via curl
# Indicators endpoint (public, no auth needed)
curl -s http://localhost:8000/api/v1/market/indicators/BTCUSDT | head -c 200

# Webhooks endpoint (requires auth)
curl -s -H "X-API-Key: ak_live_YOUR_KEY" \
  http://localhost:8000/api/v1/webhooks | head -c 200

# Deflated Sharpe endpoint (public)
curl -s -X POST http://localhost:8000/api/v1/metrics/deflated-sharpe \
  -H "Content-Type: application/json" \
  -d '{"returns": [0.01, -0.005, 0.02, 0.003], "num_trials": 100}' | head -c 200

# Strategy comparison endpoint (requires auth)
curl -s -X POST -H "X-API-Key: ak_live_YOUR_KEY" \
  -H "Content-Type: application/json" \
  http://localhost:8000/api/v1/strategies/compare \
  -d '{"strategy_ids": []}' | head -c 200

# Batch step fast endpoint (requires auth + active backtest session)
curl -s http://localhost:8000/docs | grep -c "batch"
# Expected: > 0 (appears in Swagger docs)
```

**5. Open Swagger UI and visually confirm**

Navigate to `http://$SERVER_HOST:8000/docs` and verify these endpoint groups appear:
- `POST /api/v1/backtest/{session_id}/step/batch/fast`
- `GET /api/v1/market/indicators/{symbol}`
- `GET /api/v1/market/indicators/available`
- `POST /api/v1/metrics/deflated-sharpe`
- `POST /api/v1/strategies/compare`
- `GET /api/v1/webhooks` (CRUD endpoints)

### Verification Checklist

- [ ] GitHub Actions deploy job: GREEN
- [ ] `alembic current` shows `023`
- [ ] `webhook_subscriptions` table exists and is queryable
- [ ] `/health` returns `{"status": "ok"}`
- [ ] All 6 new endpoint groups respond (non-5xx)
- [ ] Swagger UI shows all new endpoints

### Estimated Effort

- Automated deploy: ~15 minutes (CI/CD handles it)
- Manual verification: ~30 minutes
- **Total: ~45 minutes**

### Agent Assignment

- `deploy-checker` — pre-flight validation
- CI/CD pipeline — automated deploy
- `e2e-tester` — post-deploy endpoint verification

### Dependencies

- None (R1 is the root of the dependency graph)

### Risk

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Migration 023 fails on production | LOW | LOW | Migration is purely additive (CREATE TABLE). Rollback: `alembic downgrade 022` drops the table cleanly. CI/CD has automatic rollback on health check failure. |
| Health check fails after deploy | MEDIUM | LOW | Deploy workflow auto-rolls back to previous commit + migration revision. Pre-deploy backup exists. |
| New endpoints have runtime errors | LOW | LOW | All endpoints have dedicated test suites (419 new tests). Post-deploy curl verification catches issues immediately. |

---

## R2: Start RL Model Training

### Objective

Train a PPO agent on BTC historical price data using the headless gym environment with batch stepping. Success = a trained model file (`.zip`) that produces trading signals with positive Sharpe Ratio on out-of-sample data, validating the entire RL pipeline end-to-end.

### Prerequisites

- [x] `TradeReady-BTC-Headless-v0` environment registered and tested (52 tests passing)
- [x] `CompositeReward` function implemented (0.4 sortino + 0.3 pnl + 0.2 activity + 0.1 drawdown)
- [x] `BatchStepWrapper` implemented (reduces step count by N)
- [x] `NormalizationWrapper` implemented (online z-score)
- [x] `sdk/examples/rl_training.py` reference script exists
- [ ] **R1 complete** — production DB has migration 023 applied
- [ ] Historical candle data available in `candles_backfill` table (run `scripts/backfill_history.py` if missing)
- [ ] `stable-baselines3>=2.0` installed in training environment

### Steps

**1. Verify training data availability**

```bash
# Check candle data exists for BTC
docker compose exec timescaledb psql -U $POSTGRES_USER -d $POSTGRES_DB \
  -c "SELECT count(*), min(bucket), max(bucket) FROM candles_backfill WHERE symbol = 'BTCUSDT' AND interval = '1h';"

# If insufficient data, backfill:
python scripts/backfill_history.py --symbols BTCUSDT --hourly --resume
python scripts/backfill_history.py --symbols BTCUSDT --daily --resume
```

Need at minimum 6 months of hourly candles (2024-07-01 to 2025-01-01) for training + 2 months (2025-01-01 to 2025-03-01) for out-of-sample evaluation.

**Agent:** `ml-engineer`

**2. Set up the training environment**

```bash
# Install dependencies (if not already)
pip install -e tradeready-gym/
pip install -e sdk/
pip install stable-baselines3>=2.0 tensorboard

# Verify gym registration
python -c "import gymnasium as gym; import tradeready_gym; print(gym.make('TradeReady-BTC-Headless-v0', db_url='postgresql+asyncpg://...').observation_space)"
```

**3. Create the training script**

File: `scripts/train_ppo_btc.py`

This script should use the headless environment (no HTTP overhead) with batch stepping. Key parameters:

```python
# Training configuration
TRAIN_CONFIG = {
    "env_id": "TradeReady-BTC-Headless-v0",
    "symbol": "BTCUSDT",
    "db_url": os.environ["DATABASE_URL"],  # postgresql+asyncpg://...
    
    # Time windows
    "train_start": "2024-07-01T00:00:00Z",
    "train_end": "2025-01-01T00:00:00Z",       # 6 months training
    "eval_start": "2025-01-01T00:00:00Z",
    "eval_end": "2025-03-01T00:00:00Z",         # 2 months OOS eval
    
    # PPO hyperparameters (CPU-friendly)
    "total_timesteps": 500_000,
    "learning_rate": 3e-4,
    "n_steps": 2048,
    "batch_size": 64,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    
    # Environment config
    "timeframe": "1h",
    "lookback_window": 30,
    "starting_balance": 10000.0,
    "episode_length": 720,           # 30 days of hourly candles
    "reward_function": "composite",  # CompositeReward
    
    # Wrappers
    "batch_hold_steps": 5,           # Hold each action for 5 candles
    "normalize": True,               # Online z-score normalization
    
    # Output
    "model_save_path": "models/ppo_btc_v1",
    "tensorboard_log": "logs/ppo_btc_v1",
}
```

The script must:
1. Create the headless environment with `db_url` kwarg
2. Apply `BatchStepWrapper(n_steps=5)` + `NormalizationWrapper`
3. Wrap with SB3 `Monitor` for episode logging
4. Instantiate PPO with `MlpPolicy` and above hyperparameters
5. Train for 500K timesteps with TensorBoard logging
6. Save the model to `models/ppo_btc_v1.zip`
7. Run OOS evaluation (2025-01-01 to 2025-03-01) for 10 episodes
8. Print summary: avg reward, Sharpe ratio, max drawdown, win rate
9. Validate with Deflated Sharpe Ratio (DSR > 0.05 to pass)

**Agent:** `ml-engineer`

**4. Run training (CPU-only, ~$0 cost)**

```bash
# Set environment variables
export DATABASE_URL="postgresql+asyncpg://agentexchange:$POSTGRES_PASSWORD@localhost:5432/agentexchange"
export PYTHONPATH="."

# Run training with TensorBoard logging
python scripts/train_ppo_btc.py 2>&1 | tee logs/training_output.log

# Monitor progress in another terminal
tensorboard --logdir logs/ppo_btc_v1 --port 6006
```

Estimated training time: 2-6 hours on CPU (500K timesteps with headless env + batch stepping).

**Agent:** `ml-engineer`

**5. Evaluate on out-of-sample data**

The training script handles this in step 7 above, but for a more thorough evaluation:

```bash
# Run standalone evaluation
python -c "
from stable_baselines3 import PPO
import gymnasium as gym
import tradeready_gym
from tradeready_gym.wrappers.normalization import NormalizationWrapper
from tradeready_gym.wrappers.batch_step import BatchStepWrapper
from tradeready_gym.rewards.composite import CompositeReward

env = gym.make('TradeReady-BTC-Headless-v0',
    db_url='$DATABASE_URL',
    start_time='2025-01-01T00:00:00Z',
    end_time='2025-03-01T00:00:00Z',
    reward_function=CompositeReward(),
    track_training=False,
)
env = BatchStepWrapper(env, n_steps=5)
env = NormalizationWrapper(env)

model = PPO.load('models/ppo_btc_v1')
obs, _ = env.reset()
total_reward = 0
while True:
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, done, trunc, info = env.step(action)
    total_reward += reward
    if done or trunc:
        break
print(f'OOS reward: {total_reward}, Info: {info}')
env.close()
"
```

**6. Validate with Deflated Sharpe Ratio**

```bash
# Use the platform API to compute DSR
curl -s -X POST http://localhost:8000/api/v1/metrics/deflated-sharpe \
  -H "Content-Type: application/json" \
  -d '{
    "returns": [/* daily returns from OOS evaluation */],
    "num_trials": 1000,
    "annualization_factor": 252
  }'
```

A DSR p-value < 0.05 indicates the Sharpe ratio is statistically significant (not a product of overfitting).

**7. Walk-Forward Validation (optional but recommended)**

Use the walk-forward validation infrastructure in `agent/strategies/retrain.py` (the `WalkForwardValidator`) to confirm the model generalizes:

- Train window: 6 months rolling
- Test window: 1 month rolling
- Minimum WFE (Walk-Forward Efficiency): 50%
- Target Sharpe: >= 1.5

**Agent:** `ml-engineer`

### Verification Checklist

- [ ] `candles_backfill` has >= 6 months of BTCUSDT hourly data
- [ ] Training completes without errors (500K timesteps)
- [ ] Model saved to `models/ppo_btc_v1.zip`
- [ ] TensorBoard shows converging reward curve
- [ ] OOS evaluation: positive average reward across 10 episodes
- [ ] OOS Sharpe Ratio >= 1.0 (target: >= 1.5)
- [ ] Deflated Sharpe p-value < 0.05
- [ ] Max drawdown < 8% on OOS data

### Estimated Effort

- Data verification + env setup: 1 hour
- Training script creation: 2-3 hours
- Training run: 2-6 hours (CPU)
- Evaluation + DSR validation: 1 hour
- **Total: 1-2 days**

### Agent Assignment

- `ml-engineer` — primary (script creation, training execution, evaluation)
- `backend-developer` — assist if headless env needs patches
- `test-runner` — verify training script has tests

### Dependencies

- **R1 must complete first** (migration 023 applied, services running)
- Historical candle data must exist in the database

### Risk

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Insufficient candle data in DB | HIGH | MEDIUM | Run `scripts/backfill_history.py` before training. Takes ~1 hour for 6 months of BTC hourly data. |
| PPO fails to converge on CPU | MEDIUM | MEDIUM | Start with 100K timesteps as smoke test. If convergence is poor, try: reduce lookback_window to 20, increase batch_hold_steps to 10, adjust learning rate to 1e-4. |
| Headless env has import errors | LOW | LOW | 52 tests pass. If `src/` import fails, ensure `PYTHONPATH=.` is set. |
| Training takes too long on CPU | MEDIUM | MEDIUM | $5/day LLM budget constraint means GPU is not an option. Batch stepping (5x fewer operations) and headless mode (no HTTP) provide 100-500x speedup over naive approach. 500K steps should complete in 2-6 hours. |
| Model overfits to training data | HIGH | MEDIUM | DSR validation catches this. If DSR p-value > 0.05, the model is overfitted. Mitigate by: reducing training timesteps, increasing regularization (entropy coefficient), using walk-forward validation. |

---

## R3: Build Frontend Integration (4 Components)

### Objective

Build 4 frontend UI components that surface the V.0.0.3 backend APIs: webhook management, indicators widget, strategy comparison view, and batch backtest progress. Success = all 4 components render correctly, fetch data from their respective API endpoints, and are accessible from the dashboard navigation.

### Prerequisites

- [x] Backend API endpoints exist and are tested
- [ ] **R1 complete** — endpoints are live on production
- [x] Frontend architecture established (Next.js 16, React 19, Tailwind v4, shadcn/ui)
- [x] Settings page exists at `Frontend/src/components/settings/` (webhook UI goes here)
- [x] Coin detail page exists at `Frontend/src/components/coin/` (indicators widget goes here)
- [x] Strategy components exist at `Frontend/src/components/strategies/` (comparison view goes here)
- [x] Backtest components exist at `Frontend/src/components/backtest/` (progress bar goes here)

### Steps

#### Component 1: Webhook Management UI

**Location:** `Frontend/src/components/settings/webhook-section.tsx`

**1a. Add API client functions** (File: `Frontend/src/lib/api-client.ts`)

```typescript
// --- Webhooks ---
export interface WebhookSubscription {
  id: string;
  url: string;
  events: string[];
  description: string | null;
  active: boolean;
  failure_count: number;
  created_at: string;
  updated_at: string;
  last_triggered_at: string | null;
}

export function listWebhooks(): Promise<WebhookSubscription[]> {
  return request<WebhookSubscription[]>("/webhooks");
}

export function createWebhook(data: {
  url: string;
  events: string[];
  description?: string;
}): Promise<WebhookSubscription> {
  return request<WebhookSubscription>("/webhooks", { method: "POST", body: data });
}

export function deleteWebhook(id: string): Promise<void> {
  return request<void>(`/webhooks/${id}`, { method: "DELETE" });
}

export function testWebhook(id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/webhooks/${id}/test`, { method: "POST" });
}
```

**1b. Create webhook hook** (File: `Frontend/src/hooks/use-webhooks.ts`)

TanStack Query hook wrapping the API client functions above. Key queries:
- `useWebhooks()` — list all webhooks for the current account
- `useCreateWebhook()` — mutation to create a new webhook
- `useDeleteWebhook()` — mutation to delete a webhook
- `useTestWebhook()` — mutation to send a test event

**1c. Create webhook section component** (File: `Frontend/src/components/settings/webhook-section.tsx`)

Features:
- List webhooks in a table (URL, events, status, failure count, last triggered)
- "Add Webhook" button opens a dialog with URL input, event type multi-select (order.filled, trade.executed, backtest.completed, battle.finished), and optional description
- Each row has: toggle active/inactive, "Test" button, "Delete" button with confirmation
- Event types displayed as colored badges
- Failure count shown in `text-loss` when > 0
- Empty state when no webhooks configured

**1d. Wire into settings page** (File: `Frontend/src/app/(dashboard)/settings/page.tsx`)

Add `<WebhookSection />` after the existing `<ApiKeysSection />` in the settings page layout.

**Agent:** `frontend-developer`
**Est. effort:** 3-4 hours

#### Component 2: Indicators Dashboard Widget

**Location:** `Frontend/src/components/coin/indicators-widget.tsx`

**2a. Add API client functions** (File: `Frontend/src/lib/api-client.ts`)

```typescript
export interface IndicatorValues {
  symbol: string;
  interval: string;
  indicators: Record<string, number | Record<string, number>>;
  timestamp: string;
}

export function getIndicators(
  symbol: string,
  params?: { interval?: string; indicators?: string[] }
): Promise<IndicatorValues> {
  const qs = new URLSearchParams();
  if (params?.interval) qs.set("interval", params.interval);
  if (params?.indicators) qs.set("indicators", params.indicators.join(","));
  return request<IndicatorValues>(`/market/indicators/${symbol}?${qs}`);
}

export function getAvailableIndicators(): Promise<string[]> {
  return request<string[]>("/market/indicators/available");
}
```

**2b. Create indicator hook** (File: `Frontend/src/hooks/use-indicators.ts`)

- `useIndicators(symbol, interval)` — fetches indicator values with 30s `staleTime` (market data cadence)
- `useAvailableIndicators()` — fetches the list of available indicator names (cached for 5 minutes)

**2c. Create indicators widget** (File: `Frontend/src/components/coin/indicators-widget.tsx`)

Features:
- Card displaying live indicators for the selected symbol
- Grid of indicator values: RSI, MACD (line/signal/histogram), Bollinger Bands, ADX, ATR, SMA(20), EMA(12), EMA(26), OBV, VWAP, Stochastic K/D, Williams %R, CCI, MFI
- Color coding: RSI > 70 = `text-loss` (overbought), RSI < 30 = `text-profit` (oversold)
- Interval selector (1m, 5m, 15m, 1h, 4h, 1d)
- Auto-refresh every 30 seconds
- Loading skeleton while fetching
- Compact view (3-column grid) by default, expandable to full view

**2d. Wire into coin detail page** (File: `Frontend/src/app/(dashboard)/coin/[symbol]/page.tsx`)

Add `<IndicatorsWidget symbol={symbol} />` below the price chart section.

**Agent:** `frontend-developer`
**Est. effort:** 3-4 hours

#### Component 3: Strategy Comparison View

**Location:** `Frontend/src/components/strategies/strategy-comparison.tsx`

**3a. Add API client function** (File: `Frontend/src/lib/api-client.ts`)

```typescript
export interface StrategyCompareResult {
  strategies: Array<{
    strategy_id: string;
    name: string;
    sharpe_ratio: number;
    deflated_sharpe_pvalue: number;
    total_return: number;
    max_drawdown: number;
    win_rate: number;
    total_trades: number;
    rank: number;
  }>;
  winner: {
    strategy_id: string;
    name: string;
    reason: string;
  };
}

export function compareStrategies(strategyIds: string[]): Promise<StrategyCompareResult> {
  return request<StrategyCompareResult>("/strategies/compare", {
    method: "POST",
    body: { strategy_ids: strategyIds },
  });
}
```

**3b. Create comparison hook** (File: `Frontend/src/hooks/use-strategy-compare.ts`)

- `useStrategyCompare(strategyIds)` — mutation that POSTs to the comparison endpoint
- Enabled only when 2+ strategies are selected

**3c. Create comparison component** (File: `Frontend/src/components/strategies/strategy-comparison.tsx`)

Features:
- Multi-select from existing strategies (checkbox list or multi-select dropdown)
- "Compare" button triggers the comparison API call
- Results displayed as:
  - Side-by-side metrics table (Sharpe, DSR p-value, return, drawdown, win rate, trades)
  - Winner banner with reason text
  - Rank badges (1st, 2nd, 3rd with gold/silver/bronze colors)
- DSR p-value < 0.05 shown in `text-profit`, >= 0.05 shown in `text-loss` (statistically insignificant)
- Maximum 10 strategies per comparison (matches backend limit)
- Empty state when fewer than 2 strategies exist

**3d. Wire into strategies page** (File: `Frontend/src/app/(dashboard)/strategies/page.tsx`)

Add a "Compare Strategies" button in the strategies list page header that opens the comparison view (either as a dialog or a new sub-route `/strategies/compare`).

**Agent:** `frontend-developer`
**Est. effort:** 3-4 hours

#### Component 4: Batch Backtest Progress UI

**Location:** `Frontend/src/components/backtest/monitor/batch-progress.tsx`

**4a. Add API client type** (File: `Frontend/src/lib/api-client.ts`)

```typescript
export interface BatchStepFastResponse {
  session_id: string;
  steps_executed: number;
  total_steps: number;
  current_time: string;
  metrics: {
    equity: number;
    pnl: number;
    sharpe_ratio: number | null;
    max_drawdown: number;
    total_trades: number;
  };
  completed: boolean;
}
```

**4b. Create batch progress component** (File: `Frontend/src/components/backtest/monitor/batch-progress.tsx`)

Features:
- Progress bar showing `steps_executed / total_steps` as percentage
- Real-time metrics display alongside the progress bar: equity, PnL, trades
- Sharpe ratio shown when available (null until sufficient data)
- Completion state: progress bar turns `bg-profit` on completion
- Animated step counter (uses `number-ticker` from shared components)
- Estimated time remaining (based on step rate)

**4c. Wire into backtest monitor** (File: `Frontend/src/components/backtest/monitor/`)

Integrate `<BatchProgress />` into the existing backtest monitoring view. Show it when a batch-stepped backtest is in progress (detected by the `batch_size` field in the backtest session config).

**Agent:** `frontend-developer`
**Est. effort:** 2-3 hours

### Post-Component Pipeline

After all 4 components are built, run the standard frontend quality pipeline:

```bash
cd Frontend
pnpm build            # Verify zero TS errors
pnpm test             # Verify vitest tests pass
pnpm test:e2e         # E2E if available
```

**Agent pipeline:** `frontend-developer` -> `api-sync-checker` -> `code-reviewer` -> `test-runner` -> `context-manager`

### Verification Checklist

- [ ] `webhook-section.tsx` renders on the settings page
- [ ] Can create, list, test, and delete webhooks via the UI
- [ ] `indicators-widget.tsx` renders on coin detail page
- [ ] Indicators auto-refresh every 30 seconds
- [ ] `strategy-comparison.tsx` renders on strategies page
- [ ] Can select 2+ strategies and view comparison results
- [ ] `batch-progress.tsx` renders during batch-stepped backtests
- [ ] `pnpm build` passes with zero TypeScript errors
- [ ] All frontend tests pass

### Estimated Effort

- Component 1 (Webhooks): 3-4 hours
- Component 2 (Indicators): 3-4 hours
- Component 3 (Strategy Compare): 3-4 hours
- Component 4 (Batch Progress): 2-3 hours
- Testing + review: 2 hours
- **Total: 3-4 days**

### Agent Assignment

- `frontend-developer` — primary (all 4 components)
- `api-sync-checker` — verify TypeScript types match Pydantic schemas
- `code-reviewer` — review each component
- `test-runner` — verify tests

### Dependencies

- **R1 must complete first** (API endpoints must be live for integration testing)

### Risk

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| API response shape differs from TypeScript types | MEDIUM | MEDIUM | Run `api-sync-checker` after adding types. Compare against Pydantic schemas in `src/api/schemas/webhooks.py`, `src/api/schemas/indicators.py`, `src/api/schemas/strategies.py`, `src/api/schemas/backtest.py`. |
| Indicators endpoint slow under load | LOW | LOW | Redis-cached on backend (15-indicator cache key with hash). 30s staleTime on frontend prevents hammering. |
| Strategy comparison with no test results | MEDIUM | LOW | Backend returns 422 if strategies have no test runs. Show helpful empty state in the UI. |
| Webhook event type names change | LOW | LOW | Event types are defined in `src/webhooks/events.py`. Use the backend as source of truth; consider fetching available event types from an API endpoint. |

---

## R4: Set Up Scheduled Database Backups

### Objective

Establish automated daily database backups with 30-day retention, stored to a mounted volume (and optionally S3). Success = daily `pg_dump` runs at 03:00 UTC, compressed backups are stored with timestamps, and old backups beyond 30 days are automatically pruned.

### Prerequisites

- [ ] **R1 complete** (all services running, migration 023 applied)
- [x] Docker Compose services defined (`docker-compose.yml` has `timescaledb` service)
- [x] Pre-deploy backup pattern exists in `.github/workflows/deploy.yml` (can reuse the `pg_dump` flags)
- [x] `~/backups/` directory exists on production server (created by deploy workflow)

### Steps

**1. Create the backup script** (File: `scripts/backup_db.sh`)

```bash
#!/usr/bin/env bash
# Daily database backup for AgentExchange platform.
# Excludes heavy time-series hypertable data (ticks, candles_backfill, 
# portfolio_snapshots, backtest_snapshots) — these are large and regenerable.
# Includes all schema + application data (accounts, agents, orders, trades,
# positions, strategies, webhook_subscriptions, etc.).
#
# Usage:  ./scripts/backup_db.sh
# Cron:   0 3 * * * /path/to/scripts/backup_db.sh >> /var/log/agentexchange-backup.log 2>&1
#
# Environment variables (from .env):
#   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#
# Retention: 30 days (configurable via BACKUP_RETENTION_DAYS)

set -euo pipefail

# --- Configuration ---
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/TradeReady_BackEnd-}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/agentexchange-daily-$TIMESTAMP.sql.gz"

# --- Load environment ---
cd "$COMPOSE_DIR"
set -a && source .env && set +a

# --- Ensure backup directory exists ---
mkdir -p "$BACKUP_DIR"

# --- Run pg_dump via Docker ---
echo "[$(date -Iseconds)] Starting daily backup..."

docker compose exec -T timescaledb pg_dump \
  -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  --no-owner --no-acl \
  --exclude-table-data='_timescaledb_internal._hyper_*' \
  --exclude-table-data='ticks' \
  --exclude-table-data='candles_backfill' \
  --exclude-table-data='portfolio_snapshots' \
  --exclude-table-data='backtest_snapshots' \
  --exclude-table-data='battle_snapshots' \
  | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date -Iseconds)] Backup complete: $BACKUP_FILE ($BACKUP_SIZE)"

# --- Prune old backups ---
PRUNED=$(find "$BACKUP_DIR" -name "agentexchange-daily-*.sql.gz" -mtime +$BACKUP_RETENTION_DAYS -delete -print | wc -l)
echo "[$(date -Iseconds)] Pruned $PRUNED backup(s) older than $BACKUP_RETENTION_DAYS days"

# --- Optional: Upload to S3 ---
# Uncomment and configure if S3 backup is desired:
# if command -v aws &>/dev/null; then
#   aws s3 cp "$BACKUP_FILE" "s3://${S3_BACKUP_BUCKET:-agentexchange-backups}/daily/$TIMESTAMP.sql.gz"
#   echo "[$(date -Iseconds)] Uploaded to S3: s3://${S3_BACKUP_BUCKET}/daily/$TIMESTAMP.sql.gz"
# fi

echo "[$(date -Iseconds)] Backup job finished successfully"
```

**Agent:** `backend-developer`

**2. Make the script executable and test it**

```bash
chmod +x scripts/backup_db.sh

# Test run on production
ssh $SERVER_USER@$SERVER_HOST
cd ~/TradeReady_BackEnd-
./scripts/backup_db.sh

# Verify backup was created
ls -lh ~/backups/agentexchange-daily-*.sql.gz | tail -3

# Verify backup is restorable (on a test DB, never production)
gunzip -c ~/backups/agentexchange-daily-YYYYMMDD-HHMMSS.sql.gz | head -20
```

**3. Set up the cron job**

```bash
# On the production server, add the cron entry
crontab -e

# Add this line (runs at 03:00 UTC daily):
0 3 * * * /home/$USER/TradeReady_BackEnd-/scripts/backup_db.sh >> /var/log/agentexchange-backup.log 2>&1
```

**4. Add backup monitoring (optional but recommended)**

Create a simple health check that verifies a recent backup exists:

```bash
# Add to scripts/check_backup_health.sh
#!/usr/bin/env bash
# Returns exit code 1 if no backup exists from the last 26 hours
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RECENT=$(find "$BACKUP_DIR" -name "agentexchange-daily-*.sql.gz" -mmin -1560 | wc -l)
if [ "$RECENT" -eq 0 ]; then
  echo "WARNING: No backup found in the last 26 hours!"
  exit 1
fi
echo "OK: $RECENT recent backup(s) found"
exit 0
```

This can be wired into Prometheus alerting via the node_exporter textfile collector or a custom script exporter.

**5. Add a Prometheus alert rule for missing backups** (File: `monitoring/alerts/backup-alerts.yml`)

```yaml
groups:
  - name: backup_alerts
    rules:
      - alert: BackupMissing
        expr: time() - node_textfile_backup_last_success_timestamp > 93600
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "No successful database backup in the last 26 hours"
          description: "The daily pg_dump backup has not completed successfully. Check /var/log/agentexchange-backup.log on the production server."
```

**6. Document the restore procedure**

Add to `docs/quickstart.md` or create `docs/disaster-recovery.md`:

```bash
# Restore from backup (CAUTION: destructive on target DB)
gunzip -c ~/backups/agentexchange-daily-YYYYMMDD-HHMMSS.sql.gz | \
  docker compose exec -T timescaledb psql -U $POSTGRES_USER -d $POSTGRES_DB

# For a clean restore (drop + recreate):
docker compose exec timescaledb dropdb -U $POSTGRES_USER $POSTGRES_DB
docker compose exec timescaledb createdb -U $POSTGRES_USER $POSTGRES_DB
gunzip -c ~/backups/agentexchange-daily-YYYYMMDD-HHMMSS.sql.gz | \
  docker compose exec -T timescaledb psql -U $POSTGRES_USER -d $POSTGRES_DB
```

### Verification Checklist

- [ ] `scripts/backup_db.sh` exists and is executable
- [ ] Manual test run produces a valid `.sql.gz` file in `~/backups/`
- [ ] Backup file is non-empty and starts with valid SQL
- [ ] Cron job installed (`crontab -l` shows the 03:00 UTC entry)
- [ ] After 24 hours: at least 1 automated backup exists
- [ ] After 31 days: old backups are pruned (only 30 remain)
- [ ] Restore procedure tested on a staging/test database

### Estimated Effort

- Script creation: 30 minutes
- Testing: 30 minutes
- Cron setup: 15 minutes
- Monitoring + docs: 1 hour
- **Total: 2-3 hours**

### Agent Assignment

- `backend-developer` — script creation
- `deploy-checker` — verify production setup
- `doc-updater` — document restore procedure
- `context-manager` — update context.md

### Dependencies

- **R1 should complete first** (all services running), but the script can be written in parallel

### Risk

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| `pg_dump` fails silently | MEDIUM | LOW | Script uses `set -euo pipefail` — any failure exits non-zero and logs the error. Cron log captures stderr. Prometheus alert catches missing backups. |
| Backup disk fills up | MEDIUM | LOW | 30-day retention with automatic pruning. Each backup is ~5-20MB compressed (hypertable data excluded). 30 days = ~150-600MB. |
| Cron job stops running | MEDIUM | LOW | Prometheus `BackupMissing` alert fires after 26 hours. Also visible in `cron` system logs. |
| Backup is corrupted | LOW | LOW | Test restore monthly on a staging database. `pg_dump` is atomic and reliable. Gzip compression includes checksum. |

---

## R5: Begin External Agent Onboarding Documentation

### Objective

Create a comprehensive "Getting Started" guide for external AI agent developers who want to build trading agents on the AgentExchange platform. Success = a developer with Python experience can go from zero to a working agent that fetches prices, places orders, and runs a backtest within 30 minutes of reading the guide.

### Prerequisites

- [x] SDK published and documented (`sdk/CLAUDE.md`, `sdk/README.md`, 48 methods)
- [x] 5 SDK example scripts exist in `sdk/examples/`
- [x] `docs/quickstart.md` exists (basic platform setup)
- [x] `docs/skill.md` exists (LLM-readable API spec)
- [x] `docs/api_reference.md` exists (full API reference)
- [x] 4 framework integration guides exist (`docs/framework_guides/`)
- [ ] **R1 complete** (live platform for testing the guide)

### Steps

**1. Create the Getting Started guide** (File: `docs/getting-started-agents.md`)

Structure:

```markdown
# Building AI Trading Agents on AgentExchange

## What You'll Build
- An AI agent that connects to the platform
- Fetches real-time BTC prices
- Places simulated trades with virtual USDT
- Runs a backtest to validate a strategy
- Monitors performance via webhooks

## Prerequisites
- Python 3.12+
- Docker (to run the platform locally)
- ~15 minutes

## Step 1: Start the Platform (2 min)
[Docker setup from quickstart.md, condensed]

## Step 2: Get Your API Credentials (1 min)
[Register account, create agent, get API key]

## Step 3: Install the SDK (1 min)
pip install -e sdk/

## Step 4: Your First Agent — Price Watcher (3 min)
[Simple script: connect, fetch price, print it, stream via WebSocket]

## Step 5: Place Your First Trade (3 min)
[Script: buy BTC, check balance, sell BTC, check PnL]

## Step 6: Backtest a Strategy (5 min)
[Script: create backtest, loop through candles with SMA crossover, get results]

## Step 7: Train an RL Agent (10 min)
[Script: gym.make("TradeReady-BTC-v0"), PPO training loop, evaluate]

## Step 8: Deploy Webhooks for Real-Time Events (5 min)
[Script: register webhook, handle events, verify HMAC]

## Step 9: Compare Strategies with DSR (5 min)
[Script: run multiple backtests, compare with deflated Sharpe]

## Next Steps
- Full API Reference: docs/api_reference.md
- Framework Guides: LangChain, CrewAI, Agent Zero, OpenClaw
- Gymnasium Environments: tradeready-gym/ package
- MCP Server: docs/mcp_server.md (for Claude, Cline, etc.)
```

**Agent:** `doc-updater`

**2. Create a companion script** (File: `sdk/examples/getting_started.py`)

A single runnable script that walks through Steps 4-6 from the guide:

```python
"""Getting Started companion script — run this to validate your setup.

Usage:
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY
    export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET
    python sdk/examples/getting_started.py
"""
# 1. Fetch BTC price
# 2. Place a market buy
# 3. Check position
# 4. Place a market sell
# 5. Check PnL
# 6. Create a simple backtest (SMA crossover)
# 7. Print results summary
```

**Agent:** `doc-updater`

**3. Create an architecture overview diagram** (File: `docs/architecture-overview.md`)

A high-level document explaining the platform architecture for external developers:
- What the platform does (simulated exchange with real prices)
- How agents connect (SDK, REST API, WebSocket, MCP)
- What data is available (600+ USDT pairs, OHLCV candles, indicators)
- What operations are available (trading, backtesting, battles, strategies)
- Agent isolation model (each agent has own wallet, API key, risk profile)
- Rate limits and authentication flow

**Agent:** `doc-updater`

**4. Update the Fumadocs site** (File: `Frontend/content/docs/`)

Add new MDX pages to the documentation site:
- `content/docs/getting-started/index.mdx` — landing page for getting started section
- `content/docs/getting-started/first-agent.mdx` — building your first agent
- `content/docs/getting-started/backtesting.mdx` — running your first backtest
- `content/docs/getting-started/rl-training.mdx` — training an RL agent
- Update `content/docs/meta.json` to add the new section to the sidebar

**Agent:** `frontend-developer`

**5. Update the SDK README** (File: `sdk/README.md`)

Add a "Getting Started" section at the top that links to the full guide and provides a 3-line quickstart:

```python
from agentexchange import AgentExchangeClient
with AgentExchangeClient(api_key="ak_live_...", api_secret="sk_live_...") as client:
    print(client.get_price("BTCUSDT"))
```

**Agent:** `doc-updater`

**6. Add onboarding flow to the frontend** (Optional, lower priority)

Add a "Developer Docs" link in the dashboard sidebar that opens the Fumadocs getting-started page. Consider adding an API key quick-copy tooltip on the settings page.

**Agent:** `frontend-developer`

**7. Test the guide end-to-end**

Have someone follow the guide from scratch on a clean machine:
- Start platform with Docker
- Register account
- Follow all 9 steps
- Verify every code snippet works
- Note any unclear steps or missing context

**Agent:** `e2e-tester`

### Verification Checklist

- [ ] `docs/getting-started-agents.md` exists and is complete
- [ ] All code snippets in the guide execute without errors
- [ ] `sdk/examples/getting_started.py` runs successfully against a live platform
- [ ] `docs/architecture-overview.md` provides clear mental model
- [ ] Fumadocs getting-started section appears in the docs site sidebar
- [ ] SDK README links to the getting started guide
- [ ] Guide tested end-to-end by someone other than the author

### Estimated Effort

- Getting Started guide: 3-4 hours
- Companion script: 1 hour
- Architecture overview: 2 hours
- Fumadocs pages: 2 hours
- SDK README update: 30 minutes
- E2E testing: 1-2 hours
- **Total: 2-3 days**

### Agent Assignment

- `doc-updater` — primary (guide, architecture doc, SDK README)
- `frontend-developer` — Fumadocs pages
- `e2e-tester` — validate guide end-to-end
- `context-manager` — update context.md

### Dependencies

- **R1 should complete first** (live platform needed for testing code snippets)
- No hard dependency on R2-R4

### Risk

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Code snippets in the guide are wrong | MEDIUM | MEDIUM | Test every snippet against a live platform. The companion script (`getting_started.py`) serves as an automated validation tool. |
| Guide assumes too much prior knowledge | MEDIUM | MEDIUM | Target audience is "Python developer who has never used the platform." No blockchain/crypto knowledge assumed. Include a glossary section. |
| Platform setup fails on certain OS | LOW | MEDIUM | Docker abstracts OS differences. Note minimum Docker version (24+) and resources (8 CPU, 10 GB RAM from docker-compose.yml). Include troubleshooting section. |
| SDK methods change after guide is written | LOW | LOW | Guide uses stable SDK methods (get_price, place_market_order, get_portfolio). These have not changed since SDK creation. Pin to SDK version in requirements. |

---

## Summary Table

| # | Recommendation | Effort | Priority | Parallel Group | Agent(s) |
|---|----------------|--------|----------|---------------|----------|
| R1 | Deploy V.0.0.3 | 45 min | P0 (blocker) | A | deploy-checker, CI/CD, e2e-tester |
| R4 | Scheduled DB Backups | 2-3 hrs | P1 | A (script parallel, cron post-R1) | backend-developer, deploy-checker |
| R2 | RL Model Training | 1-2 days | P1 | B | ml-engineer |
| R3 | Frontend Integration | 3-4 days | P1 | B | frontend-developer, api-sync-checker |
| R5 | Onboarding Documentation | 2-3 days | P2 | B | doc-updater, frontend-developer, e2e-tester |

### Total Timeline

- **Day 0-1:** R1 (deploy) + R4 (backup script + cron)
- **Day 1-4:** R2 (training), R3 (frontend components 1-2), R5 (getting started guide)
- **Day 4-7:** R3 (frontend components 3-4), R2 (evaluation), R5 (Fumadocs + testing)
- **Day 7-10:** Buffer for iteration, testing, review
- **Day 10-14:** Final review + context sync

**Critical path:** R1 -> R3 (longest downstream dependency chain)
**Total estimated effort:** 8-12 person-days across all 5 recommendations

---

*Created: 2026-04-08*
*Plan source: C-level executive report — Section 11: Recommendations*
*Next review: 2026-04-15*
