---
task_id: 12
title: "Configure Templater plugin"
type: task
agent: backend-developer
phase: 4
depends_on: [1]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/.obsidian/plugins/templater-obsidian/manifest.json
  - development/.obsidian/plugins/templater-obsidian/main.js
  - development/.obsidian/plugins/templater-obsidian/data.json
tags:
  - task
  - obsidian
  - templates
  - plugin-config
---

# Configure Templater plugin

## Assigned Agent: `backend-developer`

## Objective

Create Templater plugin configuration so the template folder is set to `_templates/` and dynamic date insertion is enabled.

## Context

Templater is the standard Obsidian template engine. It supports dynamic date insertion, cursor placement, and folder-specific templates. The actual plugin binary must be installed by the user via Obsidian Community Plugins.

## Files to Create

- `development/.obsidian/plugins/templater-obsidian/manifest.json` -- plugin manifest
- `development/.obsidian/plugins/templater-obsidian/main.js` -- plugin entry (placeholder)
- `development/.obsidian/plugins/templater-obsidian/data.json` -- config pointing to `_templates/` folder

## data.json Config

```json
{
  "templates_folder": "_templates",
  "trigger_on_file_creation": true,
  "auto_jump_to_cursor": true,
  "date_format": "YYYY-MM-DD"
}
```

## Acceptance Criteria

- [ ] All 3 plugin files exist under `development/.obsidian/plugins/templater-obsidian/`
- [ ] `data.json` points `templates_folder` to `_templates`
- [ ] `manifest.json` has valid plugin metadata
- [ ] All JSON files are valid

## Estimated Complexity

Low
