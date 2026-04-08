---
task_id: 10
title: "Webhook management UI in Settings page"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [9]
status: "pending"
priority: "medium"
board: "[[recommendations-execution/README]]"
files:
  - "Frontend/src/components/settings/webhook-section.tsx"
  - "Frontend/src/hooks/use-webhooks.ts"
tags:
  - task
  - frontend
  - webhooks
  - settings
---

# Task 10: Webhook Management UI

## Assigned Agent: `frontend-developer`

## Objective
Build a webhook management section in the Settings page: list, create, delete webhooks with event type selection, active status toggle, and test button.

## Context
R3 Component 1. Backend has 6 webhook CRUD endpoints at `/api/v1/webhooks`. Plan details in Section R3.

## Files to Modify/Create
- `Frontend/src/hooks/use-webhooks.ts` — TanStack Query hooks: useWebhooks, useCreateWebhook, useDeleteWebhook, useTestWebhook
- `Frontend/src/components/settings/webhook-section.tsx` — List table, create dialog, test/delete buttons
- Wire into `Frontend/src/app/(dashboard)/settings/page.tsx`

## Acceptance Criteria
- [ ] List shows: URL, events (badges), active status, failure count, last triggered
- [ ] Create dialog: URL input, event checkboxes (4 types), description field
- [ ] Secret displayed once after creation with copy button
- [ ] Delete with confirmation dialog
- [ ] Test button calls POST /webhooks/{id}/test with success toast
- [ ] Active/inactive toggle
- [ ] Loading states and error handling
- [ ] Follows existing Settings page patterns

## Agent Instructions
1. Read `Frontend/src/components/settings/CLAUDE.md`
2. Read `Frontend/src/hooks/CLAUDE.md` for TanStack Query patterns
3. Supported events: `backtest.completed`, `strategy.test.completed`, `strategy.deployed`, `battle.completed`
4. Use shadcn/ui components (Dialog, Switch, Badge, Table)

## Estimated Complexity
Medium — CRUD UI with special touches (secret display, test button).
