---
task_id: 31
title: "Update development/CLAUDE.md"
type: task
agent: doc-updater
phase: 10
depends_on: [30]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/CLAUDE.md
tags:
  - task
  - obsidian
  - documentation
  - claude-md
---

# Update development/CLAUDE.md

## Assigned Agent: `doc-updater`

## Objective

Update `development/CLAUDE.md` to document the Obsidian vault structure so agents can navigate the new directories.

## Context

CLAUDE.md files are the agent navigation system. They must reflect the new directory structure added by the Obsidian integration.

## Changes Required

- Add new directories to "Subdirectories" table:
  - `_templates/` -- Obsidian Templater templates
  - `_dashboards/` -- Dataview dashboard notes
  - `_moc/` -- Map of Content index notes
  - `daily/` -- Daily development log notes
  - `.obsidian/` -- Obsidian vault configuration (committed to git)
- Add note about Obsidian vault in "Purpose" section
- Update "Patterns" section with frontmatter conventions
- Add "Obsidian Vault" section explaining coexistence with CLAUDE.md
- Update "Recent Changes" with dated entry

## Acceptance Criteria

- [ ] All new directories are documented in the Subdirectories table
- [ ] Purpose section mentions the Obsidian vault
- [ ] Frontmatter conventions are documented in Patterns section
- [ ] Coexistence rules (CLAUDE.md vs Obsidian) are clearly stated
- [ ] Recent Changes has a dated entry for the Obsidian integration

## Estimated Complexity

Low
