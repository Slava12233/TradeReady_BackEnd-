---
task_id: 19
title: "Configure Dataview plugin"
type: task
agent: backend-developer
phase: 6
depends_on: [1]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - development/.obsidian/plugins/dataview/manifest.json
  - development/.obsidian/plugins/dataview/main.js
  - development/.obsidian/plugins/dataview/data.json
tags:
  - task
  - obsidian
  - plugin-config
  - dataview
---

# Configure Dataview plugin

## Assigned Agent: `backend-developer`

## Objective

Create Dataview plugin configuration so it recognizes the frontmatter fields and date formats used in the vault.

## Context

Dataview must be configured to recognize the frontmatter fields and date formats used in the vault. The actual plugin binary must be installed by the user via Obsidian Community Plugins.

## Files to Create

- `development/.obsidian/plugins/dataview/manifest.json`
- `development/.obsidian/plugins/dataview/main.js` (placeholder)
- `development/.obsidian/plugins/dataview/data.json`

## data.json Config

```json
{
  "renderNullAs": "---",
  "taskCompletionTracking": true,
  "taskCompletionUseEmojiShorthand": false,
  "taskCompletionText": "done",
  "recursiveSubTaskCompletion": false,
  "warnOnEmptyResult": true,
  "refreshEnabled": true,
  "refreshInterval": 5000,
  "defaultDateFormat": "yyyy-MM-dd",
  "maxRecursiveRenderDepth": 8,
  "tableIdColumnName": "File",
  "tableGroupColumnName": "Group"
}
```

## Acceptance Criteria

- [ ] All 3 plugin files exist under `development/.obsidian/plugins/dataview/`
- [ ] `data.json` has correct date format (`yyyy-MM-dd`)
- [ ] Task completion tracking is enabled
- [ ] All JSON files are valid

## Estimated Complexity

Low
