---
task_id: 02
title: "Create Terms of Service page"
type: task
agent: "planner"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/app/(legal)/terms/page.tsx", "Frontend/src/components/legal/terms-of-service.tsx"]
tags:
  - task
  - legal
  - frontend
  - P0
---

# Task 02: Create Terms of Service page

## Assigned Agent: `planner` (draft content) then `frontend-developer` (implement page)

## Objective
Create a Terms of Service page for the TradeReady platform. This is legally required before any customer touches a trading platform, even a simulated one.

## Context
Marketing readiness audit (SR-11) flagged no ToS as a P0 legal liability. The platform handles simulated crypto trading with virtual USDT — ToS must clarify this is NOT real trading, no real money is at risk, and define platform usage rules.

## Key ToS Sections Needed
1. Service description (simulated crypto trading platform, virtual USDT)
2. Account terms (one account per person, API key responsibility)
3. Acceptable use (no abusive API usage, no real-money claims)
4. Intellectual property (user strategies remain theirs, platform IP is ours)
5. Disclaimers (not financial advice, no real trading, simulated data)
6. Limitation of liability
7. Termination (we can suspend accounts)
8. Governing law placeholder
9. Contact information

## Files to Create/Modify
- `Frontend/src/app/(legal)/terms/page.tsx` — New route for /terms
- `Frontend/src/components/legal/terms-of-service.tsx` — ToS content component
- `Frontend/src/components/layout/footer.tsx` — Add link to /terms (if footer exists)

## Acceptance Criteria
- [ ] /terms route renders a complete Terms of Service page
- [ ] ToS clearly states this is simulated trading with virtual currency
- [ ] ToS includes all 9 sections listed above
- [ ] Page is accessible from footer/navigation
- [ ] Page uses consistent platform styling

## Agent Instructions
1. Read `Frontend/CLAUDE.md` and `Frontend/src/app/CLAUDE.md` for routing patterns
2. Check existing legal/static pages for layout patterns to follow
3. Create a route group `(legal)` if it doesn't exist, or use the existing app router structure
4. Content should be professional but clear — this is a developer-facing platform, not a bank

## Estimated Complexity
Medium — content drafting + frontend page creation
