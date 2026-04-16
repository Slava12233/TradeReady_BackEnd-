---
task_id: 11
title: "Verify legal pages load (/terms, /privacy, /contact)"
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
  - legal
---

# Task 11: Verify legal pages load

## Objective
Confirm all three new legal/support pages render correctly in production.

## Acceptance Criteria
- [ ] `https://tradeready.io/terms` returns 200 with full 9-section Terms of Service
- [ ] `https://tradeready.io/privacy` returns 200 with full 10-section Privacy Policy (GDPR sections present)
- [ ] `https://tradeready.io/contact` returns 200 with email link, GitHub issues link, FAQ
- [ ] Sticky sidebar TOC renders on desktop (ToS + Privacy)
- [ ] "Back to dashboard" links work from Contact page
- [ ] Pages are listed in `https://tradeready.io/sitemap.xml`

## Dependencies
Task 07 — frontend deployed.

## Agent Instructions
1. Visit each of `/terms`, `/privacy`, `/contact`
2. Scroll through each page and verify content renders (not blank or error)
3. Verify TOC sidebar highlights as you scroll (Terms, Privacy only)
4. Check `curl -s https://tradeready.io/sitemap.xml | grep -E "terms|privacy|contact"` — all 3 present
5. Click through links between pages (e.g., ToS cross-link to Privacy)

## Estimated Complexity
Low — visual smoke test
