---
task_id: 35
title: "Documentation and CLAUDE.md updates"
agent: "doc-updater"
phase: 2
depends_on: [20, 33]
status: "pending"
priority: "medium"
files: ["agent/conversation/CLAUDE.md", "agent/memory/CLAUDE.md", "agent/permissions/CLAUDE.md", "agent/trading/CLAUDE.md", "agent/tools/CLAUDE.md"]
---

# Task 35: Documentation and CLAUDE.md updates

## Assigned Agent: `doc-updater`

## Objective
Create CLAUDE.md files for all new packages and update existing ones to reflect the agent ecosystem additions.

## Files to Create
- `agent/conversation/CLAUDE.md` — conversation system docs
- `agent/memory/CLAUDE.md` — memory system docs
- `agent/permissions/CLAUDE.md` — permission system docs
- `agent/trading/CLAUDE.md` — trading loop and journal docs

## Files to Modify
- `agent/tools/CLAUDE.md` — add new agent tools documentation
- `agent/CLAUDE.md` — update with new packages
- `CLAUDE.md` — add new CLAUDE.md files to the index

## Acceptance Criteria
- [ ] Each new CLAUDE.md follows the standard format (files, public APIs, patterns, gotchas)
- [ ] All new modules documented with file inventories
- [ ] Agent tools CLAUDE.md updated with 5 new tools
- [ ] Root CLAUDE.md index updated with new entries
- [ ] `<!-- last-updated -->` timestamps set

## Dependencies
- Tasks 20, 33 (all code must be written before documenting)

## Agent Instructions
1. Read existing CLAUDE.md files for format reference
2. Document each package's purpose, files, public APIs, and patterns
3. Include gotchas and non-obvious design decisions
4. Cross-reference related CLAUDE.md files

## Estimated Complexity
Low — documentation following established patterns.
