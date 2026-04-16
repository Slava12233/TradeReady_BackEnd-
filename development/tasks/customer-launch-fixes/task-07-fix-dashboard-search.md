---
task_id: 07
title: "Fix dashboard header search bar"
type: task
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/components/layout/header.tsx"]
tags:
  - task
  - frontend
  - ux
  - search
  - P0
---

# Task 07: Fix dashboard header search bar

## Assigned Agent: `frontend-developer`

## Objective
The search bar in the dashboard header is non-functional — typing does nothing. Either implement search functionality or remove the dead UI element.

## Context
Frontend UX audit (SR-05) flagged this as a P0 poor-first-impression issue. A broken search bar signals an unfinished product.

## Files to Modify
- `Frontend/src/components/layout/header.tsx` — Fix or implement search functionality

## Acceptance Criteria
- [ ] Search bar either works (filters/searches available content) or is removed
- [ ] If implemented: searching for a coin name navigates to that coin's page
- [ ] If implemented: searching for a menu item navigates to that page
- [ ] No visual artifacts or dead UI elements remain
- [ ] Existing header tests (if any) still pass

## Agent Instructions
1. Read `Frontend/src/components/layout/CLAUDE.md` for header component patterns
2. Read the current header.tsx to understand the search bar implementation
3. Decide: implement basic search (Cmd+K style, filter market pairs + nav items) or remove the search input
4. If implementing: use the existing market data hooks to search trading pairs
5. If removing: ensure layout doesn't break without the search element

## Estimated Complexity
Medium — depends on whether implementing search or removing it
