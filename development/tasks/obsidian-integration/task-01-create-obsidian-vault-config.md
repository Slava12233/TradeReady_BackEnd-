---
task_id: 1
title: "Create Obsidian vault configuration"
type: task
agent: backend-developer
phase: 1
depends_on: []
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/.obsidian/app.json
  - development/.obsidian/appearance.json
  - development/.obsidian/community-plugins.json
  - development/.obsidian/graph.json
  - development/.obsidian/hotkeys.json
  - development/.obsidian/workspace.json
tags:
  - task
  - obsidian
  - vault-foundation
---

# Create Obsidian vault configuration

## Assigned Agent: `backend-developer`

## Objective

Create `development/.obsidian/` directory with initial configuration files so Obsidian recognizes `development/` as a vault.

## Context

Obsidian needs a `.obsidian/` folder to recognize a directory as a vault. Committing this config to git means every team member gets the same setup when they open the vault.

## Files to Create

- `development/.obsidian/app.json` -- core Obsidian settings
- `development/.obsidian/appearance.json` -- minimal theme config
- `development/.obsidian/community-plugins.json` -- enable list: `["dataview", "obsidian-git", "templater-obsidian"]`
- `development/.obsidian/graph.json` -- graph view settings (color groups: tasks=blue, reviews=red, plans=green, daily=yellow, moc=purple)
- `development/.obsidian/hotkeys.json` -- empty (user customizes)
- `development/.obsidian/workspace.json` -- default workspace layout

## Config Details

**`app.json`:**
```json
{
  "newFileLocation": "folder",
  "newFileFolderPath": "daily",
  "attachmentFolderPath": "_attachments",
  "alwaysUpdateLinks": true,
  "strictLineBreaks": false,
  "showFrontmatter": true,
  "readableLineLength": true,
  "showLineNumber": true
}
```

## Acceptance Criteria

- [ ] `development/.obsidian/` directory exists with all 6 config files
- [ ] All JSON files are valid and parseable
- [ ] `community-plugins.json` lists `dataview`, `obsidian-git`, `templater-obsidian`
- [ ] `graph.json` defines color groups for tasks, reviews, plans, daily notes, and MOCs
- [ ] Opening `development/` in Obsidian recognizes it as a vault

## Estimated Complexity

Low
