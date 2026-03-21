---
task_id: 10
title: "Run evolutionary training (30 generations)"
type: task
agent: "ml-engineer"
phase: 6
depends_on: [9]
status: "pending"
board: "[[agent-deployment-training/README]]"
priority: "medium"
files: ["agent/strategies/evolutionary/results/"]
tags:
  - task
  - deployment
  - training
---

# Task 10: Run evolutionary training (30 generations)

## Assigned Agent: `ml-engineer`

## Objective
Run the full genetic algorithm evolution loop: 30 generations, 12 agents per generation, using historical battles for fitness evaluation.

## Steps
1. Quick smoke test (3 gen, 4 agents):
   ```bash
   python -m agent.strategies.evolutionary.evolve \
     --generations 3 --pop-size 4 --convergence-threshold 2
   ```
2. If smoke passes, run full evolution:
   ```bash
   python -m agent.strategies.evolutionary.evolve \
     --generations 30 --pop-size 12 --seed 42
   ```

## Acceptance Criteria
- [ ] Smoke test completes without crashes
- [ ] Full evolution runs to completion or converges early
- [ ] Best fitness improves over generations
- [ ] `evolution_log.json` saved with per-generation stats
- [ ] `champion.json` saved with best genome
- [ ] Champion saved as platform strategy version

## Dependencies
- Task 09: battle historical mode working

## Agent Instructions
Read `agent/strategies/evolutionary/CLAUDE.md`. The evolution loop creates agents via JWT auth, assigns strategy genomes, runs historical battles, and extracts fitness. Each generation takes ~5 min. Full run: ~2.5 hours. If battles fail, the loop logs errors and continues with fitness=-999.

## Estimated Complexity
High — long-running, depends on battle API stability.
