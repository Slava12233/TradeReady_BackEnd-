---
task_id: 19
title: "Add /landing to sitemap.ts"
type: task
agent: "frontend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["Frontend/src/app/sitemap.ts"]
tags:
  - task
  - frontend
  - seo
  - P1
---

# Task 19: Add /landing to sitemap.ts

## Assigned Agent: `frontend-developer`

## Objective
The `/landing` marketing page is not included in `sitemap.ts`, meaning search engines won't index it. Add it to the sitemap.

## Context
Frontend UX audit (SR-05) flagged this as a SEO gap. The landing page is the primary marketing asset but invisible to search engines.

## Files to Modify
- `Frontend/src/app/sitemap.ts` — Add `/landing` entry (and `/terms`, `/privacy`, `/contact` after those pages exist)

## Acceptance Criteria
- [ ] `/landing` appears in the generated sitemap.xml
- [ ] Legal pages (/terms, /privacy, /contact) also added if they exist
- [ ] Sitemap generates without errors
- [ ] Priority and changefreq set appropriately (landing = high priority)

## Agent Instructions
1. Read the current `sitemap.ts` to understand the format
2. Add entries for `/landing` and any new legal pages
3. Set `priority: 1.0` for landing, `0.3` for legal pages

## Estimated Complexity
Low — add entries to sitemap config
