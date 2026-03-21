---
task_id: 9
title: "Define wikilink conventions"
type: task
agent: backend-developer
phase: 3
depends_on: [4, 5, 6, 7, 8]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/_moc/wikilink-conventions.md
tags:
  - task
  - obsidian
  - wikilinks
  - conventions
---

# Define wikilink conventions

## Assigned Agent: `backend-developer`

## Objective

Create `development/_moc/wikilink-conventions.md` documenting the project's wikilink standards so both humans and agents produce consistent cross-references.

## Context

Without consistent conventions, wikilinks will diverge between human-written and agent-written notes. A conventions file serves as reference for both.

## Files to Create

- `development/_moc/wikilink-conventions.md`

## Content Requirements

The conventions file must document:
- **Link targets:** Use file name without extension (e.g., `[[context]]`, `[[agent-ecosystem-plan]]`)
- **Task links:** `[[agent-memory-system/task-01-enable-memory-all-agents|Task 01]]` (folder-scoped to avoid collisions)
- **Review links:** `[[review_2026-03-20_16-24_frontend-perf-fixes|Frontend Perf Review]]` (pipe alias for readability)
- **Board links:** `[[agent-memory-system/README|Agent Memory Board]]`
- **External code links:** Use inline code, not wikilinks: `src/agents/service.py` (no link -- source files are outside the vault)
- **Section links:** `[[context#Current State]]` for linking to specific headings
- **Tag conventions:** Prefix with category: `review/security`, `task/agent-memory`, `plan/battles`

## Acceptance Criteria

- [ ] `development/_moc/wikilink-conventions.md` exists with all convention categories documented
- [ ] Examples are provided for each link type
- [ ] Convention clearly states that wikilinks are ONLY used in `development/` files, never in CLAUDE.md or source code

## Estimated Complexity

Low
