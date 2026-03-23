---
task_id: 13
title: "Run evolutionary strategy optimization (30 generations)"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [3, 12]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/evolutionary/evolve.py"]
tags:
  - task
  - ml
  - training
  - evolutionary
---

# Task 13: Run evolutionary optimization

## Assigned Agent: `ml-engineer`

## Objective
Execute the genetic algorithm to evolve optimal strategy parameters using platform battles.

## Steps
1. `python -m agent.strategies.evolutionary.evolve --generations 30 --pop-size 12 --seed 42`
2. Monitor convergence — expect stabilization within 20-30 generations
3. `python -m agent.strategies.evolutionary.analyze --log-path agent/strategies/evolutionary/results/evolution_log.json`
4. Save champion genome parameters

## Acceptance Criteria
- [ ] Evolution completes 30 generations (or converges early)
- [ ] Champion genome saved to `champion.json`
- [ ] Analysis report generated showing fitness curve and parameter convergence
- [ ] Champion strategy registered on platform via `POST /api/v1/strategies`

## Dependencies
- Requires Task 03 (agents provisioned) for battle participants
- Requires Task 12 (upgraded fitness function)

## Estimated Complexity
High — long compute time (depends on battle duration × generations). May take hours.
