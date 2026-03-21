---
task_id: 23
title: "Document daily note workflow"
type: task
agent: doc-updater
phase: 7
depends_on: [22]
status: pending
priority: medium
board: "[[obsidian-integration/README]]"
files:
  - development/_moc/daily-log-moc.md
tags:
  - task
  - obsidian
  - daily-notes
  - documentation
---

# Document daily note workflow

## Assigned Agent: `doc-updater`

## Objective

Update `development/_moc/daily-log-moc.md` (created in Task 17) with detailed human workflow instructions for the daily note system.

## Context

Humans need clear instructions on how to use daily notes alongside the existing context.md system. The daily-log-moc may already exist from Task 17; update it with workflow details.

## Content to Include

- How to create a daily note (Templater: `Ctrl+N`, select daily-note template, or use Obsidian daily notes plugin)
- What to write in the "Human Notes" section (decisions, observations, blockers, plans)
- What agents auto-populate in the "Agent Activity" section
- How daily notes connect to `[[context]]` (context.md is the canonical record; daily notes are the working scratchpad)
- Navigation: previous/next day links, calendar view recommendation

## Acceptance Criteria

- [ ] `development/_moc/daily-log-moc.md` has detailed workflow instructions
- [ ] Instructions cover both human and agent usage
- [ ] Relationship between daily notes and context.md is explained
- [ ] Navigation tips are included

## Estimated Complexity

Low
