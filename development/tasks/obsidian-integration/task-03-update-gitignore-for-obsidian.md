---
task_id: 3
title: "Update .gitignore for Obsidian"
type: task
agent: backend-developer
phase: 1
depends_on: [1]
status: pending
priority: high
board: "[[obsidian-integration/README]]"
files:
  - .gitignore
tags:
  - task
  - obsidian
  - vault-foundation
---

# Update .gitignore for Obsidian

## Assigned Agent: `backend-developer`

## Objective

Add Obsidian-specific gitignore entries to the project `.gitignore` so workspace state and local plugin caches are excluded while shared config is committed.

## Context

`workspace.json` is per-user layout state that creates merge conflicts. Plugin `data.json` files contain local state except for Dataview (whose settings we want shared). The `.obsidian/` folder itself is committed so team members get the same plugin list and graph colors.

## Files to Modify

- `.gitignore`

## Entries to Add

```gitignore
# --- Obsidian (development vault) ---
# Commit .obsidian/ config but exclude workspace state and local plugin caches
development/.obsidian/workspace.json
development/.obsidian/workspace-mobile.json
development/.obsidian/.obsidian-git
development/.obsidian/plugins/*/data.json
!development/.obsidian/plugins/dataview/data.json
```

## Acceptance Criteria

- [ ] `.gitignore` contains all 5 Obsidian-related entries
- [ ] Existing `.gitignore` entries are preserved
- [ ] Dataview `data.json` is explicitly un-ignored (committed)

## Estimated Complexity

Low
