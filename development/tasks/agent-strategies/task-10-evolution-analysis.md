---
task_id: 10
title: "Evolution analysis & reporting"
agent: "ml-engineer"
phase: B
depends_on: [9]
status: "completed"
priority: "medium"
files: ["agent/strategies/evolutionary/analyze.py"]
---

# Task 10: Evolution analysis & reporting

## Assigned Agent: `ml-engineer`

## Objective
Analyze evolution results: which parameters converged, how the champion trades, and how it compares to a random baseline. Use battle replay data to understand the champion's behavior.

## Files to Create
- `agent/strategies/evolutionary/analyze.py`:
  - Load evolution log from disk
  - Plot fitness curve (best/avg/worst per generation) — save as JSON data points
  - Analyze parameter convergence: which params stabilized, which stayed variable
  - Run champion vs random baseline in a final battle
  - Use `GET /api/v1/battles/{id}/replay` to review champion's trades
  - Compute: avg trade duration, most-traded pairs, entry/exit patterns
  - Output: `EvolutionReport` (Pydantic model) saved to `agent/reports/`

## Acceptance Criteria
- [ ] Evolution curve data exported (JSON, plottable)
- [ ] Parameter convergence analysis identifies stable vs variable params
- [ ] Champion vs random battle completed with clear winner
- [ ] Trade behavior analysis shows top patterns (pairs, hold duration, win rate)
- [ ] Report saved to `agent/reports/evolution-report-{timestamp}.json`

## Dependencies
- Task 09: evolution complete with champion genome and log

## Agent Instructions
The replay endpoint returns paginated trade data. Aggregate across all battle steps. Focus on actionable insights: "the evolution converged on RSI_oversold=28, stop_loss=2.3%, and always traded BTC+ETH (never SOL)."

## Estimated Complexity
Medium — data analysis and API queries.
