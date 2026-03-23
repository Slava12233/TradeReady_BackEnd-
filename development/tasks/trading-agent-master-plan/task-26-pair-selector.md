---
task_id: 26
title: "Implement smart pair selector"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/trading/pair_selector.py", "agent/trading/loop.py"]
tags:
  - task
  - trading
  - intelligence
---

# Task 26: Smart pair selector

## Assigned Agent: `backend-developer`

## Objective
Create `PairSelector` that dynamically selects the top 20-30 most tradeable pairs based on volume and volatility.

## Implementation
1. Fetch 24h tickers via `GET /api/v1/market/tickers`
2. Filter: minimum $10M daily volume, exclude spread > 5%
3. Rank by volume, select top 30
4. Add "momentum" tier: top 10 by 24h change% (gainers/losers)
5. Cache result for 1 hour, refresh periodically
6. Feed selected pairs to `SignalGenerator` and `EnsembleRunner`

## Files to Create
- `agent/trading/pair_selector.py` — `PairSelector` class

## Acceptance Criteria
- [ ] `PairSelector.get_active_pairs()` returns ranked list of symbols
- [ ] Volume and spread filters applied
- [ ] Momentum tier included (big movers)
- [ ] Results cached with 1-hour TTL
- [ ] Tests with mock ticker data

## Estimated Complexity
Low — data filtering and ranking logic.
