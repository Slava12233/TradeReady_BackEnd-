---
task_id: 9
title: "Add webhook/indicator/compare/batch API functions + types to frontend"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [3]
status: "pending"
priority: "medium"
board: "[[recommendations-execution/README]]"
files:
  - "Frontend/src/lib/api-client.ts"
  - "Frontend/src/lib/types.ts"
tags:
  - task
  - frontend
  - api-client
  - types
---

# Task 09: Add API Functions + TypeScript Types for V.0.0.3 Endpoints

## Assigned Agent: `frontend-developer`

## Objective
Add API client functions and TypeScript interfaces for all V.0.0.3 backend endpoints: webhooks (CRUD), indicators, strategy comparison, batch backtest.

## Context
R3 from the C-level report. The plan at `development/recommendations-execution-plan.md` Section R3 has the exact TypeScript interfaces and function signatures.

## Files to Modify/Create
- `Frontend/src/lib/api-client.ts` — Add functions: listWebhooks, createWebhook, deleteWebhook, testWebhook, getIndicators, getAvailableIndicators, compareStrategies
- `Frontend/src/lib/types.ts` — Add interfaces: WebhookSubscription, IndicatorValues, StrategyCompareResult, BatchStepFastResponse

## Acceptance Criteria
- [ ] All TypeScript interfaces match Pydantic schemas (verify against `src/api/schemas/`)
- [ ] All API functions follow existing patterns in api-client.ts
- [ ] `pnpm build` passes with zero TS errors
- [ ] No runtime imports added (types only + fetch wrappers)

## Dependencies
- **Task 3** (deploy complete, endpoints live)

## Agent Instructions
1. Read `Frontend/src/lib/CLAUDE.md` for API client patterns
2. Read `development/recommendations-execution-plan.md` Section R3 for exact TypeScript code
3. Read `src/api/schemas/webhooks.py`, `indicators.py`, `strategies.py`, `backtest.py` to verify type alignment

## Estimated Complexity
Low — TypeScript types and fetch wrappers following existing patterns.
