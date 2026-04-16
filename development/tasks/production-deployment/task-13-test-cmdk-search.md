---
task_id: 13
title: "Test Cmd+K search on dashboard"
type: task
agent: "e2e-tester"
phase: 2
depends_on: [7]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - smoke-test
  - frontend
---

# Task 13: Test Cmd+K search on dashboard

## Objective
Verify the fix from Task 07 (customer launch fixes): the dashboard search bar now opens a functional Cmd+K command palette.

## Acceptance Criteria
- [ ] Login to the dashboard (use credentials from Task 12)
- [ ] Clicking the search field in the header opens the overlay
- [ ] Pressing `Cmd+K` (Mac) or `Ctrl+K` (Win/Linux) opens the overlay
- [ ] Typing "BTC" filters trading pairs — BTCUSDT appears
- [ ] Typing a nav keyword (e.g., "market") filters navigation items
- [ ] Arrow keys Up/Down move the active item
- [ ] Enter navigates to the selected item
- [ ] Escape closes the overlay
- [ ] Overlay shows keyboard hint (Cmd+K shortcut indicator)

## Dependencies
Task 07 — frontend deployed. Test account from Task 12.

## Agent Instructions
1. Log into `https://tradeready.io/login` with a test account
2. From the dashboard, click the header search area OR press `Ctrl+K`
3. Verify overlay opens with input focused
4. Type "BTC" — verify BTCUSDT (and other BTC pairs) appear
5. Press Enter — verify navigation to the coin detail page
6. Reopen (Ctrl+K), type "market" — verify Market nav item appears
7. Press Enter — verify navigation to `/market`
8. Reopen and press Escape — overlay closes
9. Verify no console errors during these interactions

## Estimated Complexity
Low — UI smoke test
