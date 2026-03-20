---
task_id: 13
title: "Strategy version creation (4 regimes)"
agent: "backend-developer"
phase: C
depends_on: [12]
status: "completed"
priority: "medium"
files: ["agent/strategies/regime/strategy_definitions.py"]
---

# Task 13: Strategy version creation (4 regimes)

## Assigned Agent: `backend-developer`

## Objective
Create 4 platform strategy definitions (one per market regime) with properly configured entry/exit conditions using the platform's `StrategyDefinition` schema.

## Files to Create
- `agent/strategies/regime/strategy_definitions.py`:
  - `TRENDING_STRATEGY`: MACD crossover + ADX > 25 entry, trailing stop 2x ATR exit
  - `MEAN_REVERTING_STRATEGY`: RSI oversold (<30) + Bollinger lower band bounce entry, RSI overbought (>70) exit
  - `HIGH_VOLATILITY_STRATEGY`: tight stop-loss (1%), small position (3%), ATR-based exit
  - `LOW_VOLATILITY_STRATEGY`: Bollinger squeeze breakout entry, momentum exit, larger position (10%)
  - `create_regime_strategies(rest_client, agent_id)` → creates all 4 via API, returns strategy_ids
  - Each strategy uses: `pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"]`, `timeframe="1h"`

## Acceptance Criteria
- [ ] All 4 strategies conform to the platform's `StrategyDefinition` schema
- [ ] Entry conditions use correct condition keys from `src/strategies/models.py`
- [ ] Exit conditions use correct condition keys
- [ ] Strategies can be created via `POST /api/v1/strategies` without validation errors
- [ ] Each strategy is tested via `POST /api/v1/strategies/{id}/test` with at least 1 episode
- [ ] Strategy IDs are returned for use by the regime switcher

## Dependencies
- Task 12: regime types defined (enum used in strategy naming)
- Platform running with strategy system

## Agent Instructions
Read `src/strategies/models.py` for the exact `StrategyDefinition` schema and valid condition keys. Read `src/strategies/indicators.py` for indicator parameter ranges. The 12 entry conditions are AND logic (all must pass); the 7 exit conditions are OR logic (first triggered exits).

## Estimated Complexity
Low-Medium — mostly configuration, but must match the exact schema.
