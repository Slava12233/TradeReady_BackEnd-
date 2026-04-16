---
task_id: 36
title: "Document synthetic order book"
type: task
agent: "doc-updater"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["docs/features/market-data.mdx", "Frontend/src/components/coin/order-book.tsx"]
tags:
  - task
  - documentation
  - transparency
  - P2
---

# Task 36: Document synthetic order book

## Assigned Agent: `doc-updater`

## Objective
The order book shows synthetic data, not real market depth. This should be clearly documented so users don't make decisions based on synthetic depth.

## Context
Feature completeness audit (SR-09) flagged this. The order book component exists and renders data, but it's generated, not from a real exchange order book. Users could be misled.

## Files to Modify
- `docs/features/market-data.mdx` — Add section explaining synthetic order book
- `Frontend/src/components/coin/order-book.tsx` — Add subtle "Simulated" badge/tooltip

## Acceptance Criteria
- [ ] Documentation clearly states the order book is synthetic
- [ ] UI shows a "Simulated" indicator on the order book component
- [ ] Explanation of why (simulated exchange doesn't have real order flow)
- [ ] No user can mistake the order book for real market depth

## Agent Instructions
1. Read `Frontend/src/components/coin/CLAUDE.md` for order book component
2. Add a small "Simulated data" badge or tooltip to the order book component
3. Update market data docs to explain what is real (prices, OHLCV) vs simulated (order book)

## Estimated Complexity
Low — documentation + small UI indicator
