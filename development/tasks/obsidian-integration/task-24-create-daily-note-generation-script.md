---
task_id: 24
title: "Create daily note generation script"
type: task
agent: backend-developer
phase: 7
depends_on: [22]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - scripts/create-daily-note.sh
tags:
  - task
  - obsidian
  - daily-notes
  - script
---

# Create daily note generation script

## Assigned Agent: `backend-developer`

## Objective

Create `scripts/create-daily-note.sh` that generates today's daily note from the template for use outside Obsidian (by agents or CI).

## Context

Agents and CI cannot invoke Obsidian Templater. A shell script allows the context-manager agent or a pre-commit hook to ensure a daily note always exists for today.

## Files to Create

- `scripts/create-daily-note.sh`

## Script Behavior

1. Check if `development/daily/YYYY-MM-DD.md` exists for today; if yes, exit 0
2. Copy `development/_templates/daily-note.md`, replacing Templater variables with actual values:
   - `<% tp.date.now("YYYY-MM-DD") %>` -> today's date
   - `<% tp.date.now("YYYY-MM-DD dddd") %>` -> today's date with day name
   - `<% tp.date.now("YYYY-MM-DD", -1) %>` -> yesterday's date
   - `<% tp.date.now("YYYY-MM-DD", 1) %>` -> tomorrow's date
   - `<% tp.file.cursor() %>` -> empty string
3. Write to `development/daily/YYYY-MM-DD.md`

## Acceptance Criteria

- [ ] Script exists at `scripts/create-daily-note.sh`
- [ ] Script is executable (`chmod +x`)
- [ ] Script is idempotent (exits 0 if daily note already exists)
- [ ] All Templater variables are replaced with actual date values
- [ ] Generated note follows the daily-note template structure

## Estimated Complexity

Low
