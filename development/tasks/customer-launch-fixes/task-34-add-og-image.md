---
task_id: 34
title: "Add OG image for social sharing"
type: task
agent: "frontend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/public/og-image.png", "Frontend/src/app/layout.tsx"]
tags:
  - task
  - frontend
  - marketing
  - seo
  - P2
---

# Task 34: Add OG image for social sharing

## Assigned Agent: `frontend-developer`

## Objective
No Open Graph image exists — links shared on Twitter/LinkedIn/Discord show no preview image. Create an OG image and add meta tags.

## Context
Marketing readiness audit (SR-11) flagged this. Social sharing is a primary growth channel for developer tools.

## Files to Create/Modify
- `Frontend/public/og-image.png` — Create or commission a 1200x630 OG image
- `Frontend/src/app/layout.tsx` — Add OG meta tags

## Acceptance Criteria
- [ ] OG image exists at `/og-image.png` (1200x630px)
- [ ] `<meta property="og:image">` tag in layout.tsx
- [ ] `<meta property="og:title">`, `og:description` also set
- [ ] Twitter card meta tags also present (`twitter:card`, `twitter:image`)
- [ ] Sharing a link to tradeready.io on Twitter/LinkedIn shows the preview

## Agent Instructions
1. Read `Frontend/src/app/layout.tsx` for existing meta tags
2. For MVP: create a simple text-based OG image using CSS/HTML → screenshot, or use a placeholder
3. Add all required Open Graph + Twitter Card meta tags
4. Test with social media preview validators (optional)

## Estimated Complexity
Medium — image creation + meta tags
