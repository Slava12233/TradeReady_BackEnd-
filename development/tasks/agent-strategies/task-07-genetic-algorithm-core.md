---
task_id: 07
title: "Genetic algorithm core (genome, operators)"
type: task
agent: "ml-engineer"
phase: B
depends_on: []
status: "completed"
board: "[[agent-strategies/README]]"
priority: "high"
files: ["agent/strategies/evolutionary/__init__.py", "agent/strategies/evolutionary/genome.py", "agent/strategies/evolutionary/operators.py", "agent/strategies/evolutionary/population.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 07: Genetic algorithm core (genome, operators)

## Assigned Agent: `ml-engineer`

## Objective
Implement the genetic algorithm primitives: genome encoding (strategy parameters ↔ float vector), crossover, mutation, tournament selection, and population management.

## Files to Create
- `agent/strategies/evolutionary/__init__.py`
- `agent/strategies/evolutionary/genome.py`:
  - `StrategyGenome` — Pydantic model mapping strategy parameters to a float vector:
    - `rsi_oversold`: float (20-40)
    - `rsi_overbought`: float (60-80)
    - `macd_fast`: int (8-15)
    - `macd_slow`: int (20-30)
    - `adx_threshold`: float (15-35)
    - `stop_loss_pct`: float (0.01-0.05)
    - `take_profit_pct`: float (0.02-0.10)
    - `trailing_stop_pct`: float (0.005-0.03)
    - `position_size_pct`: float (0.03-0.20)
    - `max_hold_candles`: int (10-200)
    - `max_positions`: int (1-5)
    - `pairs`: list[str] (subset of available pairs)
  - `to_strategy_definition()` → converts genome to platform `StrategyDefinition` JSONB
  - `from_random(seed)` → random genome within bounds
  - `to_vector()` / `from_vector()` → numpy array conversion

- `agent/strategies/evolutionary/operators.py`:
  - `tournament_select(population, fitness_scores, k=3)` → select one parent
  - `crossover(parent_a, parent_b)` → single-point crossover on parameter vector
  - `mutate(genome, mutation_rate=0.1, mutation_strength=0.1)` → Gaussian perturbation on 1-2 params
  - `clip_genome(genome)` → enforce all parameters within bounds

- `agent/strategies/evolutionary/population.py`:
  - `Population` class:
    - `initialize(size, seed)` → create N random genomes
    - `evolve(fitness_scores, elite_pct=0.2)` → produce next generation
    - `best(fitness_scores)` → return best genome
    - `stats(fitness_scores)` → mean, std, best, worst fitness
    - `generation` counter

## Acceptance Criteria
- [ ] `StrategyGenome` serializes to/from StrategyDefinition JSONB correctly
- [ ] Random genomes are always within parameter bounds
- [ ] Crossover produces child with parameters from both parents
- [ ] Mutation changes 1-2 parameters, result stays within bounds
- [ ] Elite selection preserves top 20% unchanged
- [ ] Population of 12 initializes and evolves for 5 generations without errors
- [ ] All monetary parameters use `Decimal` or are pure ratios (float OK for ratios)

## Dependencies
None — this is pure algorithm code with no platform dependency.

## Agent Instructions
Read `src/strategies/models.py` to understand the exact `StrategyDefinition` schema (entry_conditions, exit_conditions, pairs, timeframe, position_size_pct, max_positions). The genome must map 1:1 to this schema. Use numpy for vector operations. Keep the code under 300 lines total.

## Estimated Complexity
Medium — clean algorithm implementation with careful bounds handling.
