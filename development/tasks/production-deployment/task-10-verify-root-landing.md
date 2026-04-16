---
task_id: 10
title: "Verify root URL serves landing page"
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

# Task 10: Verify root URL serves landing page (not Coming Soon)

## Objective
Confirm Task 10 of customer launch fixes landed: visiting `https://tradeready.io/` shows the marketing landing page, not the old Coming Soon page.

## Acceptance Criteria
- [ ] `curl -sL https://tradeready.io/` does NOT contain "Coming Soon"
- [ ] Response contains hero section copy ("Your AI Agent Trades Crypto" or similar)
- [ ] `<title>` is "TradeReady — Your AI Agent Trades Crypto in 5 Minutes"
- [ ] Landing page CSS loads (check for `landing.css`)
- [ ] Navigation links to `/login`, `/register`, `/docs` are present
- [ ] Links to `/terms`, `/privacy`, `/contact` in footer are present

## Dependencies
Task 07 — frontend is deployed via Vercel, but the check is the same.

## Agent Instructions
1. Visit `https://tradeready.io/` in a real browser
2. Verify the hero section renders (not Coming Soon template)
3. Check page source: `view-source:https://tradeready.io/` — confirm no "Coming Soon" text
4. Scroll through the page — all landing sections should render (hero, price ticker, features, footer)
5. Check footer for ToS/Privacy/Contact links

## Estimated Complexity
Low — visual smoke test
