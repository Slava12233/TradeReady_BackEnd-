---
task_id: 11
title: "Document display_name registration field"
type: task
agent: "doc-updater"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["docs/quickstart.mdx", "docs/api_reference.md", "sdk/README.md"]
tags:
  - task
  - documentation
  - api
  - P1
---

# Task 11: Document display_name registration field

## Assigned Agent: `doc-updater`

## Objective
The `display_name` field is required at registration but undocumented. First API call fails with 422 for developers who only send `username` + `password`. Either document it clearly or make it optional with a default.

## Context
E2E user journey test (SR-02) discovered this — first registration attempt returned 422. The field is required in the Pydantic schema but not mentioned in quickstart docs.

## Files to Modify
- `docs/quickstart.mdx` — Add `display_name` to registration example
- `docs/api_reference.md` — Ensure registration endpoint docs include all required fields
- `sdk/README.md` — Update SDK usage examples if they show registration
- Optionally: `src/api/schemas/auth.py` — Consider making `display_name` optional with default = username

## Acceptance Criteria
- [ ] Registration docs clearly show `display_name` as required (or it's made optional)
- [ ] Quickstart example includes the field
- [ ] SDK examples include the field
- [ ] No more surprise 422 on first registration attempt

## Agent Instructions
1. Read `docs/CLAUDE.md` for documentation conventions
2. Check `src/api/schemas/` for the registration schema to understand what's required
3. If making `display_name` optional, default it to the username value
4. Update all doc files that show registration examples

## Estimated Complexity
Low — documentation update or 1-line schema change
