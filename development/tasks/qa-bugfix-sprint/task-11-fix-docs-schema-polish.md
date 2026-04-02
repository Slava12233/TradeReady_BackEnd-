---
task_id: 11
title: "Fix docs & schema for candles/pairs/stop_price (BUG-013/014/015)"
type: task
agent: "doc-updater"
phase: 3
depends_on: []
status: "pending"
priority: "low"
board: "[[qa-bugfix-sprint/README]]"
files: ["docs/api_reference.md", "src/api/schemas/trading.py", "scripts/seed_pairs.py"]
tags:
  - task
  - documentation
  - schema
  - P2
  - P3
---

# Task 11: Fix docs & schema for candles, pairs, stop_price (BUG-013/014/015)

## Assigned Agent: `doc-updater`

## Objective
Fix three documentation/schema inconsistencies:
1. **BUG-013:** Document that candles uses path param `/candles/{symbol}`, not query param
2. **BUG-014:** Update pair count in docs (439 actual vs 647 documented) + re-run seed script
3. **BUG-015:** Either add `stop_price` alias to `OrderRequest` schema OR update docs to say `price`

## Files to Modify/Create
- `docs/api_reference.md` — fix candles endpoint docs, pair count
- `src/api/schemas/trading.py` — optionally add `stop_price` as alias for `price` (line ~112)
- Documentation referencing pair count or stop_price field

## Acceptance Criteria
- [ ] Candles endpoint documented as `GET /market/candles/{symbol}?interval=1h&limit=100`
- [ ] Pair count in docs matches reality (or notes it varies by exchange activity)
- [ ] Stop-loss order documentation says `price` (or `stop_price` accepted as alias)
- [ ] SDK examples use correct field names

## Dependencies
None.

## Agent Instructions
1. For BUG-013: Grep for any docs/SDK references to `GET /market/candles?symbol=` and change to path param style
2. For BUG-014: Run `python scripts/seed_pairs.py` to refresh pairs, then count and update docs
3. For BUG-015: Decide whether to add alias or just fix docs:
   - **If adding alias:** In `src/api/schemas/trading.py`, use `validation_alias=AliasChoices("price", "stop_price")` on the `price` field
   - **If docs only:** Update all references from `stop_price` to `price`
4. Verify changes are consistent across all docs, SDK, and CLAUDE.md files

## Estimated Complexity
Low — mostly text changes with one optional schema tweak.
