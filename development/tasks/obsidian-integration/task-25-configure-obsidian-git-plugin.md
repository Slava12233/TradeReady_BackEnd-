---
task_id: 25
title: "Configure Obsidian Git plugin"
type: task
agent: backend-developer
phase: 8
depends_on: [1]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/.obsidian/plugins/obsidian-git/manifest.json
  - development/.obsidian/plugins/obsidian-git/main.js
  - development/.obsidian/plugins/obsidian-git/data.json
tags:
  - task
  - obsidian
  - plugin-config
  - git
---

# Configure Obsidian Git plugin

## Assigned Agent: `backend-developer`

## Objective

Create Obsidian Git plugin configuration for bidirectional sync between Obsidian and the git repo.

## Context

Obsidian Git enables the bidirectional workflow: agents push changes via CLI git; humans pull automatically in Obsidian and push via the plugin. Auto-save is disabled to reduce noise; auto-pull is every 10 minutes.

## Files to Create

- `development/.obsidian/plugins/obsidian-git/manifest.json`
- `development/.obsidian/plugins/obsidian-git/main.js` (placeholder)
- `development/.obsidian/plugins/obsidian-git/data.json`

## data.json Config

```json
{
  "autoSaveInterval": 0,
  "autoPushInterval": 0,
  "autoPullInterval": 10,
  "autoPullOnBoot": true,
  "disablePush": false,
  "pullBeforePush": true,
  "disablePopups": false,
  "listChangedFilesInMessageBody": true,
  "showStatusBar": true,
  "updateSubmodules": false,
  "syncMethod": "merge",
  "gitPath": "",
  "customMessageOnAutoBackup": "docs(vault): auto-sync {{date}}",
  "autoBackupAfterFileChange": false,
  "treeStructure": false,
  "refreshSourceControl": true
}
```

## Design Decisions

- `autoSaveInterval: 0` -- disabled; humans commit manually
- `autoPullInterval: 10` -- pull every 10 minutes to pick up agent changes
- `autoPullOnBoot: true` -- always start with latest
- `pullBeforePush: true` -- prevent conflicts
- `customMessageOnAutoBackup` -- conventional commit format

## Acceptance Criteria

- [ ] All 3 plugin files exist under `development/.obsidian/plugins/obsidian-git/`
- [ ] Auto-save is disabled (`autoSaveInterval: 0`)
- [ ] Auto-pull is set to 10 minutes
- [ ] Commit message uses conventional format
- [ ] All JSON files are valid

## Estimated Complexity

Low
