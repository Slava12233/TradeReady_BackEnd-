# agent/strategies/rl/ — PPO Reinforcement Learning Strategy

<!-- last-updated: 2026-03-20 -->

> Trains, evaluates, and deploys a PPO portfolio agent via Stable-Baselines3 on the `TradeReady-Portfolio-v0` gymnasium environment.

## What This Module Does

The `rl/` sub-package implements a complete PPO reinforcement learning pipeline for portfolio allocation. It trains a neural network policy that takes raw market observations (OHLCV + indicators) and outputs portfolio weight vectors for a set of assets. Training uses the `TradeReady-Portfolio-v0` environment from `tradeready-gym/`. A trained model can then be deployed against a backtest session or live sandbox account via `PPODeployBridge`.

This module requires `stable-baselines3[extra]` and `torch` to be installed. These are declared in `agent/pyproject.toml` under `[project.optional-dependencies]` extras (`pip install -e "agent/[rl]"`).

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | `RLConfig` — Pydantic-settings with env prefix `RL_`. All PPO hyperparameters, date windows, asset list, model output directory. |
| `train.py` | `train(config: RLConfig) -> Path` — Full SB3 PPO training pipeline; returns path to saved `.zip` checkpoint. |
| `evaluate.py` | `ModelEvaluator`, `EvaluationReport`, `StrategyMetrics` — Load models, run test-split evaluation, compare against 3 benchmarks. |
| `deploy.py` | `PPODeployBridge` — Loads a trained model and drives it against a backtest session or live account via REST tools. |
| `data_prep.py` | CLI script — Validates OHLCV data coverage across train/val/test splits before training starts. |
| `runner.py` | `SeedMetrics`, CLI script — Orchestrates the full pipeline: validate → multi-seed train → evaluate → compare. |
| `models/` | Output directory for trained `.zip` checkpoints (gitignored). |
| `results/` | Output directory for evaluation JSON reports. |

## Public API

```python
from agent.strategies.rl.config import RLConfig
from agent.strategies.rl.train import train
from agent.strategies.rl.evaluate import ModelEvaluator, EvaluationReport, StrategyMetrics
from agent.strategies.rl.deploy import PPODeployBridge
```

### `RLConfig` (`config.py`)

Pydantic v2 `BaseSettings`, env prefix `RL_`. Key fields:

| Field | Default | Purpose |
|-------|---------|---------|
| `learning_rate` | `3e-4` | Adam optimiser learning rate |
| `n_steps` | `2048` | Steps per environment per update cycle |
| `total_timesteps` | `500_000` | Total training budget |
| `n_envs` | `4` | Parallel training environments |
| `reward_type` | `"sharpe"` | One of: `pnl`, `sharpe`, `sortino`, `drawdown` |
| `env_symbols` | `["BTCUSDT","ETHUSDT","SOLUSDT"]` | Assets for `TradeReady-Portfolio-v0` |
| `train_start` / `train_end` | `2024-01-01` / `2024-10-01` | ISO-8601 training window |
| `val_start` / `val_end` | `2024-10-01` / `2024-12-01` | ISO-8601 validation window |
| `test_start` / `test_end` | `2024-12-01` / `2025-01-01` | ISO-8601 held-out test window |
| `platform_api_key` | `""` | TradeReady `ak_live_...` key (required) |
| `models_dir` | `agent/strategies/rl/models/` | Checkpoint and final model output path |

### `ModelEvaluator` (`evaluate.py`)

| Method | Returns | Description |
|--------|---------|-------------|
| `load_models(model_dir)` | `dict[str, PPO]` | Scan for `ppo_seed*.zip` files and load them |
| `evaluate(model_dir, seed_filter)` | `EvaluationReport` | Run test-split evaluation + 3 benchmarks + optional ensemble |

Benchmarks always evaluated: equal-weight rebalancing, buy-and-hold BTC, buy-and-hold ETH.

### `PPODeployBridge` (`deploy.py`)

Loads a trained PPO model and drives it step-by-step against a backtest session or live account.

| Method | Description |
|--------|-------------|
| `__init__(model_path, config)` | Load the `.zip` model checkpoint |
| `run_backtest(session_id, steps)` | Drive the model against an existing backtest session |
| `run_live(agent_api_key, steps)` | Drive the model against the live sandbox |

The bridge maintains an observation buffer (`lookback_window` candles, default 30) and returns equal weights until the buffer is fully populated.

## CLI Commands

```bash
# Validate data availability before training
python -m agent.strategies.rl.data_prep \
    --base-url http://localhost:8000 \
    --api-key ak_live_... \
    --assets BTCUSDT ETHUSDT SOLUSDT

# Train a single seed
python -m agent.strategies.rl.train \
    --api-key ak_live_... \
    --timesteps 500000 \
    --reward sharpe

# Quick smoke test (no platform tracking)
python -m agent.strategies.rl.train --timesteps 1000 --no-track

# Train multiple seeds + evaluate (pipeline runner)
python -m agent.strategies.rl.runner --seeds 42,123,456 --timesteps 500000

# Evaluate trained models on held-out test split
python -m agent.strategies.rl.evaluate --model-dir agent/strategies/rl/models/

# Deploy against an existing backtest session
python -m agent.strategies.rl.deploy \
    --model agent/strategies/rl/models/ppo_seed42.zip \
    --mode backtest \
    --session-id <uuid>

# Deploy live (paper-trading sandbox)
python -m agent.strategies.rl.deploy \
    --model agent/strategies/rl/models/ppo_seed42.zip \
    --mode live \
    --steps 100
```

## Patterns

- **ISO-8601 strings for all date fields** — never `datetime` objects; forwarded directly to the backtest API without conversion.
- **Multi-seed training** — `runner.py` trains N seeds and picks the best by test-split Sharpe ratio; this is the recommended path for production-quality models.
- **No platform logic in this layer** — all HTTP calls go through `PlatformRESTClient` from `agent/tools/rest_tools.py`.
- **Reward type is a config field** — swap reward functions without code changes by setting `RL_REWARD_TYPE=pnl` (or `sharpe`, `sortino`, `drawdown`).

## Gotchas

- **`stable-baselines3` and `torch` are not installed by default.** Install via `pip install -e "agent/[rl]"`.
- **`rl/models/` is gitignored.** Trained `.zip` files are not committed. Regenerate with `python -m agent.strategies.rl.runner`.
- **`PPODeployBridge` needs `lookback_window` candles before it produces valid predictions.** The bridge silently returns equal weights for the first `lookback_window` steps (default 30).
- **SB3's `predict()` returns a numpy array of portfolio weights, not a single action.** The `rl_weights_to_signals()` converter in `ensemble/meta_learner.py` normalizes and thresholds these before passing to `MetaLearner`.
- **`data_prep.py` exits with code 1 if any split has insufficient history.** Do not skip this validation step — the training will fail or produce biased results if data gaps exist.
- **Security note:** SB3 `.zip` model files contain Python pickle. Only load from trusted, locally-generated paths. Never load models from network paths or untrusted sources.

## Recent Changes

- `2026-03-20` — Initial CLAUDE.md created.
