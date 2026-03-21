---
task_id: 12
title: "Extract landing-only CSS from globals.css"
type: task
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "medium"
files:
  - "Frontend/src/app/globals.css"
  - "Frontend/src/app/page.tsx"
tags:
  - task
  - frontend
  - performance
---

# Task 12: Extract Landing-Only CSS from globals.css

## Assigned Agent: `frontend-developer`

## Objective

Move ~660 lines of landing page hero/section animations from `globals.css` into a scoped CSS module or a landing-specific stylesheet, so dashboard pages don't load unused animation CSS.

## Context

`globals.css` is 1090 lines, with lines 221-883 being landing-only custom CSS (hero animations, grid pulse, float effects, shimmer, CTA glow, section animations, ticker effects). All dashboard pages load this CSS unnecessarily.

From the performance review (M2): "660 lines landing CSS in globals — loaded on every page."

## Files to Modify

- `Frontend/src/app/globals.css` — Remove landing-specific CSS (lines ~221-883)
- Create `Frontend/src/styles/landing.css` or `Frontend/src/app/landing.module.css` — Move landing CSS here
- `Frontend/src/app/page.tsx` or the landing layout — Import the landing CSS file

## Acceptance Criteria

- [ ] `globals.css` reduced by ~660 lines
- [ ] Landing page still looks identical (all animations work)
- [ ] Dashboard pages no longer load landing animation CSS
- [ ] Tailwind theme variables and base styles remain in globals.css
- [ ] CSS containment, reduced-motion, and accessibility styles remain in globals.css
- [ ] No visual regressions on any page
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/app/globals.css` to identify the exact line ranges of landing-only CSS
2. Read `Frontend/src/app/page.tsx` and landing components to understand which CSS classes they use
3. Create a new file and move the landing CSS there
4. Import the new file in the landing page or its layout
5. Keep Tailwind `@theme`, base styles, and accessibility/performance CSS in globals.css
6. Test both landing and dashboard pages visually

## Estimated Complexity

Medium — large CSS move, requires careful identification of landing-only vs global styles
