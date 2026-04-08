---
task_id: 13
title: "Create headless Gymnasium environment (in-process, no HTTP)"
type: task
agent: "ml-engineer"
phase: 2
depends_on: [1]
status: "pending"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tradeready-gym/tradeready_gym/envs/headless_env.py"
  - "tradeready-gym/tradeready_gym/__init__.py"
tags:
  - task
  - gymnasium
  - performance
  - phase-2
---

# Task 13: Create headless Gymnasium environment (in-process, no HTTP)

## Assigned Agent: `ml-engineer`

## Objective
Create a headless Gymnasium environment that imports platform source directly and calls engine methods in-process — zero HTTP overhead for maximum training speed.

## Context
Improvement 5d: Even with batch stepping, there's still HTTP overhead. For same-machine training, a headless env that imports `BacktestEngine` directly eliminates all network latency. Requires a DB connection string (for price data).

## Files to Modify/Create
- `tradeready-gym/tradeready_gym/envs/headless_env.py` — Create: imports platform source (`from src.backtesting.engine import BacktestEngine`), creates engine/replayer/sandbox in-process during `reset()`, calls engine methods directly in `step()`
- `tradeready-gym/tradeready_gym/__init__.py` — Register as `TradeReady-BTC-Headless-v0`

## Acceptance Criteria
- [ ] `HeadlessTradingEnv` class extends Gymnasium `Env`
- [ ] Constructor accepts `db_url: str` (database connection string for price data)
- [ ] `reset()` creates engine, replayer, sandbox in-process
- [ ] `step()` calls engine methods directly (no HTTP)
- [ ] Observation and action spaces match existing `BaseTradingEnv`
- [ ] Registered as `TradeReady-BTC-Headless-v0` via `gymnasium.register()`
- [ ] Handles `close()` cleanup properly (close DB connections)
- [ ] `ruff check` passes

## Dependencies
- **Task 01** (batch backtest engine) — uses same engine internals

## Agent Instructions
1. Read `tradeready-gym/CLAUDE.md` for env patterns, observation/action spaces
2. Read `src/backtesting/CLAUDE.md` for engine, sandbox, and replayer architecture
3. Read `tradeready-gym/tradeready_gym/envs/base_trading_env.py` to match the observation/action space interface
4. Use `sqlalchemy.ext.asyncio.create_async_engine` for DB connection
5. The env needs to be synchronous (Gymnasium standard) but engine is async — use `asyncio.run()` or an event loop wrapper
6. Price data comes from TimescaleDB — query candles the same way the engine does

## Estimated Complexity
High — requires bridging async engine code into synchronous Gymnasium interface, plus managing DB connections within env lifecycle.
