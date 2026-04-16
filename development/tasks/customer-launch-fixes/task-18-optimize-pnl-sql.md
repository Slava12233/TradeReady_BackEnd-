---
task_id: 18
title: "Optimize PnL endpoint SQL (reduce 10K row fetch)"
type: task
agent: "backend-developer"
phase: 2
depends_on: [13]
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/portfolio/service.py", "src/database/repositories/portfolio.py"]
tags:
  - task
  - performance
  - database
  - P1
---

# Task 18: Optimize PnL endpoint SQL

## Assigned Agent: `backend-developer`

## Objective
The PnL endpoint fetches up to 10K ORM rows into Python memory for aggregation. Move the aggregation to SQL (SUM, GROUP BY) to reduce memory usage and improve response time.

## Context
Performance audit (SR-08) flagged this as HIGH — loading 10K rows into Python causes memory spikes under load. SQL aggregation is orders of magnitude more efficient.

## Files to Modify
- `src/portfolio/service.py` — Replace Python-side aggregation with SQL query
- `src/database/repositories/portfolio.py` — Add aggregation query method

## Acceptance Criteria
- [ ] PnL calculation done in SQL (SUM, GROUP BY) instead of Python loop
- [ ] Memory usage for PnL endpoint drops significantly (no 10K row fetch)
- [ ] PnL numbers remain identical to current implementation
- [ ] Response time improves for accounts with many trades
- [ ] Test: verify PnL results match between old and new implementation

## Dependencies
Task 13 (PnL period filter fix) should complete first — this task optimizes the same code path.

## Agent Instructions
1. Read `src/portfolio/CLAUDE.md` and `src/database/repositories/CLAUDE.md`
2. Write a SQL query that computes realized PnL, fees, and net PnL using SUM/GROUP BY
3. Replace the current `fetch all rows + Python loop` pattern
4. Use SQLAlchemy's `func.sum()` or raw SQL depending on query complexity
5. Write a comparison test that verifies old and new implementations produce identical results

## Estimated Complexity
Medium — SQL aggregation query + test
