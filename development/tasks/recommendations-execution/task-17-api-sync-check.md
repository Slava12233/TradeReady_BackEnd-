---
task_id: 17
title: "API sync check: frontend types vs backend schemas"
type: task
agent: "api-sync-checker"
phase: 3
depends_on: [9, 14]
status: "pending"
priority: "medium"
board: "[[recommendations-execution/README]]"
files: []
tags:
  - task
  - api-sync
  - frontend
  - backend
---

# Task 17: API Sync Check

## Assigned Agent: `api-sync-checker`

## Objective
Verify all new TypeScript types in the frontend match the Pydantic schemas in the backend.

## Context
Task 9 added frontend types for webhooks, indicators, strategy comparison, and batch backtest. This verifies alignment.

## Acceptance Criteria
- [ ] WebhookSubscription TS type matches WebhookResponse Pydantic schema
- [ ] IndicatorValues TS type matches IndicatorResponse schema
- [ ] StrategyCompareResult TS type matches StrategyComparisonResponse schema
- [ ] BatchStepFastResponse TS type matches BatchStepFastResponse schema
- [ ] API route paths in api-client.ts match backend route paths
- [ ] Report any mismatches

## Dependencies
- **Tasks 9, 14** (frontend types added and build passes)

## Estimated Complexity
Low — comparison of types across two languages.
