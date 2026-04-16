---
task_id: 22
title: "Fix quickstart docs placeholder URLs"
type: task
agent: "doc-updater"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["docs/quickstart.mdx", "docs/getting-started.mdx", "sdk/README.md"]
tags:
  - task
  - documentation
  - P1
---

# Task 22: Fix quickstart docs placeholder URLs

## Assigned Agent: `doc-updater`

## Objective
Quickstart documentation contains placeholder `your-org` git URLs that don't resolve. Replace with real TradeReady URLs.

## Context
Marketing readiness audit (SR-11) flagged this — developers who follow the quickstart guide hit broken links immediately. Bad first impression.

## Files to Modify
- `docs/quickstart.mdx` — Replace placeholder URLs
- `docs/getting-started.mdx` — Same
- `sdk/README.md` — Same
- Any other docs with `your-org` or placeholder URLs

## Acceptance Criteria
- [ ] Zero instances of `your-org` in documentation
- [ ] All URLs in docs resolve to real pages
- [ ] API base URL is `https://api.tradeready.io`
- [ ] Frontend URL is `https://tradeready.io` or `https://www.tradeready.io`
- [ ] SDK install command uses real package name

## Agent Instructions
1. Grep for `your-org`, `example.com`, `localhost` (in doc context) across `docs/` and `sdk/`
2. Replace with real production URLs
3. Verify the URLs are consistent with the actual deployment

## Estimated Complexity
Low — search and replace
