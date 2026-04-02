---
task_id: 04
title: "Update docs for correct backtest/analytics URLs (BUG-007/008/009/010)"
type: task
agent: "doc-updater"
phase: 1
depends_on: []
status: "pending"
priority: "medium"
board: "[[qa-bugfix-sprint/README]]"
files: ["docs/api_reference.md", "docs/skill.md", "sdk/", "src/api/routes/CLAUDE.md"]
tags:
  - task
  - documentation
  - backtest
  - analytics
  - P1
---

# Task 04: Update documentation for correct backtest & analytics URLs

## Assigned Agent: `doc-updater`

## Objective
Fix all documentation that references incorrect API paths for backtest and analytics endpoints. The routes exist in the codebase but are documented with wrong URLs, causing QA to report false 404s.

## Context
QA tested these wrong URLs (all returned 404):
- `POST /backtest/{id}/trade` → correct: `POST /api/v1/backtest/{session_id}/order`
- `GET /backtest/{id}/equity` → correct: `GET /api/v1/backtest/{session_id}/results/equity-curve`
- `GET /backtest/sessions` → correct: `GET /api/v1/backtest/list`
- `GET /analytics/portfolio-history` → correct: `GET /api/v1/analytics/portfolio/history`

## Files to Modify/Create
- `docs/api_reference.md` — fix all backtest and analytics endpoint paths
- `docs/skill.md` — if it references these endpoints
- `sdk/` — check SDK client methods for wrong paths
- `src/api/routes/CLAUDE.md` — verify route table matches actual registered routes
- `src/backtesting/CLAUDE.md` — verify endpoint references
- `Frontend/src/lib/api-client.ts` — check if frontend uses wrong paths

## Acceptance Criteria
- [ ] All backtest endpoint paths in docs match `src/api/routes/backtest.py` registered routes
- [ ] All analytics endpoint paths in docs match `src/api/routes/analytics.py` registered routes
- [ ] SDK client uses correct paths
- [ ] Frontend API client uses correct paths
- [ ] No remaining references to the wrong URLs anywhere in the codebase

## Dependencies
None — documentation-only changes.

## Agent Instructions
1. Read `src/api/routes/backtest.py` to get the definitive list of all registered backtest routes
2. Read `src/api/routes/analytics.py` for all analytics routes
3. Grep the entire codebase for the wrong URL patterns: `/backtest/sessions`, `/backtest/{id}/trade`, `/backtest/{id}/equity`, `/analytics/portfolio-history`
4. Fix every occurrence to match the actual registered paths
5. Also verify the candles endpoint is documented as path param (`/market/candles/{symbol}`) not query param

## Estimated Complexity
Low — find-and-replace across docs and client code.
