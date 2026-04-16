---
task_id: 04
title: "Add support/contact channel"
type: task
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/app/(legal)/contact/page.tsx", "Frontend/src/components/layout/footer.tsx", "Frontend/src/components/layout/sidebar.tsx"]
tags:
  - task
  - support
  - frontend
  - P0
---

# Task 04: Add support/contact channel

## Assigned Agent: `frontend-developer`

## Objective
Users currently have no way to report bugs or ask questions. Add a contact/support page with at minimum an email address, and optionally a link to a Discord/GitHub issues page.

## Context
Marketing readiness audit (SR-11) flagged no support channel as a P0 user abandonment risk. Users who hit issues will leave permanently if they can't report them.

## Files to Create/Modify
- `Frontend/src/app/(legal)/contact/page.tsx` — Contact/support page
- `Frontend/src/components/layout/footer.tsx` — Add support link to footer
- `Frontend/src/components/layout/sidebar.tsx` — Add help/support link to sidebar

## Acceptance Criteria
- [ ] /contact page exists with support email (support@tradeready.io or placeholder)
- [ ] Footer contains a "Support" or "Contact" link
- [ ] Sidebar has a help/support icon/link
- [ ] Page lists: email, GitHub issues URL (for bug reports), Discord (optional)
- [ ] Page uses consistent platform styling

## Agent Instructions
1. Read `Frontend/src/components/layout/CLAUDE.md` for sidebar/footer patterns
2. Keep it simple — a static page with contact methods is sufficient
3. Use a mailto: link for email, standard href for GitHub issues
4. Match the visual style of existing static pages (docs, landing)

## Estimated Complexity
Low — static page + navigation links
