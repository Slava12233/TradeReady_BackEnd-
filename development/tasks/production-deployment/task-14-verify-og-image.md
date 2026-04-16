---
task_id: 14
title: "Verify OG image meta tags"
type: task
agent: "deploy-checker"
phase: 2
depends_on: [7]
status: "pending"
priority: "medium"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - smoke-test
  - seo
  - marketing
---

# Task 14: Verify OG image meta tags

## Objective
Confirm the fix from Task 34 (customer launch fixes): sharing the site on social media shows a preview image.

## Acceptance Criteria
- [ ] `https://tradeready.io/opengraph-image` returns a 1200x630 PNG
- [ ] Homepage HTML contains `<meta property="og:image">` tag
- [ ] Homepage HTML contains `<meta property="og:title">` with TradeReady branding
- [ ] Homepage HTML contains `<meta name="twitter:card" content="summary_large_image">`
- [ ] Preview check on Twitter card validator OR Facebook debugger shows proper preview

## Dependencies
Task 07 — frontend deployed.

## Agent Instructions
1. Fetch OG image: `curl -sI https://tradeready.io/opengraph-image` — verify 200 with `content-type: image/png`
2. View homepage source: `curl -sL https://tradeready.io/ | grep -E 'og:|twitter:'`
3. Verify all required meta tags present
4. Test social preview:
   - Twitter Card Validator: https://cards-dev.twitter.com/validator
   - OR LinkedIn Post Inspector: https://www.linkedin.com/post-inspector/
5. Take a screenshot of the preview for marketing records

## Estimated Complexity
Low — smoke test + external validator
