---
task_id: 8
title: "Webhook management UI in Settings page"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [6]
status: "pending"
priority: "medium"
board: "[[v003-next-steps/README]]"
files:
  - "Frontend/src/components/settings/webhook-settings.tsx"
  - "Frontend/src/lib/api-client.ts"
  - "Frontend/src/hooks/use-webhooks.ts"
tags:
  - task
  - frontend
  - webhooks
  - settings
---

# Task 08: Webhook Management UI in Settings Page

## Assigned Agent: `frontend-developer`

## Objective
Build a webhook management section in the Settings page: list, create, delete webhooks with event type selection, active status, and a test button.

## Context
The backend has 6 webhook CRUD endpoints (`/api/v1/webhooks`). Users need a UI to manage their webhook subscriptions.

## Files to Modify/Create
- `Frontend/src/components/settings/webhook-settings.tsx` — New component: webhook list table, create dialog, test button
- `Frontend/src/lib/api-client.ts` — Add webhook API functions (createWebhook, listWebhooks, deleteWebhook, testWebhook)
- `Frontend/src/hooks/use-webhooks.ts` — TanStack Query hooks for webhook data

## Acceptance Criteria
- [ ] Webhook list shows: URL, events, active status, failure count, last triggered
- [ ] Create dialog with URL input, event type checkboxes, description field
- [ ] Secret displayed once after creation (with copy button)
- [ ] Delete with confirmation dialog
- [ ] Test button that calls POST /webhooks/{id}/test with success toast
- [ ] Toggle active/inactive via switch
- [ ] Loading states and error handling
- [ ] Follows existing Settings page patterns

## Dependencies
- **Task 6** (security fixes verified) — ensures the API is safe to expose in UI

## Agent Instructions
1. Read `Frontend/src/components/settings/CLAUDE.md` for settings page patterns
2. Read `Frontend/src/hooks/CLAUDE.md` for TanStack Query patterns
3. Look at existing settings sections for layout/style patterns
4. Supported events: `backtest.completed`, `strategy.test.completed`, `strategy.deployed`, `battle.completed`

## Estimated Complexity
Medium — standard CRUD UI with a few special touches (secret display, test button).
