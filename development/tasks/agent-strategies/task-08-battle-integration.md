---
task_id: 08
title: "Battle integration runner"
type: task
agent: "backend-developer"
phase: B
depends_on: [7]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "high"
files: ["agent/strategies/evolutionary/battle_runner.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 08: Battle integration runner

## Assigned Agent: `backend-developer`

## Objective
Build the bridge between the genetic algorithm and the platform's battle system: create agents, assign strategy genomes, run historical battles, and extract fitness scores.

## Files to Create
- `agent/strategies/evolutionary/battle_runner.py`:
  - `BattleRunner` class:
    - `__init__(config: AgentConfig, rest_client: PlatformRESTClient)`
    - `setup_agents(population_size: int)` → create N agents via REST, store agent_ids
    - `reset_agents()` → reset all agent balances via REST
    - `assign_strategies(genomes: list[StrategyGenome])` → create/update strategy per agent via REST
    - `run_battle(preset: str, historical_window: tuple[str, str])` → create battle, add participants, run to completion, return battle_id
    - `get_fitness(battle_id: str)` → fetch results, compute fitness per agent: `sharpe - 0.5 * max_drawdown_pct`
    - `cleanup(battle_id: str)` → optional cleanup of battle data
  - Uses `agent/tools/rest_tools.py` PlatformRESTClient for all API calls
  - Polls battle status every 5 seconds until `completed`
  - Handles battle failures gracefully (agent gets fitness = -999)

## Acceptance Criteria
- [ ] Creates N agents programmatically (reuses across generations via reset)
- [ ] Assigns strategy definitions from genomes correctly
- [ ] Creates and runs historical battle to completion
- [ ] Extracts fitness scores for all participants
- [ ] Handles API errors (timeout, 500) without crashing
- [ ] Agent creation uses unique names: `evo-gen{N}-agent{M}`
- [ ] Logging shows battle progress: created → started → running → completed

## Dependencies
- Task 07: genome-to-strategy conversion works
- Platform running with battle system functional
- Historical candle data loaded

## Agent Instructions
Read `src/battles/CLAUDE.md` for battle lifecycle and presets. Read `src/api/routes/CLAUDE.md` for the 20 battle endpoints. Use the `historical_week` preset for standard runs. The battle engine is synchronous for historical mode — the client drives stepping via REST.

**Important:** Historical battles require the client to drive stepping. Use `POST /api/v1/battles/{id}/step` in a loop. Check `src/battles/historical_engine.py` for how the step API works.

## Estimated Complexity
Medium-High — significant API integration with error handling.
