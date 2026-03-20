---
task_id: 11
title: "Evolutionary system tests"
agent: "test-runner"
phase: B
depends_on: [7, 8]
status: "completed"
priority: "medium"
files: ["agent/tests/test_genome.py", "agent/tests/test_operators.py", "agent/tests/test_battle_runner.py"]
---

# Task 11: Evolutionary system tests

## Assigned Agent: `test-runner`

## Objective
Write tests for the genetic algorithm components: genome encoding/decoding, operators (crossover, mutation, selection), and battle runner integration.

## Files to Create
- `agent/tests/test_genome.py`:
  - Random genome is within bounds
  - Genome ↔ StrategyDefinition round-trip
  - Genome ↔ vector round-trip
  - Invalid bounds raise errors

- `agent/tests/test_operators.py`:
  - Crossover produces child with mixed parent genes
  - Mutation changes 1-2 params, stays in bounds
  - Tournament selection picks higher-fitness parent more often (statistical test, 100 runs)
  - Elite selection preserves top N unchanged
  - Population evolves without errors for 5 generations (mock fitness)

- `agent/tests/test_battle_runner.py`:
  - Battle runner creates agents (mock API)
  - Strategy assignment sends correct JSONB
  - Fitness extraction computes `sharpe - 0.5 * drawdown` correctly
  - API failure handling returns fitness = -999

## Acceptance Criteria
- [ ] All tests pass: `pytest agent/tests/test_genome.py agent/tests/test_operators.py agent/tests/test_battle_runner.py -v`
- [ ] Genome round-trip tests verify all 12+ parameters
- [ ] Operator tests are deterministic (fixed seeds)
- [ ] Battle runner tests mock the REST API (no live platform needed)

## Dependencies
- Task 07: genome and operator code
- Task 08: battle runner code

## Agent Instructions
Use `pytest` with fixed seeds for reproducibility. Mock the REST API with `httpx.MockTransport`. For the statistical tournament selection test, run 100 selections and verify higher-fitness parents are picked >60% of the time.

## Estimated Complexity
Medium — multiple test files, mocking required.
