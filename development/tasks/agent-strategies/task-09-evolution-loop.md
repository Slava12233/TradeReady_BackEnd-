---
task_id: 09
title: "Evolution loop orchestrator"
type: task
agent: "ml-engineer"
phase: B
depends_on: [7, 8]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "high"
files: ["agent/strategies/evolutionary/evolve.py", "agent/strategies/evolutionary/config.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 09: Evolution loop orchestrator

## Assigned Agent: `ml-engineer`

## Objective
Build the main evolution script that runs N generations: initialize population → run battle → rank → evolve → repeat. Includes convergence detection and champion tracking.

## Files to Create
- `agent/strategies/evolutionary/config.py`:
  - `EvolutionConfig(BaseSettings)`:
    - population_size: 12
    - generations: 30
    - elite_pct: 0.2
    - mutation_rate: 0.1
    - mutation_strength: 0.1
    - battle_preset: "historical_week"
    - historical_start/end: date range for battles
    - convergence_threshold: 5 (generations with no improvement)
    - fitness_fn: "sharpe_minus_drawdown"
    - seed: 42

- `agent/strategies/evolutionary/evolve.py`:
  - CLI: `python -m agent.strategies.evolutionary.evolve --generations 30 --pop-size 12`
  - Main loop:
    1. Initialize population (random genomes)
    2. For each generation:
       a. Reset agents, assign genomes as strategies
       b. Run historical battle
       c. Get fitness scores
       d. Log: gen #, best/avg/worst fitness, best genome params
       e. Check convergence (fitness plateau for N generations)
       f. Save champion genome as strategy version via API
       g. Evolve population → next generation
    3. Final: save champion genome to disk, log summary
  - Outputs:
    - `agent/strategies/evolutionary/results/evolution_log.json` — per-generation stats
    - `agent/strategies/evolutionary/results/champion.json` — best genome
    - Strategy version on platform (champion's params)

## Acceptance Criteria
- [ ] Full evolution loop runs for 30 generations without crashes
- [ ] Best fitness improves over generations (not flat from gen 1)
- [ ] Convergence detection stops early if no improvement for 5 generations
- [ ] Champion genome is saved to disk AND as a strategy version on the platform
- [ ] Evolution log is JSON-serializable with per-generation stats
- [ ] Logging shows clear progress: `gen 15/30 | best: 1.42 | avg: 0.87 | worst: -0.23`
- [ ] Handles battle failures (skip generation, log error, continue)
- [ ] `--seed` flag ensures reproducible evolution

## Dependencies
- Task 07: genome, operators, population management
- Task 08: battle runner creates/runs battles
- Platform running with battles and backtesting

## Agent Instructions
Start with a small test: 3 generations, 4 agents. Verify the loop works before scaling to 30x12. The biggest risk is battle API failures mid-evolution — build retry logic. Use `structlog` for all logging.

## Estimated Complexity
High — orchestrating multiple platform APIs in a long-running loop.
