---
task_id: 09
title: "Train regime classifier on 12 months historical data"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [8]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/regime/classifier.py"]
tags:
  - task
  - ml
  - training
  - regime
---

# Task 09: Train regime classifier

## Assigned Agent: `ml-engineer`

## Objective
Train the XGBoost regime classifier on 12 months of BTC 1h data, validate accuracy, generate checksum, and run the full validation pipeline.

## Steps
1. `python -m agent.strategies.regime.classifier --train --data-url http://localhost:8000`
2. Verify accuracy ≥ 70% on temporal test split
3. Verify SHA-256 checksum sidecar created
4. `python -m agent.strategies.regime.switcher --demo --candles 300`
5. `python -m agent.strategies.regime.validate --base-url http://localhost:8000 --months 12`

## Acceptance Criteria
- [ ] Model file saved with `.sha256` checksum sidecar
- [ ] Test accuracy ≥ 70%
- [ ] Switcher demo runs without errors
- [ ] 12-month validation shows regime-adaptive outperforms static strategy

## Estimated Complexity
Medium — mostly compute time, but may need parameter tuning if accuracy is low.
