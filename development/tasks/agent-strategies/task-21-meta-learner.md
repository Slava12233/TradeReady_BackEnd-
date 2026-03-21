---
task_id: 21
title: "Meta-learner signal combiner"
type: task
agent: "ml-engineer"
phase: E
depends_on: [5, 10, 14]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "low"
files: ["agent/strategies/ensemble/__init__.py", "agent/strategies/ensemble/meta_learner.py", "agent/strategies/ensemble/signals.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 21: Meta-learner signal combiner

## Assigned Agent: `ml-engineer`

## Objective
Build the ensemble signal combiner that takes trading signals from 3 different strategies (PPO, evolved, regime) and produces a single consensus signal via confidence-weighted voting.

## Files to Create
- `agent/strategies/ensemble/__init__.py`
- `agent/strategies/ensemble/signals.py`:
  - `SignalSource` enum: RL, EVOLVED, REGIME
  - `WeightedSignal` model: source, symbol, action (BUY/SELL/HOLD), confidence, metadata
  - `ConsensusSignal` model: symbol, action, combined_confidence, contributing_signals, agreement_rate

- `agent/strategies/ensemble/meta_learner.py`:
  - `MetaLearner` class:
    - `__init__(weights: dict[SignalSource, float])` — per-source weight (default equal)
    - `combine(signals: list[WeightedSignal])` → ConsensusSignal:
      1. Group by symbol
      2. Per symbol: weighted vote = sum(signal.action * signal.confidence * weight)
      3. If combined confidence > threshold (0.6) → act
      4. If all disagree → output HOLD (disagreement = uncertainty)
    - `agreement_rate(signals)` → float (0-1, how much signals agree)
    - Properties: `confidence_threshold`, `min_agreement_rate`
  - Signal conversion:
    - PPO weights → BUY/SELL/HOLD per asset (weight increase = BUY, decrease = SELL, same = HOLD)
    - Evolved strategy → BUY/SELL/HOLD from StrategyExecutor.decide()
    - Regime strategy → BUY/SELL/HOLD from active regime's strategy

## Acceptance Criteria
- [ ] 3/3 agreement → high combined confidence (>0.8)
- [ ] 2/3 agreement → medium confidence (check if > threshold)
- [ ] 0/3 agreement → HOLD output
- [ ] Weights are configurable and normalized (sum to 1.0)
- [ ] Agreement rate accurately reflects signal consensus
- [ ] Signal conversion from each source produces valid WeightedSignal
- [ ] Handles missing signals (source offline → treated as HOLD with confidence 0)

## Dependencies
- Task 05: PPO deploy bridge (produces portfolio weights → signals)
- Task 10: evolved champion (produces strategy-based signals)
- Task 14: regime switcher (produces regime-based signals)

## Agent Instructions
The meta-learner is strategy-agnostic — it only sees `WeightedSignal` objects. The signal conversion layer adapts each source's native output. Keep the combiner under 150 lines. Use numpy for weighted voting math.

## Estimated Complexity
Medium — careful signal normalization and edge case handling.
