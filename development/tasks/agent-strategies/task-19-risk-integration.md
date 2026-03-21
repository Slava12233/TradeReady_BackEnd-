---
task_id: 19
title: "Risk agent integration with signal strategies"
type: task
agent: "ml-engineer"
phase: D
depends_on: [5, 18]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: ["agent/strategies/risk/middleware.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 19: Risk agent integration with signal strategies

## Assigned Agent: `ml-engineer`

## Objective
Wire the Risk Agent as middleware between any signal strategy (PPO, regime, evolved) and the order execution layer.

## Files to Create
- `agent/strategies/risk/middleware.py`:
  - `RiskMiddleware` class:
    - `__init__(risk_agent, veto_pipeline, dynamic_sizer, sdk_client)`
    - `process_signal(signal: TradeSignal)` → `ExecutionDecision`:
      1. Fetch current portfolio state via SDK
      2. Run `risk_agent.assess(portfolio, positions, pnl)`
      3. Run `veto_pipeline.evaluate(signal, assessment)`
      4. If approved: run `dynamic_sizer.calculate_size()`
      5. Return: original signal + veto decision + final size + risk assessment
    - `execute_if_approved(execution_decision)` → places order via SDK if approved
    - Logging: every signal → assessment → veto decision → execution is logged

## Acceptance Criteria
- [ ] Middleware wraps any strategy transparently (strategy doesn't know about risk)
- [ ] Portfolio state is fresh (fetched per signal, not cached)
- [ ] Veto decisions are logged with full context (signal, assessment, reason)
- [ ] Approved trades use dynamically sized position (not original signal size)
- [ ] Integration test: PPO signal → risk middleware → order placed (mock SDK)

## Dependencies
- Task 05: PPO deploy bridge (produces TradeSignal objects)
- Task 18: veto pipeline and dynamic sizer

## Agent Instructions
The middleware follows the decorator pattern. A strategy produces signals; the middleware filters/adjusts them. The strategy never imports risk code — the middleware sits in between.

## Estimated Complexity
Low — composition of existing components.
