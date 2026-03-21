---
task_id: 26
title: "Document Git workflow"
type: task
agent: doc-updater
phase: 8
depends_on: [25]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/_moc/git-workflow.md
tags:
  - task
  - obsidian
  - documentation
  - git
---

# Document Git workflow

## Assigned Agent: `doc-updater`

## Objective

Create `development/_moc/git-workflow.md` documenting the bidirectional sync workflow between Obsidian and the git repo.

## Context

Bidirectional sync needs clear ownership rules to prevent conflicts. This document defines who owns which files and how sync works.

## Content to Include

- How Obsidian Git auto-pulls agent changes
- How to manually commit from Obsidian (sidebar, `Ctrl+Shift+K`)
- Conflict resolution strategy (merge, not rebase; agent files are append-only so conflicts are rare)
- What files humans should edit vs. what agents own
- File ownership map:
  - `daily/*.md` -- shared
  - `context.md` -- agent-owned, human-readable
  - `code-reviews/*.md` -- agent-owned
  - `tasks/**/*.md` -- agent-owned
  - Planning docs -- human-owned
  - `_moc/*.md` -- human-owned
  - `_dashboards/*.md` -- human-owned

## Acceptance Criteria

- [ ] `development/_moc/git-workflow.md` exists with valid frontmatter
- [ ] File ownership map is clearly documented
- [ ] Conflict resolution strategy is explained
- [ ] Instructions for manual commit from Obsidian are included

## Estimated Complexity

Low
