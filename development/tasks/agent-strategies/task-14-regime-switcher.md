---
task_id: 14
title: "Regime switching logic"
type: task
agent: "ml-engineer"
phase: C
depends_on: [12, 13]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: ["agent/strategies/regime/switcher.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 14: Regime switching logic

## Assigned Agent: `ml-engineer`

## Objective
Build the orchestration layer that detects the current market regime and activates the corresponding strategy version.

## Files to Create
- `agent/strategies/regime/switcher.py`:
  - `RegimeSwitcher` class:
    - `__init__(classifier, strategy_map: dict[RegimeType, str])` — maps regime → strategy_id
    - `detect_regime(candles: list[dict])` → (RegimeType, confidence)
    - `should_switch(new_regime, confidence)` → bool (minimum confidence 0.7, cooldown 5 candles)
    - `get_active_strategy()` → current strategy_id
    - `step(candles)` → processes new candle data, switches strategy if needed, returns (regime, strategy_id, switched: bool)
  - State tracking:
    - current_regime: RegimeType
    - candles_since_switch: int (cooldown counter)
    - regime_history: list[(timestamp, regime, confidence)]
  - CLI demo: `python -m agent.strategies.regime.switcher --demo` runs against 1 month of historical data, prints regime changes

## Acceptance Criteria
- [ ] Regime detection uses trained classifier from Task 12
- [ ] Cooldown prevents switching within 5 candles of last switch
- [ ] Confidence threshold (0.7) prevents low-confidence switches
- [ ] Regime history is logged with timestamps
- [ ] Demo mode shows regime changes across 1 month of data
- [ ] Integrates cleanly with the agent's decision loop (returns strategy_id to use)

## Dependencies
- Task 12: trained classifier model
- Task 13: strategy IDs for each regime

## Agent Instructions
The switcher is stateful — it tracks the current regime and cooldown. Design it to be called once per candle in the agent's main loop. The demo mode should fetch candles from the platform and run the full switching logic offline.

## Estimated Complexity
Low-Medium — straightforward state machine with classifier integration.
