---
task_id: E-05
title: "Add frontend build + lint job"
type: task
agent: "frontend-developer"
track: E
depends_on: []
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: [".github/workflows/test.yml"]
tags:
  - task
  - ci
  - frontend
  - build
---

# Task E-05: Add frontend build + lint job

## Assigned Agent: `frontend-developer`

## Objective
Add a new CI job that runs `npm ci && npm run build && npm run lint` for the frontend.

## Context
Frontend build and lint are not currently in CI. A broken build could reach production.

## Files to Modify
- `.github/workflows/test.yml`

## Acceptance Criteria
- [ ] New `frontend` job added
- [ ] Uses Node.js 20+ (match the project's Node version)
- [ ] Runs `npm ci` in Frontend directory
- [ ] Runs `npm run build` — catches TypeScript errors and build failures
- [ ] Runs `npm run lint` — catches ESLint issues
- [ ] Working directory set to `Frontend/`
- [ ] Build failures block the pipeline

## Dependencies
None — can start immediately (parallel with Track A and E-01).

## Agent Instructions
Read `Frontend/CLAUDE.md` for the frontend setup. Check `Frontend/package.json` for the correct Node version and available scripts. Create a separate job in the workflow:

```yaml
frontend:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '20'
    - run: npm ci
      working-directory: Frontend
    - run: npm run build
      working-directory: Frontend
    - run: npm run lint
      working-directory: Frontend
```

## Estimated Complexity
Low — standard Node.js CI job.
