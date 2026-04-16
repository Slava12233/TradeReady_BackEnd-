---
task_id: 09
title: "Unify branding to TradeReady"
type: task
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/components/layout/sidebar.tsx", "Frontend/src/components/landing/hero-section.tsx", "Frontend/src/components/coming-soon/coming-soon.tsx"]
tags:
  - task
  - frontend
  - branding
  - ux
  - P1
---

# Task 09: Unify branding to TradeReady

## Assigned Agent: `frontend-developer`

## Objective
The platform uses 3 different names: "TradeReady.io", "AGENT X", and "TradeReady". Unify all references to a single brand name: **TradeReady**.

## Context
Frontend UX audit (SR-05) flagged inconsistent branding as a HIGH issue. Users encounter different names in sidebar, landing page, and Coming Soon page — this creates a confused identity.

## Files to Modify
- Search entire `Frontend/src/` for "AGENT X", "TradeReady.io", and normalize to "TradeReady"
- Key files likely: sidebar.tsx, hero-section.tsx, coming-soon.tsx, any metadata/title files
- `Frontend/src/app/layout.tsx` — Check page title/metadata

## Acceptance Criteria
- [ ] Zero instances of "AGENT X" remain in the frontend codebase
- [ ] "TradeReady.io" only used where a full domain is appropriate (footer, docs)
- [ ] All UI-facing text uses "TradeReady" consistently
- [ ] Page title / meta tags use "TradeReady"
- [ ] Favicon and any logo references are consistent

## Agent Instructions
1. Grep for "AGENT X" (case-insensitive) across all frontend files
2. Grep for "TradeReady.io" and decide case-by-case (domain references OK, brand name should be "TradeReady")
3. Update all instances
4. Check `<title>`, `<meta>` tags in layout.tsx and page files

## Estimated Complexity
Low — search and replace across a known set of files
