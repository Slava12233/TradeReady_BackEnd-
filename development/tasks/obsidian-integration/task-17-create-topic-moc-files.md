---
task_id: 17
title: "Create topic MOC files"
type: task
agent: backend-developer
phase: 5
depends_on: [16]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/_moc/task-boards-moc.md
  - development/_moc/code-reviews-moc.md
  - development/_moc/plans-moc.md
  - development/_moc/research-moc.md
  - development/_moc/daily-log-moc.md
tags:
  - task
  - obsidian
  - moc
  - navigation
---

# Create topic MOC files

## Assigned Agent: `backend-developer`

## Objective

Create MOC (Map of Content) files for each major content area to serve as curated entry points with Dataview queries.

## Context

MOCs serve as curated entry points that Dataview queries keep automatically updated. Humans see a structured overview; the graph view shows topic clusters.

## Files to Create

### `development/_moc/task-boards-moc.md`
- Lists all 6 completed task boards with wikilinks
- Dataview query: all task boards sorted by created date
- Dataview query: tasks by status across all boards

### `development/_moc/code-reviews-moc.md`
- Dataview query: all reviews sorted by date with verdict
- Filtered views: Needs Fixes, Passed

### `development/_moc/plans-moc.md`
- Dataview query: all files where `type = "plan"` sorted by date
- Grouped by status (draft/active/archived/complete)

### `development/_moc/research-moc.md`
- Dataview query: all files where `type = "research-report"`

### `development/_moc/daily-log-moc.md`
- Dataview query: recent daily notes
- Instructions for daily note workflow

## Acceptance Criteria

- [ ] All 5 MOC files exist with valid frontmatter (`type: moc`)
- [ ] Each MOC has Dataview queries appropriate to its topic
- [ ] Task boards MOC lists all 6 completed boards with wikilinks
- [ ] Code reviews MOC has verdict-filtered views

## Estimated Complexity

Medium (6 files with Dataview queries)
