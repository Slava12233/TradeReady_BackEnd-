---
task_id: 03
title: "Create Privacy Policy page"
type: task
agent: "planner"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/app/(legal)/privacy/page.tsx", "Frontend/src/components/legal/privacy-policy.tsx"]
tags:
  - task
  - legal
  - frontend
  - gdpr
  - P0
---

# Task 03: Create Privacy Policy page

## Assigned Agent: `planner` (draft content) then `frontend-developer` (implement page)

## Objective
Create a Privacy Policy page. Required by GDPR if targeting EU users, and generally expected by all users of a platform that collects account data.

## Context
Marketing readiness audit (SR-11) flagged no Privacy Policy as a P0 legal liability. The platform collects: username, display_name, email (if added later), API keys, trading activity, agent configurations.

## Key Privacy Policy Sections Needed
1. What data we collect (account info, trading activity, agent configs, API usage logs)
2. How we use data (provide service, improve platform, analytics)
3. Data storage and security (bcrypt passwords, encrypted API keys, PostgreSQL/TimescaleDB)
4. Data retention (how long we keep data, deletion policy)
5. Third-party services (Binance market data feed — read-only, no user data shared)
6. Cookies and tracking (if any)
7. User rights (access, deletion, export — GDPR compliance)
8. Children's privacy (13+ or 18+ depending on jurisdiction)
9. Changes to policy (notification method)
10. Contact information

## Files to Create/Modify
- `Frontend/src/app/(legal)/privacy/page.tsx` — New route for /privacy
- `Frontend/src/components/legal/privacy-policy.tsx` — Privacy Policy content component
- `Frontend/src/components/layout/footer.tsx` — Add link to /privacy

## Acceptance Criteria
- [ ] /privacy route renders a complete Privacy Policy page
- [ ] Policy covers all 10 sections listed above
- [ ] GDPR-relevant rights (access, erasure, portability) mentioned
- [ ] Page is accessible from footer/navigation
- [ ] Page uses consistent platform styling

## Agent Instructions
1. Read `Frontend/CLAUDE.md` for conventions
2. Follow same pattern as Task 02 (ToS page) for layout consistency
3. Be specific about what data is collected — reference the actual platform architecture

## Estimated Complexity
Medium — content drafting + frontend page creation
