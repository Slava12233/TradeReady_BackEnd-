---
task_id: B-07
title: "Validate with DSR API"
type: task
agent: "ml-engineer"
track: B
depends_on: ["B-06"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["src/metrics/deflated_sharpe.py"]
tags:
  - task
  - ml
  - validation
  - dsr
---

# Task B-07: Validate with DSR API

## Assigned Agent: `ml-engineer`

## Objective
Submit the trained model's OOS returns to the Deflated Sharpe Ratio (DSR) API endpoint to confirm the model isn't just a lucky backtest result.

## Context
DSR accounts for multiple testing bias — the more models you try, the more likely one looks good by chance. A DSR p-value < 0.05 means the Sharpe ratio is statistically significant.

## Files to Reference
- `src/metrics/deflated_sharpe.py` — DSR calculation logic
- API endpoint for DSR validation

## Acceptance Criteria
- [ ] DSR endpoint returns a valid response
- [ ] DSR p-value documented
- [ ] If p-value < 0.05: model passes validation
- [ ] If p-value >= 0.05: document as "not statistically significant" (expected for first model)
- [ ] Record number of trials/models tested (should be 1 for first run)

## Dependencies
- **B-06**: OOS evaluation metrics needed as input

## Agent Instructions
Read `src/metrics/deflated_sharpe.py` to understand the DSR implementation. Call the API endpoint with the OOS returns data. With only 1 model tested, DSR should be similar to regular Sharpe — but this validates the pipeline works for future multi-model comparisons. Even if DSR doesn't pass the 0.05 threshold, that's OK for a first model — document the result.

## Estimated Complexity
Low — API call and documentation.
