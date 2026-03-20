---
task_id: 05
title: "PPO evaluation & deployment bridge"
agent: "ml-engineer"
phase: A
depends_on: [4]
status: "completed"
priority: "high"
files: ["agent/strategies/rl/evaluate.py", "agent/strategies/rl/deploy.py"]
---

# Task 05: PPO evaluation & deployment bridge

## Assigned Agent: `ml-engineer`

## Objective
Create evaluation script (test on held-out data, compare vs benchmarks) and deployment bridge (translate trained model's portfolio weights into platform orders).

## Files to Create
- `agent/strategies/rl/evaluate.py`:
  - Load trained model(s)
  - Run on test-period environment (held-out data the model never saw)
  - Compute: Sharpe, ROI, max drawdown, win rate, trades count
  - Compare vs 3 benchmarks: (a) equal-weight rebalancing, (b) buy-and-hold BTC, (c) buy-and-hold ETH
  - If 3 seeds trained: compute ensemble (mean weights) and evaluate that too
  - Output: EvaluationReport (Pydantic model) with per-strategy comparison table
  - CLI: `python -m agent.strategies.rl.evaluate --model-dir agent/strategies/rl/models/`

- `agent/strategies/rl/deploy.py`:
  - Load trained model
  - Connect to platform via SDK (live or backtest mode)
  - Each step: get observation → model.predict() → convert weights to rebalancing orders
  - Weight delta → order generation: if target_weight > current_weight → buy, else → sell
  - Respect minimum order size ($1 USD)
  - Output: trade log with reasoning (weights before/after, orders placed)

## Acceptance Criteria
- [ ] Evaluation passes on held-out data: Sharpe > 0.8 AND max_drawdown < 15%
- [ ] Benchmark comparison shows PPO agent outperforms at least 2 of 3 benchmarks
- [ ] Ensemble (3 seeds) outperforms any single seed
- [ ] Deploy bridge generates valid orders (correct symbol, side, quantity)
- [ ] Deploy bridge handles edge cases: no rebalancing needed (weights unchanged), zero-weight asset
- [ ] EvaluationReport is JSON-serializable and saved to `agent/reports/`

## Dependencies
- Task 04: at least 1 trained model
- Platform running for backtest evaluation

## Agent Instructions
For benchmarks, create simple `gymnasium.Env` wrappers that implement equal-weight and buy-and-hold. Or just compute the returns analytically from the candle data (simpler). The deploy bridge must use `Decimal` for all quantities.

## Estimated Complexity
Medium — evaluation is straightforward, deploy bridge needs careful order generation.
