---
task_id: 10
title: "Route root URL to product"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [9]
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/app/page.tsx", "Frontend/src/app/(dashboard)/page.tsx"]
tags:
  - task
  - frontend
  - routing
  - ux
  - P1
---

# Task 10: Route root URL to product (not Coming Soon)

## Assigned Agent: `frontend-developer`

## Objective
The root URL (`/`) currently serves the Coming Soon page, hiding the actual product. Change root to serve the landing page or redirect to the dashboard for authenticated users.

## Context
Frontend UX audit (SR-05) flagged this as HIGH — visitors to tradeready.io see "Coming Soon" instead of the actual working platform. The Coming Soon page was created during development but is now counterproductive since the platform is live.

## Files to Modify
- `Frontend/src/app/page.tsx` — Change from Coming Soon to landing page or auth-aware redirect
- Consider: authenticated users → `/dashboard`, unauthenticated → `/landing` or inline landing content

## Acceptance Criteria
- [ ] Root URL (`/`) no longer shows Coming Soon page
- [ ] Unauthenticated visitors see the landing/marketing page
- [ ] Authenticated visitors redirect to dashboard (optional, nice-to-have)
- [ ] Coming Soon page can be removed or kept at a separate route if needed
- [ ] No broken links or navigation regressions

## Dependencies
Task 09 (branding) should complete first so the landing page has consistent branding.

## Agent Instructions
1. Read `Frontend/src/app/CLAUDE.md` for routing conventions
2. The landing page content exists at `/landing` — consider moving it to `/` or redirecting
3. The simplest approach: swap Coming Soon component for Landing page component at root
4. Ensure the auth flow still works (login/register links must remain accessible)

## Estimated Complexity
Low — route swap
