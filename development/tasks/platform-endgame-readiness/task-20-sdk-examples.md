---
task_id: 20
title: "Create SDK example scripts (5 examples)"
type: task
agent: "backend-developer"
phase: 3
depends_on: [1, 4, 7, 10, 17]
status: "done"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "sdk/examples/basic_backtest.py"
  - "sdk/examples/rl_training.py"
  - "sdk/examples/genetic_optimization.py"
  - "sdk/examples/strategy_tester.py"
  - "sdk/examples/webhook_integration.py"
tags:
  - task
  - sdk
  - documentation
  - examples
  - phase-3
---

# Task 20: Create SDK example scripts (5 examples)

## Assigned Agent: `backend-developer`

## Objective
Create 5 standalone, self-contained example scripts demonstrating the platform's key capabilities for external agent developers.

## Context
Improvement 7: No example projects exist showing how to build an agent on top of the platform. These examples serve as onboarding material.

## Files to Modify/Create
- `sdk/examples/basic_backtest.py` — Create session → batch step fast → get results → print metrics
- `sdk/examples/rl_training.py` — PPO training with Stable-Baselines3 + TradeReady-Portfolio-v0 gym env + batch stepping
- `sdk/examples/genetic_optimization.py` — Create 10 strategy variants → test each → deflated Sharpe filter → compare → deploy winner
- `sdk/examples/strategy_tester.py` — Create strategy → create version → run multi-episode test → check DSR → deploy if significant
- `sdk/examples/webhook_integration.py` — Register webhook → start local HTTP server → kick off backtest → wait for completion event

## Acceptance Criteria
- [x] Each script is self-contained (single file, runnable with `python examples/X.py`)
- [x] Each script has clear comments explaining each step
- [x] Each script uses real SDK methods (not mocked)
- [x] Each script includes basic error handling
- [x] Each script has `if __name__ == "__main__"` block
- [x] Each script has a docstring at the top explaining what it demonstrates
- [x] `ruff check` passes on all files

## Dependencies
- **Task 01** (batch backtest), **Task 04** (DSR), **Task 07** (indicators), **Task 10** (strategy compare), **Task 17** (webhooks) — examples use features from all improvements

## Agent Instructions
1. Read `sdk/CLAUDE.md` for SDK client patterns and available methods
2. Read the SDK client code to understand method signatures
3. Keep examples simple and focused — each demonstrates ONE workflow
4. Use environment variables for configuration (`TRADEREADY_API_URL`, `TRADEREADY_API_KEY`)
5. The RL training example should import from `stable_baselines3` — add a check/message if not installed
6. The webhook example needs a simple HTTP server (use `http.server` from stdlib)

## Estimated Complexity
Medium — 5 scripts, each self-contained, but following clear patterns.
