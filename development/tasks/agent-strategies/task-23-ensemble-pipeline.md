---
task_id: 23
title: "Full ensemble pipeline"
type: task
agent: "ml-engineer"
phase: E
depends_on: [21, 22, 19]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "low"
files: ["agent/strategies/ensemble/run.py", "agent/strategies/ensemble/config.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 23: Full ensemble pipeline

## Assigned Agent: `ml-engineer`

## Objective
Build the complete ensemble runner that initializes all 3 signal sources + risk overlay, runs them per step, combines signals, and executes orders.

## Files to Create
- `agent/strategies/ensemble/config.py`:
  - `EnsembleConfig(BaseSettings)`:
    - weights: dict (from optimization)
    - confidence_threshold: 0.6
    - enable_risk_overlay: True
    - enable_rl_signal: True
    - enable_evolved_signal: True
    - enable_regime_signal: True
    - symbols: list[str]
    - mode: "backtest" | "live"

- `agent/strategies/ensemble/run.py`:
  - `EnsembleRunner` class:
    - `__init__(config, sdk_client, rest_client)` — initializes all components
    - `initialize()` → loads PPO model, evolved champion, regime classifier, risk agent
    - `step(candles: dict[str, list])` → runs full pipeline:
      1. Get RL signal (PPO model predict)
      2. Get evolved signal (strategy executor)
      3. Get regime signal (regime switcher → strategy executor)
      4. Combine via meta-learner
      5. Apply risk overlay
      6. Execute approved orders
      7. Return: StepResult with all signals, consensus, risk assessment, orders placed
    - `run_backtest(start, end)` → full backtest loop
    - `generate_report()` → EnsembleReport: per-signal contribution stats, agreement rate, overall performance
  - CLI: `python -m agent.strategies.ensemble.run --mode backtest`

## Acceptance Criteria
- [ ] All 3 signals generate valid output per step
- [ ] Meta-learner combines with optimized weights
- [ ] Risk overlay vetoes/resizes as expected
- [ ] Backtest mode runs full historical period
- [ ] StepResult tracks which signals contributed to each trade
- [ ] Report shows signal agreement rate and per-source hit rate
- [ ] Can disable any signal source via config (graceful degradation)

## Dependencies
- Task 21: meta-learner
- Task 22: optimized weights
- Task 19: risk middleware

## Agent Instructions
The ensemble runner is the "main" for Strategy 5. It coordinates everything. Keep it clean — delegate to each component, don't put signal logic in the runner. Each component should be independently testable.

## Estimated Complexity
High — orchestrating multiple components in a coherent pipeline.
